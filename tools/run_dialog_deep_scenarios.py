#!/usr/bin/env python3
"""Run multi-turn deep dialog scenarios against /api/chat in portal mode."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request


@dataclass
class CheckResult:
    passed: bool
    reasons: list[str]


def read_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("scenario file must be a JSON array")
    return data


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def post_json(url: str, payload: dict[str, Any], token: str, timeout: float) -> tuple[int, Any, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return resp.status, None, raw
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        return exc.code, data, raw


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str,
    timeout: float,
) -> tuple[int, Any, str]:
    method = (method or "GET").upper()
    headers = {"Accept": "application/json"}
    body = None
    if token:
        headers["Authorization"] = f"Token {token}"
    if method in {"POST", "PUT", "PATCH", "DELETE"} and payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return resp.status, None, raw
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        return exc.code, data, raw


def extract_text(data: Any, raw: str) -> str:
    if isinstance(data, dict):
        for key in ("final_response", "response", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return raw.strip()


def _json_path_get(data: Any, path: str) -> Any:
    current = data
    for part in (path or "").split("."):
        if part == "":
            continue
        if isinstance(current, list):
            if not part.isdigit():
                return None
            idx = int(part)
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
            continue
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current.get(part)
            continue
        return None
    return current


def _evaluate_post_assert(expect: dict[str, Any], status_code: int, data: Any) -> list[str]:
    reasons: list[str] = []
    expected_status = expect.get("status_code")
    if isinstance(expected_status, int) and status_code != expected_status:
        reasons.append(f"post_status_mismatch:{status_code}->{expected_status}")

    equals = expect.get("equals") or {}
    if isinstance(equals, dict):
        for path, wanted in equals.items():
            got = _json_path_get(data, str(path))
            if got != wanted:
                reasons.append(f"post_equals_mismatch:{path}:{got}->{wanted}")

    gte = expect.get("gte") or {}
    if isinstance(gte, dict):
        for path, wanted in gte.items():
            got = _json_path_get(data, str(path))
            try:
                if float(got) < float(wanted):
                    reasons.append(f"post_gte_mismatch:{path}:{got}<{wanted}")
            except (TypeError, ValueError):
                reasons.append(f"post_gte_invalid:{path}:{got}")

    exists = expect.get("exists") or []
    if isinstance(exists, list):
        for path in exists:
            got = _json_path_get(data, str(path))
            if got is None:
                reasons.append(f"post_missing:{path}")

    not_exists = expect.get("not_exists") or []
    if isinstance(not_exists, list):
        for path in not_exists:
            got = _json_path_get(data, str(path))
            if got is not None:
                reasons.append(f"post_unexpected:{path}")

    return reasons


def evaluate_step(step: dict[str, Any], status_code: int, data: Any, text: str) -> CheckResult:
    reasons: list[str] = []
    if status_code >= 400:
        reasons.append(f"http_{status_code}")
        return CheckResult(False, reasons)

    expected_intent = step.get("expect_intent")
    if expected_intent:
        got_intent = str((data or {}).get("intent") or "")
        if got_intent != expected_intent:
            reasons.append(f"intent_mismatch:{got_intent}->{expected_intent}")

    if "expect_confirm_required" in step:
        got_confirm = bool((data or {}).get("confirm_required"))
        want_confirm = bool(step.get("expect_confirm_required"))
        if got_confirm != want_confirm:
            reasons.append(f"confirm_mismatch:{got_confirm}->{want_confirm}")

    expected_lane = step.get("expect_lane")
    if expected_lane:
        got_lane = str(((data or {}).get("routing") or {}).get("lane") or "")
        if got_lane != expected_lane:
            reasons.append(f"lane_mismatch:{got_lane}->{expected_lane}")

    expected_pending = step.get("expect_pending_type")
    if expected_pending:
        got_pending = str(((data or {}).get("pending_action") or {}).get("type") or "")
        if got_pending != expected_pending:
            reasons.append(f"pending_mismatch:{got_pending}->{expected_pending}")

    if step.get("expect_no_pending_action"):
        if isinstance(data, dict) and data.get("pending_action"):
            reasons.append("pending_should_be_empty")

    expect_any = step.get("expect_any", []) or []
    if expect_any:
        if not any(keyword in text for keyword in expect_any):
            reasons.append(f"missing_any:{'|'.join(expect_any)}")

    for keyword in step.get("expect_all", []) or []:
        if keyword not in text:
            reasons.append(f"missing:{keyword}")

    for keyword in step.get("forbid_any", []) or []:
        if keyword in text:
            reasons.append(f"forbidden:{keyword}")

    return CheckResult(passed=not reasons, reasons=reasons)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deep multi-turn chat scenarios.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--endpoint", default="/api/chat")
    parser.add_argument("--token", default=os.getenv("PORTAL_TOKEN", ""))
    parser.add_argument("--scenarios", default="spec/dialog_deep_scenarios_zh.json")
    parser.add_argument("--provider-model", default="qwen2.5-7B-instruct")
    parser.add_argument("--provider-type", default="OLLAMA")
    parser.add_argument("--model-provider", default="OLLAMA")
    parser.add_argument(
        "--provider-profile-id",
        type=int,
        default=int(os.getenv("PORTAL_PROVIDER_PROFILE_ID", "0") or 0),
        help="Force provider_profile_id in /api/chat payload (or env PORTAL_PROVIDER_PROFILE_ID)",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--out-json", default="spec/dialog_deep_results.json")
    args = parser.parse_args()

    scenarios = read_json(Path(args.scenarios))
    url = args.base_url.rstrip("/") + args.endpoint

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": args.provider_model,
        "summary": {},
        "scenarios": [],
    }

    total_steps = 0
    passed_steps = 0
    passed_scenarios = 0
    model_source_counter: Counter[str] = Counter()

    for scenario in scenarios:
        sid = str(scenario.get("id") or "")
        title = str(scenario.get("title") or sid)
        steps = scenario.get("steps") or []
        run_id = ""
        scenario_ok = True
        step_results: list[dict[str, Any]] = []

        for idx, step in enumerate(steps, start=1):
            total_steps += 1
            message = str(step.get("user") or "")
            payload = {
                "message": message,
                "run_id": run_id or None,
                "portal_mode": True,
                "model_provider": args.model_provider,
                "provider_type": args.provider_type,
                "provider_model": args.provider_model,
            }
            if args.provider_profile_id and args.provider_profile_id > 0:
                payload["provider_profile_id"] = int(args.provider_profile_id)
            payload = {k: v for k, v in payload.items() if v is not None}
            status_code, data, raw = post_json(url, payload, token=args.token, timeout=args.timeout)
            text = extract_text(data, raw)
            if isinstance(data, dict) and data.get("run_id"):
                run_id = str(data.get("run_id"))

            check = evaluate_step(step, status_code, data, text)
            post_assert_result = None
            post_assert_cfg = step.get("post_assert_api")
            if isinstance(post_assert_cfg, dict):
                method = str(post_assert_cfg.get("method") or "GET").upper()
                path = str(post_assert_cfg.get("path") or "").strip()
                body = post_assert_cfg.get("body")
                expect = post_assert_cfg.get("expect") or {}
                if path:
                    assert_url = args.base_url.rstrip("/") + path
                    post_status, post_data, _ = request_json(
                        assert_url,
                        method=method,
                        payload=body if isinstance(body, dict) else None,
                        token=args.token,
                        timeout=args.timeout,
                    )
                    post_reasons = _evaluate_post_assert(expect, post_status, post_data)
                    if post_reasons:
                        check.passed = False
                        check.reasons.extend(post_reasons)
                    post_assert_result = {
                        "method": method,
                        "path": path,
                        "status_code": post_status,
                        "passed": not post_reasons,
                        "reasons": post_reasons,
                    }

            if check.passed:
                passed_steps += 1
            else:
                scenario_ok = False

            routing = (data or {}).get("routing") if isinstance(data, dict) else {}
            lane = (routing or {}).get("lane")
            model_source = (routing or {}).get("model_source") if isinstance(routing, dict) else ""
            if isinstance(model_source, str) and model_source:
                model_source_counter[model_source] += 1
            pending_type = ((data or {}).get("pending_action") or {}).get("type") if isinstance(data, dict) else ""
            step_results.append(
                {
                    "index": idx,
                    "user": message,
                    "status_code": status_code,
                    "intent": (data or {}).get("intent") if isinstance(data, dict) else "",
                    "routing_lane": lane,
                    "model_source": model_source or "",
                    "pending_action_type": pending_type,
                    "security_blocked": lane == "policy_guard",
                    "confirm_required": bool((data or {}).get("confirm_required")) if isinstance(data, dict) else False,
                    "response": text,
                    "passed": check.passed,
                    "reasons": check.reasons,
                    "post_assert": post_assert_result,
                }
            )

            print(f"[{sid}#{idx}] status={status_code} pass={check.passed}")
            if args.sleep > 0:
                time.sleep(args.sleep)

        if scenario_ok:
            passed_scenarios += 1

        report["scenarios"].append(
            {
                "id": sid,
                "title": title,
                "passed": scenario_ok,
                "run_id": run_id,
                "steps": step_results,
            }
        )

    report["summary"] = {
        "scenario_total": len(scenarios),
        "scenario_passed": passed_scenarios,
        "step_total": total_steps,
        "step_passed": passed_steps,
        "pass_rate": round((passed_steps / total_steps) * 100, 2) if total_steps else 0,
        "model_source_distribution": dict(model_source_counter),
    }

    write_json(Path(args.out_json), report)
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"saved -> {args.out_json}")
    return 0 if passed_scenarios == len(scenarios) else 2


if __name__ == "__main__":
    sys.exit(main())
