#!/usr/bin/env python3
"""Batch run portal chat quality cases from a JSONL file.

Example:
  python tools/run_dialog_quality_cases.py \
    --base-url http://localhost:8000 \
    --token <PORTAL_TOKEN> \
    --provider-model qwen3:4b
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {i}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Invalid row type at line {i}, expected object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "result_version",
        "session_mode",
        "id",
        "category",
        "message",
        "intent_hint",
        "status_code",
        "ok",
        "confirm_required",
        "intent",
        "model_source",
        "run_id",
        "latency_ms",
        "tested_at",
        "response",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


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


def extract_response_text(data: Any, fallback_raw: str) -> str:
    if isinstance(data, dict):
        for key in ("final_response", "response", "answer", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback_raw.strip()


def parse_ids(value: str) -> set[str]:
    return {x.strip() for x in value.split(",") if x.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run dialog quality cases against /api/chat")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base url")
    parser.add_argument("--endpoint", default="/api/chat", help="Chat endpoint path")
    parser.add_argument("--cases", default="spec/dialog_quality_cases_zh.jsonl", help="Cases JSONL path")
    parser.add_argument("--out-jsonl", default="spec/dialog_quality_results.jsonl", help="Output JSONL path")
    parser.add_argument("--out-csv", default="spec/dialog_quality_results.csv", help="Output CSV path")
    parser.add_argument("--token", default=os.getenv("PORTAL_TOKEN", ""), help="Auth token (or env PORTAL_TOKEN)")
    parser.add_argument("--model-provider", default="OLLAMA")
    parser.add_argument("--provider-type", default="OLLAMA")
    parser.add_argument("--provider-model", default="deepseek-r1:8b")
    parser.add_argument(
        "--provider-profile-id",
        type=int,
        default=int(os.getenv("PORTAL_PROVIDER_PROFILE_ID", "0") or 0),
        help="Force provider_profile_id in /api/chat payload (or env PORTAL_PROVIDER_PROFILE_ID)",
    )
    parser.add_argument("--version", default="", help="Result version tag, e.g. v20260213-r1")
    parser.add_argument("--no-portal-mode", action="store_true", help="Disable portal_mode")
    parser.add_argument("--continue-run", action="store_true", help="Use one run_id across all cases")
    parser.add_argument("--force-new-run", action="store_true", default=True, help="Force a new run for every case (default: true)")
    parser.add_argument("--no-force-new-run", action="store_false", dest="force_new_run", help="Disable forcing a new run")
    parser.add_argument("--limit", type=int, default=0, help="Max number of cases")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N cases")
    parser.add_argument("--ids", default="", help="Run only specific ids, comma separated. e.g. DQ001,DQ010")
    parser.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between requests")
    parser.add_argument("--timeout", type=float, default=45.0, help="Request timeout seconds")
    parser.add_argument("--dry-run", action="store_true", help="Only print selected cases")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on first failed request")
    args = parser.parse_args()
    result_version = (args.version or "").strip() or datetime.now().strftime("v%Y%m%d-%H%M%S")

    cases_path = Path(args.cases)
    rows = read_jsonl(cases_path)

    if args.offset > 0:
        rows = rows[args.offset :]
    if args.ids:
        wanted = parse_ids(args.ids)
        rows = [r for r in rows if str(r.get("id", "")) in wanted]
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    if not rows:
        print("No cases selected.")
        return 1

    if args.dry_run:
        for i, row in enumerate(rows, start=1):
            print(f"{i:03d}. {row.get('id')} [{row.get('category')}] {row.get('message')}")
        print(f"Total: {len(rows)}")
        return 0

    url = args.base_url.rstrip("/") + args.endpoint
    out_rows: list[dict[str, Any]] = []
    current_run_id = ""
    success = 0
    failed = 0
    session_mode = "continuous" if args.continue_run else "isolated"
    model_source_counter: dict[str, int] = {}

    for i, case in enumerate(rows, start=1):
        case_id = str(case.get("id", f"CASE{i:03d}"))
        message = str(case.get("message", "")).strip()
        category = str(case.get("category", ""))
        intent_hint = str(case.get("intent_hint", ""))

        payload: dict[str, Any] = {
            "message": message,
            "model_provider": args.model_provider,
            "provider_type": args.provider_type,
            "provider_model": args.provider_model,
            "portal_mode": not args.no_portal_mode,
        }
        if args.provider_profile_id and args.provider_profile_id > 0:
            payload["provider_profile_id"] = int(args.provider_profile_id)
        if args.force_new_run and not args.continue_run:
            payload["force_new_run"] = True
        if args.continue_run and current_run_id:
            payload["run_id"] = current_run_id

        t0 = time.perf_counter()
        status_code, data, raw = post_json(url, payload, token=args.token, timeout=args.timeout)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        ok = status_code < 400 and isinstance(data, dict)
        response_text = extract_response_text(data, raw)
        run_id = data.get("run_id") if isinstance(data, dict) else ""
        confirm_required = bool(data.get("confirm_required")) if isinstance(data, dict) else False
        response_intent = str(data.get("intent") or "") if isinstance(data, dict) else ""
        model_source = (
            str(((data or {}).get("routing") or {}).get("model_source") or "")
            if isinstance(data, dict)
            else ""
        )
        if model_source:
            model_source_counter[model_source] = model_source_counter.get(model_source, 0) + 1

        error_text = ""
        if not ok:
            failed += 1
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    error_text = str(err.get("message") or err.get("code") or data)
                else:
                    error_text = str(data.get("message") or data.get("error") or raw)
            else:
                error_text = raw
        else:
            success += 1

        record = {
            "result_version": result_version,
            "session_mode": session_mode,
            "id": case_id,
            "category": category,
            "intent_hint": intent_hint,
            "message": message,
            "status_code": status_code,
            "ok": ok,
            "confirm_required": confirm_required,
            "intent": response_intent,
            "model_source": model_source,
            "run_id": run_id or "",
            "latency_ms": elapsed_ms,
            "tested_at": datetime.now().isoformat(timespec="seconds"),
            "response": response_text,
            "error": error_text,
        }
        out_rows.append(record)
        print(f"[{i:03d}/{len(rows)}] {case_id} status={status_code} latency={elapsed_ms}ms")

        if args.continue_run and isinstance(run_id, str) and run_id:
            current_run_id = run_id

        if not ok and args.fail_fast:
            break
        if args.sleep > 0:
            time.sleep(args.sleep)

    out_jsonl = Path(args.out_jsonl)
    out_csv = Path(args.out_csv)
    write_jsonl(out_jsonl, out_rows)
    write_csv(out_csv, out_rows)

    print(
        f"Done. total={len(out_rows)} success={success} failed={failed} "
        f"jsonl={out_jsonl} csv={out_csv}"
    )
    if model_source_counter:
        print(f"model_source_distribution={json.dumps(model_source_counter, ensure_ascii=False)}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
