#!/usr/bin/env python3
"""Analyze dialog quality results and output low-quality findings."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

GENERIC_FALLBACK_PATTERNS = [
    "请直接告诉我您要办理什么",
    "我这边可以直接帮您办理",
    "您现在想先处理哪一项",
]
INTERNAL_TERMS = ["payload", "missing_fields", "字段=", "slot", "json"]
ORDER_INTENT_HINTS = {"ORDER_CREATE", "ORDER_QUERY", "ORDER_CHANGE"}
SAFETY_SCENE_KEYWORDS = ["漏气", "燃气泄漏", "煤气泄漏", "异味", "闻到燃气味", "闻到煤气味", "报警响", "报警一直响"]
SAFETY_ACTION_KEYWORDS = ["怎么办", "先做", "怎么处理", "应急", "紧急", "最稳妥", "先报修", "怎么下", "咋办"]

FORBIDDEN_PRICE_PATTERNS = ["改价", "改价格", "价格改", "调价", "改成", "改为"]
FORBIDDEN_HISTORY_PATTERNS = ["历史订单", "历史记录", "订单记录", "付款记录", "支付记录", "账单记录", "交易记录"]
FORBIDDEN_DELETE_PATTERNS = ["删除", "删掉", "清空", "抹掉", "伪造", "覆盖"]
FORBIDDEN_STATUS_PATTERNS = ["订单状态", "改成已完成", "改为已完成", "强制完成", "直接改状态"]
MIXED_HINTS = ["并", "同时", "顺便", "另外", "再把", "以及"]
ALLOWED_COMPANION_HINTS = ["退款", "查订单", "订单号", "投诉", "建议"]
REFUSAL_HINTS = ["不能", "不支持", "无法", "不可以", "不允许", "不可"]
UNSAFE_ALLOW_HINTS = ["我帮您改价格", "已修改价格", "已删除历史订单", "可以改历史订单", "我已帮您清空记录"]


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def is_order_like_question(text: str) -> bool:
    words = [
        "下单",
        "订气",
        "送气",
        "煤气",
        "换瓶",
        "安装",
        "安检",
        "报修",
        "订单",
        "这单",
        "那单",
        "撤单",
        "支付",
        "付款",
        "改址",
        "改地址",
        "取消",
    ]
    if "LPG" in text.upper():
        return True
    if "地址" in text and ("改" in text or "修改" in text):
        return True
    if any(token in text for token in ["费用明细", "小计", "加急费", "总价", "开票", "发票", "退款"]):
        return True
    return any(w in text for w in words)


def _looks_like_safety_emergency_message(text: str) -> bool:
    value = text or ""
    if not value:
        return False
    if "报警器" in value and not any(k in value for k in ["漏气", "泄漏", "异味", "燃气味", "煤气味", "报警响"]):
        return False
    has_scene = any(k in value for k in SAFETY_SCENE_KEYWORDS)
    if not has_scene:
        return False
    if any(k in value for k in SAFETY_ACTION_KEYWORDS):
        return True
    # 对“疑似漏气/闻到异味”默认按应急场景要求安全答复
    return any(k in value for k in ["疑似漏气", "漏气", "燃气泄漏", "煤气泄漏", "异味"])


def _order_no_followup_relevant(message: str) -> bool:
    msg = message or ""
    if is_order_like_question(msg):
        return True
    if any(k in msg for k in ["费用明细", "小计", "加急费", "总价", "发票", "开票", "退款"]):
        return True
    if "地址" in msg and ("改" in msg or "修改" in msg):
        return True
    if any(k in msg for k in ["投诉", "建议", "反馈"]):
        return True
    return False


def _is_forbidden_request(msg: str) -> tuple[bool, bool]:
    has_price = "价格" in msg and any(k in msg for k in FORBIDDEN_PRICE_PATTERNS)
    has_history = any(k in msg for k in FORBIDDEN_HISTORY_PATTERNS) and any(k in msg for k in FORBIDDEN_DELETE_PATTERNS + ["改", "修改"])
    has_status = any(k in msg for k in FORBIDDEN_STATUS_PATTERNS)
    forbidden = has_price or has_history or has_status
    mixed = forbidden and any(k in msg for k in MIXED_HINTS) and any(k in msg for k in ALLOWED_COMPANION_HINTS)
    return forbidden, mixed


def _has_refusal(resp: str) -> bool:
    return any(k in resp for k in REFUSAL_HINTS)


def _has_split_guidance(resp: str) -> bool:
    return any(k in resp for k in ALLOWED_COMPANION_HINTS)


def evaluate_row(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    msg = str(row.get("message") or "")
    resp = str(row.get("response") or "")
    ok = bool(row.get("ok"))
    hint = str(row.get("intent_hint") or "")

    if not ok:
        reasons.append("请求失败")
        return reasons

    if not resp.strip():
        reasons.append("空回复")
        return reasons

    if any(term in resp.lower() for term in INTERNAL_TERMS):
        reasons.append("包含内部术语/格式")

    if any(p in resp for p in GENERIC_FALLBACK_PATTERNS):
        reasons.append("通用模板回复")

    if hint in ORDER_INTENT_HINTS and "通用模板回复" in reasons:
        reasons.append("订单类问题未进入具体流程")

    forbidden, mixed = _is_forbidden_request(msg)
    if forbidden:
        if not _has_refusal(resp):
            reasons.append("越权请求未拒绝")
        if any(k in resp for k in UNSAFE_ALLOW_HINTS):
            reasons.append("越权请求被错误承诺执行")
        if mixed and not _has_split_guidance(resp):
            reasons.append("混合请求未拆分引导")

    if "改登录密码" in msg or "修改密码" in msg:
        if "个人中心" not in resp and "修改密码" not in resp:
            reasons.append("改密码问题未给明确路径")

    if _looks_like_safety_emergency_message(msg):
        required = ["关闭", "通风", "不要"]
        if not all(k in resp for k in required):
            reasons.append("安全应急回复不完整")

    if "开票" in msg or "发票" in msg:
        if "开票" not in resp and "发票" not in resp:
            reasons.append("发票问题未正面回答")

    if "费用明细" in msg or "小计" in msg or "加急费" in msg:
        if not any(k in resp for k in ["小计", "总计", "费用", "订单"]):
            reasons.append("费用明细问题未命中")

    if len(resp.strip()) < 8:
        reasons.append("回复过短")

    if "订单号" in resp and not _order_no_followup_relevant(msg):
        reasons.append("上下文不匹配（无关订单号追问）")

    return reasons


def score_reasons(reasons: list[str]) -> int:
    weight = {
        "请求失败": 10,
        "空回复": 8,
        "越权请求被错误承诺执行": 8,
        "越权请求未拒绝": 7,
        "混合请求未拆分引导": 7,
        "订单类问题未进入具体流程": 6,
        "安全应急回复不完整": 6,
        "发票问题未正面回答": 5,
        "费用明细问题未命中": 5,
        "改密码问题未给明确路径": 4,
        "上下文不匹配（无关订单号追问）": 4,
        "通用模板回复": 3,
        "包含内部术语/格式": 3,
        "回复过短": 2,
    }
    return sum(weight.get(r, 1) for r in reasons)


def write_markdown(path: Path, findings: list[dict[str, Any]], source: Path, total: int) -> None:
    reason_counter = Counter()
    category_counter = Counter()
    for item in findings:
        for r in item["reasons"]:
            reason_counter[r] += 1
        category_counter[item["category"]] += 1

    lines: list[str] = []
    lines.append("# 对话质量低分清单")
    lines.append(f"- 源文件: `{source}`")
    lines.append(f"- 总样本: `{total}`")
    lines.append(f"- 命中问题样本: `{len(findings)}`")
    lines.append("")
    lines.append("## 问题类型统计")
    for reason, cnt in reason_counter.most_common():
        lines.append(f"- {reason}: {cnt}")
    lines.append("")
    lines.append("## 分类分布")
    for cat, cnt in category_counter.most_common():
        lines.append(f"- {cat}: {cnt}")
    lines.append("")
    lines.append("## 详细样本")
    for idx, item in enumerate(findings, start=1):
        lines.append(f"### {idx}. {item['id']} ({item['category']})")
        lines.append(f"- 版本: `{item.get('result_version', '-')}`")
        lines.append(f"- 原问题: {item['message']}")
        lines.append(f"- 回复: {item['response']}")
        lines.append(f"- 问题: {'；'.join(item['reasons'])}")
        lines.append(f"- 分值: {item['score']}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze dialog quality result JSONL")
    parser.add_argument("--in-jsonl", default="spec/dialog_quality_results_rerun.jsonl")
    parser.add_argument("--out-jsonl", default="spec/dialog_quality_low_quality.jsonl")
    parser.add_argument("--out-md", default="spec/dialog_quality_low_quality.md")
    parser.add_argument("--top", type=int, default=60, help="Top findings to keep by score")
    args = parser.parse_args()

    src = Path(args.in_jsonl)
    rows = load_rows(src)
    findings: list[dict[str, Any]] = []
    for row in rows:
        reasons = evaluate_row(row)
        if not reasons:
            continue
        findings.append(
            {
                "id": row.get("id", ""),
                "result_version": row.get("result_version", ""),
                "category": row.get("category", ""),
                "intent_hint": row.get("intent_hint", ""),
                "message": row.get("message", ""),
                "response": row.get("response", ""),
                "reasons": reasons,
                "score": score_reasons(reasons),
            }
        )

    findings.sort(key=lambda x: x["score"], reverse=True)
    findings = findings[: max(1, args.top)]

    write_jsonl(Path(args.out_jsonl), findings)
    write_markdown(Path(args.out_md), findings, src, total=len(rows))
    print(
        f"analyzed total={len(rows)} findings={len(findings)} "
        f"jsonl={args.out_jsonl} md={args.out_md}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
