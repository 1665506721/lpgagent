from datetime import datetime, timedelta


OVERDUE_LEVEL_NONE = "NONE"
OVERDUE_LEVEL_MILD = "MILD"
OVERDUE_LEVEL_SEVERE = "SEVERE"
OVERDUE_LEVEL_UNKNOWN = "UNKNOWN"

OVERDUE_STATUS_SET = {"DISPATCHED", "DELIVERING"}
ALLOW_MODIFY_STATUS_SET = {"CREATED", "CONFIRMED"}

MILD_THRESHOLD = timedelta(minutes=30)
SEVERE_THRESHOLD = timedelta(hours=2)


def can_modify_address(status):
    # 中文注释：地址修改仅允许在创建/确认阶段
    return status in ALLOW_MODIFY_STATUS_SET


def can_cancel_order(status):
    # 中文注释：取消订单仅允许在创建/确认阶段
    return status in ALLOW_MODIFY_STATUS_SET


def status_display(status):
    # 中文注释：订单状态中文展示
    mapping = {
        "CREATED": "已创建",
        "CONFIRMED": "已确认",
        "DISPATCHED": "已出库/已安排配送",
        "DELIVERING": "配送中",
        "DONE": "已送达",
        "CANCELLED": "已取消",
    }
    return mapping.get(status, "未知状态")


def status_explain(status):
    # 中文注释：订单状态解释，用于客服话术
    mapping = {
        "CREATED": "订单已提交，正在等待确认或分配。",
        "CONFIRMED": "订单已确认，正在安排配送。",
        "DISPATCHED": "师傅已接单或已从站点出库，正在备货或在路上。",
        "DELIVERING": "正在配送途中，通常很快送达，请保持电话畅通。",
        "DONE": "订单已完成，如有问题可随时反馈。",
        "CANCELLED": "订单已取消，如需恢复请重新下单或联系客服。",
    }
    return mapping.get(status, "")


def _normalize_eta(eta):
    if eta is None:
        return None
    if isinstance(eta, datetime):
        return eta
    if isinstance(eta, str):
        try:
            cleaned = eta.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        except Exception:
            return None
    return None


def overdue_level(now, eta, status):
    # 中文注释：仅对配送相关状态进行超时判断
    if status not in OVERDUE_STATUS_SET:
        return OVERDUE_LEVEL_NONE
    eta_dt = _normalize_eta(eta)
    if eta_dt is None:
        return OVERDUE_LEVEL_UNKNOWN
    if eta_dt.tzinfo is None and now.tzinfo is not None:
        eta_dt = eta_dt.replace(tzinfo=now.tzinfo)
    elif eta_dt.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=eta_dt.tzinfo)
    elif eta_dt.tzinfo is not None and now.tzinfo is not None:
        now = now.astimezone(eta_dt.tzinfo)
    delta = now - eta_dt
    if delta >= SEVERE_THRESHOLD:
        return OVERDUE_LEVEL_SEVERE
    if delta >= MILD_THRESHOLD:
        return OVERDUE_LEVEL_MILD
    return OVERDUE_LEVEL_NONE


def is_overdue(now, eta, status):
    # 中文注释：用于布尔判断，UNKNOWN 视为未确认超时
    level = overdue_level(now, eta, status)
    return level in {OVERDUE_LEVEL_MILD, OVERDUE_LEVEL_SEVERE}


def overdue_next_actions(level):
    # 中文注释：根据超时等级给出建议动作
    if level == OVERDUE_LEVEL_MILD:
        return ["建议再等待一会儿", "如需催单可创建工单跟进"]
    if level == OVERDUE_LEVEL_SEVERE:
        return ["建议立即创建催单工单", "如情况紧急可联系人工热线"]
    if level == OVERDUE_LEVEL_UNKNOWN:
        return ["暂无法判断是否超时", "可提供预计时间或联系人工确认"]
    return ["建议耐心等待并保持电话畅通"]
