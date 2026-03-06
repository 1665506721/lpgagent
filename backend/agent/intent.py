import re


GREETING_KEYWORDS = ["你好", "您好", "在吗", "谢谢", "辛苦了", "早上好", "晚上好"]
IDENTITY_KEYWORDS = ["你是谁", "你能做什么", "怎么用", "你是什么"]
OUT_OF_SCOPE_KEYWORDS = ["财务", "报销", "比特币", "股票", "写诗", "天气", "政治", "明星"]

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
SAFETY_LOW_KEYWORDS = [
    "软管多久换",
    "钢瓶放哪里",
    "厨房可以吗",
    "老人小孩",
    "日常检查",
    "注意事项",
]

COMPLAINT_KEYWORDS = ["态度差", "投诉", "不满意", "服务差", "骂人", "迟到", "敷衍", "不礼貌"]
URGE_KEYWORDS = ["超时", "还没到", "催", "多久到", "送到哪了", "催单"]

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


def _first_match(text, keywords):
    for keyword in keywords:
        if keyword in text:
            return keyword
    return ""


def _extract_order_id(text):
    if not text:
        return None
    match = re.search(r"(?<!\d)(\d{6,10})(?!\d)", text)
    if not match:
        return None
    return int(match.group(1))


def _extract_phone(text):
    if not text:
        return None
    masked = re.search(r"\d{3}\*{4}\d{4}", text)
    if masked:
        return masked.group(0)
    digits = re.search(r"(?<!\d)(\d{11})(?!\d)", text)
    if digits:
        value = digits.group(1)
        return f"{value[:3]}****{value[-4:]}"
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
    match = re.search(r"([\u4e00-\u9fff0-9A-Za-z\-]{4,}?(?:路|街|巷|号|小区|楼|单元|室|区|市).*)", text)
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


def _is_out_of_scope(text):
    # 中文注释：只有明确无关领域关键词且不包含订单/安全关键词时才超出范围
    if not _contains_any(text, OUT_OF_SCOPE_KEYWORDS):
        return False
    if _contains_any(text, ORDER_DOMAIN_KEYWORDS) or _contains_any(text, SAFETY_BASE_KEYWORDS):
        return False
    return True


def extract_slots(intent, message):
    # 中文注释：基于意图进行槽位抽取，确保规则优先且稳定可回放
    text = message or ""
    slots = {}
    order_id = _extract_order_id(text)
    if order_id:
        slots["order_id"] = order_id

    masked = re.search(r"\d{3}\*{4}\d{4}", text)
    if masked:
        slots["phone_masked"] = masked.group(0)
    else:
        digits = re.search(r"(?<!\d)(1\d{10})(?!\d)", text)
        if digits:
            value = digits.group(1)
            slots["phone"] = value
            slots["phone_masked"] = f"{value[:3]}****{value[-4:]}"
            slots["phone_last4"] = value[-4:]

    tail4 = re.search(r"(?:后四位|尾号)\s*(\d{4})", text)
    if tail4:
        slots["phone_last4"] = tail4.group(1)

    if intent in {"ORDER_CREATE", "ORDER_MODIFY_ADDRESS"}:
        slots["address"] = _extract_address(text)
        slots["new_address"] = _extract_new_address(text)

    if intent == "ORDER_CREATE":
        slots["quantity"] = _extract_quantity(text)
        slots["cylinder_type"] = _extract_product_type(text)

    return {k: v for k, v in slots.items() if v}


def intent_router(message):
    # 中文注释：规则优先的意图识别，确保不依赖 LLM 也能稳定命中
    text = message or ""

    match = _first_match(text, SAFETY_HIGH_KEYWORDS)
    if match:
        return {
            "intent": "SAFETY_HIGH",
            "confidence": 0.97,
            "slots": extract_slots("SAFETY_HIGH", text),
            "route_reason": f"matched safety_high keyword {match}",
        }

    match = _first_match(text, ORDER_MODIFY_KEYWORDS)
    if match:
        return {
            "intent": "ORDER_MODIFY_ADDRESS",
            "confidence": 0.92,
            "slots": extract_slots("ORDER_MODIFY_ADDRESS", text),
            "route_reason": f"matched modify keyword {match}",
        }

    match = _first_match(text, COMPLAINT_KEYWORDS)
    if match:
        return {
            "intent": "TICKET_COMPLAINT",
            "confidence": 0.9,
            "slots": extract_slots("TICKET_COMPLAINT", text),
            "route_reason": f"matched complaint keyword {match}",
        }

    match = _first_match(text, URGE_KEYWORDS)
    if match:
        return {
            "intent": "ORDER_URGE",
            "confidence": 0.88,
            "slots": extract_slots("ORDER_URGE", text),
            "route_reason": f"matched urge keyword {match}",
        }

    match = _first_match(text, ORDER_QUERY_KEYWORDS)
    if match or ("订单" in text and _extract_order_id(text)):
        return {
            "intent": "ORDER_QUERY",
            "confidence": 0.86,
            "slots": extract_slots("ORDER_QUERY", text),
            "route_reason": "matched order query keyword or order_id",
        }

    match = _first_match(text, ORDER_CREATE_KEYWORDS)
    if match:
        return {
            "intent": "ORDER_CREATE",
            "confidence": 0.84,
            "slots": extract_slots("ORDER_CREATE", text),
            "route_reason": f"matched create keyword {match}",
        }

    match = _first_match(text, SAFETY_LOW_KEYWORDS)
    if match:
        return {
            "intent": "SAFETY_LOW",
            "confidence": 0.82,
            "slots": extract_slots("SAFETY_LOW", text),
            "route_reason": f"matched safety_low keyword {match}",
        }

    match = _first_match(text, IDENTITY_KEYWORDS)
    if match:
        return {
            "intent": "IDENTITY",
            "confidence": 0.75,
            "slots": {},
            "route_reason": f"matched identity keyword {match}",
        }

    match = _first_match(text, GREETING_KEYWORDS)
    if match:
        return {
            "intent": "GREETING",
            "confidence": 0.7,
            "slots": {},
            "route_reason": f"matched greeting keyword {match}",
        }

    if _is_out_of_scope(text):
        return {
            "intent": "OUT_OF_SCOPE",
            "confidence": 0.65,
            "slots": {},
            "route_reason": "matched out_of_scope keywords",
        }

    return {
        "intent": "UNKNOWN",
        "confidence": 0.3,
        "slots": extract_slots("UNKNOWN", text),
        "route_reason": "no rule matched",
    }
