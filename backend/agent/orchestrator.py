import json
import os
import re
import sys
from datetime import datetime

from django.db.models import Max
from django.utils import timezone
from langchain_core.messages import HumanMessage, SystemMessage

from agent.contract import AgentOutput, IntentEnum, RiskLevelEnum
from agent.forms import build_form
from agent.intent import intent_router
from agent.llm_router import LLMRouter, get_language_guard
from agent.prompts import (
    ASK_CREATE_ORDER_TEMPLATE,
    ASK_MODIFY_ADDRESS_TEMPLATE,
    ASK_QUERY_ORDER_TEMPLATE,
    ASK_TICKET_TEMPLATE,
    COMPLAINT_RESPONSE_TEMPLATE,
    DELIVERY_INFO_TEMPLATE,
    GREETING_RESPONSE_TEMPLATE,
    IDENTITY_RESPONSE_TEMPLATE,
    ORDER_RESPONSE_TEMPLATE,
    OUT_OF_SCOPE_RESPONSE,
    SAFETY_LOW_TEMPLATE,
    SAFETY_MEDIUM_TEMPLATE,
    SAFETY_RESPONSE_TEMPLATE,
    SAFETY_STEPS,
    SAFETY_WARNING,
    UNKNOWN_RESPONSE_TEMPLATE,
    URGE_EXPLAIN_TEMPLATE,
    URGE_RESPONSE_TEMPLATE,
    PROMPT_VERSION,
    SYSTEM_TEMPLATE_ID,
    build_system_prompt,
    build_writer_prompt,
)
from agent.rules import (
    OVERDUE_LEVEL_MILD,
    OVERDUE_LEVEL_SEVERE,
    OVERDUE_LEVEL_UNKNOWN,
    overdue_level,
    overdue_next_actions,
    status_display,
    status_explain,
    can_modify_address,
)
from agent.portal_orchestrator import run_portal_orchestrator, run_portal_orchestrator_legacy
from agent.tools import execute_tool
from core.models import AgentEvent


GREETING_KEYWORDS = ["你好", "您好", "在吗", "谢谢", "辛苦了", "早上好", "晚上好"]
IDENTITY_KEYWORDS = ["你是谁", "你能做什么", "怎么用", "你是什么"]
OUT_OF_SCOPE_KEYWORDS = ["财务", "报销", "比特币", "股票", "写诗", "天气", "政治", "明星"]

DELIVERY_INFO_KEYWORDS = [
    "怎么送燃气",
    "怎么配送",
    "配送流程",
    "送气流程",
    "多久能到",
    "配送时间",
    "上门配送",
]

ORDER_DOMAIN_KEYWORDS = [
    "订气",
    "下单",
    "订单",
    "改地址",
    "投诉",
    "催单",
    "配送",
    "送达",
    "退款",
    "工单",
]
ORDER_QUERY_KEYWORDS = ["查订单", "订单状态", "到哪了", "订单号", "查询订单", "物流", "订单到哪了"]
ORDER_CREATE_KEYWORDS = ["订气", "下单", "要几瓶", "送到哪里", "订购", "订一瓶", "送气"]
ORDER_MODIFY_KEYWORDS = ["改地址", "修改地址", "换地址", "地址改", "改到", "改为"]
SAFETY_BASE_KEYWORDS = ["燃气", "煤气", "天然气", "安全", "报警", "泄漏", "漏气", "异味"]

SAFETY_HIGH_KEYWORDS = [
    "泄漏",
    "漏气",
    "异味",
    "臭鸡蛋味",
    "报警器响",
    "报警器",
    "着火",
    "火灾",
    "爆炸",
    "昏迷",
    "中毒",
    "一氧化碳",
    "头晕",
    "恶心",
    "呼吸困难",
]
SAFETY_SMELL_KEYWORDS = ["异味", "臭鸡蛋味", "闻到味道", "闻到臭味", "煤气味"]
SAFETY_SELF_REPAIR_KEYWORDS = ["自己修", "自己换", "自己拧", "自己处理", "自行维修", "自行处理"]
SAFETY_MEDIUM_KEYWORDS = [
    "点火失败",
    "爆鸣",
    "火苗异常",
    "回火",
    "热水器",
    "通风",
    "软管松动",
    "减压阀异常",
]
SAFETY_LOW_KEYWORDS = [
    "软管多久换",
    "钢瓶放哪里",
    "厨房可以吗",
    "老人小孩",
    "日常检查",
    "注意事项",
]
SAFETY_SERVICE_KEYWORDS = ["预约安检", "上门安检", "上门检查", "上门看看", "预约上门", "上门检修"]

COMPLAINT_KEYWORDS = ["态度差", "投诉", "不满意", "服务差", "骂人", "迟到", "敷衍", "不礼貌"]
URGE_KEYWORDS = ["超时", "还没到", "催", "多久到", "送到哪了", "催单"]

ORDER_ALLOWED_FIELDS = [
    "order_id",
    "status",
    "product_type",
    "quantity",
    "address",
    "created_at",
    "eta",
]

STATUS_MAP = {
    "CREATED": "已创建",
    "CONFIRMED": "已确认",
    "DISPATCHED": "已出库/已安排配送",
    "DELIVERING": "配送中",
    "DONE": "已送达",
    "CANCELLED": "已取消",
}

STATUS_EXPLAIN = {
    "CREATED": "订单已提交，正在等待确认或分配。",
    "CONFIRMED": "订单已确认，正在安排配送。",
    "DISPATCHED": "通常表示师傅已接单，正在备货或在路上。",
    "DELIVERING": "师傅已出发或在路上，请保持电话畅通。",
    "DONE": "订单已完成，如有问题可随时反馈。",
    "CANCELLED": "订单已取消，如需恢复请重新下单或联系客服。",
}

CHINESE_NUM_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

def _contains_any(text, keywords):
    return any(keyword in text for keyword in keywords)


def _next_step_index(run):
    current = (
        AgentEvent.objects.filter(run=run).aggregate(Max("step_index")).get("step_index__max")
    )
    return (current or 0) + 1


def _append_event(run, state, input_json=None, output_json=None, tool_name=None, policy_result=None):
    # 中文注释：统一追加事件，保证链路可追溯
    if policy_result is None:
        policy_result = {"allow": True, "reasons": []}
    return AgentEvent.objects.create(
        run=run,
        step_index=_next_step_index(run),
        state=state,
        input_json=input_json,
        output_json=output_json,
        tool_name=tool_name,
        policy_result=policy_result,
        created_at=timezone.now(),
    )


def _call_tool(run, tool_name, tool_input):
    # 中文注释：工具调用前记录 EXEC_TOOL，真实执行由工具层写 TOOL_EXEC
    _append_event(run, AgentEvent.STATE_EXEC_TOOL, input_json=tool_input, tool_name=tool_name)
    return execute_tool(run, tool_name, tool_input)


def _get_llm(model_provider, api_keys=None, provider_config=None):
    # 中文注释：惰性初始化 LLM，并记录可用状态用于写作策略
    try:
        return (
            LLMRouter(
                model_provider, api_keys=api_keys, provider_config=provider_config
            ).get_llm(),
            {"available": True, "error": None},
        )
    except Exception as exc:
        return None, {"available": False, "error": str(exc)}


def _probe_llm_available(llm):
    # 中文注释：portal 模式的连通性探测由 API 层处理，这里仅保留兼容占位
    return True, None

def _english_ratio(text):
    # 中文注释：粗略判断英文占比，用于中文守门
    if not text:
        return 0.0
    total = sum(1 for ch in text if ch.strip())
    if total == 0:
        return 0.0
    english = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    return english / total


def _ensure_chinese(text, llm, fallback_text):
    # 中文注释：保障输出为中文，必要时触发一次改写
    if not text:
        return _sanitize_response(fallback_text)
    lower_text = text.lower()
    if _english_ratio(text) <= 0.2 and "i am" not in lower_text and "designed to" not in lower_text:
        return _sanitize_response(text)
    if llm is None:
        return _sanitize_response(fallback_text)
    prompt = f"{get_language_guard()} 请将下面内容改写为中文客服表达，保留信息，不新增内容。"
    try:
        response = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=text)])
    except Exception:
        return _sanitize_response(fallback_text)
    content = getattr(response, "content", response)
    if isinstance(content, str) and content.strip():
        return _sanitize_response(content.strip())
    return _sanitize_response(fallback_text)


def _sanitize_response(text):
    # 中文注释：清理不希望对用户展示的符号与标签
    if not text:
        return text
    cleaned = re.sub(r"【[^】]*】", "", str(text))
    cleaned = cleaned.replace("*", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_order_id(text):
    if not text:
        return None
    match = re.search(r"(?<!\d)(\d{6,10})(?!\d)", text)
    if not match:
        return None
    return int(match.group(1))


def _detect_provided_query(message, slots):
    # 中文注释：统一识别用户提供的查询条件，避免小模型反复索取信息
    order_id = slots.get("order_id") or _extract_order_id(message)
    if order_id:
        return {
            "type": "order_id",
            "value": str(order_id),
            "normalized": str(order_id),
            "is_valid": True,
        }
    phone = slots.get("phone") or slots.get("phone_masked") or slots.get("phone_last4")
    if not phone:
        phone = _extract_phone(message)
    if phone:
        normalized = re.sub(r"[^0-9]", "", phone)
        is_valid = len(normalized) == 11 or "*" in phone
        return {
            "type": "phone",
            "value": phone,
            "normalized": normalized or phone,
            "is_valid": is_valid,
        }
    return {
        "type": None,
        "value": None,
        "normalized": None,
        "is_valid": False,
    }


def _extract_phone(text):
    if not text:
        return None
    # 中文注释：优先返回完整手机号以降低冲突，已脱敏则保持原样
    masked = re.search(r"\d{3}\*{4}\d{4}", text)
    if masked:
        return masked.group(0)
    digits = re.search(r"(?<!\d)(\d{11})(?!\d)", text)
    if digits:
        return digits.group(1)
    parts = re.search(r"(?<!\d)(1\d{2})[-\s]?(\d{4})[-\s]?(\d{4})(?!\d)", text)
    if parts:
        return "".join(parts.groups())
    return None


def _extract_quantity(text):
    if not text:
        return None
    match = re.search(r"(\d+)\s*瓶", text)
    if not match:
        match = re.search(r"(\d+)\s*罐", text)
    if match:
        return int(match.group(1))
    match = re.search(r"([一二两三四五六七八九十])\s*瓶", text)
    if match:
        return CHINESE_NUM_MAP.get(match.group(1))
    return None


def _extract_product_type(text):
    if not text:
        return None
    if re.search(r"15\s*kg", text, re.IGNORECASE):
        return "15kg"
    if re.search(r"15\s*公斤", text):
        return "15kg"
    if re.search(r"5\s*kg", text, re.IGNORECASE):
        return "5kg"
    if re.search(r"5\s*公斤", text):
        return "5kg"
    return None


def _extract_address(text):
    if not text:
        return None
    markers = ["送到", "送至", "地址是", "地址为"]
    for marker in markers:
        if marker in text:
            value = text.split(marker, 1)[1].strip()
            return value or None
    match = re.search(r"([\\u4e00-\\u9fff0-9A-Za-z\\-]{4,}?(?:路|街|巷|号|小区|楼|单元|室|区|市).*)", text)
    if match:
        return match.group(1).strip()
    return None


def _extract_new_address(text):
    if not text:
        return None
    markers = ["改到", "改为", "地址改到", "地址改为"]
    for marker in markers:
        if marker in text:
            value = text.split(marker, 1)[1].strip()
            return value or None
    return None


def _is_order_domain(text):
    return _contains_any(text, ORDER_DOMAIN_KEYWORDS)


def _is_out_of_scope(text):
    # 中文注释：只有明确无关领域关键词且不包含订单/安全关键词时才超出范围
    if not _contains_any(text, OUT_OF_SCOPE_KEYWORDS):
        return False
    if _contains_any(text, ORDER_DOMAIN_KEYWORDS) or _contains_any(text, SAFETY_BASE_KEYWORDS):
        return False
    return True


def _safety_level(text):
    # 中文注释：安全问题按高/中/低分流
    if _contains_any(text, SAFETY_HIGH_KEYWORDS):
        return "HIGH"
    if _contains_any(text, SAFETY_MEDIUM_KEYWORDS):
        return "MEDIUM"
    if _contains_any(text, SAFETY_LOW_KEYWORDS):
        return "LOW"
    if _contains_any(text, SAFETY_BASE_KEYWORDS):
        return "LOW"
    return None


def _format_eta(iso_text):
    # 中文注释：将ISO时间转为易读中文格式，避免直接暴露ISO字符串
    if not iso_text:
        return "待确认"
    try:
        cleaned = iso_text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return f"{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}"
    except Exception:
        return "待确认"


def _parse_eta_datetime(iso_text):
    # 中文注释：解析预计时间为 datetime，便于超时判断
    if not iso_text:
        return None
    try:
        cleaned = iso_text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            return dt.astimezone()
        return dt
    except Exception:
        return None


def _format_overdue_delta(now, eta_dt):
    # 中文注释：将超时差值转为客服可读文本
    if not eta_dt or not now:
        return ""
    if eta_dt.tzinfo is None and now.tzinfo is not None:
        eta_dt = eta_dt.replace(tzinfo=now.tzinfo)
    delta = now - eta_dt
    minutes = int(delta.total_seconds() // 60)
    if minutes <= 0:
        return ""
    if minutes < 60:
        return f"已超过预计时间约{minutes}分钟"
    hours = minutes // 60
    remain = minutes % 60
    if remain == 0:
        return f"已超过预计时间约{hours}小时"
    return f"已超过预计时间约{hours}小时{remain}分钟"


def _is_confirm_message(text):
    # 中文注释：判断用户是否明确同意创建催单工单
    if not text:
        return False
    keywords = ["同意", "创建工单", "帮我催", "现在催", "立刻催", "要工单"]
    return any(keyword in text for keyword in keywords)


def _get_pending_action(run):
    # 中文注释：从最近事件中读取待确认动作，避免额外存储依赖
    last_event = AgentEvent.objects.filter(run=run).order_by("-step_index").first()
    if not last_event:
        return None
    output = last_event.output_json
    if isinstance(output, dict):
        return output.get("pending_action")
    return None


def _infer_issue_type(message):
    # 中文注释：根据投诉描述粗略推断问题类型
    text = message or ""
    if "态度" in text or "服务差" in text or "不礼貌" in text:
        return "态度问题"
    if "延误" in text or "超时" in text or "迟到" in text or "没到" in text:
        return "配送延误"
    if "费用" in text or "价格" in text or "收费" in text:
        return "费用争议"
    if "安全" in text or "泄漏" in text or "漏气" in text:
        return "安全隐患"
    return None


def _extract_phone_last4(text):
    # 中文注释：优先提取完整手机号，其次使用后四位，便于表单预填
    if not text:
        return None
    full = re.search(r"(?<!\d)(\d{11})(?!\d)", text)
    if full:
        return full.group(1)
    match = re.search(r"(\d{4})$", text)
    return match.group(1) if match else None


def _get_form_fixed_response(form_id):
    # 中文注释：表单场景使用固定文案，避免小模型重复追问字段
    mapping = {
        "order_query_v1": (
            "您好，为了帮您准确查询订单，请提供订单号或下单手机号之一。"
            "如果您不确定，我可以先帮您列最近订单。"
        ),
        "order_create_v1": (
            "您好，为了尽快为您下单，请告诉我服务类型、规格、数量和地址。"
            "我会逐项补全并在执行前向您确认。"
        ),
        "ticket_complaint_v1": (
            "您好，请描述投诉问题（可附订单号）。"
            "我会先整理摘要并在您确认后提交。"
        ),
        "order_modify_address_v1": (
            "您好，请告诉我订单号和新地址。"
            "我会先核对可改址条件，再请您确认执行。"
        ),
        "order_urge_confirm_v1": (
            "您好，如需催单请回复“确认催单”。"
            "我会在您确认后创建催单工单。"
        ),
        "safety_service_request_v1": (
            "您好，请提供安检地址、联系人和预约时间。"
            "我会整理后给您确认，再提交预约。"
        ),
    }
    return mapping.get(form_id, "您好，请继续补充关键信息，我会在执行前向您确认。")


def _respond_with_form(
    run,
    llm,
    intent,
    message,
    form_id,
    prefill,
    missing_fields,
    required_structure,
    base_response,
    risk_level=RiskLevelEnum.LOW,
    need_human=False,
    extra_payload=None,
):
    # 中文注释：表单场景使用固定回复，避免模型自由发挥
    form = build_form(form_id, prefill)
    fixed_response = _get_form_fixed_response(form_id)
    planning_output = {
        "ui_action": "SHOW_FORM",
        "form_id": form_id,
        "prefill": prefill,
        "missing_fields": missing_fields,
    }
    if extra_payload:
        if "order_query_state" in extra_payload:
            planning_output["order_query_state"] = extra_payload.get("order_query_state")
        if "provided_query" in extra_payload:
            planning_output["provided_query"] = extra_payload.get("provided_query")
        if "identity_verified" in extra_payload:
            planning_output["identity_verified"] = extra_payload.get("identity_verified")
    _append_event(run, AgentEvent.STATE_PLANNING, output_json=planning_output)
    payload = {
        "user_message": message,
        "intent": intent.value,
        "tool_results": {},
        "kb_snippets": [],
        "required_structure": required_structure,
        "show_form": True,
        "route": "form",
        "missing_fields": missing_fields,
        "writer_variant": "small",
    }
    if extra_payload:
        payload.update(extra_payload)
    final_response = _write_response(None, payload, fixed_response, fixed_response)
    final_response = _ensure_chinese(final_response, llm, fixed_response)
    _append_response_event(
        run,
        final_response,
        payload=payload,
        kb_results=None,
        extra={"ui_action": "SHOW_FORM", "form_id": form_id},
    )
    _append_event(run, AgentEvent.STATE_DONE)
    return AgentOutput(
        intent=intent,
        tool_calls=[],
        final_response=final_response,
        risk_level=risk_level,
        need_human=need_human,
        ui_action="SHOW_FORM",
        form=form,
    )


def _parse_form_submission(message):
    # 中文注释：解析“提交表单：{...}”格式的提交内容
    if not message:
        return None
    prefixes = ["提交表单：", "提交表单:"]
    for prefix in prefixes:
        if message.startswith(prefix):
            json_text = message.split(prefix, 1)[1].strip()
            try:
                payload = json.loads(json_text)
            except Exception:
                return None
            if not isinstance(payload, dict):
                return None
            form_id = payload.get("form_id")
            data = payload.get("data") or payload.get("payload")
            if not form_id or not isinstance(data, dict):
                return None
            return form_id, data
    return None


def _map_issue_type_to_category(issue_type):
    # 中文注释：将表单中的问题类型映射到工单分类
    mapping = {
        "态度问题": "SERVICE_ISSUE",
        "配送延误": "DELIVERY_DELAY",
        "费用争议": "REFUND",
        "安全隐患": "GAS_LEAK",
    }
    return mapping.get(issue_type, "OTHER")


def _handle_form_submission(run, message, user_id, llm, required_structure, form_id, data):
    # 中文注释：表单提交转为工具调用，保持链路可回放
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={"route": "form_submit", "form_id": form_id},
    )
    if form_id == "order_create_v1":
        if not user_id:
            base_response = "提交下单表单仍需要用户ID，请提供用户ID后再试。"
            return AgentOutput(
                intent=IntentEnum.CREATE_ORDER,
                tool_calls=[],
                final_response=base_response,
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )
        tool_output = _call_tool(
            run,
            "create_order",
            {
                "user_id": user_id,
                "product_type": data.get("cylinder_type") or "15kg",
                "quantity": data.get("quantity"),
                "address": data.get("address"),
            },
        )
        order_id = tool_output.get("order_id")
        base_response = f"订单已创建，订单号{order_id}。" if order_id else "订单已创建。"
        payload = {
            "user_message": message,
            "intent": IntentEnum.CREATE_ORDER.value,
            "tool_results": {"create_order": tool_output},
            "kb_snippets": [],
            "required_structure": required_structure,
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.CREATE_ORDER,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if form_id == "ticket_complaint_v1":
        if not user_id:
            base_response = "提交投诉需要用户ID，请提供用户ID后再试。"
            return AgentOutput(
                intent=IntentEnum.CREATE_TICKET,
                tool_calls=[],
                final_response=base_response,
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )
        category = _map_issue_type_to_category(data.get("issue_type"))
        tool_output = _call_tool(
            run,
            "create_ticket",
            {
                "user_id": user_id,
                "order_id": data.get("related_order_id"),
                "category": category,
                "description": data.get("description") or "投诉工单",
            },
        )
        ticket_id = tool_output.get("ticket_id")
        base_response = f"投诉工单已创建，工单号{ticket_id}。" if ticket_id else "投诉工单已创建。"
        payload = {
            "user_message": message,
            "intent": IntentEnum.CREATE_TICKET.value,
            "tool_results": {"create_ticket": tool_output},
            "kb_snippets": [],
            "required_structure": required_structure,
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.CREATE_TICKET,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if form_id == "order_modify_address_v1":
        tool_output = _call_tool(
            run,
            "modify_order_address",
            {"order_id": data.get("order_id"), "new_address": data.get("new_address")},
        )
        base_response = tool_output.get("message") or "地址已更新。"
        if tool_output.get("error"):
            base_response = "地址修改失败，请核对订单号或地址。"
        payload = {
            "user_message": message,
            "intent": IntentEnum.MODIFY_ORDER.value,
            "tool_results": {"modify_order_address": tool_output},
            "kb_snippets": [],
            "required_structure": required_structure,
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.MODIFY_ORDER,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if form_id == "order_urge_confirm_v1":
        order_id = data.get("order_id")
        if not order_id:
            base_response = "催单需要订单号，请补充后再试。"
            return AgentOutput(
                intent=IntentEnum.QUERY_ORDER,
                tool_calls=[],
                final_response=base_response,
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )
        description = f"催单工单，订单{order_id}，原因：{data.get('urge_reason') or '已超时'}"
        tool_output = _call_tool(
            run,
            "create_ticket",
            {
                "user_id": user_id,
                "order_id": order_id,
                "category": "DELIVERY_DELAY",
                "description": description,
            },
        )
        ticket_id = tool_output.get("ticket_id")
        base_response = f"已为您创建催单工单，工单号{ticket_id}。" if ticket_id else "已为您创建催单工单。"
        payload = {
            "user_message": message,
            "intent": IntentEnum.QUERY_ORDER.value,
            "tool_results": {"create_ticket": tool_output},
            "kb_snippets": [],
            "required_structure": required_structure,
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.QUERY_ORDER,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if form_id == "order_query_v1":
        query_type = data.get("query_type")
        if query_type == "订单号" and data.get("order_id"):
            tool_output = _call_tool(run, "query_order", {"order_id": data.get("order_id")})
            tool_results = {"query_order": tool_output}
            summary = None
            if tool_output and tool_output.get("order_id"):
                summary = _summarize_order(tool_output)
            base_response = ORDER_RESPONSE_TEMPLATE.format(
                status_text=(summary or {}).get("status_text", "未知状态"),
                eta_text=(summary or {}).get("eta_text", "待确认"),
            ) if summary else "未查询到有效订单，请核对订单号。"
        else:
            phone_value = data.get("phone") or data.get("phone_last4")
            tool_output = _call_tool(
                run,
                "external_query_orders_by_phone",
                {"phone": phone_value, "limit": 20},
            )
            tool_results = {"external_query_orders_by_phone": tool_output}
            results = tool_output.get("results", []) if isinstance(tool_output, dict) else []
            if results:
                lines = []
                for index, item in enumerate(results, start=1):
                    status_text = status_display(item.get("status"))
                    eta_text = _format_eta(item.get("eta") or item.get("created_at"))
                    lines.append(
                        f"{index}. 订单号 {item.get('order_id')} | {status_text} | 预计 {eta_text}"
                    )
                base_response = (
                    f"为您找到{len(results)}笔订单，已为您整理如下：\n"
                    "订单列表：\n"
                    + "\n".join(lines)
                    + "\n如需查看某一笔详情，请告知订单号。"
                )
            else:
                base_response = "未查询到有效订单，请核对手机号。"
        payload = {
            "user_message": message,
            "intent": IntentEnum.QUERY_ORDER.value,
            "tool_results": tool_results,
            "kb_snippets": [],
            "required_structure": required_structure,
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.QUERY_ORDER,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if form_id == "safety_service_request_v1":
        if not user_id:
            base_response = "预约安全服务需要用户ID，请提供用户ID后再试。"
            return AgentOutput(
                intent=IntentEnum.SAFETY_GUIDE,
                tool_calls=[],
                final_response=base_response,
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )
        description = data.get("issue_description") or "安全服务预约"
        tool_output = _call_tool(
            run,
            "create_ticket",
            {
                "user_id": user_id,
                "order_id": None,
                "category": "OTHER",
                "description": description,
            },
        )
        ticket_id = tool_output.get("ticket_id")
        base_response = f"已为您提交预约需求，工单号{ticket_id}。" if ticket_id else "已为您提交预约需求。"
        payload = {
            "user_message": message,
            "intent": IntentEnum.SAFETY_GUIDE.value,
            "tool_results": {"create_ticket": tool_output},
            "kb_snippets": [],
            "required_structure": required_structure,
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.SAFETY_GUIDE,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    base_response = "表单提交已收到，但未识别表单类型。"
    return AgentOutput(
        intent=IntentEnum.UNKNOWN,
        tool_calls=[],
        final_response=base_response,
        risk_level=RiskLevelEnum.LOW,
        need_human=False,
    )

def _summarize_order(order_payload):
    # 中文注释：生成订单摘要，供回复写作器使用
    status_raw = order_payload.get("status") if isinstance(order_payload, dict) else None
    status_text = status_display(status_raw)
    eta_text = _format_eta(order_payload.get("eta") or order_payload.get("created_at"))
    return {
        "order_id": order_payload.get("order_id"),
        "status_raw": status_raw,
        "status_text": status_text,
        "status_explain": status_explain(status_raw),
        "eta_text": f"{eta_text}（本地时间）",
    }


def _collect_kb_snippets(kb_results, limit=3):
    snippets = []
    for item in kb_results or []:
        for bullet in item.get("bullets", []):
            if bullet and bullet not in snippets:
                snippets.append(bullet)
            if len(snippets) >= limit:
                return snippets
    return snippets


def _collect_kb_refs(kb_results):
    # ??????????? KB ?????doc_id/source/title?
    refs = []
    seen = set()
    for item in kb_results or []:
        meta = item.get("meta") or {}
        doc_id = item.get("doc_id")
        source = meta.get("source")
        key = (doc_id, source)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "doc_id": doc_id,
                "source": source,
                "title": item.get("title"),
                "domain": item.get("domain"),
            }
        )
    return refs


def _infer_tools_used(tool_results):
    # ?????? tool_results ????????????????
    if not isinstance(tool_results, dict):
        return []
    mapping = {
        "internal": "query_order",
        "external": "external_query_order",
        "external_list": "external_query_orders_by_phone",
        "create_ticket": "create_ticket",
        "create_order": "create_order",
        "modify_order_address": "modify_order_address",
        "kb_results": "kb_search",
    }
    tools = []
    for key in tool_results.keys():
        mapped = mapping.get(key, key)
        if mapped not in tools:
            tools.append(mapped)
    return tools


def _build_prompt_context(
    intent,
    route=None,
    safety_level=None,
    show_form=False,
    kb_results=None,
    writer_variant="small",
):
    # ??????????????????
    return {
        "intent": intent,
        "route": route,
        "safety_level": safety_level,
        "show_form": show_form,
        "has_kb": bool(kb_results),
        "writer_variant": writer_variant,
    }


def _payload_to_facts(payload):
    # 中文注释：将payload整理为“已知事实列表”，避免小模型理解JSON失败
    facts = []
    if not isinstance(payload, dict):
        return "已知事实列表：暂无。"
    user_message = payload.get("user_message")
    if user_message:
        facts.append(f"用户问题：{user_message}")
    intent = payload.get("intent")
    if intent:
        facts.append(f"意图：{intent}")
    route = payload.get("route")
    if route:
        facts.append(f"处理路径：{route}")
    order_query_state = payload.get("order_query_state")
    if order_query_state:
        facts.append(f"订单查询状态：{order_query_state}")
    provided_query = payload.get("provided_query")
    if isinstance(provided_query, dict) and provided_query.get("type"):
        facts.append(
            "查询条件：{qtype} {value}".format(
                qtype=provided_query.get("type"),
                value=provided_query.get("value"),
            )
        )
    identity_verified = payload.get("identity_verified")
    if identity_verified is not None:
        facts.append(f"身份已验证：{bool(identity_verified)}")
    allowed_fields = payload.get("allowed_fields")
    if allowed_fields:
        facts.append(f"允许展示字段：{','.join(allowed_fields)}")
    safety_level = payload.get("safety_level")
    if safety_level:
        facts.append(f"安全等级：{safety_level}")
    if payload.get("show_form"):
        facts.append("需要用户补充信息并填写表单")
    missing_fields = payload.get("missing_fields")
    if missing_fields:
        facts.append("缺失信息：" + "、".join(missing_fields))
    tool_summary = payload.get("tool_results_summary")
    if isinstance(tool_summary, dict):
        order_id = tool_summary.get("order_id")
        if order_id:
            facts.append(f"订单号：{order_id}")
        status_text = tool_summary.get("status_text")
        if status_text:
            facts.append(f"状态：{status_text}")
        status_explain = tool_summary.get("status_explain")
        if status_explain:
            facts.append(f"状态说明：{status_explain}")
        eta_text = tool_summary.get("eta_text")
        if eta_text:
            facts.append(f"预计时间：{eta_text}")
        overdue_note = tool_summary.get("overdue_note")
        if overdue_note:
            facts.append(f"超时情况：{overdue_note}")
        next_actions = tool_summary.get("next_actions")
        if next_actions:
            facts.append(f"建议动作：{next_actions}")
    kb_snippets = payload.get("kb_snippets") or []
    if kb_snippets:
        facts.append("KB要点：" + "；".join(kb_snippets))
    fixed_phrases = payload.get("fixed_phrases")
    if fixed_phrases:
        facts.append("固定话术：" + fixed_phrases)
    if not facts:
        return "已知事实列表：暂无。"
    return "已知事实列表：\n- " + "\n- ".join(facts)






def _append_response_event(run, final_response, payload=None, kb_results=None, extra=None):
    # ????????? RESPOND ??????????? KB ??
    prompt_meta = {}
    if isinstance(payload, dict):
        prompt_meta = payload.get("_prompt_meta") or {}
    output = {"final_response": final_response, "prompt": prompt_meta}
    if payload is not None:
        output["tools_used"] = _infer_tools_used(payload.get("tool_results"))
        if kb_results is None:
            kb_results = payload.get("kb_results")
    if kb_results is not None:
        output["kb_refs"] = _collect_kb_refs(kb_results)
    if extra:
        output.update(extra)
    _append_event(run, AgentEvent.STATE_RESPOND, output_json=output)




def _get_emergency_phone(kb_results=None):
    # ????????? KB ?????????
    for item in kb_results or []:
        meta = item.get("meta") or {}
        if meta.get("emergency_phone"):
            return meta.get("emergency_phone")
        if meta.get("hotline"):
            return meta.get("hotline")
    return os.getenv("EMERGENCY_PHONE") or "XXX-XXXXXXX"


def _get_service_hotline(kb_results=None):
    # ????????? KB ?????????
    for item in kb_results or []:
        meta = item.get("meta") or {}
        if meta.get("service_hotline"):
            return meta.get("service_hotline")
    return os.getenv("SERVICE_HOTLINE") or "400-XXX-XXXX"



def _write_response(llm, payload, fixed_phrases, fallback_text, prompt_context=None):
    # ??????LLM?????????????????
    payload = dict(payload)
    payload["fixed_phrases"] = fixed_phrases
    payload["llm_available"] = llm is not None
    if "kb_results" not in payload and isinstance(payload.get("tool_results"), dict):
        if "kb_results" in payload["tool_results"]:
            payload["kb_results"] = payload["tool_results"]["kb_results"]
    if prompt_context is None:
        prompt_context = _build_prompt_context(
            payload.get("intent"),
            route=payload.get("route"),
            safety_level=payload.get("safety_level"),
            show_form=payload.get("show_form", False),
            kb_results=payload.get("kb_results"),
            writer_variant=payload.get("writer_variant", "small"),
        )
    writer_prompt, writer_template = build_writer_prompt(_payload_to_facts(payload), prompt_context)
    system_prompt = build_system_prompt(prompt_context)
    prompt_meta = {
        "version": PROMPT_VERSION,
        "system_template": SYSTEM_TEMPLATE_ID,
        "writer_template": writer_template,
    }
    payload["_prompt_meta"] = prompt_meta
    # 中文注释：高风险场景优先使用固定应急话术，避免模型遗漏关键信息
    if prompt_context.get("safety_level") == "HIGH":
        return _sanitize_response(fixed_phrases)
    if llm is None:
        return _sanitize_response(fallback_text)
    try:
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=writer_prompt),
            ]
        )
    except Exception:
        return fallback_text
    content = getattr(response, "content", response)
    if isinstance(content, str) and content.strip():
        text = content.strip()
        order_query_state = payload.get("order_query_state")
        if order_query_state and order_query_state != "NEED_MORE_INFO":
            forbidden = ["请提供订单号", "请提供手机号", "订单号或手机号"]
            if any(item in text for item in forbidden):
                return _sanitize_response(fallback_text)
        if prompt_context.get("safety_level") in {"MEDIUM", "LOW"}:
            forbidden = ["订单", "查单", "手机号", "订单号"]
            if any(item in text for item in forbidden):
                return _sanitize_response(fallback_text)
        if text == fallback_text.strip():
            # 中文注释：避免模型直接复用模板，尝试轻量改写一次
            rewrite_prompt = (
                "请在保持信息一致的前提下，用更自然的客服口吻重写下面内容，"
                "避免逐字复述原文：\n"
                f"{text}"
            )
            try:
                rewrite_response = llm.invoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=rewrite_prompt),
                    ]
                )
                rewrite_text = getattr(rewrite_response, "content", rewrite_response)
                if isinstance(rewrite_text, str) and rewrite_text.strip():
                    return _sanitize_response(rewrite_text.strip())
            except Exception:
                return _sanitize_response(text)
        return _sanitize_response(text)
    return _sanitize_response(fallback_text)


def _build_low_fallback_tips(message):
    # 中文注释：针对不同问题给出差异化低风险要点
    if "软管" in message:
        return [
            "发现老化、龟裂应立即更换",
            "软管长度不宜过长，避免扭曲挤压",
            "使用卡箍固定，定期检查是否松动",
        ]
    if "钢瓶" in message or "厨房" in message:
        return [
            "放置在通风良好的位置",
            "远离明火和热源",
            "保持直立放置，避免倾倒",
        ]
    if "老人" in message or "小孩" in message:
        return [
            "避免让儿童接触阀门和灶具",
            "使用后及时关闭阀门",
            "提醒老人注意通风与看护",
        ]
    return [
        "保持通风良好",
        "定期检查软管与阀门",
        "发现异常立即停止使用",
    ]


def _build_medium_fallback_tips(message):
    # 中文注释：针对不同问题给出差异化中风险要点
    if "点火失败" in message:
        return [
            "确认气源是否开启",
            "保持通风后再尝试点火",
            "多次失败请停止使用并报修",
        ]
    if "火苗" in message or "回火" in message:
        return [
            "火苗异常先停止使用",
            "检查灶具周围是否有异物",
            "不要自行拆卸，联系专业人员",
        ]
    if "热水器" in message:
        return [
            "保持通风良好",
            "检查排烟是否通畅",
            "异常报警请停止使用并报修",
        ]
    return [
        "先停止使用并保持通风",
        "观察异常现象是否持续",
        "联系专业人员上门检查",
    ]

def run_orchestrator(
    run,
    message,
    user_id,
    model_provider,
    api_keys=None,
    provider_config=None,
    runtime_context=None,
):
    portal_mode = (runtime_context or {}).get("portal_mode") if isinstance(runtime_context, dict) else False
    portal_user_id = (runtime_context or {}).get("portal_user_id") if isinstance(runtime_context, dict) else None
    portal_tone_style = (runtime_context or {}).get("portal_tone_style") if isinstance(runtime_context, dict) else "neutral"
    portal_rag_config = (runtime_context or {}).get("portal_rag_config") if isinstance(runtime_context, dict) else None
    portal_memory = (runtime_context or {}).get("portal_memory") if isinstance(runtime_context, dict) else None
    portal_model_reachable = (runtime_context or {}).get("portal_model_reachable", True) if isinstance(runtime_context, dict) else True
    portal_route_mode = (runtime_context or {}).get("route_mode", "v2") if isinstance(runtime_context, dict) else "v2"
    portal_write_allowed = (runtime_context or {}).get("write_allowed", True) if isinstance(runtime_context, dict) else True
    portal_degraded_reason = (runtime_context or {}).get("degraded_reason") if isinstance(runtime_context, dict) else None
    portal_model_source = (runtime_context or {}).get("portal_model_source", "none") if isinstance(runtime_context, dict) else "none"
    if portal_mode:
        if not portal_user_id:
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                input_json={"message": message, "portal_mode": True},
                output_json={"route": "portal_mode_auth_required"},
                policy_result={"allow": True, "reasons": ["portal_mode"]},
            )
            final_response = "请先登录企业用户账号后，再使用聊天代操作。"
            _append_response_event(
                run,
                final_response,
                payload={
                    "route": "portal_mode_auth_required",
                    "tool_results": {},
                    "required_structure": "称呼 + 一句话结论 → 关键说明 → 重要提醒 → 下一步建议 → 关怀句",
                },
            )
            _append_event(run, AgentEvent.STATE_DONE)
            return AgentOutput(
                intent=IntentEnum.UNKNOWN,
                tool_calls=[],
                final_response=final_response,
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
                routing={
                    "mode": portal_route_mode or "v2",
                    "lane": "fallback_readonly",
                    "model_source": "none",
                    "write_allowed": False,
                    "degraded_reason": "auth_required",
                },
            )
        def _run_portal_reply(llm_instance, *, write_allowed=None, degraded_reason=None, model_source=None):
            effective_write_allowed = portal_write_allowed if write_allowed is None else bool(write_allowed)
            effective_reason = degraded_reason if degraded_reason is not None else portal_degraded_reason
            effective_model_source = model_source or portal_model_source or "none"
            if str(portal_route_mode or "").lower() == "legacy":
                return run_portal_orchestrator_legacy(
                    run,
                    message,
                    portal_user_id,
                    llm=llm_instance,
                    tone_style=portal_tone_style or "neutral",
                    rag_config=portal_rag_config,
                    memory=portal_memory,
                )
            return run_portal_orchestrator(
                run,
                message,
                portal_user_id,
                llm=llm_instance,
                tone_style=portal_tone_style or "warm",
                rag_config=portal_rag_config,
                memory=portal_memory,
                route_mode=portal_route_mode or "v2",
                write_allowed=effective_write_allowed,
                degraded_reason=effective_reason,
                model_source=effective_model_source,
            )

        if "test" in sys.argv:
            return _run_portal_reply(
                llm_instance=None,
                write_allowed=portal_write_allowed,
                degraded_reason=portal_degraded_reason,
                model_source=portal_model_source or "none",
            )
        if not portal_model_reachable:
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                input_json={"message": message, "portal_mode": True},
                output_json={"route": "portal_mode_model_unavailable_degrade"},
                policy_result={"allow": True, "reasons": ["model_unavailable_degrade"]},
            )
            return _run_portal_reply(
                llm_instance=None,
                write_allowed=False,
                degraded_reason=portal_degraded_reason or "local_model_unavailable",
                model_source="none",
            )
        portal_llm, portal_llm_meta = _get_llm(
            model_provider, api_keys=api_keys, provider_config=provider_config
        )
        if not portal_llm_meta.get("available"):
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                input_json={"message": message, "portal_mode": True},
                output_json={
                    "route": "portal_mode_model_unavailable",
                    "llm_error": portal_llm_meta.get("error"),
                },
                policy_result={"allow": True, "reasons": ["model_unavailable_degrade"]},
            )
            return _run_portal_reply(
                llm_instance=None,
                write_allowed=False,
                degraded_reason=portal_degraded_reason or "cloud_llm_unavailable",
                model_source="none",
            )
        probe_ok, probe_error = _probe_llm_available(portal_llm)
        if not probe_ok:
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                input_json={"message": message, "portal_mode": True},
                output_json={
                    "route": "portal_mode_model_probe_failed",
                    "llm_error": probe_error,
                },
                policy_result={"allow": True, "reasons": ["model_probe_failed_degrade"]},
            )
            return _run_portal_reply(
                llm_instance=None,
                write_allowed=False,
                degraded_reason=portal_degraded_reason or "cloud_probe_failed",
                model_source="none",
            )
        return _run_portal_reply(
            llm_instance=portal_llm,
            write_allowed=portal_write_allowed,
            degraded_reason=portal_degraded_reason,
            model_source=portal_model_source or "cloud",
        )

    route_info = intent_router(message)
    intent_name = route_info.get("intent")
    slots = route_info.get("slots") or {}
    confidence = route_info.get("confidence", 0.0)
    route_reason = route_info.get("route_reason", "")
    pending_action = _get_pending_action(run)
    confirm_action = False
    if (
        intent_name == "UNKNOWN"
        and pending_action
        and pending_action.get("type") == "CREATE_TICKET"
        and _is_confirm_message(message)
    ):
        # 中文注释：用户确认催单时，覆盖为催单意图以执行工单流程
        confirm_action = True
        intent_name = "ORDER_URGE"
        slots = {"order_id": pending_action.get("order_id")}
        confidence = max(confidence, 0.8)
        route_reason = "confirm pending_action create_ticket"

    if intent_name == "UNKNOWN":
        fallback_query = _detect_provided_query(message, slots)
        if fallback_query.get("is_valid"):
            intent_name = "ORDER_QUERY"
            slots.update({"order_id": _extract_order_id(message), "phone": _extract_phone(message)})
            confidence = max(confidence, 0.6)
            route_reason = "fallback_query_identifier"

    intent = IntentEnum.UNKNOWN
    route = "unknown_in_scope"
    data = {}
    phone_value = slots.get("phone") or slots.get("phone_masked") or slots.get("phone_last4")

    if intent_name == "SAFETY_HIGH":
        intent = IntentEnum.SAFETY_GUIDE
        route = "safety"
        data = {"level": "HIGH"}
    elif intent_name == "SAFETY_LOW":
        intent = IntentEnum.SAFETY_GUIDE
        route = "safety"
        data = {"level": "LOW"}
    elif intent_name == "ORDER_MODIFY_ADDRESS":
        intent = IntentEnum.MODIFY_ORDER
        route = "modify_address"
        data = {"order_id": slots.get("order_id"), "new_address": slots.get("new_address")}
    elif intent_name == "TICKET_COMPLAINT":
        intent = IntentEnum.CREATE_TICKET
        route = "complaint"
        data = {"order_id": slots.get("order_id"), "description": message}
    elif intent_name == "ORDER_URGE":
        intent = IntentEnum.QUERY_ORDER
        route = "urge"
        data = {
            "order_id": slots.get("order_id"),
            "phone": phone_value,
            "pending_action": pending_action,
            "confirm_action": confirm_action,
        }
    elif intent_name == "ORDER_QUERY":
        intent = IntentEnum.QUERY_ORDER
        route = "query_order"
        data = {"order_id": slots.get("order_id"), "phone": phone_value}
    elif intent_name == "ORDER_CREATE":
        intent = IntentEnum.CREATE_ORDER
        route = "create_order"
        data = {
            "quantity": slots.get("quantity"),
            "address": slots.get("address"),
            "product_type": slots.get("cylinder_type"),
        }
    elif intent_name == "IDENTITY":
        route = "identity"
    elif intent_name == "GREETING":
        route = "greeting"
    elif intent_name == "OUT_OF_SCOPE":
        route = "out_of_scope"

    llm, llm_meta = _get_llm(
        model_provider, api_keys=api_keys, provider_config=provider_config
    )
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        input_json={"message": message, "user_id": user_id},
        output_json={
            "route": "rule_intent_router",
            "intent": intent_name,
            "confidence": confidence,
            "slots": slots,
            "route_reason": route_reason,
            "llm_available": llm_meta.get("available"),
            "llm_error": llm_meta.get("error"),
        },
    )

    if route == "out_of_scope":
        final_response = OUT_OF_SCOPE_RESPONSE
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": {},
            "kb_snippets": [],
            "required_structure": "称呼 + 一句话结论 → 关键说明 → 重要提醒 → 下一步建议 → 关怀句",
            "route": "out_of_scope",
        }
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.UNKNOWN,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    required_structure = "称呼 + 一句话结论 → 关键说明 → 重要提醒 → 下一步建议 → 关怀句"

    form_submission = _parse_form_submission(message)
    if form_submission:
        form_id, data = form_submission
        return _handle_form_submission(
            run,
            message,
            user_id,
            llm,
            required_structure,
            form_id,
            data,
        )

    if _contains_any(message or "", SAFETY_SERVICE_KEYWORDS) and intent_name != "SAFETY_HIGH":
        prefill = {
            "address": _extract_address(message),
            "issue_description": message,
            "contact_phone_last4": _extract_phone_last4(message),
        }
        missing_fields = []
        if not prefill.get("address"):
            missing_fields.append("address")
        if not prefill.get("issue_description"):
            missing_fields.append("issue_description")
        return _respond_with_form(
            run,
            llm,
            IntentEnum.SAFETY_GUIDE,
            message,
            "safety_service_request_v1",
            prefill,
            missing_fields,
            required_structure,
            "已为您生成安全服务预约表单，请填写后提交。",
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if route == "greeting":
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": {},
            "kb_snippets": [],
            "required_structure": required_structure,
            "route": "greeting",
        }
        base_response = GREETING_RESPONSE_TEMPLATE
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.UNKNOWN,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if route == "identity":
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": {},
            "kb_snippets": [],
            "required_structure": required_structure,
            "route": "identity",
        }
        base_response = IDENTITY_RESPONSE_TEMPLATE
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.UNKNOWN,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if route == "delivery_info":
        kb_results = []
        try:
            kb_output = _call_tool(
                run,
                "kb_search",
                {"domain": "biz", "query": message, "top_k": 4},
            )
            if isinstance(kb_output, dict):
                kb_results = kb_output.get("results", [])
        except Exception:
            kb_results = []
        kb_snippets = _collect_kb_snippets(kb_results, limit=3)
        base_response = DELIVERY_INFO_TEMPLATE
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": {"kb_results": kb_results},
            "kb_snippets": kb_snippets,
            "required_structure": required_structure,
            "route": "delivery_info",
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.UNKNOWN,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if route == "safety":
        level = data.get("level", "LOW")
        kb_results = []
        if level in {"MEDIUM", "LOW"}:
            try:
                kb_output = _call_tool(
                    run,
                    "kb_search",
                    {"domain": "safety", "query": message, "top_k": 4},
                )
                if isinstance(kb_output, dict):
                    kb_results = kb_output.get("results", [])
            except Exception:
                kb_results = []
        kb_snippets = _collect_kb_snippets(kb_results, limit=3)

        if level == "HIGH":
            steps_text = "；".join(SAFETY_STEPS)
            emergency_phone = _get_emergency_phone(kb_results)
            warning_text = SAFETY_WARNING.format(emergency_phone=emergency_phone)
            base_body = SAFETY_RESPONSE_TEMPLATE.format(
                steps=steps_text, warning=warning_text
            )
            is_self_repair = _contains_any(message or "", SAFETY_SELF_REPAIR_KEYWORDS)
            is_smell = _contains_any(message or "", SAFETY_SMELL_KEYWORDS)
            is_mixed = _contains_any(message or "", ORDER_DOMAIN_KEYWORDS)
            if is_self_repair:
                intro = (
                    "不建议、也不要自行拧紧或拆装软管与阀门。"
                    "轻微漏气也可能因火花引发事故。请先按下面步骤处理，确保人身安全。"
                )
                safety_subtype = "HIGH_SELF_REPAIR"
            elif is_mixed:
                intro = "先处理安全：疑似漏气时请立即按下面步骤处置。确认安全后我再帮您查订单。"
                safety_subtype = "HIGH_MIXED"
            elif is_smell:
                intro = "您描述的是明显燃气异味，可能存在泄漏风险。请先按下面步骤处理，确保人身安全。"
                safety_subtype = "HIGH_SMELL"
            else:
                intro = "这属于高风险安全情况，请先按下面步骤处理，确保人身安全。"
                safety_subtype = "HIGH_GENERAL"
            base_response = f"{intro}{base_body}"
            if _contains_any(message or "", ["昏迷", "呼吸困难"]):
                base_response = (
                    f"{base_response} 如有人昏迷或呼吸困难，请立刻拨打120，"
                    "将患者转移到通风处，必要时在专业人员指导下进行心肺复苏。"
                )
            payload = {
                "user_message": message,
                "intent": intent.value,
                "tool_results": {"kb_results": kb_results},
                "kb_snippets": kb_snippets,
                "required_structure": required_structure,
                "safety_level": level,
                "route": "safety",
                "safety_subtype": safety_subtype,
                "writer_variant": "small",
            }
            final_response = _write_response(llm, payload, base_response, base_response)
            final_response = _ensure_chinese(final_response, llm, base_response)
            _append_response_event(run, final_response, payload=payload)
            _append_event(run, AgentEvent.STATE_DONE)
            return AgentOutput(
                intent=IntentEnum.SAFETY_GUIDE,
                tool_calls=[],
                final_response=final_response,
                risk_level=RiskLevelEnum.HIGH,
                need_human=True,
            )

        if level == "MEDIUM":
            tips = kb_snippets or _build_medium_fallback_tips(message)
            tips_text = "；".join(tips[:5])
            base_response = SAFETY_MEDIUM_TEMPLATE.format(tips=tips_text)
            payload = {
                "user_message": message,
                "intent": intent.value,
                "tool_results": {"kb_results": kb_results},
                "kb_snippets": kb_snippets,
                "required_structure": required_structure,
                "safety_level": level,
                "route": "safety",
                "writer_variant": "small",
            }
            final_response = _write_response(llm, payload, base_response, base_response)
            final_response = _ensure_chinese(final_response, llm, base_response)
            _append_response_event(run, final_response, payload=payload)
            _append_event(run, AgentEvent.STATE_DONE)
            return AgentOutput(
                intent=IntentEnum.SAFETY_GUIDE,
                tool_calls=[],
                final_response=final_response,
                risk_level=RiskLevelEnum.MEDIUM,
                need_human=True,
            )

        tips = kb_snippets or _build_low_fallback_tips(message)
        tips_text = "；".join(tips[:6])
        base_response = SAFETY_LOW_TEMPLATE.format(tips=tips_text)
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": {"kb_results": kb_results},
            "kb_snippets": kb_snippets,
            "required_structure": required_structure,
            "route": "safety",
            "safety_level": "LOW",
            "writer_variant": "small",
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.SAFETY_GUIDE,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if route == "complaint":
        order_id = data.get("order_id")
        description = data.get("description") or message
        issue_type = _infer_issue_type(message)
        missing_fields = []
        if not issue_type:
            missing_fields.append("issue_type")
        if not description:
            missing_fields.append("description")
        if not order_id:
            missing_fields.append("related_order_id")
        if missing_fields:
            prefill = {
                "related_order_id": order_id,
                "issue_type": issue_type,
                "description": description,
                "contact_phone_last4": _extract_phone_last4(message),
            }
            return _respond_with_form(
                run,
                llm,
                IntentEnum.CREATE_TICKET,
                message,
                "ticket_complaint_v1",
                prefill,
                missing_fields,
                required_structure,
                "已为您生成投诉工单表单，请补充信息后提交。",
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )
        ticket_note = ""
        tool_output = None
        if user_id and order_id:
            tool_output = _call_tool(
                run,
                "create_ticket",
                {
                    "user_id": user_id,
                    "order_id": order_id,
                    "category": "SERVICE_ISSUE",
                    "description": description,
                },
            )
            if tool_output.get("ticket_id"):
                ticket_note = f"我已为您登记工单，工单号{tool_output.get('ticket_id')}。"
        base_response = f"{ticket_note}{COMPLAINT_RESPONSE_TEMPLATE}"
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": {"create_ticket": tool_output} if tool_output else {},
            "kb_snippets": [],
            "required_structure": required_structure,
            "route": "complaint",
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.CREATE_TICKET,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if route == "urge":
        order_id = data.get("order_id") or _extract_order_id(message)
        phone = data.get("phone") or _extract_phone(message)
        pending_action = data.get("pending_action") or {}
        confirm_action = data.get("confirm_action")
        if confirm_action and pending_action.get("order_id"):
            # 中文注释：用户确认催单时直接创建工单
            order_id = pending_action.get("order_id")
            status_raw = pending_action.get("status")
            eta_raw = pending_action.get("eta")
            summary = _summarize_order(
                {"order_id": order_id, "status": status_raw, "eta": eta_raw}
            )
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={
                    "route": "urge_decision",
                    "order_id": order_id,
                    "overdue_level": pending_action.get("overdue_level"),
                    "decision": "confirm_create_ticket",
                },
            )
            description = (
                f"催单工单，订单{order_id}，状态{summary.get('status_text') or status_raw}，"
                f"预计{summary.get('eta_text')}，用户确认催单"
            )
            tool_output = _call_tool(
                run,
                "create_ticket",
                {
                    "user_id": user_id,
                    "order_id": order_id,
                    "category": "DELIVERY_DELAY",
                    "description": description,
                },
            )
            ticket_id = tool_output.get("ticket_id")
            if ticket_id:
                base_response = f"已为您创建催单工单，工单号{ticket_id}。后续可凭工单号或订单号查询进度。"
            else:
                base_response = "已记录您的催单需求，但创建工单需要用户信息或订单确认。"
            payload = {
                "user_message": message,
                "intent": intent.value,
                "tool_results": {"create_ticket": tool_output},
                "tool_results_summary": summary or {},
                "kb_snippets": [],
                "required_structure": required_structure,
            }
            final_response = _write_response(llm, payload, base_response, base_response)
            final_response = _ensure_chinese(final_response, llm, base_response)
            _append_response_event(run, final_response, payload=payload)
            _append_event(run, AgentEvent.STATE_DONE)
            return AgentOutput(
                intent=IntentEnum.QUERY_ORDER,
                tool_calls=[],
                final_response=final_response,
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )
        if not order_id and not phone:
            return _respond_with_form(
                run,
                llm,
                IntentEnum.QUERY_ORDER,
                message,
                "order_query_v1",
                {},
                ["order_id_or_phone_last4"],
                required_structure,
                "为了帮您催单，请先填写订单查询表单。",
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )

        tool_results = {}
        base_response = URGE_EXPLAIN_TEMPLATE
        summary = None
        decision = "no_ticket"
        overdue_info = {}
        pending_action_output = None
        if order_id:
            internal_output = _call_tool(run, "query_order", {"order_id": order_id})
            tool_results["internal"] = internal_output
            order_payload = internal_output if "order_id" in internal_output else None
            if not order_payload:
                external_output = _call_tool(
                    run, "external_query_order", {"order_id": order_id}
                )
                tool_results["external"] = external_output
                if "order_id" in external_output:
                    order_payload = external_output
            if order_payload:
                summary = _summarize_order(order_payload)
                status_raw = order_payload.get("status")
                eta_raw = order_payload.get("eta") or order_payload.get("created_at")
                eta_dt = _parse_eta_datetime(eta_raw)
                now = timezone.now()
                level = overdue_level(now, eta_dt, status_raw)
                overdue_note = _format_overdue_delta(now, eta_dt)
                overdue_info = {
                    "overdue_level": level,
                    "overdue_note": overdue_note,
                    "next_actions": overdue_next_actions(level),
                }
                if level == OVERDUE_LEVEL_SEVERE:
                    decision = "auto_create_ticket"
                    description = (
                        f"催单工单，订单{order_id}，状态{summary.get('status_text')}，"
                        f"预计{summary.get('eta_text')}，用户诉求催单"
                    )
                    tool_output = _call_tool(
                        run,
                        "create_ticket",
                        {
                            "user_id": user_id,
                            "order_id": order_id,
                            "category": "DELIVERY_DELAY",
                            "description": description,
                        },
                    )
                    tool_results["create_ticket"] = tool_output
                    ticket_id = tool_output.get("ticket_id")
                    if ticket_id:
                        base_response = (
                            f"已为您创建催单工单，工单号{ticket_id}。"
                            "后续可凭工单号或订单号查询进度。"
                        )
                    else:
                        base_response = "已记录您的催单需求，但创建工单需要用户信息或订单确认。"
                elif level == OVERDUE_LEVEL_MILD:
                    decision = "ask_confirm"
                    pending_action_output = {
                        "type": "CREATE_TICKET",
                        "order_id": order_id,
                        "status": status_raw,
                        "eta": eta_raw,
                        "overdue_level": level,
                    }
                    base_response = (
                        "如果您希望我现在帮您催单，我可以立即为您创建催单工单。"
                        "请回复：同意催单。"
                    )
                elif level == OVERDUE_LEVEL_UNKNOWN:
                    decision = "unknown_eta"
                    base_response = "暂时无法判断是否超时，您可提供预计时间或联系人工确认。"
                else:
                    decision = "no_ticket"
                    base_response = URGE_EXPLAIN_TEMPLATE
            else:
                decision = "order_not_found"
                base_response = (
                    "根据您提供的信息，暂未查询到有效订单。"
                    "请核对信息是否正确，或直接联系人工客服协助处理。"
                )
        else:
            list_output = _call_tool(
                run, "external_query_orders_by_phone", {"phone": phone, "limit": 20}
            )
            tool_results["external_list"] = list_output
            results = list_output.get("results", [])
            if results:
                lines = []
                for index, item in enumerate(results, start=1):
                    status_text = status_display(item.get("status"))
                    eta_text = _format_eta(item.get("eta") or item.get("created_at"))
                    lines.append(
                        f"{index}. 订单号 {item.get('order_id')} | {status_text} | 预计 {eta_text}"
                    )
                base_response = (
                    f"为您找到{len(results)}笔订单，已为您整理如下：\n"
                    "订单列表：\n"
                    + "\n".join(lines)
                    + "\n如需催单，请告知具体订单号。"
                )
            else:
                decision = "order_not_found"
                base_response = (
                    "根据您提供的信息，暂未查询到有效订单。"
                    "请核对信息是否正确，或直接联系人工客服协助处理。"
                )

        planning_output = {
            "route": "urge_decision",
            "order_id": order_id,
            "overdue_level": overdue_info.get("overdue_level"),
            "decision": decision,
        }
        if decision == "ask_confirm":
            planning_output.update(
                {
                    "ui_action": "SHOW_FORM",
                    "form_id": "order_urge_confirm_v1",
                    "prefill": {"order_id": order_id, "urge_reason": "已超时"},
                    "missing_fields": [],
                }
            )
        _append_event(run, AgentEvent.STATE_PLANNING, output_json=planning_output)
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": tool_results,
            "tool_results_summary": {**(summary or {}), **overdue_info},
            "kb_snippets": [],
            "required_structure": required_structure,
            "route": "urge",
            "show_form": decision == "ask_confirm",
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        form = None
        ui_action = None
        if decision == "ask_confirm":
            form = build_form(
                "order_urge_confirm_v1",
                {"order_id": order_id, "urge_reason": "已超时"},
            )
            ui_action = "SHOW_FORM"
        response_output = {}
        if pending_action_output:
            response_output["pending_action"] = pending_action_output
        if ui_action and form:
            response_output["ui_action"] = ui_action
            response_output["form_id"] = form.get("form_id")
        _append_response_event(run, final_response, payload=payload, extra=response_output)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.QUERY_ORDER,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
            ui_action=ui_action,
            form=form,
        )

    if route == "query_order":
        provided_query = _detect_provided_query(message, slots)
        order_id = data.get("order_id") or _extract_order_id(message)
        phone = data.get("phone") or _extract_phone(message)
        if provided_query.get("type") == "order_id" and provided_query.get("normalized"):
            try:
                order_id = order_id or int(provided_query.get("normalized"))
            except (TypeError, ValueError):
                order_id = order_id
        if provided_query.get("type") == "phone":
            phone = phone or provided_query.get("normalized") or provided_query.get("value")
        order_query_state = "NEED_MORE_INFO"
        if not provided_query.get("is_valid"):
            order_query_state = "NEED_MORE_INFO"
        elif order_id or phone:
            order_query_state = "QUERY_EXECUTED"
        if not order_id and not phone:
            return _respond_with_form(
                run,
                llm,
                IntentEnum.QUERY_ORDER,
                message,
                "order_query_v1",
                {},
                ["order_id_or_phone_last4"],
                required_structure,
                "为了查询订单，请先填写订单查询表单。",
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
                extra_payload={
                    "order_query_state": order_query_state,
                    "provided_query": provided_query,
                    "identity_verified": bool(user_id),
                    "allowed_fields": ORDER_ALLOWED_FIELDS,
                },
            )

        tool_results = {}
        base_response = (
            "根据您提供的信息，暂未查询到有效订单。"
            "请核对信息是否正确，或直接联系人工客服协助处理。"
        )
        summary = None
        if order_id:
            internal_output = _call_tool(run, "query_order", {"order_id": order_id})
            tool_results["internal"] = internal_output
            order_payload = internal_output if "order_id" in internal_output else None
            if not order_payload:
                external_output = _call_tool(
                    run, "external_query_order", {"order_id": order_id}
                )
                tool_results["external"] = external_output
                if "order_id" in external_output:
                    order_payload = external_output
            internal_error = isinstance(internal_output, dict) and internal_output.get("error")
            external_error = tool_results.get("external", {}).get("error")
            if internal_error or external_error:
                order_query_state = "TOOL_ERROR"
            if order_payload:
                summary = _summarize_order(order_payload)
                base_response = (
                    f"已为您查询到订单{summary.get('order_id')}，当前{summary['status_text']}。"
                    f"{summary['status_explain']}预计送达时间：{summary['eta_text']}。"
                    "如需催单或有其他问题，我可以继续协助。"
                )
            else:
                if order_query_state != "TOOL_ERROR":
                    order_query_state = "NO_RESULT"
        else:
            list_output = _call_tool(
                run, "external_query_orders_by_phone", {"phone": phone, "limit": 20}
            )
            tool_results["external_list"] = list_output
            results = list_output.get("results", [])
            if isinstance(list_output, dict) and list_output.get("error"):
                order_query_state = "TOOL_ERROR"
            if results:
                lines = []
                for index, item in enumerate(results, start=1):
                    status_text = status_display(item.get("status"))
                    eta_text = _format_eta(item.get("eta") or item.get("created_at"))
                    lines.append(
                        f"{index}. 订单号 {item.get('order_id')} | {status_text} | 预计 {eta_text}"
                    )
                base_response = (
                    f"为您找到{len(results)}笔订单，已为您整理如下：\n"
                    "订单列表：\n"
                    + "\n".join(lines)
                    + "\n如需查看某一笔详情，请告知订单号。"
                )
                order_query_state = "QUERY_EXECUTED"
            else:
                if order_query_state != "TOOL_ERROR":
                    order_query_state = "NO_RESULT"

        if order_query_state == "NO_RESULT":
            base_response = (
                "很抱歉，未根据您提供的信息查询到有效订单。"
                "请核对订单号或手机号是否正确，或联系人工客服协助处理。"
            )
        if order_query_state == "TOOL_ERROR":
            base_response = "当前系统繁忙，暂时无法完成查询。请稍后再试或联系人工客服。"

        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "route": "order_query_state",
                "order_query_state": order_query_state,
                "provided_query": provided_query,
                "identity_verified": bool(user_id),
                "allowed_fields": ORDER_ALLOWED_FIELDS,
            },
        )
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": tool_results,
            "tool_results_summary": summary or {},
            "kb_snippets": [],
            "required_structure": required_structure,
            "route": "query_order",
            "order_query_state": order_query_state,
            "provided_query": provided_query,
            "identity_verified": bool(user_id),
            "allowed_fields": ORDER_ALLOWED_FIELDS,
            "writer_variant": "small",
        }
        if order_query_state in {"NEED_MORE_INFO", "NO_RESULT", "TOOL_ERROR"}:
            final_response = base_response
        else:
            final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.QUERY_ORDER,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if route == "modify_address":
        order_id = data.get("order_id")
        new_address = data.get("new_address")
        if not order_id or not new_address:
            if order_id:
                status_check = _call_tool(run, "query_order", {"order_id": order_id})
                status_raw = status_check.get("status") if isinstance(status_check, dict) else None
                if status_raw and not can_modify_address(status_raw):
                    payload = {
                        "user_message": message,
                        "intent": intent.value,
                        "tool_results": {"query_order": status_check},
                        "kb_snippets": [],
                        "required_structure": required_structure,
                        "route": "modify_address",
                    }
                    base_response = "当前订单状态不支持改地址，请联系人工客服协助处理。"
                    final_response = _write_response(llm, payload, base_response, base_response)
                    final_response = _ensure_chinese(final_response, llm, base_response)
                    _append_response_event(run, final_response, payload=payload)
                    _append_event(run, AgentEvent.STATE_DONE)
                    return AgentOutput(
                        intent=IntentEnum.MODIFY_ORDER,
                        tool_calls=[],
                        final_response=final_response,
                        risk_level=RiskLevelEnum.LOW,
                        need_human=False,
                    )
            missing_fields = []
            if not order_id:
                missing_fields.append("order_id")
            if not new_address:
                missing_fields.append("new_address")
            prefill = {
                "order_id": order_id,
                "new_address": new_address,
                "contact_phone_last4": _extract_phone_last4(message),
            }
            return _respond_with_form(
                run,
                llm,
                IntentEnum.MODIFY_ORDER,
                message,
                "order_modify_address_v1",
                prefill,
                missing_fields,
                required_structure,
                "为了尽快为您改地址，我还需要补充订单号和新地址等信息。",
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )

        tool_output = _call_tool(
            run,
            "modify_order_address",
            {"order_id": order_id, "new_address": new_address},
        )
        base_response = tool_output.get("message") or "地址已更新。"
        if tool_output.get("error"):
            base_response = "地址修改失败，请核对订单号或地址。"
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": {"modify_order_address": tool_output},
            "kb_snippets": [],
            "required_structure": required_structure,
            "route": "modify_address",
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.MODIFY_ORDER,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    if route == "create_order":
        quantity = data.get("quantity")
        address = data.get("address")
        product_type = data.get("product_type") or "15kg"
        missing_fields = []
        if not quantity:
            missing_fields.append("quantity")
        if not address:
            missing_fields.append("address")
        if not product_type:
            missing_fields.append("cylinder_type")
        if missing_fields:
            prefill = {
                "quantity": quantity,
                "address": address,
                "cylinder_type": product_type,
                "contact_phone_last4": _extract_phone_last4(message),
            }
            return _respond_with_form(
                run,
                llm,
                IntentEnum.CREATE_ORDER,
                message,
                "order_create_v1",
                prefill,
                missing_fields,
                required_structure,
                "为了帮您下单，我还需要补充部分信息。请按提示逐项告诉我，我会在执行前先向您确认。",
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )
        if not user_id:
            payload = {
                "user_message": message,
                "intent": intent.value,
                "tool_results": {},
                "kb_snippets": [],
                "required_structure": required_structure,
            }
            base_response = ASK_CREATE_ORDER_TEMPLATE
            final_response = _write_response(llm, payload, base_response, base_response)
            final_response = _ensure_chinese(final_response, llm, base_response)
            _append_response_event(run, final_response, payload=payload)
            _append_event(run, AgentEvent.STATE_DONE)
            return AgentOutput(
                intent=IntentEnum.CREATE_ORDER,
                tool_calls=[],
                final_response=final_response,
                risk_level=RiskLevelEnum.LOW,
                need_human=False,
            )

        tool_output = _call_tool(
            run,
            "create_order",
            {
                "user_id": user_id,
                "product_type": product_type,
                "quantity": quantity,
                "address": address,
            },
        )
        if tool_output.get("order_id"):
            base_response = f"订单已创建，订单号{tool_output.get('order_id')}。"
        else:
            base_response = "订单已创建。"
        payload = {
            "user_message": message,
            "intent": intent.value,
            "tool_results": {"create_order": tool_output},
            "kb_snippets": [],
            "required_structure": required_structure,
        }
        final_response = _write_response(llm, payload, base_response, base_response)
        final_response = _ensure_chinese(final_response, llm, base_response)
        _append_response_event(run, final_response, payload=payload)
        _append_event(run, AgentEvent.STATE_DONE)
        return AgentOutput(
            intent=IntentEnum.CREATE_ORDER,
            tool_calls=[],
            final_response=final_response,
            risk_level=RiskLevelEnum.LOW,
            need_human=False,
        )

    payload = {
        "user_message": message,
        "intent": intent.value,
        "tool_results": {},
        "kb_snippets": [],
        "required_structure": required_structure,
    }
    normalized_message = message or "（未提供问题）"
    base_response = UNKNOWN_RESPONSE_TEMPLATE.format(message=normalized_message)
    final_response = _write_response(llm, payload, base_response, base_response)
    final_response = _ensure_chinese(final_response, llm, base_response)
    _append_response_event(run, final_response, payload=payload)
    _append_event(run, AgentEvent.STATE_DONE)
    return AgentOutput(
        intent=IntentEnum.UNKNOWN,
        tool_calls=[],
        final_response=final_response,
        risk_level=RiskLevelEnum.LOW,
        need_human=False,
    )




