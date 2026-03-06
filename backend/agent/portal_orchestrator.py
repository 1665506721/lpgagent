import json
import re
import secrets
import sys
import unicodedata
from contextvars import ContextVar
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Max
from django.utils import timezone
from langchain_core.messages import HumanMessage, SystemMessage

from agent.contract import AgentOutput, IntentEnum, RiskLevelEnum
from agent.tools import execute_tool
from core.models import AgentEvent
from customer_portal.constants import (
    ACCESSORY_SKUS,
    ACCESSORY_SKU_LABELS,
    DELIVERY_PRICES,
    INSTALLATION_PRICE,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_IN_SERVICE,
    ORDER_STATUS_LABELS,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING_PAYMENT,
    ORDER_STATUS_SCHEDULED,
    SERVICE_TYPE_ACCESSORIES,
    SERVICE_TYPE_CYLINDER_EXCHANGE,
    SERVICE_TYPE_INSTALLATION,
    SERVICE_TYPE_LABELS,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
    SERVICE_TYPE_REPAIR,
    SERVICE_TYPE_SAFETY_CHECK,
    SAFETY_CHECK_PRICE,
    REPAIR_PRICE,
)


CONFIRM_KEYWORDS = [
    "确认",
    "确定",
    "同意",
    "没问题",
    "可以执行",
    "确认下单",
    "确认支付",
]
REJECT_KEYWORDS = [
    "取消",
    "不用",
    "不需要",
    "算了",
    "放弃",
]

SERVICE_KEYWORDS = [
    (SERVICE_TYPE_CYLINDER_EXCHANGE, ["换瓶", "回收空瓶"]),
    (SERVICE_TYPE_INSTALLATION, ["安装", "installation"]),
    (SERVICE_TYPE_SAFETY_CHECK, ["安检", "安全检查", "safety_check"]),
    (SERVICE_TYPE_REPAIR, ["报修", "维修", "故障", "检修", "修一下", "上门检修", "故障检修", "来个师傅修", "repair"]),
    (SERVICE_TYPE_ACCESSORIES, ["配件", "软管", "减压阀", "报警器"]),
    (SERVICE_TYPE_LPG_CYLINDER_DELIVERY, ["订气", "叫气", "来气", "煤气罐", "液化气配送", "配送", "送气", "送煤气"]),
]

ORDER_NO_PATTERN = re.compile(r"(LPG\d{10,})", re.IGNORECASE)
ORDER_ID_PATTERN = re.compile(r"(?:订单|order)\s*#?\s*(\d{1,10})", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9}|123)(?!\d)")
DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
SLOT_PATTERN = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)\s*[-到]\s*([01]?\d|2[0-3]):([0-5]\d)")
ZH_HOUR_RANGE_PATTERN = re.compile(r"([01]?\d|2[0-3])\s*点\s*(?:到|-|至)\s*([01]?\d|2[0-3])\s*点")
CHOICE_INDEX_PATTERN = re.compile(r"第\s*(\d{1,2})\s*(?:个|条|笔|单)?")

CHINESE_NUMBERS = {
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

MISSING_FIELD_LABELS = {
    "service_type": "服务类型",
    "cylinder_type": "瓶型",
    "quantity": "数量",
    "return_empty": "是否回收空瓶",
    "install_item": "安装项目",
    "check_scope": "安检范围",
    "issue_desc": "报修描述",
    "items": "配件清单",
    "address": "服务地址",
    "address_confirm": "地址确认",
    "delivery_mode": "配送方式",
    "eta": "预约时段",
    "contact_name": "联系人",
    "contact_phone": "联系电话",
}

SAFETY_RAG_KEYWORDS = ["漏气", "异味", "报警", "安全", "燃气泄漏", "爆炸", "通风", "阀门"]
BIZ_RAG_KEYWORDS = [
    "价格",
    "费用",
    "发票",
    "开票",
    "营业时间",
    "服务时间",
    "流程",
    "配送范围",
    "怎么下单",
    "优惠",
    "年检",
    "检验",
    "复检",
    "涨价",
    "调价",
]
PRICE_QUERY_KEYWORDS = ["价格", "多少钱", "费用", "报价", "单价", "涨价", "调价", "价目", "收费"]
INSPECTION_QUERY_KEYWORDS = ["年检", "检验", "复检", "年审", "检瓶", "到期", "检测周期", "多久检一次"]
INSPECTION_BOOKING_KEYWORDS = ["预约安检", "上门安检", "安排安检", "安检下单", "做安检", "安检服务"]
ORDER_ACTION_HINTS = ["下单", "订", "配送", "送", "来一单", "帮我下", "安排上门"]
DIRECT_CHAT_KEYWORDS = {
    "greeting": ["你好", "您好", "在吗", "有人吗"],
    "thanks": ["谢谢", "辛苦了", "多谢"],
    "bye": ["再见", "拜拜", "先这样"],
}
PASSWORD_CHANGE_HINT_KEYWORDS = ["改密码", "修改密码", "重置密码", "密码忘了", "忘记密码"]
ADDRESS_DELETE_KEYWORDS = ["删地址", "删除地址", "移除地址", "地址删除", "把地址删掉", "取消这个地址"]
NOTIFICATION_KEYWORDS = ["通知", "消息", "站内信", "提醒"]
NOTIFICATION_READ_ALL_KEYWORDS = ["全部已读", "全已读", "一键已读", "全部阅读", "都已读", "全部标记已读"]
NOTIFICATION_READ_KEYWORDS = ["已读", "标记已读", "读掉", "读了", "这条已读"]
INVOICE_KEYWORDS = ["发票", "开票", "税号", "普票", "专票", "抬头"]
ORDER_FEE_KEYWORDS = ["费用明细", "小计", "总价", "加急费", "价格明细", "金额明细"]
SAFETY_EMERGENCY_KEYWORDS = ["漏气", "燃气泄漏", "煤气泄漏", "异味", "报警", "怎么办", "先做什么", "应急"]
SAFETY_EMERGENCY_SCENE_KEYWORDS = [
    "漏气",
    "漏了",
    "燃气泄漏",
    "煤气泄漏",
    "异味",
    "阀门漏",
    "报警响",
    "报警一直响",
    "闻到燃气味",
    "闻到煤气味",
    "燃气味",
    "煤气味",
]
SAFETY_EMERGENCY_ACTION_KEYWORDS = [
    "怎么办",
    "先做什么",
    "怎么处理",
    "如何处理",
    "应急",
    "紧急",
    "马上",
    "立刻",
    "第一步",
    "最稳妥",
    "先报修",
    "怎么下",
    "怎么弄",
    "咋办",
]
SAFETY_LEAK_CHECK_KEYWORDS = [
    "怎么判断",
    "如何判断",
    "咋判断",
    "怎么检查",
    "如何检查",
    "检查漏气",
    "检漏",
    "试漏",
    "肥皂水",
    "是不是漏气",
    "是否漏气",
    "是不是泄漏",
    "如何排查",
    "怎么排查",
]
GENERAL_SAFETY_QUERY_KEYWORDS = [
    "用气安全",
    "燃气安全",
    "煤气安全",
    "注意安全",
    "安全注意",
    "安全事项",
    "安全规范",
    "日常安全",
    "使用煤气",
    "使用燃气",
    "注意什么",
    "注意事项",
    "怎么更安全",
]
RESOURCE_QUERY_VERBS = [
    "查",
    "看看",
    "看下",
    "查看",
    "查下",
    "查一下",
    "列出",
    "列下",
    "列一下",
    "帮我列",
    "给我列",
    "展示",
    "帮我看",
    "给我看",
    "帮我查",
    "给我查",
    "有多少",
    "有几个",
    "有哪些",
    "有哪几个",
]
RESOURCE_QUERY_NOUN_HINTS = ["列表", "清单", "全部", "所有", "明细", "汇总"]
RESOURCE_QUERY_BLOCK_VERBS = [
    "新增",
    "添加",
    "新建",
    "创建",
    "新加",
    "删除",
    "删",
    "移除",
    "设为",
    "设置",
    "设成",
    "修改",
    "更新",
    "更改",
    "改",
    "改址",
    "下单",
    "支付",
    "取消",
    "标记",
    "已读",
    "投诉",
    "建议",
]
CAPABILITY_HELP_KEYWORDS = [
    "你能做什么",
    "能做什么",
    "不会点网页",
    "一步一步",
    "先问我什么",
    "别太官方",
    "别模板化",
    "看懂错别字",
    "能不能看懂",
    "默认带出来",
    "能做、不能做",
]
THEME_EYE_KEYWORDS = ["护眼模式", "护眼", "暖色模式", "阅读模式"]
THEME_DARK_KEYWORDS = ["黑夜模式", "夜间模式", "深色模式", "暗黑模式", "深色主题", "黑暗模式"]
THEME_LIGHT_KEYWORDS = ["浅色模式", "明亮模式", "日间模式", "默认主题", "标准主题", "普通模式", "白天模式", "白天主题"]
THEME_SWITCH_ACTION_KEYWORDS = ["切换", "改", "换", "用", "开启", "打开", "设为", "改成", "换成"]
ORDER_QUERY_HINT_KEYWORDS = [
    "查一下",
    "查下",
    "查订单",
    "订单查询",
    "订单详情",
    "我的订单",
    "我有哪些订单",
    "有哪些订单",
    "订单有哪些",
    "订单有几个",
    "有几笔订单",
    "订单列表",
    "最近订单",
    "进行中的单",
    "进行中的单子",
    "这单",
    "那单",
    "昨天那单",
    "预计送达",
    "送达窗口",
    "第2页",
    "第3页",
    "统计",
    "没完成",
]
ORDER_QUERY_BLOCK_ACTION_KEYWORDS = [
    "改址",
    "改地址",
    "修改地址",
    "地址改为",
    "地址改成",
    "取消",
    "撤单",
    "支付",
    "付款",
    "退款",
    "申请退款",
    "下单",
    "预约",
    "新增",
    "添加",
    "删除",
    "设为",
    "设置",
    "修改",
]
ORDER_GUIDE_KEYWORDS = [
    "如何自助下单",
    "自助下单",
    "怎么下单",
    "下单流程",
    "下单步骤",
    "下单说明",
]
ORDER_GUIDE_ACTION_HINTS = ["我要", "帮我", "现在", "立刻", "马上", "给我", "先来", "安排"]

YES_KEYWORDS = ["是", "好的", "可以", "行", "确认", "就这个", "没问题", "用默认地址"]
NO_KEYWORDS = ["否", "不是", "不要", "不用", "换地址", "改地址", "不使用默认地址", "不用默认地址"]
PAY_ACTION_KEYWORDS = ["去支付", "我现在付", "现在付", "马上付", "发起支付", "支付订单", "付款订单", "立即支付"]
PAY_STATUS_ONLY_KEYWORDS = ["待付款", "没付款", "未付款", "超过30分钟", "过期", "废了"]
ADDRESS_MANAGE_KEYWORDS = [
    "新增地址",
    "添加地址",
    "加地址",
    "新建地址",
    "创建地址",
    "建个地址",
    "新加地址",
    "建一条地址",
    "默认地址",
    "地址管理",
    "收货地址",
]
PROFILE_QUERY_KEYWORDS = ["个人资料", "我的资料", "账号资料", "账号信息", "我的信息", "显示名", "用户名"]
ACCESSORY_CART_KEYWORDS = ["购物车", "清空购物车", "最贵那件", "SKU", "sku", "配件单"]
CART_CONTEXT_KEYWORDS = ["购物车", "加购物车", "清空购物车", "购物车里", "购物车内", "购物车现在"]
CART_ADD_KEYWORDS = ["加购物车", "加入购物车", "放购物车", "加购", "加上", "再来", "要", "来", "买"]
CART_WEAK_ADD_KEYWORDS = ["要", "来", "买"]
CART_REMOVE_KEYWORDS = ["删", "移除", "去掉", "不要", "取消这个", "拿掉"]
CART_CLEAR_KEYWORDS = ["清空购物车", "全删", "全部删", "都不要了", "清掉购物车", "购物车清空"]
CART_CHECKOUT_KEYWORDS = ["结算", "去支付", "付款", "下单", "买单", "支付购物车", "购物车下单"]
ORDER_QUOTE_KEYWORDS = [
    "先算",
    "先报价",
    "先给我算",
    "先给个价格",
    "先估个价",
    "确认后再下",
    "确认后下单",
    "先看总价",
    "算个总价",
    "先算个总价",
    "估个总价",
]
FORBIDDEN_PRICE_TAMPER_KEYWORDS = ["改价", "改价格", "价格改", "调价", "改成", "改为", "降到", "涨到", "抹掉"]
FORBIDDEN_HISTORY_TAMPER_KEYWORDS = [
    "历史订单",
    "历史记录",
    "订单记录",
    "付款记录",
    "支付记录",
    "账单记录",
    "历史账单",
    "交易记录",
]
FORBIDDEN_DELETE_TAMPER_KEYWORDS = ["删除", "删掉", "清空", "抹掉", "覆盖", "伪造"]
FORBIDDEN_STATUS_TAMPER_KEYWORDS = ["订单状态", "状态改", "改成已完成", "改为已完成", "改成已支付", "改为已支付", "强制完成", "直接改状态"]
MIXED_SPLIT_HINTS = ["并", "同时", "顺便", "另外", "再把", "再帮我", "以及"]
BATCH_CONNECTOR_HINTS = ["并", "同时", "顺便", "另外", "再", "再帮我", "以及", "再喊", "再叫"]
ACCESSORY_PURCHASE_NORMALIZE_KEYWORDS = ["弄个", "来个", "帮我弄", "给我配", "配一个", "配一套"]
ON_SITE_SERVICE_SIGNAL_KEYWORDS = ["检修", "修一下", "上门检修", "故障检修", "来个师傅修", "喊个师傅", "叫个师傅", "师傅来检修"]
SERVICE_INFO_TERMS = [
    "配件",
    "软管",
    "减压阀",
    "报警器",
    "自闭阀",
    "灶具",
    "点火器",
    "卡箍",
    "生料带",
    "换瓶",
    "安装",
    "安检",
    "报修",
    "配送",
    "送气",
    "液化气",
    "煤气",
]
SERVICE_INFO_QUESTION_TERMS = [
    "怎么",
    "如何",
    "多久",
    "是否",
    "能不能",
    "区别",
    "推荐",
    "注意",
    "判断",
    "用法",
    "更换",
    "流程",
    "规则",
    "是什么",
]
ORDER_EXECUTION_TERMS = [
    "下单",
    "订",
    "买",
    "购买",
    "加购物车",
    "加入购物车",
    "结算",
    "来一件",
    "来两件",
    "帮我下",
    "马上",
    "立刻",
    "预约",
    "安排上门",
]
ACCESSORY_TERMS = ["配件", "软管", "减压阀", "报警器", "自闭阀", "灶具", "点火器", "卡箍", "生料带", "胶管", "燃气灶"]
ACCESSORY_PURCHASE_KEYWORDS = [
    "加入购物车",
    "加购物车",
    "放购物车",
    "加购",
    "帮我下",
    "给我下",
    "帮我买",
    "给我买",
    "购买",
    "买",
    "下单",
    "结算",
]
ACCESSORY_QUESTION_KEYWORDS = ["怎么", "如何", "多久", "是否", "能不能", "可不可以", "可以吗", "吗", "判断", "注意", "推荐"]
ALARM_DEVICE_RISK_KEYWORDS = ["坏了", "故障", "失灵", "误报", "不响", "一直响", "拆", "拆下", "取下", "拔掉", "关掉", "关闭"]
FEEDBACK_PROGRESS_KEYWORDS = ["投诉进度", "建议进度", "反馈进度", "处理进度", "处理到哪", "怎么查进度", "提交后怎么查", "投诉提交后", "建议提交后"]
ONLINE_FEEDBACK_KEYWORDS = ["在线客服", "线上客服", "页面", "按钮", "系统", "体验", "交互", "回复太慢", "客服太慢", "功能建议", "界面建议"]
ORDER_SERVICE_FEEDBACK_KEYWORDS = ["订单", "这单", "那单", "配送员", "师傅", "上门", "服务态度", "送货", "改单", "取消单"]
FEEDBACK_STATUS_HINT_MAP = [
    ("待处理", "NEW"),
    ("新建", "NEW"),
    ("处理中", "PROCESSING"),
    ("处理", "PROCESSING"),
    ("已处理", "CLOSED"),
    ("已关闭", "CLOSED"),
    ("关闭", "CLOSED"),
]
STATUS_HINT_MAP = [
    ("待付款", ORDER_STATUS_PENDING_PAYMENT),
    ("待支付", ORDER_STATUS_PENDING_PAYMENT),
    ("已支付", ORDER_STATUS_PAID),
    ("已预约", ORDER_STATUS_SCHEDULED),
    ("进行中", ORDER_STATUS_IN_SERVICE),
    ("服务中", ORDER_STATUS_IN_SERVICE),
    ("已完成", ORDER_STATUS_COMPLETED),
    ("已取消", ORDER_STATUS_CANCELED),
    ("已过期", ORDER_STATUS_EXPIRED),
]

KB_TOP_K = 6
KB_MIN_SCORE = 0.3
KB_MIN_ACCEPTED_HITS = 1
KB_MAX_BULLETS = 5
LLM_ROUTE_HIGH_CONF = 0.72
LLM_ROUTE_LOW_CONF = 0.55
LLM_RECENT_ACCOUNT_LIMIT = 12
LLM_RECENT_WITHIN_HOURS = 24
LLM_RECENT_MAX_CHARS = 1100
COMPANY_NAME = "安燃"
EMERGENCY_HOTLINE = "400-888-0000"
SERVICE_HOTLINE = "400-888-0000"
ORDER_ESTIMATE_DELIVERY_FEE = Decimal("15")
CHAT_CONTEXT_EXPIRE_MINUTES = 30

MANUAL_HANDOFF_KEYWORDS = [
    "开户申请",
    "企业开户",
    "开户办理",
    "开户",
    "签约申请",
    "合同签约",
    "资费争议",
    "价格争议",
    "价格投诉",
    "收费争议",
]
MANUAL_CONTACT_REQUEST_KEYWORDS = [
    "联系客服",
    "联系人工",
    "人工客服",
    "转人工",
    "转接人工",
    "人工电话",
    "客服电话",
    "找客服",
    "找人工",
]
MANUAL_QUEUE_CANCEL_KEYWORDS = [
    "取消人工排队",
    "不用人工",
    "先不用人工",
    "不转人工",
    "取消转人工",
]
UNSAFE_OPERATION_KEYWORDS = [
    "拆",
    "拆下",
    "拆卸",
    "改装",
    "改造",
    "私改",
    "自己修",
    "自行维修",
    "自行改",
    "动手修",
    "绕过",
    "旁路",
]
UNSAFE_DEVICE_TERMS = [
    "报警器",
    "减压阀",
    "角阀",
    "燃气阀",
    "软管",
    "胶管",
    "钢瓶",
    "煤气罐",
    "燃气灶",
    "灶具",
    "管道",
]
SAFETY_CARE_CLOSING = "为了您和家人的平安，请务必优先保证人身安全，这是我们最牵挂的事。"

WRITE_INTENT_CODES = {
    "BATCH_ACTION",
    "CREATE_ORDER",
    "CART_ADD",
    "CART_REMOVE",
    "CART_CLEAR",
    "CART_CHECKOUT",
    "CANCEL_ORDER",
    "PAY_ORDER",
    "MODIFY_ADDRESS",
    "CREATE_FEEDBACK",
    "UPDATE_PROFILE",
    "ADDRESS_CREATE",
    "ADDRESS_SET_DEFAULT",
    "ADDRESS_UPDATE_DEFAULT",
    "ADDRESS_DELETE",
    "CHANGE_PASSWORD",
    "NOTIFICATION_READ",
    "NOTIFICATION_READ_ALL",
    "REQUEST_REFUND",
}
PENDING_ORDER_SIDE_QUERY_INTENTS = {
    "PRICE_QUERY",
    "INVOICE_HELP",
    "CYLINDER_INSPECTION_QUERY",
    "SAFETY_LEAK_CHECK",
    "QUERY_ORDER",
    "ADDRESS_QUERY",
    "PROFILE_QUERY",
    "NOTIFICATION_QUERY",
    "ORDER_GUIDE",
    "CAPABILITY_HELP",
    "THEME_SET_EYE",
    "THEME_SET_DARK",
    "THEME_SET_LIGHT",
}
PENDING_FEEDBACK_SIDE_QUERY_INTENTS = {
    "PRICE_QUERY",
    "INVOICE_HELP",
    "CYLINDER_INSPECTION_QUERY",
    "SAFETY_LEAK_CHECK",
    "SAFETY_EMERGENCY",
    "ADDRESS_QUERY",
    "PROFILE_QUERY",
    "NOTIFICATION_QUERY",
    "ORDER_GUIDE",
    "CAPABILITY_HELP",
    "THEME_SET_EYE",
    "THEME_SET_DARK",
    "THEME_SET_LIGHT",
}

DEFAULT_MODIFIABLE_ORDER_STATUSES = (
    ORDER_STATUS_PENDING_PAYMENT,
    ORDER_STATUS_PAID,
    ORDER_STATUS_SCHEDULED,
)

WRITE_ACTION_TYPES = {
    "BATCH_ACTION",
    "CREATE_ORDER",
    "CART_ADD",
    "CART_REMOVE",
    "CART_CLEAR",
    "CART_CHECKOUT",
    "CANCEL_ORDER",
    "PAY_ORDER",
    "MODIFY_ADDRESS",
    "CREATE_FEEDBACK",
    "UPDATE_PROFILE",
    "CREATE_ADDRESS",
    "SET_DEFAULT_ADDRESS",
    "UPDATE_ADDRESS",
    "DELETE_ADDRESS",
    "CHANGE_PASSWORD",
    "NOTIFICATION_READ",
    "NOTIFICATION_READ_ALL",
    "REQUEST_REFUND",
}
QUERY_INTENT_CODES = {
    "ADDRESS_QUERY",
    "PROFILE_QUERY",
    "NOTIFICATION_QUERY",
    "QUERY_ORDER",
}

PORTAL_LLM_CTX = ContextVar("portal_llm_ctx", default=None)
PORTAL_TONE_CTX = ContextVar("portal_tone_ctx", default="neutral")
PORTAL_RAG_CTX = ContextVar("portal_rag_ctx", default=None)
PORTAL_MEMORY_CTX = ContextVar("portal_memory_ctx", default=None)
PORTAL_USER_CTX = ContextVar("portal_user_ctx", default=None)
PORTAL_INPUT_CTX = ContextVar("portal_input_ctx", default="")
PORTAL_ROUTE_MODE_CTX = ContextVar("portal_route_mode_ctx", default="legacy")
PORTAL_MODEL_SOURCE_CTX = ContextVar("portal_model_source_ctx", default="none")
PORTAL_WRITE_ALLOWED_CTX = ContextVar("portal_write_allowed_ctx", default=True)
PORTAL_DEGRADED_REASON_CTX = ContextVar("portal_degraded_reason_ctx", default=None)
PORTAL_LANE_CTX = ContextVar("portal_lane_ctx", default="smalltalk")
PORTAL_ROUTING_EXTRA_CTX = ContextVar("portal_routing_extra_ctx", default=None)
PORTAL_STAGE0_CTX = ContextVar("portal_stage0_ctx", default=None)


def _next_step_index(run):
    current = AgentEvent.objects.filter(run=run).aggregate(Max("step_index")).get("step_index__max")
    return (current or 0) + 1


def _rag_settings():
    cfg = PORTAL_RAG_CTX.get() or {}

    def _to_int(value, fallback, low, high):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(low, min(high, parsed))

    def _to_float(value, fallback, low, high):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(low, min(high, parsed))

    top_k = _to_int(cfg.get("top_k"), KB_TOP_K, 1, 8)
    min_score = _to_float(cfg.get("min_score"), KB_MIN_SCORE, 0.0, 1.0)
    min_hits = _to_int(cfg.get("min_hits"), KB_MIN_ACCEPTED_HITS, 1, 5)
    max_bullets = _to_int(cfg.get("max_bullets"), KB_MAX_BULLETS, 1, 8)
    enable_rewrite = cfg.get("enable_rewrite")
    if isinstance(enable_rewrite, str):
        enable_rewrite = enable_rewrite.lower() in {"1", "true", "yes", "on"}
    if not isinstance(enable_rewrite, bool):
        enable_rewrite = True
    return {
        "top_k": top_k,
        "min_score": min_score,
        "min_hits": min_hits,
        "max_bullets": max_bullets,
        "enable_rewrite": enable_rewrite,
    }


def _append_event(run, state, input_json=None, output_json=None, policy_result=None):
    if policy_result is None:
        policy_result = {"allow": True, "reasons": []}
    AgentEvent.objects.create(
        run=run,
        step_index=_next_step_index(run),
        state=state,
        input_json=input_json,
        output_json=output_json,
        policy_result=policy_result,
        created_at=timezone.now(),
    )


def _latest_pending_action(run):
    events = AgentEvent.objects.filter(run=run).order_by("-step_index")
    for event in events:
        if not isinstance(event.output_json, dict):
            continue
        if event.output_json.get("pending_action_cleared"):
            return None
        action = event.output_json.get("pending_action")
        if not isinstance(action, dict):
            continue
        if action.get("status") in {"CLEARED", "DONE", "CANCELED"}:
            return None
        if action.get("status") in {"COLLECTING", "AWAIT_CONFIRM", "PARTIAL_DONE"}:
            return action
    return None


def _has_any(text, keywords):
    return any(keyword in (text or "") for keyword in keywords)


def _compact_text(text):
    return re.sub(r"\s+", "", text or "")


def _normalize_user_text(text):
    value = str(text or "")
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("～", "~").replace("—", "-").replace("－", "-")
    normalized = re.sub(r"[ \t\r\f\v]+", " ", normalized)
    normalized = re.sub(r"[。！？!?]{2,}", "。", normalized)
    normalized = re.sub(r"[，,]{2,}", "，", normalized)
    normalized = re.sub(r"^(嗯+|啊+|呃+|欸+|那个+|就是+|然后+)\s*", "", normalized.strip(), flags=re.IGNORECASE)
    return normalized.strip()


def _clean_contact_name(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = re.sub(r"^(用|就用|联系人|收货人|联系人是)\s*", "", raw)
    cleaned = re.sub(r"[：:，,。.\s]+$", "", cleaned).strip()
    if len(cleaned) > 16:
        cleaned = cleaned[:16]
    return cleaned


def _is_confirm_message(text):
    value = (text or "").strip()
    return bool(value) and _has_any(value, CONFIRM_KEYWORDS)


def _is_reject_message(text):
    value = (text or "").strip()
    return bool(value) and _has_any(value, REJECT_KEYWORDS)


def _looks_like_yes(text):
    value = (text or "").strip()
    if not value:
        return False
    if _has_any(value, NO_KEYWORDS):
        return False
    if value in {"是", "嗯", "好", "行", "可以"}:
        return True
    return _has_any(value, YES_KEYWORDS)


def _looks_like_no(text):
    value = (text or "").strip()
    if not value:
        return False
    return _has_any(value, NO_KEYWORDS)


def _extract_service_type(text):
    value = text or ""
    if _looks_like_price_query(value) or _looks_like_inspection_query(value):
        return None
    if _looks_like_accessory_info_query(value) and not _has_accessory_purchase_intent(value):
        return None
    if _has_any(value, ["喊个师傅", "叫个师傅", "师傅来"]) and _has_any(value, ["检修", "维修", "报修", "故障", "修一下", "修"]):
        return SERVICE_TYPE_REPAIR
    if _has_any(value, ["上门看看", "喊个人上门", "叫人上门", "派人上门", "上门检查一下", "上门看下", "喊个师傅", "叫个师傅"]):
        return SERVICE_TYPE_SAFETY_CHECK
    install_object_keywords = ["报警器", "切断阀", "联动", "自闭阀", "灶具", "减压阀", "阀门", "软管"]
    if (
        (
            _has_any(value, ["安装", "装个", "装上", "装一", "上门安装", "联动"])
            or re.search(r"(我要装|给我装|帮我装)", value)
        )
        and _has_any(value, install_object_keywords)
        and not _is_cart_context(value)
        and not _has_any(value, ["加购物车", "加入购物车", "买配件"])
    ):
        return SERVICE_TYPE_INSTALLATION
    value_lc = value.lower()
    for service_type, keywords in SERVICE_KEYWORDS:
        if _has_any(value_lc, [item.lower() for item in keywords]):
            return service_type
    if _has_any(value, ["叫气", "来气", "来罐气", "送煤气", "叫煤气"]):
        return SERVICE_TYPE_LPG_CYLINDER_DELIVERY
    if (
        _has_any(value, ["煤气", "液化气", "气罐"])
        and (_extract_quantity(value) or "送" in value or "配送" in value)
        and not _has_any(value, ["漏气", "异味", "报警", "安全"])
    ):
        return SERVICE_TYPE_LPG_CYLINDER_DELIVERY
    if ("下单" in value or "订气" in value) and (
        _extract_cylinder_type(value) or "瓶" in value or "煤气" in value or "液化气" in value
    ):
        return SERVICE_TYPE_LPG_CYLINDER_DELIVERY
    return None


def _is_run_context_stale(run, expire_minutes=CHAT_CONTEXT_EXPIRE_MINUTES):
    if not run:
        return False
    latest_event_at = (
        AgentEvent.objects.filter(run=run)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    reference = latest_event_at or getattr(run, "created_at", None)
    if not reference:
        return False
    return timezone.now() - reference > timedelta(minutes=max(1, int(expire_minutes or CHAT_CONTEXT_EXPIRE_MINUTES)))


def _looks_like_price_query(text):
    value = (text or "").strip()
    if not value:
        return False
    if not _has_any(value, PRICE_QUERY_KEYWORDS):
        return False
    if _has_any(value, ["费用明细", "价格明细", "金额明细", "小计", "加急费"]):
        return False
    if _has_any(value, ORDER_ACTION_HINTS) and _has_any(value, ["我要", "帮我", "现在", "立刻"]):
        return False
    return True


def _looks_like_inspection_query(text):
    value = (text or "").strip()
    if not value:
        return False
    if _has_any(value, INSPECTION_BOOKING_KEYWORDS):
        return False
    if not _has_any(value, INSPECTION_QUERY_KEYWORDS):
        return False
    if _has_any(value, ORDER_ACTION_HINTS) and _has_any(value, ["下单", "预约", "安排"]):
        return False
    return True


def _looks_like_safety_leak_check_query(text):
    value = (text or "").strip()
    if not value:
        return False
    has_scene = _has_any(value, SAFETY_EMERGENCY_SCENE_KEYWORDS + SAFETY_EMERGENCY_KEYWORDS)
    if not has_scene:
        return False
    return _has_any(value, SAFETY_LEAK_CHECK_KEYWORDS)


def _looks_like_general_safety_question(text):
    value = (text or "").strip()
    if not value:
        return False
    if _is_safety_emergency_query(value) or _looks_like_safety_leak_check_query(value):
        return False
    if _has_any(value, GENERAL_SAFETY_QUERY_KEYWORDS):
        return True
    has_gas = _has_any(value, ["燃气", "煤气", "液化气", "钢瓶"])
    has_safety_ask = _has_any(value, ["安全", "注意", "规范", "建议", "注意事项"])
    return bool(has_gas and has_safety_ask)


def _safety_topic_from_text(text):
    value = (text or "").strip()
    if not value:
        return "none"
    if _is_safety_emergency_query(value) or _looks_like_safety_leak_check_query(value):
        return "safety_leak"
    if _looks_like_general_safety_question(value):
        return "safety_general"
    if _has_any(value, SAFETY_RAG_KEYWORDS):
        return "safety_general"
    return "none"


def _safety_kind_from_text(text):
    value = _normalize_user_text(text)
    if not value:
        return "none"
    if _is_high_risk_safety_query(value) or _is_safety_emergency_query(value):
        return "emergency"
    if _looks_like_safety_leak_check_query(value):
        return "leak_assess"
    if _has_any(value, ["泄漏", "漏气"]) and _has_any(value, ["判断", "检查", "检漏", "试漏", "排查", "是否", "是不是", "怎么"]):
        return "leak_assess"
    if _looks_like_general_safety_question(value):
        return "general_qa"
    if _has_any(value, ["燃气", "煤气", "液化气", "钢瓶", "气瓶", "软管", "阀门", "减压阀", "报警器"]) and (
        _has_any(value, ["多久", "更换", "是否", "可不可以", "能不能", "可以吗", "怎么", "如何", "注意", "规范", "平放", "立放"])
        or "?" in value
        or "？" in value
    ):
        return "general_qa"
    return "none"


def _is_safety_overview_request(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    return _has_any(value, ["日常用气安全", "安全注意事项", "安全清单", "安全总则", "安全规范总览", "安全要点"])


def _safety_typed_fallback_reply(text, safety_kind):
    kind = str(safety_kind or "none")
    value = _normalize_user_text(text)
    if kind == "emergency":
        return _safety_emergency_reply()
    if kind == "leak_assess":
        return (
            "可以先按这 3 步判断是否疑似泄漏：\n"
            "1. 用肥皂水涂在阀门、减压阀和软管接口处，持续冒泡通常表示该处有泄漏。\n"
            "2. 观察是否有持续异味或报警器反复报警。\n"
            "3. 一旦怀疑泄漏，先关阀开窗，避免一切火源和电器开关，再联系专业人员上门排查。"
        )
    if kind == "general_qa":
        if _is_safety_overview_request(value):
            return _basic_safety_general_reply()
        if "软管" in value and _has_any(value, ["多久", "更换", "寿命", "年限"]):
            return (
                "燃气软管通常建议 1-2 年检查或更换一次；如果出现老化、裂纹、发硬、松动，要立即更换。"
                "日常尽量避免软管过长、折弯和靠近高温。"
            )
        if _has_any(value, ["气瓶", "钢瓶"]) and _has_any(value, ["平放", "横放", "倒放"]):
            return (
                "液化气瓶不建议平放、横放或倒放，必须保持直立使用和运输。"
                "平放会影响减压器工作并增加泄漏风险。"
            )
        return (
            "这类属于日常用气安全问题。核心是三点：设备定期检查、用气保持通风、人离火灭后先关灶再关阀。"
            "如果您告诉我具体场景（家用/餐饮、设备类型），我可以给到更细的可执行建议。"
        )
    if _is_safety_overview_request(value):
        return _basic_safety_general_reply()
    return (
        "先给您一个稳妥原则：设备异常先停用、保持通风、不要自行拆改，优先联系专业人员处理。"
        "您也可以补一句具体场景，我直接给步骤。"
    )


def _looks_like_resource_query(text, resource_terms):
    value = _normalize_user_text(text)
    if not value:
        return False
    value_compact = _compact_text(value)
    if _has_any(value, RESOURCE_QUERY_BLOCK_VERBS):
        return False
    if not _has_any(value, resource_terms):
        return False
    if _has_any(value, RESOURCE_QUERY_VERBS):
        return True
    if "?" in value or "？" in value:
        return True
    if _has_any(value, RESOURCE_QUERY_NOUN_HINTS):
        return True
    if _has_any(value, ["我有", "我现在有", "我目前有", "我当前有"]) and _has_any(
        value, ["有几个", "有多少", "有哪些", "有哪几个"]
    ):
        return True
    for term in resource_terms:
        term_compact = _compact_text(term)
        if not term_compact:
            continue
        direct_forms = {
            term_compact,
            f"我的{term_compact}",
            f"{term_compact}列表",
            f"我的{term_compact}列表",
            f"全部{term_compact}",
            f"所有{term_compact}",
        }
        if value_compact in direct_forms:
            return True
        if f"我的{term_compact}" in value_compact and _has_any(
            value_compact, ["有几个", "有多少", "有哪些", "有哪几个", "列表", "清单", "全部", "所有"]
        ):
            return True
    return False


def _query_intent_override(text):
    value = _normalize_user_text(text)
    if not value:
        return None
    if _looks_like_resource_query(value, ["地址", "收货地址", "默认地址", "地址列表", "我的地址"]):
        return "ADDRESS_QUERY"
    if _looks_like_resource_query(value, ["资料", "账号信息", "账户信息", "个人资料", "我的资料", "个人信息", "显示名", "用户名"]):
        return "PROFILE_QUERY"
    if _looks_like_resource_query(value, ["通知", "消息", "站内信", "提醒", "通知列表", "消息列表", "未读消息", "我的通知"]):
        return "NOTIFICATION_QUERY"
    return None


def _query_entity_from_intent(intent_code):
    mapping = {
        "ADDRESS_QUERY": "ADDRESS",
        "PROFILE_QUERY": "PROFILE",
        "NOTIFICATION_QUERY": "NOTIFICATION",
        "QUERY_ORDER": "ORDER",
    }
    return mapping.get(str(intent_code or "").upper(), "NONE")


def _compute_task_entity_signal(text, pending_action=None):
    value = _normalize_user_text(text)
    evidence = []
    if isinstance(pending_action, dict) and _is_write_pending_action(pending_action):
        return {
            "task_type": "ACTION",
            "entity": "NONE",
            "confidence": 0.98,
            "intent": str(pending_action.get("type") or ""),
            "strength": "WRITE_PENDING",
            "evidence": [f"pending_action={pending_action.get('type')}"],
        }

    query_intent = _query_intent_override(value)
    if query_intent:
        evidence.append("query_override")
        return {
            "task_type": "QUERY",
            "entity": _query_entity_from_intent(query_intent),
            "confidence": 0.92,
            "intent": query_intent,
            "strength": "QUERY_STRONG",
            "evidence": evidence,
        }

    if _extract_order_ref(value)[0] or _extract_order_ref(value)[1] or _looks_like_query_order(value):
        if _has_any(value, ORDER_QUERY_BLOCK_ACTION_KEYWORDS):
            return {
                "task_type": "ACTION",
                "entity": "ORDER",
                "confidence": 0.82,
                "intent": "UNKNOWN",
                "strength": "ACTION_STRONG",
                "evidence": ["order_query_blocked_by_action_terms"],
            }
        return {
            "task_type": "QUERY",
            "entity": "ORDER",
            "confidence": 0.88,
            "intent": "QUERY_ORDER",
            "strength": "QUERY_STRONG",
            "evidence": ["order_ref_or_order_query"],
        }

    if _is_high_risk_safety_query(value):
        return {
            "task_type": "KNOWLEDGE",
            "entity": "SAFETY",
            "confidence": 0.96,
            "intent": "SAFETY_EMERGENCY",
            "strength": "SAFETY_HIGH_RISK",
            "evidence": ["high_risk_safety"],
        }

    if _is_ambiguous_request(value):
        return {
            "task_type": "AMBIGUOUS",
            "entity": "NONE",
            "confidence": 0.72,
            "intent": "UNKNOWN",
            "strength": "AMBIGUOUS",
            "evidence": ["low_information_input"],
        }

    return {
        "task_type": "SMALLTALK",
        "entity": "NONE",
        "confidence": 0.6,
        "intent": "UNKNOWN",
        "strength": "SMALLTALK",
        "evidence": [],
    }


def _set_rag_topic(topic):
    normalized = str(topic or "none")
    _set_routing_extra(kb_topic=normalized, rag_topic_selected=normalized)


def _is_ambiguous_request(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    if _is_high_risk_safety_query(value) or _is_safety_emergency_query(value):
        return False
    if _direct_chat_reply(value):
        return False
    if _query_intent_override(value):
        return False
    if _looks_like_query_order(value) or _extract_order_ref(value)[0] or _extract_order_ref(value)[1]:
        return False
    if _extract_service_type(value) or _is_cart_context(value):
        return False
    if _has_any(
        value,
        [
            "我有个问题",
            "我想问个事",
            "想问一下",
            "咨询一下",
            "帮我看看",
            "看下这个",
            "这个怎么弄",
            "怎么处理这个",
        ],
    ):
        return True
    if len(value) <= 8 and not _has_any(value, ["地址", "订单", "资料", "通知", "燃气", "煤气", "发票", "价格"]):
        return True
    return False


def _clarify_topic_from_text(text):
    value = _normalize_user_text(text)
    if _has_any(value, ["地址", "收货", "默认地址"]):
        return "address"
    if _has_any(value, ["订单", "这单", "那单", "支付", "取消", "改址"]):
        return "order"
    if _has_any(value, ["燃气", "煤气", "液化气", "安全", "漏气", "异味"]):
        return "safety"
    if _has_any(value, ["资料", "账号", "个人信息", "通知", "消息"]):
        return "account"
    return "general"


def _ambiguity_clarify_reply(topic, round_no=1):
    first_round_mapping = {
        "address": "我先确认一下，您是要“查询地址列表”，还是要“新增/修改地址”？",
        "order": "我先确认一下，您是要“查询订单状态”，还是要“执行订单操作（支付/取消/改址）”？",
        "safety": "我先确认一下，您是要“日常用气安全建议”，还是“疑似泄漏应急处理”？",
        "account": "我先确认一下，您是要“查询账号资料/通知”，还是要“修改资料设置”？",
        "general": "我先确认一下，您这次是要我“查询信息”、还是“直接办理业务”？",
    }
    second_round_mapping = {
        "address": "为了马上处理，请直接回复：1 查询地址列表；2 新增地址；3 修改或删除地址。",
        "order": "为了马上处理，请直接回复：1 查询订单状态；2 支付或取消订单；3 订单改址。",
        "safety": "为了马上处理，请直接回复：1 日常用气安全建议；2 疑似泄漏应急处理。",
        "account": "为了马上处理，请直接回复：1 查询资料或通知；2 修改资料设置。",
        "general": "为了马上处理，请直接回复：1 查询信息；2 办理业务；3 安全咨询。",
    }
    mapping = second_round_mapping if int(round_no or 1) >= 2 else first_round_mapping
    return mapping.get(topic, mapping["general"])


def _ambiguity_fallback_reply(topic):
    mapping = {
        "address": "我先按通用入口给您处理：您可以直接说“查地址列表”，或“新增地址 张三 13800138000 上海市xx路xx号”。",
        "order": "我先按通用入口给您处理：您可以直接说“查订单状态”，或“取消订单 LPG2026xxxx”。",
        "safety": "我先按通用入口给您处理：您可以直接说“日常用气安全建议”，或“闻到煤气味怎么办”。",
        "account": "我先按通用入口给您处理：您可以直接说“看我的资料”或“看我的通知”。",
        "general": "我先按通用入口给您处理：您可以直接说“查地址”“查订单”“下单”或“安全咨询”。",
    }
    return mapping.get(topic, mapping["general"])


def _get_topic_followup_state():
    memory = _portal_memory()
    state = memory.get("topic_followup") if isinstance(memory, dict) else None
    if not isinstance(state, dict):
        return None
    topic = str(state.get("topic") or "").strip().lower()
    expected_slot = str(state.get("expected_slot") or "").strip().lower()
    if not topic or not expected_slot:
        return None
    return {
        "topic": topic,
        "expected_slot": expected_slot,
        "updated_at": str(state.get("updated_at") or ""),
    }


def _set_topic_followup_state(topic, expected_slot):
    payload = {
        "topic": str(topic or "").strip().lower(),
        "expected_slot": str(expected_slot or "").strip().lower(),
        "updated_at": timezone.now().isoformat(),
    }
    if not payload["topic"] or not payload["expected_slot"]:
        return
    _update_portal_memory({"topic_followup": payload})


def _clear_topic_followup_state():
    memory = _portal_memory()
    if not isinstance(memory, dict) or "topic_followup" not in memory:
        return
    memory.pop("topic_followup", None)
    PORTAL_MEMORY_CTX.set(memory)


def _extract_safety_scene_slot(text):
    value = _normalize_user_text(text)
    if not value:
        return ""
    if _has_any(value, ["餐饮门店", "餐饮店"]):
        return "餐饮门店"
    if _has_any(value, ["餐饮", "后厨", "饭店", "餐馆"]):
        return "餐饮"
    if _has_any(value, ["家用", "家庭", "住宅"]):
        return "家用"
    if _has_any(value, ["商用", "门店", "店铺"]):
        return "商用"
    return ""


def _should_set_safety_scene_followup(text, safety_kind):
    if str(safety_kind or "") != "general_qa":
        return False
    value = _normalize_user_text(text)
    if not value:
        return False
    if _extract_safety_scene_slot(value):
        return False
    if _has_any(value, ["软管", "平放", "横放", "倒放", "泄漏", "漏气", "检漏", "报警器", "减压阀", "阀门"]):
        return False
    return _has_any(value, ["燃气安全", "用气安全", "安全注意", "注意安全", "安全要点", "安全规范"])


def _safety_scene_fallback_reply(scene):
    scene_value = str(scene or "").strip()
    if scene_value == "餐饮":
        return (
            "按餐饮场景，先抓 4 个要点：\n"
            "1. 每日开店前检查软管、阀门和接口，异常先停用再报修。\n"
            "2. 后厨保持持续通风，灶台周边不堆放易燃物。\n"
            "3. 班后执行“先关灶、再关阀、再复核”并留记录。\n"
            "4. 员工统一培训应急流程，闻到异味先关阀开窗撤离，再联系专业人员。"
        )
    if scene_value == "家用":
        return (
            "按家用场景，建议重点做这 4 点：\n"
            "1. 做饭时保持通风，不让老人和孩子单独长时间用气。\n"
            "2. 软管和阀门每月看一次，发现老化松动立即更换。\n"
            "3. 外出或睡前执行“先关灶、再关阀”。\n"
            "4. 出现异味先关阀开窗，不动电器开关，撤离后联系专业人员。"
        )
    return (
        "这个场景下可先按通用原则执行：保持通风、定期检查接口与阀门、离场先关灶再关阀。"
        "如果您再补一句具体设备（钢瓶/管道/报警器），我可以给更细的检查清单。"
    )


def _get_clarify_state():
    memory = _portal_memory()
    state = memory.get("clarify_state") if isinstance(memory, dict) else None
    if not isinstance(state, dict):
        return None
    topic = str(state.get("topic") or "").strip()
    try:
        round_no = int(state.get("round") or 0)
    except Exception:
        round_no = 0
    if not topic or round_no <= 0:
        return None
    return {"topic": topic, "round": min(round_no, 2)}


def _set_clarify_state(topic, round_no, user_text):
    state = {
        "topic": str(topic or "general"),
        "round": max(1, min(int(round_no or 1), 2)),
        "last_user_text": str(user_text or "")[:200],
        "updated_at": timezone.now().isoformat(),
    }
    _update_portal_memory({"clarify_state": state})


def _clear_clarify_state():
    memory = _portal_memory()
    if not isinstance(memory, dict) or "clarify_state" not in memory:
        return
    memory.pop("clarify_state", None)
    PORTAL_MEMORY_CTX.set(memory)


def _extract_phone(text):
    match = PHONE_PATTERN.search(text or "")
    return match.group(1) if match else None


def _extract_contact_name(text):
    value = (text or "").strip()
    match = re.search(r"(?:联系人|收货人|联系\s*人)[:：\s]*([\u4e00-\u9fa5]{2,8})", value)
    if match:
        return _clean_contact_name(match.group(1))
    phone = _extract_phone(value)
    if phone == "123" and not _has_any(value, ["联系人", "收货人", "联系电话", "手机号"]):
        phone = None
    if phone:
        name_match = re.search(r"([\u4e00-\u9fa5]{2,8})\s*" + re.escape(phone), value)
        if name_match:
            return _clean_contact_name(name_match.group(1))
    return None


def _extract_order_ref(text):
    value = text or ""
    no_match = ORDER_NO_PATTERN.search(value)
    order_no = no_match.group(1).upper() if no_match else ""
    order_id = None
    id_match = ORDER_ID_PATTERN.search(value)
    if id_match:
        try:
            order_id = int(id_match.group(1))
        except (TypeError, ValueError):
            order_id = None
    return order_id, order_no


def _extract_address_id(text):
    value = text or ""
    match = re.search(r"(?:地址\s*(?:id|ID|#|编号)?|address\s*(?:id|ID|#)?)\s*[:：#-]?\s*(\d{1,10})", value)
    if not match and "地址" in value:
        match = re.search(r"(?:id|ID|编号|#)\s*[:：#-]?\s*(\d{1,10})", value)
    if not match and _has_any(value, ["删", "删除", "移除"]):
        match = re.search(r"(?:id|ID|编号|#)\s*[:：#-]?\s*(\d{1,10})", value)
    if not match and _has_any(value, ["删", "删除", "移除", "设为默认", "默认地址", "修改", "更新", "改成", "改为"]):
        match = re.search(r"(\d{1,10})\s*号?\s*地址", value)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_page(text):
    value = text or ""
    match = re.search(r"第\s*(\d{1,3})\s*页", value)
    if not match:
        return None
    try:
        page = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return max(1, page)


def _extract_choice_index(text):
    value = text or ""
    match = CHOICE_INDEX_PATTERN.search(value)
    if not match:
        return None
    try:
        index = int(match.group(1))
    except (TypeError, ValueError):
        return None
    if index < 1:
        return None
    return index


def _extract_status_filter(text):
    value = text or ""
    for hint, status in STATUS_HINT_MAP:
        if hint in value:
            return status
    return ""


def _looks_like_pay_action(text):
    value = text or ""
    if any(keyword in value for keyword in PAY_ACTION_KEYWORDS):
        return True
    if "支付" in value and "待支付" not in value and "已支付" not in value:
        return True
    if "付款" in value and not any(keyword in value for keyword in PAY_STATUS_ONLY_KEYWORDS):
        return True
    return False


def _looks_like_query_order(text):
    value = text or ""
    if any(keyword in value for keyword in ORDER_QUERY_HINT_KEYWORDS):
        return True
    if _looks_like_resource_query(value, ["订单", "订单列表", "我的订单", "最近订单", "历史订单"]):
        return True
    if re.search(r"(?:我|现在|目前|当前)?(?:有多少|有几个|有哪些|有哪几笔).*(?:订单|单子)", value):
        return True
    if ("订单" in value or "单子" in value or "这单" in value or "那单" in value) and any(
        token in value for token in ["查", "看", "进度", "状态", "最新", "列表", "多少", "到哪", "到了吗", "啥状态", "现在在哪"]
    ):
        return True
    return False


def _looks_like_order_guide_query(text):
    value = text or ""
    if not value:
        return False
    if not any(keyword in value for keyword in ORDER_GUIDE_KEYWORDS):
        return False
    if _extract_service_type(value) and (_extract_quantity(value) or _extract_cylinder_type(value)):
        return False
    if _has_any(value, ORDER_GUIDE_ACTION_HINTS) and _has_any(value, ["下单", "订气", "叫气"]):
        return False
    return True


def _is_cart_context(text):
    value = text or ""
    if any(keyword in value for keyword in CART_CONTEXT_KEYWORDS):
        return True
    has_accessory_item = bool(_extract_accessory_items(value))
    strong_add_keywords = [keyword for keyword in CART_ADD_KEYWORDS if keyword not in CART_WEAK_ADD_KEYWORDS]
    has_cart_action = any(
        keyword in value
        for keyword in strong_add_keywords + CART_REMOVE_KEYWORDS + CART_CLEAR_KEYWORDS + CART_CHECKOUT_KEYWORDS
    )
    if "配件" in value and has_cart_action:
        return True
    if has_accessory_item and ("购物车" in value or has_cart_action):
        return True
    return False


def _looks_like_accessory_info_query(text):
    value = (text or "").strip()
    if not value:
        return False
    if _has_any(value, ["购物车", "加购", "加入购物车", "结算", "下单", "购买", "买", "来一件", "来两件"]):
        return False
    question_terms = ["怎么", "如何", "多久", "是否", "能不能", "可不可以", "可以吗", "区别", "推荐", "注意", "判断", "用法", "安装", "更换", "坏了", "故障", "失灵", "拆"]
    if not _has_any(value, ACCESSORY_TERMS):
        return False
    return _has_any(value, question_terms) or "？" in value or "?" in value


def _looks_like_service_info_query(text):
    value = (text or "").strip()
    if not value:
        return False
    if _has_any(value, ORDER_EXECUTION_TERMS):
        return False
    if _looks_like_price_query(value) or _looks_like_inspection_query(value) or _looks_like_safety_leak_check_query(value):
        return False
    if _is_cart_context(value):
        return False
    if not _has_any(value, SERVICE_INFO_TERMS) and not _extract_service_type(value):
        return False
    return _has_any(value, SERVICE_INFO_QUESTION_TERMS) or "？" in value or "?" in value


def _looks_like_alarm_device_risk_query(text):
    value = (text or "").strip()
    if "报警器" not in value:
        return False
    if _has_any(value, ["漏气", "泄漏", "异味", "燃气味", "煤气味"]):
        return True
    if _has_any(value, ALARM_DEVICE_RISK_KEYWORDS):
        return True
    return _has_any(value, ACCESSORY_QUESTION_KEYWORDS) and ("报警器" in value)


def _has_accessory_purchase_intent(text):
    value = text or ""
    if not value:
        return False
    if _has_any(value, ["要不要", "怎么", "如何", "是否", "能不能", "可不可以", "吗", "？", "?"]):
        return False
    if _has_any(value, ["加入购物车", "加购物车", "放购物车", "加购"]):
        return True
    if _has_any(value, ["帮我下", "给我下", "帮我买", "给我买", "购买", "下单", "结算"]):
        return True
    if _has_any(value, ACCESSORY_PURCHASE_NORMALIZE_KEYWORDS):
        return True
    if _extract_accessory_items(value) and _extract_quantity(value) and _has_any(value, ["我要", "我想要", "给我", "来", "弄", "配"]):
        return True
    if _extract_accessory_items(value) and _has_any(value, ["我要", "我想要", "给我", "来个", "来一", "来两", "来三"]):
        return True
    # 避免把“下来/要不要”这类词误判为购买意图。
    if _has_any(value, ["来一", "来两", "来三", "来个", "来件", "来套", "要一", "要两", "要个", "要件"]):
        return True
    if "买" in value and not _has_any(value, ["买吗", "能买", "可以买", "可买吗"]):
        return True
    return False


def _looks_like_address_book_update(text):
    value = _normalize_user_text(text)
    if not value or "地址" not in value:
        return False
    if _has_any(value, ["改址", "订单改址"]) or ("订单" in value and _has_any(value, ["改地址", "地址改为", "地址改成"])):
        return False
    if not _has_any(value, ["改", "修改", "更新", "更改", "改成", "改为", "变更"]):
        return False
    if _extract_address_id(value):
        return True
    if _has_any(value, ["默认地址"]) and _has_any(value, ["改", "修改", "更新", "改成", "改为"]):
        return True
    return False


def _wants_address_and_order_query(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    has_address_query = _looks_like_resource_query(value, ["地址", "收货地址", "地址列表", "我的地址"])
    has_order_query = _looks_like_query_order(value)
    if not (has_address_query and has_order_query):
        return False
    if _has_any(value, ["并", "同时", "顺便", "另外", "再", "一起", "也"]):
        return True
    return False


def _looks_like_cart_add(text):
    value = text or ""
    if not _extract_accessory_items(value):
        return False
    if _looks_like_alarm_device_risk_query(value):
        return False
    if _looks_like_accessory_info_query(value):
        return False
    if _is_cart_context(value):
        return True
    if "配件" in value and _has_accessory_purchase_intent(value):
        return True
    if _has_accessory_purchase_intent(value) and not _has_any(value, ACCESSORY_QUESTION_KEYWORDS):
        return True
    return False


def _looks_like_cart_remove(text):
    value = text or ""
    if not _extract_accessory_items(value):
        return False
    if not _is_cart_context(value):
        return False
    return any(keyword in value for keyword in CART_REMOVE_KEYWORDS)


def _looks_like_cart_clear(text):
    value = text or ""
    return any(keyword in value for keyword in CART_CLEAR_KEYWORDS)


def _looks_like_cart_checkout(text):
    value = text or ""
    if not _is_cart_context(value) and "配件" not in value:
        return False
    return any(keyword in value for keyword in CART_CHECKOUT_KEYWORDS)


def _build_cart_items_line(items):
    parts = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        sku = str(item.get("sku") or "")
        name = ACCESSORY_SKU_LABELS.get(sku, sku or "配件")
        qty = int(item.get("quantity") or 1)
        parts.append(f"{name}×{max(1, qty)}")
    return "、".join(parts)


def _build_cart_summary_reply(result):
    items = result.get("items") if isinstance(result, dict) else []
    if not items:
        return "您的购物车目前是空的。您可以直接说“软管2件加入购物车”。"
    lines = ["我帮您看了购物车："]
    for idx, item in enumerate(items[:6], start=1):
        name = item.get("name") or ACCESSORY_SKU_LABELS.get(item.get("sku"), item.get("sku") or "配件")
        lines.append(
            f"{idx}. {name} × {item.get('quantity') or 0}，小计 ¥{item.get('amount') or '0.00'}"
        )
    lines.append(
        f"合计 {result.get('selected_count') or 0} 件，金额 ¥{result.get('total_amount') or '0.00'}。"
    )
    lines.append("如果您确认，我可以直接帮您结算并支付。")
    return "\n".join(lines)


def _is_fee_detail_query(text):
    value = text or ""
    if not value:
        return False
    if any(keyword in value for keyword in ORDER_FEE_KEYWORDS):
        return True
    if "总价" in value and any(keyword in value for keyword in ["费用", "金额", "拆开", "明细"]):
        return True
    return False


def _is_order_quote_intent(text):
    value = text or ""
    if not value:
        return False
    has_quote_hint = any(keyword in value for keyword in ORDER_QUOTE_KEYWORDS)
    if not has_quote_hint:
        # 兼容“先看总价，我确认后你再下单”这类自然表达
        has_quote_hint = (
            "确认后" in value
            and ("下单" in value or "再下" in value)
            and ("总价" in value or "报价" in value or "价格" in value)
        )
    if not has_quote_hint:
        has_quote_hint = bool(re.search(r"(先|帮我先).{0,8}(算|估).{0,8}(总价|报价|价格)", value))
    if not has_quote_hint:
        return False
    if _has_any(value, ["确认后再下", "确认后你再下", "确认后再下单", "确认后下单", "confirm first"]):
        return True
    has_order_intent = _has_any(value, ["下单", "再下", "帮我下", "订", "叫气", "送气"])
    has_order_slots = bool(_extract_service_type(value) or _extract_cylinder_type(value) or _extract_quantity(value))
    if has_order_intent:
        return True
    return has_order_slots


def _looks_like_inspection_policy_question(text):
    value = text or ""
    if not value:
        return False
    if not _has_any(value, ["多久检一次", "几年一检", "检验周期", "年检周期", "法检周期"]):
        return False
    if _has_any(value, ["我的", "这单", "那单", "订单", "什么时候到期", "到期"]):
        return False
    return True


def _is_feedback_progress_query(text):
    value = text or ""
    if not value:
        return False
    if any(keyword in value for keyword in FEEDBACK_PROGRESS_KEYWORDS):
        return True
    if ("投诉" in value or "建议" in value or "反馈" in value) and any(
        keyword in value for keyword in ["进度", "状态", "处理到", "怎么查", "查询"]
    ):
        return True
    return False


def _is_online_feedback_topic(text):
    value = text or ""
    if not value:
        return False
    if any(keyword in value for keyword in ONLINE_FEEDBACK_KEYWORDS):
        return True
    if ("建议" in value or "投诉" in value) and any(keyword in value for keyword in ["页面", "功能", "系统", "客服回复"]):
        return True
    return False


def _is_order_service_feedback_topic(text):
    value = text or ""
    if not value:
        return False
    if _extract_order_ref(value)[0] or _extract_order_ref(value)[1]:
        return True
    return any(keyword in value for keyword in ORDER_SERVICE_FEEDBACK_KEYWORDS)


def _is_safety_emergency_query(text):
    value = text or ""
    if not value:
        return False
    if _is_cart_context(value):
        return False
    if "报警器" in value and not any(
        keyword in value for keyword in ["漏气", "泄漏", "异味", "燃气味", "煤气味", "报警响", "报警一直响"]
    ):
        return False
    has_scene = any(keyword in value for keyword in SAFETY_EMERGENCY_SCENE_KEYWORDS)
    has_action = any(keyword in value for keyword in SAFETY_EMERGENCY_ACTION_KEYWORDS)
    if has_scene and has_action:
        return True
    if any(keyword in value for keyword in ["疑似漏气", "闻到煤气味", "闻到燃气味"]) and any(
        keyword in value for keyword in ["稳妥", "先做", "先处理", "先报修", "怎么下", "咋办", "怎么办"]
    ):
        return True
    if ("燃气泄漏" in value or "煤气泄漏" in value) and ("先" in value or "快" in value):
        return True
    return False


def _detect_forbidden_ops(text):
    value = text or ""
    if not value:
        return None
    has_forbidden_verb = any(keyword in value for keyword in FORBIDDEN_DELETE_TAMPER_KEYWORDS + FORBIDDEN_PRICE_TAMPER_KEYWORDS)
    if not has_forbidden_verb and not any(keyword in value for keyword in FORBIDDEN_STATUS_TAMPER_KEYWORDS):
        return None

    if (
        "价格" in value
        and any(keyword in value for keyword in FORBIDDEN_PRICE_TAMPER_KEYWORDS)
        and any(keyword in value for keyword in ["订单", "购物车", "商品", "配件", "账单", "付款记录", "支付记录"])
    ):
        return {
            "type": "PRICE_TAMPER",
            "reason": "订单和商品价格是受控数据，不能直接改写。",
        }

    if (
        (
            any(keyword in value for keyword in FORBIDDEN_HISTORY_TAMPER_KEYWORDS)
            or ("订单" in value and ("记录" in value or "历史" in value))
        )
        and any(keyword in value for keyword in FORBIDDEN_DELETE_TAMPER_KEYWORDS + ["改", "修改"])
    ):
        return {
            "type": "HISTORY_TAMPER",
            "reason": "历史订单和支付记录不能删除或篡改。",
        }

    if any(keyword in value for keyword in FORBIDDEN_STATUS_TAMPER_KEYWORDS):
        return {
            "type": "STATUS_TAMPER",
            "reason": "订单状态必须按业务流程流转，不能手动强制修改。",
        }

    if any(keyword in value for keyword in ["伪造账单", "做假账", "改账单", "修改账单"]):
        return {
            "type": "BILL_TAMPER",
            "reason": "账单数据不能被伪造或手动改写。",
        }

    return None


def _split_mixed_request(text):
    value = text or ""
    if not value:
        return None
    has_mixed_hint = any(keyword in value for keyword in MIXED_SPLIT_HINTS)
    if not has_mixed_hint:
        return None
    if _has_any(value, ["退款", "申请退款", "退订单", "退货"]):
        return "REQUEST_REFUND"
    if _looks_like_query_order(value):
        return "QUERY_ORDER"
    if _has_any(value, ["投诉", "建议", "反馈"]):
        return "CREATE_FEEDBACK"
    return None


def _build_forbidden_reply(text, forbidden):
    reason = (forbidden or {}).get("reason") or "这类操作不支持直接执行。"
    mixed_intent = _split_mixed_request(text)
    if mixed_intent == "REQUEST_REFUND":
        return (
            f"{reason}不过退款可以正常办理。"
            "您把订单号发我，我马上按流程帮您申请退款。"
        )
    if mixed_intent == "QUERY_ORDER":
        return (
            f"{reason}我可以先帮您查这笔订单的当前状态和费用明细。"
            "您把订单号发我就行。"
        )
    if mixed_intent == "CREATE_FEEDBACK":
        return (
            f"{reason}如果您对处理方式有意见，我可以立刻帮您提交投诉或建议。"
        )
    return (
        f"{reason}我可以继续帮您做合规操作，比如查订单、申请退款或提交投诉建议。"
    )


def _extract_feedback_status(text):
    value = text or ""
    for hint, status in FEEDBACK_STATUS_HINT_MAP:
        if hint in value:
            return status
    return ""

def _extract_address(text):
    value = (text or "").strip()

    def _looks_like_address_ref(fragment):
        cleaned = (fragment or "").strip(" ：:,，。")
        if not cleaned:
            return True
        if _has_any(cleaned, ["那个", "这条", "那条", "那位", "这位", "这个", "那边", "那家", "这家"]):
            return True
        if re.fullmatch(r"1\d{2,10}", cleaned):
            return True
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", cleaned):
            return True
        has_address_shape = bool(re.search(r"(省|市|区|县|路|街|巷|号|栋|楼|单元|室)", cleaned))
        if not has_address_shape and cleaned.endswith(("的", "那个")):
            return True
        return False

    id_update_match = re.search(r"地址\s*(?:id|ID|编号|#)?\s*\d{1,10}\s*(?:改成|改为|更新为|更新成|为)\s*([^，。]+)", value)
    if id_update_match:
        tail = id_update_match.group(1).strip(" ：:,，。")
        if len(tail) >= 4 and not _looks_like_address_ref(tail):
            return tail
    markers = ["地址改为", "地址改成", "地址是", "地址为", "送到", "送至", "改到", "改为", "地址"]
    for marker in markers:
        if marker in value:
            tail = value.split(marker, 1)[1].strip(" ：:,，。")
            if len(tail) >= 4 and not _looks_like_address_ref(tail):
                return tail
    address_like = re.search(r"([\u4e00-\u9fa5A-Za-z0-9#\-]{4,}(?:省|市|区|县|路|街|巷|号|栋|楼|单元|室).*)", value)
    if address_like:
        return address_like.group(1).strip()
    return None


def _normalize_match_text(value):
    return re.sub(r"[^0-9a-z\u4e00-\u9fa5]", "", str(value or "").lower())


def _address_candidate_brief(item):
    if not isinstance(item, dict):
        return {}
    return {
        "id": item.get("id"),
        "address_full": item.get("address_full") or "",
        "door_note": item.get("door_note") or "",
        "contact_name": item.get("contact_name") or "",
        "contact_phone": item.get("contact_phone") or "",
        "is_default": bool(item.get("is_default")),
    }


def _extract_address_selector_hint(text):
    value = (text or "").strip()
    if not value:
        return {}
    if not _has_any(value, ["地址", "默认", "那个", "这条", "那条", "这位", "那位", "改成", "改为", "换成", "换到", "选"]):
        return {}

    selector = {}
    address_id = _extract_address_id(value)
    if address_id:
        selector["address_id"] = int(address_id)
    if _has_any(value, ["默认地址", "地址默认那个", "就默认那个", "默认那个", "用默认"]):
        selector["use_default"] = True

    phone_matches = re.findall(r"(?<!\d)(1\d{2,10})(?!\d)", value)
    if phone_matches:
        selector["phone_prefix"] = str(phone_matches[0]).strip()

    name_match = re.search(r"([\u4e00-\u9fa5]{2,8})\s*的\s*(?:那个|那条|这条|那位|这位)", value)
    if not name_match:
        name_match = re.search(r"(?:联系人|收货人|名字|人名)\s*(?:是|叫|为|改成|改为)?\s*([\u4e00-\u9fa5]{2,8})", value)
    if name_match:
        raw_name = _clean_contact_name(name_match.group(1))
        for prefix in ["改成地址是", "改成地址为", "地址改成", "地址改为", "改成", "改为", "地址是", "地址为", "用", "换成", "换到"]:
            if raw_name.startswith(prefix):
                raw_name = raw_name[len(prefix) :].strip()
        if raw_name:
            selector["name_fragment"] = _clean_contact_name(raw_name)

    addr_fragment_match = re.search(
        r"地址(?:改成|改为|改到|换成|换到|是|为)?\s*([A-Za-z0-9\u4e00-\u9fa5#\-]{2,30})\s*(?:那个|那条|这条|那位|这位)?",
        value,
    )
    if addr_fragment_match:
        fragment = (addr_fragment_match.group(1) or "").strip()
        fragment = re.sub(r"(?:的)?(?:那个|那条|这条|那位|这位)$", "", fragment).strip()
        if fragment and not re.search(r"(省|市|区|县|路|街|巷|号|栋|楼|单元|室)", fragment):
            pure_digits = re.sub(r"\D", "", fragment)
            if pure_digits and re.fullmatch(r"\d{2,10}", pure_digits):
                pass
            elif selector.get("phone_prefix") and _normalize_match_text(fragment) == _normalize_match_text(selector.get("phone_prefix")):
                pass
            elif re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", fragment):
                if not selector.get("name_fragment"):
                    selector["name_fragment"] = _clean_contact_name(fragment)
            elif not selector.get("name_fragment") or selector.get("name_fragment") != fragment:
                selector["address_fragment"] = fragment

    return selector


def _format_address_selector_hint(selector):
    if not isinstance(selector, dict):
        return ""
    if selector.get("address_id"):
        return f"地址ID {selector.get('address_id')}"
    if selector.get("phone_prefix"):
        return f"手机号前缀 {selector.get('phone_prefix')}"
    if selector.get("name_fragment"):
        return f"联系人 {selector.get('name_fragment')}"
    if selector.get("address_fragment"):
        return f"地址关键词 {selector.get('address_fragment')}"
    if selector.get("use_default"):
        return "默认地址"
    return "该地址"


def _resolve_address_selector(addresses, selector):
    if not isinstance(selector, dict) or not selector:
        return {"status": "none"}
    candidates = [_address_candidate_brief(item) for item in (addresses or []) if isinstance(item, dict)]
    if not candidates:
        return {"status": "not_found", "selector": selector, "candidates": []}

    address_id = selector.get("address_id")
    if address_id is not None:
        for item in candidates:
            try:
                if int(item.get("id")) == int(address_id):
                    return {"status": "matched", "selector": selector, "match": item}
            except (TypeError, ValueError):
                continue
        return {"status": "not_found", "selector": selector, "candidates": []}

    if selector.get("use_default") is True:
        for item in candidates:
            if item.get("is_default"):
                return {"status": "matched", "selector": selector, "match": item}

    filtered = list(candidates)
    phone_prefix = str(selector.get("phone_prefix") or "").strip()
    if phone_prefix:
        filtered = [
            item
            for item in filtered
            if re.sub(r"\D", "", str(item.get("contact_phone") or "")).startswith(re.sub(r"\D", "", phone_prefix))
        ]

    name_fragment = str(selector.get("name_fragment") or "").strip()
    if name_fragment:
        name_norm = _normalize_match_text(name_fragment)
        filtered = [
            item
            for item in filtered
            if name_norm and name_norm in _normalize_match_text(item.get("contact_name") or "")
        ]

    addr_fragment = str(selector.get("address_fragment") or "").strip()
    if addr_fragment:
        addr_norm = _normalize_match_text(addr_fragment)
        filtered = [
            item
            for item in filtered
            if addr_norm
            and (
                addr_norm in _normalize_match_text(item.get("address_full") or "")
                or addr_norm in _normalize_match_text(item.get("door_note") or "")
            )
        ]

    if len(filtered) == 1:
        return {"status": "matched", "selector": selector, "match": filtered[0]}
    if len(filtered) > 1:
        return {"status": "ambiguous", "selector": selector, "candidates": filtered[:5]}
    return {"status": "not_found", "selector": selector, "candidates": []}


def _extract_address_payload(text):
    value = (text or "").strip()
    payload = {}
    phone = _extract_phone(value)
    if phone == "123" and not _has_any(value, ["联系人", "收货人", "联系电话", "手机号"]):
        phone = None
    if phone:
        payload["contact_phone"] = phone
    name = _extract_contact_name(value)
    if name:
        payload["contact_name"] = name

    address_full = _extract_address(value)
    if address_full and name and phone:
        address_full = re.sub(r"^\s*" + re.escape(name) + r"\s*" + re.escape(phone) + r"\s*", "", address_full).strip()
    elif address_full and phone:
        address_full = re.sub(r"^\s*" + re.escape(phone) + r"\s*", "", address_full).strip()
    if not address_full and phone:
        tail_match = re.search(re.escape(phone) + r"\s*([^\n，。]{6,180})", value)
        if tail_match:
            address_full = tail_match.group(1).strip(" ：:,，。")
    if address_full:
        payload["address_full"] = address_full

    if "门牌" in value:
        note_match = re.search(r"门牌(?:备注)?\s*(?:是|为|：|:)?\s*([^\n，。]{1,80})", value)
        if note_match:
            payload["door_note"] = note_match.group(1).strip()
    return payload


def _sanitize_modify_address_text(address_text):
    value = str(address_text or "").strip()
    if not value:
        return ""
    cleaned = value
    prefix_patterns = [
        r"^(?:把)?(?:这单|那单|订单)?(?:的)?(?:地址)?(?:改址|改地址|改成|改为|修改为|修改成|变更为|变更成|调整为)(?:到|为|成)?",
        r"^(?:地址)(?:改成|改为|改到|修改为|修改成)?(?:到|为|成)?",
        r"^(?:改址|改地址)(?:到|为|成)?",
    ]
    for pattern in prefix_patterns:
        cleaned = re.sub(pattern, "", cleaned).strip(" ：:,，。;；")
    trailing_markers = ["联系人", "联系电话", "电话", "手机号", "收货人"]
    cut_index = len(cleaned)
    for marker in trailing_markers:
        idx = cleaned.find(marker)
        if idx > 0:
            cut_index = min(cut_index, idx)
    if cut_index < len(cleaned):
        cleaned = cleaned[:cut_index].strip(" ：:,，。;；")
    if len(cleaned) >= 6:
        return cleaned
    return value


def _extract_notes(text):
    value = (text or "").strip()
    for marker in ["备注", "说明", "要求"]:
        if marker in value:
            tail = value.split(marker, 1)[1].strip(" ：:,，。")
            if tail:
                return tail
    return None


def _extract_invoice_note(text):
    value = (text or "").strip()
    if not value or not any(keyword in value for keyword in INVOICE_KEYWORDS):
        return ""
    if _has_any(value, ["不开票", "不要发票", "不需要发票", "不用开票", "先不开票"]):
        return ""
    parts = []
    if "普票" in value:
        parts.append("票种：普票")
    if "专票" in value:
        parts.append("票种：专票")

    title_match = re.search(r"(?:抬头|发票抬头)\s*(?:是|为|：|:)?\s*([^\n，。,；;]{2,60})", value)
    if title_match:
        parts.append(f"抬头：{title_match.group(1).strip()}")

    tax_match = re.search(r"(?:税号)\s*(?:是|为|：|:)?\s*([A-Za-z0-9]{8,30})", value)
    if tax_match:
        parts.append(f"税号：{tax_match.group(1).strip().upper()}")

    if not parts:
        parts.append("需要开票（详细信息待补充）")
    return "发票信息：" + "；".join(parts)


def _strip_invoice_note_from_notes(notes):
    raw = str(notes or "").strip()
    if not raw:
        return ""
    chunks = [chunk.strip() for chunk in re.split(r"[；;]", raw) if chunk and chunk.strip()]
    kept = []
    for chunk in chunks:
        if "发票信息" in chunk:
            continue
        if _has_any(chunk, ["需要开票", "开票", "发票抬头", "税号"]) and len(chunks) > 1:
            continue
        kept.append(chunk)
    if not kept:
        return ""
    return "；".join(kept)


def _extract_invoice_fields(text):
    value = (text or "").strip()
    if not value:
        return {}
    negative = ["不开票", "不要发票", "不需要发票", "不用开票", "先不开票"]
    if _has_any(value, negative):
        return {"need_invoice": False, "invoice_title": "", "invoice_tax_no": ""}
    if not _has_any(value, INVOICE_KEYWORDS):
        return {}
    output = {"need_invoice": True}
    title_match = re.search(r"(?:抬头|发票抬头)\s*(?:是|为|：|:)?\s*([^\n，。,；;]{2,60})", value)
    if title_match:
        output["invoice_title"] = title_match.group(1).strip()
    tax_match = re.search(r"(?:税号)\s*(?:是|为|：|:)?\s*([A-Za-z0-9]{8,30})", value)
    if tax_match:
        output["invoice_tax_no"] = tax_match.group(1).strip().upper()
    return output


def _looks_like_invoice_preference_update(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    if not _has_any(value, INVOICE_KEYWORDS):
        return False
    if _has_any(value, ["不开票", "不要发票", "不需要发票", "不用开票", "先不开票"]):
        return True
    explicit_toggle_terms = [
        "开票改成",
        "开票改为",
        "改成开票",
        "改为开票",
        "要开票",
        "需要开票",
        "开发票",
        "开票",
        "发票改成",
        "发票改为",
    ]
    if _has_any(value, explicit_toggle_terms):
        if _has_any(value, ["流程", "规则", "怎么", "如何", "补开", "税号怎么", "抬头怎么", "企业开票流程"]):
            # 中文注释：存在明显咨询语义时，避免误当成“开关偏好”。
            return _has_any(value, ["改成", "改为", "要", "需要", "不用", "不要"])
        return True
    return False


def _pick_default_modifiable_order(run, portal_user_id):
    candidates = []
    for status_code in DEFAULT_MODIFIABLE_ORDER_STATUSES:
        result = execute_tool(
            run,
            "portal_list_orders",
            {"portal_user_id": portal_user_id, "status": status_code, "page": 1, "page_size": 1},
        )
        items = result.get("items") if isinstance(result, dict) else []
        if not items:
            continue
        item = items[0] if isinstance(items[0], dict) else {}
        created_at = item.get("created_at")
        created_ts = datetime.min
        if created_at:
            try:
                created_ts = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            except Exception:
                created_ts = datetime.min
        candidates.append(
            {
                "id": item.get("id"),
                "order_no": item.get("order_no"),
                "status": item.get("status"),
                "created_at": created_at,
                "_created_ts": created_ts,
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.get("_created_ts") or datetime.min, reverse=True)
    chosen = dict(candidates[0] or {})
    chosen.pop("_created_ts", None)
    return chosen


def _filter_payload_by_service_type(service_type, payload):
    if not isinstance(payload, dict):
        return {}
    if service_type in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}:
        keep = {"cylinder_type", "quantity", "return_empty"}
    elif service_type == SERVICE_TYPE_INSTALLATION:
        keep = {"install_item"}
    elif service_type == SERVICE_TYPE_SAFETY_CHECK:
        keep = {"check_scope"}
    elif service_type == SERVICE_TYPE_REPAIR:
        keep = {"issue_desc"}
    elif service_type == SERVICE_TYPE_ACCESSORIES:
        keep = {"items"}
    else:
        return dict(payload)
    return {key: value for key, value in payload.items() if key in keep}


def _merge_notes(existing, incoming):
    base = (existing or "").strip()
    extra = (incoming or "").strip()
    if not extra:
        return base
    if not base:
        return extra
    if extra in base:
        return base
    return f"{base}；{extra}"


def _parse_chinese_quantity(text):
    if text in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[text]
    if text == "十一":
        return 11
    if text == "十二":
        return 12
    return None


def _extract_quantity(text):
    value = text or ""
    m = re.search(r"(\d+)\s*(瓶|罐|个|件|套|只|台|条)", value)
    if m:
        try:
            return max(1, int(m.group(1)))
        except (TypeError, ValueError):
            return None
    chinese = re.search(r"([一二两三四五六七八九十]{1,2})\s*(瓶|罐|个|件|套|只|台|条)", value)
    if chinese:
        qty = _parse_chinese_quantity(chinese.group(1))
        if qty:
            return qty
    if "一瓶" in value or "一罐" in value:
        return 1
    return None


def _extract_cylinder_type(text):
    value = (text or "").lower()
    if "45kg" in value or "45公斤" in value or "45 公斤" in value:
        return "45kg"
    if "15kg" in value or "15公斤" in value or "15 公斤" in value:
        return "15kg"
    if "5kg" in value or "5公斤" in value or "5 公斤" in value:
        return "5kg"
    return None


def _extract_invalid_cylinder_size(text):
    value = (text or "").lower()
    match = re.search(r"(\d+)\s*(kg|公斤)", value)
    if not match:
        return None
    try:
        size = int(match.group(1))
    except (TypeError, ValueError):
        return None
    if size in {5, 15, 45}:
        return None
    return size


def _extract_time_request(text):
    value = (text or "").strip()
    if not value:
        return {}

    if _has_any(value.lower(), ["asap", "尽快", "马上", "立刻", "越快越好", "现在"]):
        return {"asap": True}

    now = timezone.localtime(timezone.now())
    eta_date = ""
    eta_slot = ""

    date_match = DATE_PATTERN.search(value)
    if date_match:
        eta_date = date_match.group(1)

    slot_match = SLOT_PATTERN.search(value)
    if slot_match:
        start_hour = int(slot_match.group(1))
        start_min = int(slot_match.group(2))
        end_hour = int(slot_match.group(3))
        end_min = int(slot_match.group(4))
        if start_min in {0, 30} and end_min in {0, 30}:
            duration = (end_hour * 60 + end_min) - (start_hour * 60 + start_min)
            if duration == 120:
                eta_slot = f"{start_hour:02d}:{start_min:02d}-{end_hour:02d}:{end_min:02d}"

    if not eta_slot:
        zh_hour = ZH_HOUR_RANGE_PATTERN.search(value)
        if zh_hour:
            start_hour = int(zh_hour.group(1))
            end_hour = int(zh_hour.group(2))
            if end_hour > start_hour and (end_hour - start_hour) == 2:
                eta_slot = f"{start_hour:02d}:00-{end_hour:02d}:00"

    if not eta_date:
        if "后天" in value:
            eta_date = (now + timedelta(days=2)).date().isoformat()
        elif "明天" in value:
            eta_date = (now + timedelta(days=1)).date().isoformat()
        elif "今天" in value:
            eta_date = now.date().isoformat()

    if not eta_slot:
        period_slot_map = [
            ("上午", "09:00-11:00"),
            ("中午", "11:00-13:00"),
            ("下午", "13:00-15:00"),
            ("傍晚", "17:00-19:00"),
            ("晚上", "19:00-21:00"),
        ]
        for key, slot in period_slot_map:
            if key in value:
                eta_slot = slot
                break

    if eta_date and eta_slot:
        return {"eta_date": eta_date, "eta_slot": eta_slot}
    return {}


def _extract_delivery_mode(text):
    value = (text or "").strip().lower()
    if not value:
        return None
    if _has_any(value, ["立即配送", "马上送", "尽快送", "现在送", "asap", "马上", "立刻", "尽快", "立即"]):
        return "ASAP"
    if _has_any(value, ["预约配送", "预约", "定时", "指定时间", "明天", "后天", "今天"]) and not _has_any(
        value, ["尽快", "马上", "立即"]
    ):
        return "SCHEDULED"
    return None


def _extract_urgent_flag(text):
    value = text or ""
    if _has_any(value, ["不加急", "普通", "正常"]):
        return False
    if "加急" in value:
        return True
    return None


def _extract_accessory_items(text):
    value = text or ""
    sku_keywords = {
        "HOSE": ["软管", "燃气软管", "胶管", "燃气胶管"],
        "REGULATOR": ["减压阀", "调压阀"],
        "ALARM": ["报警器", "燃气报警器"],
        "VALVE": ["自闭阀"],
        "STOVE_1B": ["单眼灶", "单灶", "单眼燃气灶", "单头灶"],
        "STOVE_2B": ["双眼灶", "双灶", "双眼燃气灶", "双头灶", "燃气灶", "灶具"],
        "IGNITER": ["点火器"],
        "SEAL_TAPE": ["生料带", "密封带"],
        "CLAMP_SET": ["卡箍", "卡箍套装"],
    }
    fallback_qty = _extract_quantity(value) or 1
    items = []
    for sku, keywords in sku_keywords.items():
        hit_keyword = None
        for keyword in keywords:
            if keyword in value:
                hit_keyword = keyword
                break
        if not hit_keyword:
            continue

        qty = fallback_qty
        qty_match = re.search(
            re.escape(hit_keyword) + r"\s*(\d+|[一二两三四五六七八九十]{1,2})\s*(个|件|套|只|台|条)?",
            value,
        )
        if not qty_match:
            qty_match = re.search(
                r"(\d+|[一二两三四五六七八九十]{1,2})\s*(个|件|套|只|台|条)?\s*" + re.escape(hit_keyword),
                value,
            )
        if qty_match:
            raw_qty = qty_match.group(1)
            if raw_qty.isdigit():
                qty = int(raw_qty)
            else:
                qty = _parse_chinese_quantity(raw_qty) or qty
        items.append({"sku": sku, "quantity": max(1, int(qty))})
    return items


def _extract_display_name(text):
    value = (text or "").strip()
    patterns = [
        r"(?:改名(?:字)?|修改(?:昵称|用户名|姓名|显示名))\s*(?:为|成)?\s*([\u4e00-\u9fa5A-Za-z0-9_（）()]{2,32})",
        r"(?:叫我|昵称改为|用户名改为)\s*([\u4e00-\u9fa5A-Za-z0-9_]{2,32})",
        r"(?:用户名|昵称|姓名|显示名)\s*改(?:为|成)?\s*([\u4e00-\u9fa5A-Za-z0-9_（）()]{2,32})",
        r"改成[“\"']?([\u4e00-\u9fa5A-Za-z0-9_（）()]{2,32})[”\"']?",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return None


def _extract_notification_id(text):
    value = text or ""
    match = re.search(r"(?:通知|消息|第)\s*#?\s*(\d{1,10})", value)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_password_fields(text, last_asked=None):
    value = (text or "").strip()
    if not value:
        return {}
    output = {}
    patterns = {
        "old_password": [
            r"(?:旧密码|原密码)\s*(?:是|为|:|：)?\s*([^\s，。,；;]{3,64})",
        ],
        "new_password": [
            r"(?:新密码)\s*(?:是|为|:|：)?\s*([^\s，。,；;]{3,64})",
        ],
        "confirm_password": [
            r"(?:确认密码|确认新密码|再次输入)\s*(?:是|为|:|：)?\s*([^\s，。,；;]{3,64})",
        ],
    }
    for key, regex_list in patterns.items():
        for regex in regex_list:
            match = re.search(regex, value, re.IGNORECASE)
            if match:
                output[key] = match.group(1).strip()
                break
    if last_asked in {"old_password", "new_password", "confirm_password"} and last_asked not in output:
        if " " not in value and not _has_any(value, ["确认", "取消", "算了", "不用"]):
            output[last_asked] = value
    return output


def _secure_action_cache_key(action_id):
    return f"portal_secure_action:{action_id}"


def _load_secure_action_payload(action_id):
    if not action_id:
        return {}
    data = cache.get(_secure_action_cache_key(action_id))
    return data if isinstance(data, dict) else {}


def _save_secure_action_payload(action_id, payload):
    if not action_id:
        return
    safe_payload = payload if isinstance(payload, dict) else {}
    cache.set(_secure_action_cache_key(action_id), safe_payload, timeout=1800)


def _clear_secure_action_payload(action_id):
    if not action_id:
        return
    cache.delete(_secure_action_cache_key(action_id))


def _mask_password_preview(value):
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 2:
        return "*" * len(text)
    return f"{text[0]}{'*' * max(2, len(text) - 2)}{text[-1]}"


def _direct_chat_reply(text):
    value = text or ""
    if _has_any(value, DIRECT_CHAT_KEYWORDS["greeting"]) and len(value.strip()) <= 8:
        return "您好，我在。您直接说需求就行，我会马上帮您处理。"
    if _has_any(value, DIRECT_CHAT_KEYWORDS["thanks"]):
        return "不客气，能帮到您就好。需要的话我可以继续处理下一件事。"
    if _has_any(value, DIRECT_CHAT_KEYWORDS["bye"]):
        return "好的，如需帮助随时叫我。祝您今天顺利。"
    return None


def _needs_manual_handoff(text):
    value = (text or "").strip()
    if not value:
        return False
    if _has_any(value, ["开户"]) and not _has_any(value, ["开票", "发票"]):
        return True
    if _has_any(value, MANUAL_HANDOFF_KEYWORDS):
        return True
    return False


def _is_manual_contact_request(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    return _has_any(value, MANUAL_CONTACT_REQUEST_KEYWORDS)


def _is_manual_queue_cancel_request(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    return _has_any(value, MANUAL_QUEUE_CANCEL_KEYWORDS)


def _get_manual_queue_state():
    memory = _portal_memory()
    state = memory.get("handoff_queue") if isinstance(memory, dict) else None
    if not isinstance(state, dict):
        return None
    if not bool(state.get("active")):
        return None
    status = str(state.get("status") or "WAITING").upper()
    if status not in {"WAITING", "CONNECTING", "CANCELED"}:
        status = "WAITING"
    try:
        current_ahead = max(0, int(state.get("current_ahead") or 0))
    except Exception:
        current_ahead = 0
    try:
        initial_ahead = max(0, int(state.get("initial_ahead") or current_ahead))
    except Exception:
        initial_ahead = current_ahead
    try:
        eta_minutes = max(1, int(state.get("eta_minutes") or max(1, current_ahead * 2)))
    except Exception:
        eta_minutes = max(1, current_ahead * 2)
    try:
        progress_turns = max(0, int(state.get("progress_turns") or 0))
    except Exception:
        progress_turns = 0
    return {
        "active": True,
        "status": status,
        "initial_ahead": initial_ahead,
        "current_ahead": current_ahead,
        "eta_minutes": eta_minutes,
        "progress_turns": progress_turns,
        "joined_at": str(state.get("joined_at") or ""),
        "source": str(state.get("source") or "session_estimate"),
    }


def _manual_queue_routing_payload(state):
    if not isinstance(state, dict) or not bool(state.get("active")):
        return None
    return {
        "status": str(state.get("status") or "WAITING"),
        "ahead_count": max(0, int(state.get("current_ahead") or 0)),
        "eta_minutes": max(1, int(state.get("eta_minutes") or 1)),
        "source": str(state.get("source") or "session_estimate"),
        "can_collect_issue": True,
    }


def _set_manual_queue_routing_extra(state):
    payload = _manual_queue_routing_payload(state)
    if payload:
        _set_routing_extra(manual_handoff=True, manual_queue=payload)
        return
    _set_routing_extra(manual_handoff=False, manual_queue=None)


def _start_manual_queue(run):
    seed = int(str(getattr(run, "id", "")).replace("-", "")[-2:] or "0", 16)
    initial_ahead = 2 + (seed % 6)
    state = {
        "active": True,
        "status": "WAITING",
        "initial_ahead": initial_ahead,
        "current_ahead": initial_ahead,
        "eta_minutes": max(1, initial_ahead * 2),
        "progress_turns": 0,
        "joined_at": timezone.now().isoformat(),
        "source": "session_estimate",
    }
    _update_portal_memory({"handoff_queue": state})
    _set_manual_queue_routing_extra(state)
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={
            "event": "portal_manual_queue_started",
            "status": state.get("status"),
            "ahead_count": state.get("current_ahead"),
            "eta_minutes": state.get("eta_minutes"),
            "source": state.get("source"),
        },
    )
    return state


def _advance_manual_queue(run, state):
    if not isinstance(state, dict) or not bool(state.get("active")):
        return None
    next_state = dict(state)
    progress_turns = max(0, int(next_state.get("progress_turns") or 0)) + 1
    initial_ahead = max(0, int(next_state.get("initial_ahead") or next_state.get("current_ahead") or 0))
    current_ahead = max(0, initial_ahead - progress_turns)
    status = "CONNECTING" if current_ahead == 0 else "WAITING"
    eta_minutes = 1 if status == "CONNECTING" else max(1, current_ahead * 2)
    next_state.update(
        {
            "active": True,
            "status": status,
            "progress_turns": progress_turns,
            "current_ahead": current_ahead,
            "eta_minutes": eta_minutes,
            "source": str(next_state.get("source") or "session_estimate"),
        }
    )
    _update_portal_memory({"handoff_queue": next_state})
    _set_manual_queue_routing_extra(next_state)
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={
            "event": "portal_manual_queue_updated",
            "status": status,
            "ahead_count": current_ahead,
            "eta_minutes": eta_minutes,
            "progress_turns": progress_turns,
        },
    )
    return next_state


def _cancel_manual_queue(run):
    memory = _portal_memory()
    if isinstance(memory, dict) and "handoff_queue" in memory:
        memory.pop("handoff_queue", None)
        PORTAL_MEMORY_CTX.set(memory)
    _set_manual_queue_routing_extra(None)
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={"event": "portal_manual_queue_canceled"},
    )


def _build_manual_queue_reply(state):
    safe_state = state if isinstance(state, dict) else {}
    status = str(safe_state.get("status") or "WAITING")
    ahead = max(0, int(safe_state.get("current_ahead") or 0))
    eta = max(1, int(safe_state.get("eta_minutes") or 1))
    if status == "CONNECTING":
        return (
            "正在为您接入人工客服，已轮到您。\n"
            "在接入完成前，您也可以先把问题发给我，我会先帮您整理诉求要点。"
        )
    return (
        "正在为您排队接入人工客服。\n"
        f"当前前面还有 {ahead} 位，预计约 {eta} 分钟。\n"
        "您也可以先把问题告诉我，我会先帮您整理，人工接入后处理更快。"
    )


def _append_manual_queue_footer_if_active(message, lane="smalltalk"):
    text = str(message or "").strip()
    if not text:
        return text
    if lane in {"safety", "policy_guard"}:
        return text
    state = _get_manual_queue_state()
    if not state:
        _set_manual_queue_routing_extra(None)
        return text
    _set_manual_queue_routing_extra(state)
    if _has_any(text, ["正在为您排队接入人工客服", "正在为您接入人工客服", "当前人工客服排队进度"]):
        return text
    status = str(state.get("status") or "WAITING")
    if status == "CONNECTING":
        footer = "当前人工客服排队进度：已轮到您，正在接入。您可以继续把问题发我，我先帮您整理。"
    else:
        footer = (
            f"当前人工客服排队进度：前面还有 {int(state.get('current_ahead') or 0)} 位，"
            f"预计约 {max(1, int(state.get('eta_minutes') or 1))} 分钟。您可以先把问题告诉我。"
        )
    return f"{text}\n\n{footer}"


def _is_forbidden_unsafe_instruction_query(text):
    value = (text or "").strip()
    if not value:
        return False
    if _is_safety_emergency_query(value):
        return False
    return _has_any(value, UNSAFE_OPERATION_KEYWORDS) and _has_any(value, UNSAFE_DEVICE_TERMS)


def _manual_handoff_reply():
    return (
        f"这类事项需要人工专员介入处理，我先给您最稳妥的方式：请拨打{SERVICE_HOTLINE}联系人工客服。\n\n"
        "如果您愿意，我也可以先帮您整理诉求要点，您转人工时会更快。"
    )


def _unsafe_instruction_block_reply():
    return (
        "这类燃气设备操作严禁自行拆卸或改装，也不建议您自己动手处理，必须由持证专业人员处理。\n\n"
        f"建议您先关闭阀门、保持通风，随后联系{COMPANY_NAME}专业人员上门处理，或直接拨打24小时应急电话：{EMERGENCY_HOTLINE}。\n\n"
        f"{SAFETY_CARE_CLOSING}"
    )


def _recent_user_messages(run, limit=4, within_minutes=CHAT_CONTEXT_EXPIRE_MINUTES):
    cutoff = timezone.now() - timedelta(minutes=max(1, int(within_minutes or CHAT_CONTEXT_EXPIRE_MINUTES)))
    events = (
        AgentEvent.objects.filter(run=run, input_json__isnull=False, created_at__gte=cutoff)
        .order_by("-step_index")
    )
    messages = []
    for event in events:
        payload = event.input_json if isinstance(event.input_json, dict) else {}
        message = str(payload.get("message") or "").strip()
        if not message:
            continue
        if message in messages:
            continue
        messages.append(message)
        if len(messages) >= limit:
            break
    messages.reverse()
    return messages


def _recent_dialog_context(portal_user_id, limit=LLM_RECENT_ACCOUNT_LIMIT, within_minutes=CHAT_CONTEXT_EXPIRE_MINUTES):
    if not portal_user_id:
        return []
    try:
        from customer_portal.models import CustomerChatMessage
    except Exception:
        return []
    try:
        cutoff = timezone.now() - timedelta(minutes=max(1, int(within_minutes or CHAT_CONTEXT_EXPIRE_MINUTES)))
    except Exception:
        cutoff = timezone.now() - timedelta(minutes=CHAT_CONTEXT_EXPIRE_MINUTES)
    try:
        rows = (
            CustomerChatMessage.objects.filter(user_id=portal_user_id, created_at__gte=cutoff)
            .order_by("-created_at")
            .only("role", "content", "created_at")[: max(1, int(limit or LLM_RECENT_ACCOUNT_LIMIT))]
        )
    except Exception:
        return []
    context = []
    for row in rows:
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        role = "用户" if str(getattr(row, "role", "")) == "user" else "助手"
        content = re.sub(r"\s+", " ", content)
        if len(content) > 180:
            content = content[:180].rstrip() + "..."
        context.append(f"{role}: {content}")
    context.reverse()
    return context


def _build_recent_context_for_llm(
    run,
    portal_user_id,
    run_limit=4,
    account_limit=LLM_RECENT_ACCOUNT_LIMIT,
    within_minutes=CHAT_CONTEXT_EXPIRE_MINUTES,
    within_hours=None,
    max_chars=LLM_RECENT_MAX_CHARS,
):
    account_window_minutes = within_minutes
    if within_hours is not None:
        try:
            account_window_minutes = max(1, int(within_hours) * 60)
        except Exception:
            account_window_minutes = within_minutes

    combined = []
    for item in _recent_user_messages(run, limit=run_limit, within_minutes=within_minutes):
        text = str(item or "").strip()
        if text:
            combined.append(f"用户: {text}")
    combined.extend(
        _recent_dialog_context(
            portal_user_id,
            limit=account_limit,
            within_minutes=account_window_minutes,
        )
    )

    deduped = []
    seen = set()
    for item in combined:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)

    if not deduped:
        return "无"

    output = []
    total = 0
    for item in reversed(deduped):
        line = f"- {item}"
        line_len = len(line) + 1
        if output and total + line_len > max_chars:
            break
        output.append(line)
        total += line_len
    output.reverse()
    return "\n".join(output) if output else "无"


def _portal_memory():
    memory = PORTAL_MEMORY_CTX.get()
    if isinstance(memory, dict):
        return dict(memory)
    return {}


def _set_lane(lane):
    PORTAL_LANE_CTX.set(lane or "smalltalk")


def _clear_routing_extra():
    PORTAL_ROUTING_EXTRA_CTX.set({})


def _set_routing_extra(**kwargs):
    current = PORTAL_ROUTING_EXTRA_CTX.get()
    if not isinstance(current, dict):
        current = {}
    for key, value in kwargs.items():
        if value is None or value == "":
            current.pop(key, None)
            continue
        current[key] = value
    PORTAL_ROUTING_EXTRA_CTX.set(current)


def _routing_meta(lane=None):
    chosen_lane = lane or PORTAL_LANE_CTX.get() or "smalltalk"
    payload = {
        "mode": str(PORTAL_ROUTE_MODE_CTX.get() or "legacy"),
        "lane": chosen_lane,
        "model_source": str(PORTAL_MODEL_SOURCE_CTX.get() or "none"),
        "write_allowed": bool(PORTAL_WRITE_ALLOWED_CTX.get()),
        "degraded_reason": PORTAL_DEGRADED_REASON_CTX.get() or None,
    }
    extras = PORTAL_ROUTING_EXTRA_CTX.get()
    if isinstance(extras, dict):
        for key, value in extras.items():
            if value is not None:
                payload[key] = value
    return payload


def _is_user_dissatisfied(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    return _has_any(
        value,
        [
            "没回答",
            "答非所问",
            "不是这个意思",
            "你没懂",
            "你理解错了",
            "不对",
            "不满意",
            "别问了",
            "直接回答",
            "转人工",
        ],
    )


def _build_stage0_signal(text, pending_action=None, llm_route=None, task_signal=None, heuristic_intent="UNKNOWN", current_intent="UNKNOWN"):
    route = llm_route if isinstance(llm_route, dict) else {}
    signal = task_signal if isinstance(task_signal, dict) else {}
    intent = str(current_intent or heuristic_intent or "UNKNOWN").upper()
    if str(signal.get("strength") or "").upper() == "QUERY_STRONG" and str(signal.get("intent") or "").upper() in QUERY_INTENT_CODES:
        intent = str(signal.get("intent") or intent).upper()
    needs_tool = bool(
        intent in WRITE_INTENT_CODES
        or intent in QUERY_INTENT_CODES
        or intent in {"QUERY_ORDER", "CART_QUERY"}
    )
    needs_kb = bool(route.get("needs_kb")) or intent in {
        "PRICE_QUERY",
        "INVOICE_HELP",
        "CYLINDER_INSPECTION_QUERY",
        "SAFETY_LEAK_CHECK",
        "SAFETY_EMERGENCY",
    }
    kb_domain = str(route.get("kb_domain") or "none").lower()
    if kb_domain not in {"safety", "biz", "none"}:
        kb_domain = "none"
    if needs_kb and kb_domain == "none":
        kb_domain = "safety" if intent in {"SAFETY_LEAK_CHECK", "SAFETY_EMERGENCY"} else "biz"
    safety_kind = _safety_kind_from_text(text)
    task_type = str(signal.get("task_type") or "").upper()
    if not task_type:
        if _is_write_intent(intent):
            task_type = "ACTION"
        elif intent in QUERY_INTENT_CODES or intent == "QUERY_ORDER":
            task_type = "QUERY"
        else:
            task_type = "SMALLTALK"
    try:
        confidence = float(route.get("confidence")) if route.get("confidence") is not None else float(signal.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    clarify_needed = bool(task_type == "AMBIGUOUS" and confidence < 0.45 and not _is_user_dissatisfied(text))
    user_satisfaction_signal = "frustrated" if _is_user_dissatisfied(text) else "normal"
    if user_satisfaction_signal == "frustrated":
        clarify_needed = False
    output = {
        "task_type": task_type,
        "entity": str(signal.get("entity") or _query_entity_from_intent(intent)),
        "intent": intent,
        "confidence": confidence,
        "needs_tool": needs_tool,
        "can_execute_now": not _is_write_intent(intent),
        "needs_kb": bool(needs_kb),
        "kb_domain": kb_domain,
        "kb_topic": str(route.get("kb_topic") or ("safety_general" if _looks_like_general_safety_question(text) else _infer_kb_topic(text, domain=kb_domain))),
        "kb_query": str(route.get("kb_query") or text),
        "clarify_needed": clarify_needed,
        "user_satisfaction_signal": user_satisfaction_signal,
        "source": "stage0_llm" if route else "rule_fallback",
        "router_lane": str(route.get("lane") or "smalltalk"),
        "router_why": str(route.get("why") or "")[:80],
        "router_intent": str(route.get("intent") or "UNKNOWN").upper(),
        "heuristic_intent": str(heuristic_intent or "UNKNOWN").upper(),
        "write_pending": bool(isinstance(pending_action, dict) and _is_write_pending_action(pending_action)),
        "safety_kind": safety_kind,
    }
    return output


def _compact_stage0_for_routing(stage0_signal):
    if not isinstance(stage0_signal, dict):
        return None
    return {
        "task_type": stage0_signal.get("task_type"),
        "intent": stage0_signal.get("intent"),
        "confidence": stage0_signal.get("confidence"),
        "needs_tool": stage0_signal.get("needs_tool"),
        "needs_kb": stage0_signal.get("needs_kb"),
        "safety_kind": stage0_signal.get("safety_kind"),
        "clarify_needed": stage0_signal.get("clarify_needed"),
        "user_satisfaction_signal": stage0_signal.get("user_satisfaction_signal"),
        "source": stage0_signal.get("source"),
    }


def _is_write_intent(intent_code):
    return str(intent_code or "").upper() in WRITE_INTENT_CODES


def _is_write_pending_action(action):
    return isinstance(action, dict) and str(action.get("type") or "").upper() in WRITE_ACTION_TYPES


def _readonly_fallback_reply():
    reason = str(PORTAL_DEGRADED_REASON_CTX.get() or "").strip().lower()
    if reason in {"no_cloud_profile", "cloud_profile_missing"}:
        return (
            "我现在先用只读模式为您服务，写操作暂时还不能直接执行。"
            "您在右上角“模型设置”绑定云模型后，我就能继续代您下单或修改。"
            "现在我可以先帮您查订单、查资料或做安全应急解答。"
        )
    if reason in {"cloud_model_unavailable", "cloud_probe_failed", "cloud_llm_unavailable"}:
        return (
            "当前云模型暂时不可用，我先切到只读模式保证您能继续咨询。"
            "写操作稍后再试，或在“模型设置”切换可用模型。"
            "我现在仍可帮您查订单进度、资料和安全问题。"
        )
    return (
        "我先在只读模式继续为您服务，写操作暂时不能执行。"
        "完成模型配置后我就能继续代您操作。"
        "现在我可以先帮您查询和答疑。"
    )


def _update_portal_memory(patch):
    if not isinstance(patch, dict):
        return
    current = _portal_memory()
    current.update(patch)
    PORTAL_MEMORY_CTX.set(current)


def _persist_portal_memory(intent, pending_action=None):
    portal_user_id = PORTAL_USER_CTX.get()
    if not portal_user_id:
        return
    try:
        from customer_portal.models import CustomerConversationMemory
    except Exception:
        return

    try:
        memory_row, _ = CustomerConversationMemory.objects.get_or_create(
            user_id=portal_user_id,
            defaults={"memory_json": {}},
        )
    except Exception:
        return

    existing = memory_row.memory_json if isinstance(memory_row.memory_json, dict) else {}
    merged = dict(existing)
    incoming = _portal_memory()
    if incoming:
        merged.update(incoming)
    merged["last_intent"] = intent.value if hasattr(intent, "value") else str(intent)
    merged["last_user_message"] = (PORTAL_INPUT_CTX.get() or "")[:500]
    merged["last_active_at"] = timezone.now().isoformat()

    if isinstance(pending_action, dict) and pending_action.get("type") == "CREATE_ORDER":
        draft = pending_action.get("draft") if isinstance(pending_action.get("draft"), dict) else {}
        if draft:
            merged["last_service_type"] = draft.get("service_type") or merged.get("last_service_type")
            merged["draft_order"] = draft
            pref = dict(merged.get("order_pref") or {})
            for field in ["address_id", "contact_name", "contact_phone", "is_urgent", "eta_date", "eta_slot"]:
                if draft.get(field) not in [None, ""]:
                    pref[field] = draft.get(field)
            payload = draft.get("service_payload") if isinstance(draft.get("service_payload"), dict) else {}
            if payload.get("cylinder_type"):
                pref["cylinder_type"] = payload.get("cylinder_type")
            merged["order_pref"] = pref
    elif merged.get("draft_order"):
        # 操作完成后清理临时草稿，避免后续误用。
        merged.pop("draft_order", None)

    try:
        memory_row.memory_json = merged
        memory_row.save(update_fields=["memory_json", "updated_at"])
        PORTAL_MEMORY_CTX.set(merged)
    except Exception:
        return


def _llm_invoke_text(messages):
    llm = PORTAL_LLM_CTX.get()
    if not llm:
        return ""
    try:
        output = llm.invoke(messages)
    except Exception:
        return ""
    if isinstance(output, str):
        return output.strip()
    content = getattr(output, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts).strip()
    return ""


def _parse_json_from_text(text):
    value = (text or "").strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", value)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _llm_decide_kb_route(run, text):
    if "test" in sys.argv:
        return None
    llm = PORTAL_LLM_CTX.get()
    if not llm:
        return None
    history_text = _build_recent_context_for_llm(run, PORTAL_USER_CTX.get(), run_limit=4)
    prompt = (
        "你是客服路由器。请判断用户问题是否需要查询知识库。\n"
        "仅输出 JSON，不要额外文本。\n"
        "输出格式：{\"need_kb\": true/false, \"domain\": \"safety|biz|none\", \"topic\": \"price|invoice|inspection|safety_leak|safety_general|policy|none\", \"query\": \"检索问题\"}\n"
        "规则：\n"
        "1) 订单/下单/取消/支付/改址/投诉建议 走业务工具，不走知识库。\n"
        "2) 燃气安全与应急常识可走 safety。\n"
        "3) 价格、发票、规则、流程、气瓶年检周期可走 biz。\n"
        "4) 纯寒暄不走知识库。\n"
        f"最近上下文：\n{history_text}\n"
        f"当前用户问题：{text}"
    )
    raw = _llm_invoke_text([SystemMessage(content=prompt)])
    parsed = _parse_json_from_text(raw)
    if not isinstance(parsed, dict):
        return None
    need_kb = bool(parsed.get("need_kb"))
    domain = str(parsed.get("domain") or "none").lower()
    topic = str(parsed.get("topic") or "none").lower()
    query = str(parsed.get("query") or text).strip() or text
    if not need_kb or domain not in {"safety", "biz"}:
        return {"need_kb": False, "domain": "none", "topic": "none", "query": query}
    return {"need_kb": True, "domain": domain, "topic": topic, "query": query}


def _heuristic_kb_route(text):
    query = (text or "").strip()
    if not query:
        return {"need_kb": False, "domain": "none", "topic": "none", "query": ""}
    if "报警器" in query and not any(keyword in query for keyword in ["漏气", "泄漏", "异味", "应急"]):
        return {"need_kb": False, "domain": "none", "topic": "none", "query": query}
    safety_topic = _safety_topic_from_text(query)
    if safety_topic in {"safety_leak", "safety_general"}:
        return {"need_kb": True, "domain": "safety", "topic": safety_topic, "query": query}
    if any(keyword in query for keyword in BIZ_RAG_KEYWORDS):
        topic = "policy"
        if _looks_like_price_query(query):
            topic = "price"
        elif _has_any(query, INVOICE_KEYWORDS):
            topic = "invoice"
        elif _looks_like_inspection_query(query):
            topic = "inspection"
        return {"need_kb": True, "domain": "biz", "topic": topic, "query": query}
    return {"need_kb": False, "domain": "none", "topic": "none", "query": query}


def _rewrite_kb_query(run, user_text, domain, seed_query=None):
    query = (seed_query or user_text or "").strip()
    if not query:
        return ""
    if "test" in sys.argv:
        return query
    llm = PORTAL_LLM_CTX.get()
    if not llm:
        return query
    history_text = _build_recent_context_for_llm(run, PORTAL_USER_CTX.get(), run_limit=4)
    prompt = (
        "你是检索查询改写器。请把用户问题改写成更适合知识库检索的中文短句。\n"
        "要求：\n"
        "1) 只输出一行纯文本，不要 JSON；\n"
        "2) 保留原意与约束，不新增事实；\n"
        "3) 长度控制在 8-36 字；\n"
        "3.1) 如果是价格/年检问题，保留规格、时间（年月）等关键信息；\n"
        f"4) 当前知识域：{domain}。\n"
        f"最近上下文：\n{history_text}\n"
        f"用户原问题：{user_text}\n"
        f"候选检索词：{query}"
    )
    rewritten = _llm_invoke_text([SystemMessage(content=prompt)]).strip()
    if not rewritten:
        return query
    # 避免模型输出多段解释，取首行作为检索词
    first_line = rewritten.splitlines()[0].strip()
    return first_line or query


def _collect_kb_hits(run, domain, query, top_k=KB_TOP_K, min_score=KB_MIN_SCORE, max_bullets=KB_MAX_BULLETS):
    try:
        if domain == "safety":
            result = execute_tool(run, "safety_search", {"query": query, "top_k": top_k})
        else:
            result = execute_tool(run, "kb_search", {"domain": "biz", "query": query, "top_k": top_k})
    except Exception as exc:
        return {
            "query": query,
            "domain": domain,
            "raw_hits": [],
            "accepted_hits": [],
            "accepted_count": 0,
            "best_score": 0.0,
            "avg_score": 0.0,
            "bullets": [],
            "error": str(exc),
        }
    entries = result.get("results") or []
    accepted = [item for item in entries if float(item.get("score") or 0.0) >= min_score]
    bullets = []
    for entry in accepted:
        for bullet in entry.get("bullets", [])[:2]:
            text = str(bullet or "").strip()
            if text and text not in bullets:
                bullets.append(text)
            if len(bullets) >= max_bullets:
                break
        if len(bullets) >= max_bullets:
            break
    best_score = max([float(item.get("score") or 0.0) for item in entries], default=0.0)
    avg_score = (
        round(sum(float(item.get("score") or 0.0) for item in accepted) / len(accepted), 3)
        if accepted
        else 0.0
    )
    return {
        "query": query,
        "domain": domain,
        "raw_hits": entries,
        "accepted_hits": accepted,
        "accepted_count": len(accepted),
        "best_score": round(best_score, 3),
        "avg_score": avg_score,
        "bullets": bullets,
    }


def _llm_compose_kb_reply(run, text, bullets, kb_meta=None):
    llm = PORTAL_LLM_CTX.get()
    if not llm or not bullets:
        return None
    history_text = _build_recent_context_for_llm(run, PORTAL_USER_CTX.get(), run_limit=4)
    bullets_text = "\n".join([f"- {item}" for item in bullets])
    meta_text = ""
    if isinstance(kb_meta, dict):
        meta_text = (
            f"\n检索信息：domain={kb_meta.get('domain')} "
            f"query={kb_meta.get('query')} "
            f"accepted_count={kb_meta.get('accepted_count')} "
            f"best_score={kb_meta.get('best_score')}"
        )
    safety_extra = ""
    if _looks_like_safety_leak_check_query(text) or _is_safety_emergency_query(text):
        safety_extra = (
            "\n安全场景要求：\n"
            f"- 必须包含“严禁明火检漏”；\n"
            f"- 必须给出我司 24 小时应急电话：{EMERGENCY_HOTLINE}；\n"
            "- 先给可执行步骤，再给提醒；\n"
            f"- 若用户场景复杂或危急，结尾必须追加：{_safety_escalation_notice()}"
        )
    prompt = (
        "你是LPG企业用户客服。请结合知识点回复用户，要求：\n"
        "1) 只输出中文，自然友好，不要内部术语；\n"
        "2) 回答简洁但有温度，避免机械模板；\n"
        "3) 不编造知识点之外的规则；\n"
        "4) 先结论，再解释，再给一个可执行下一步；\n"
        "5) 2-5个短段落，必要时使用 **小标题** 和 1. 2. 分点；\n"
        f"6) 可自然提及{COMPANY_NAME}的服务实践（如上门师傅会协助做基础检查），但不要编造未给出的承诺。\n"
        f"7) {_llm_service_guardrail_prompt()}\n"
        f"最近上下文：\n{history_text}\n"
        f"用户问题：{text}\n"
        f"知识点：\n{bullets_text}"
        f"{meta_text}"
        f"{safety_extra}"
    )
    reply = _llm_invoke_text([SystemMessage(content=prompt)])
    if not reply:
        return None
    return _append_safety_escalation_notice(text, reply)


def _llm_general_reply(run, text, stage0_signal=None):
    llm = PORTAL_LLM_CTX.get()
    if not llm:
        return None
    history_text = _build_recent_context_for_llm(run, PORTAL_USER_CTX.get(), run_limit=4)
    stage0 = stage0_signal if isinstance(stage0_signal, dict) else PORTAL_STAGE0_CTX.get()
    stage0_text = ""
    if isinstance(stage0, dict):
        stage0_hint = {
            "task_type": stage0.get("task_type"),
            "intent": stage0.get("intent"),
            "entity": stage0.get("entity"),
            "confidence": stage0.get("confidence"),
            "needs_tool": stage0.get("needs_tool"),
            "needs_kb": stage0.get("needs_kb"),
            "kb_topic": stage0.get("kb_topic"),
            "clarify_needed": stage0.get("clarify_needed"),
            "user_satisfaction_signal": stage0.get("user_satisfaction_signal"),
        }
        stage0_text = f"\n上游语义理解信号（仅用于辅助理解，严禁原样复述给用户）：{json.dumps(stage0_hint, ensure_ascii=False)}"
    prompt = (
        "你是LPG企业用户客服助手。请用温暖、专业、自然的中文回复。\n"
        "要求：\n"
        "1) 只输出中文；2) 不要输出字段名、JSON、系统术语；\n"
        "3) 不编造订单与规则；4) 先给结论，再给下一步；\n"
        "5) 优先2-5个短段落，必要时使用 1. 2. 编号；\n"
        f"6) 可自然带出{COMPANY_NAME}服务特色（如上门复检、送气师傅协助核查），但不得夸大承诺。\n"
        f"7) {_llm_service_guardrail_prompt()}\n"
        "8) 对知识咨询优先直接回答，不要机械反问“A还是B”；仅在必须执行写操作且关键信息缺失时才追问。\n"
        "9) 用户问明确安全问句时，先给直接结论和可执行步骤；除非用户明确要总览清单，不要输出泛化总则模板。\n"
        f"最近上下文：\n{history_text}\n"
        f"用户问题：{text}"
        f"{stage0_text}"
    )
    reply = _llm_invoke_text([SystemMessage(content=prompt)])
    if not reply:
        return None
    return _append_safety_escalation_notice(text, reply)


def _llm_detect_intent(text):
    if "test" in sys.argv:
        return "UNKNOWN"
    llm = PORTAL_LLM_CTX.get()
    if not llm:
        return "UNKNOWN"
    intent_pool = [
        "CREATE_ORDER",
        "QUERY_ORDER",
        "CANCEL_ORDER",
        "PAY_ORDER",
        "MODIFY_ADDRESS",
        "CREATE_FEEDBACK",
        "FEEDBACK_QUERY",
        "PRICE_QUERY",
        "INVOICE_HELP",
        "CYLINDER_INSPECTION_QUERY",
        "SAFETY_EMERGENCY",
        "SAFETY_LEAK_CHECK",
        "ORDER_GUIDE",
        "CART_QUERY",
        "CART_ADD",
        "CART_REMOVE",
        "CART_CLEAR",
        "CART_CHECKOUT",
        "PROFILE_QUERY",
        "ADDRESS_QUERY",
        "ADDRESS_CREATE",
        "ADDRESS_SET_DEFAULT",
        "ADDRESS_UPDATE_DEFAULT",
        "ADDRESS_DELETE",
        "CHANGE_PASSWORD",
        "NOTIFICATION_QUERY",
        "NOTIFICATION_READ",
        "NOTIFICATION_READ_ALL",
        "THEME_SET_EYE",
        "THEME_SET_DARK",
        "THEME_SET_LIGHT",
        "CAPABILITY_HELP",
        "UNKNOWN",
    ]
    prompt = (
        "你是客服意图分类器。请只输出 JSON，不要其他内容。\n"
        f"可选意图：{','.join(intent_pool)}\n"
        "输出格式：{\"intent\":\"意图名\"}\n"
        "规则：\n"
        "1) 涉及写操作意图时，只做分类，不执行。\n"
        "2) 没把握就输出 UNKNOWN。\n"
        f"用户问题：{text}"
    )
    raw = _llm_invoke_text([SystemMessage(content=prompt)])
    parsed = _parse_json_from_text(raw)
    if not isinstance(parsed, dict):
        return "UNKNOWN"
    intent = str(parsed.get("intent") or "UNKNOWN").strip().upper()
    if intent not in set(intent_pool):
        return "UNKNOWN"
    return intent


def _llm_route_turn(run, text, pending_action=None):
    if "test" in sys.argv:
        return None
    llm = PORTAL_LLM_CTX.get()
    if not llm:
        return None
    history_text = _build_recent_context_for_llm(run, PORTAL_USER_CTX.get(), run_limit=4)
    pending_type = ""
    pending_status = ""
    if isinstance(pending_action, dict):
        pending_type = str(pending_action.get("type") or "")
        pending_status = str(pending_action.get("status") or "")
    prompt = (
        "你是门户客服总路由器（LLM-first）。请只输出 JSON。\n"
        "输出格式："
        "{\"lane\":\"action|rag|smalltalk|safety\","
        "\"intent\":\"意图名或UNKNOWN\","
        "\"confidence\":0-1,"
        "\"why\":\"20字内原因\","
        "\"needs_kb\":true/false,"
        "\"kb_domain\":\"safety|biz|none\","
        "\"kb_topic\":\"price|invoice|inspection|safety_leak|safety_general|policy|none\","
        "\"kb_query\":\"检索问题\"}\n"
        "规则：\n"
        "1) 写操作仅分类，不能执行。\n"
        "2) 若是问句（如何/能否/是否/多久/吗）且无明确办理动作，优先 smalltalk 或 rag，不直接 action。\n"
        "3) 泄漏、火灾、异味报警等人身安全问题优先 safety。\n"
        "4) 订单下单/支付/取消/改址/购物车等明确办理行为才走 action。\n"
        "5) 不确定时降低 confidence，并优先 smalltalk。\n"
        f"当前待办流程：type={pending_type or 'none'},status={pending_status or 'none'}\n"
        f"最近上下文：\n{history_text}\n"
        f"用户问题：{text}"
    )
    raw = _llm_invoke_text([SystemMessage(content=prompt)])
    parsed = _parse_json_from_text(raw)
    if not isinstance(parsed, dict):
        return None
    lane = str(parsed.get("lane") or "smalltalk").strip().lower()
    if lane not in {"action", "rag", "smalltalk", "safety"}:
        lane = "smalltalk"
    intent = str(parsed.get("intent") or "UNKNOWN").strip().upper()
    try:
        confidence = float(parsed.get("confidence"))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    why = str(parsed.get("why") or "").strip()[:80]
    needs_kb = bool(parsed.get("needs_kb"))
    kb_domain = str(parsed.get("kb_domain") or "none").strip().lower()
    if kb_domain not in {"safety", "biz", "none"}:
        kb_domain = "none"
    kb_topic = str(parsed.get("kb_topic") or "none").strip().lower()
    kb_query = str(parsed.get("kb_query") or text).strip() or text
    return {
        "lane": lane,
        "intent": intent or "UNKNOWN",
        "confidence": confidence,
        "why": why,
        "needs_kb": needs_kb and kb_domain in {"safety", "biz"},
        "kb_domain": kb_domain,
        "kb_topic": kb_topic,
        "kb_query": kb_query,
    }


def _is_explanatory_question(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    if "?" in value or "？" in value:
        return True
    question_terms = ["如何", "怎么", "怎样", "是否", "能否", "能不能", "可不可以", "多久", "流程", "规则", "吗", "判断", "注意"]
    return _has_any(value, question_terms)


def _has_explicit_execution_signal(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    if _is_order_quote_intent(value):
        return True
    if _looks_like_cart_add(value) or _looks_like_cart_checkout(value) or _looks_like_cart_remove(value):
        return True
    if _has_any(value, ["下单", "帮我下", "立即支付", "现在支付", "取消订单", "改地址", "申请退款"]):
        return True
    return False


def _should_prefer_explanatory_lane(text):
    value = _normalize_user_text(text)
    if not _is_explanatory_question(value):
        return False
    if _is_safety_emergency_query(value):
        return False
    if _has_explicit_execution_signal(value):
        return False
    return True


def _hard_signal_intent(text):
    value = _normalize_user_text(text)
    if not value:
        return None
    if _is_safety_emergency_query(value):
        return "SAFETY_EMERGENCY"
    if _looks_like_safety_leak_check_query(value) or _looks_like_alarm_device_risk_query(value):
        return "SAFETY_LEAK_CHECK"
    if _looks_like_price_query(value):
        return "PRICE_QUERY"
    if _looks_like_inspection_query(value):
        return "CYLINDER_INSPECTION_QUERY"
    if _has_any(value, INVOICE_KEYWORDS) and _has_any(value, ["流程", "规则", "怎么", "如何", "补开", "税号", "抬头"]):
        return "INVOICE_HELP"
    if _extract_order_ref(value)[0] or _extract_order_ref(value)[1] or _looks_like_query_order(value):
        return "QUERY_ORDER"
    if _is_cart_context(value):
        return "CART_QUERY"
    return None


def _apply_low_confidence_corrector(text, fallback_intent):
    hard = _hard_signal_intent(text)
    if hard:
        return hard
    return fallback_intent


def _allow_llm_intent_override(user_text, intent):
    value = _normalize_user_text(user_text)
    if not value:
        return False
    intent_code = str(intent or "").upper()
    if intent_code in {"UNKNOWN", ""}:
        return False
    # 这些意图可直接放行：不涉及高风险误触发，且经常需要模型兜底理解。
    if intent_code in {
        "PRICE_QUERY",
        "INVOICE_HELP",
        "CYLINDER_INSPECTION_QUERY",
        "SAFETY_EMERGENCY",
        "SAFETY_LEAK_CHECK",
        "ORDER_GUIDE",
        "CAPABILITY_HELP",
        "NOTIFICATION_QUERY",
        "THEME_SET_EYE",
        "THEME_SET_DARK",
        "THEME_SET_LIGHT",
    }:
        return True

    if intent_code == "QUERY_ORDER":
        if _looks_like_query_order(value):
            return True
        if _extract_order_ref(value)[0] or _extract_order_ref(value)[1]:
            return True
        if _has_any(value, ORDER_QUERY_HINT_KEYWORDS):
            return True
        return False

    if intent_code == "CREATE_ORDER":
        if _is_order_quote_intent(value):
            return True
        service_type = _extract_service_type(value)
        if service_type and service_type != SERVICE_TYPE_ACCESSORIES:
            return True
        if _extract_cylinder_type(value) and _extract_quantity(value):
            return True
        if _has_any(value, ORDER_ACTION_HINTS) and _has_any(value, ["下单", "配送", "上门", "订气", "叫气"]):
            return True
        return False

    if intent_code == "MODIFY_ADDRESS":
        if _looks_like_address_book_update(value):
            return False
        if _extract_order_ref(value)[0] or _extract_order_ref(value)[1]:
            return True
        if _has_any(value, ["这单", "那单", "订单", "改址", "订单改址", "订单地址"]):
            return True
        return False

    if intent_code == "ADDRESS_UPDATE_DEFAULT":
        return _looks_like_address_book_update(value)

    if intent_code in {"CART_ADD", "CART_REMOVE", "CART_CHECKOUT", "CART_CLEAR", "CART_QUERY"}:
        if intent_code == "CART_ADD":
            return _looks_like_cart_add(value)
        if intent_code == "CART_REMOVE":
            return _looks_like_cart_remove(value)
        if intent_code == "CART_CHECKOUT":
            return _looks_like_cart_checkout(value)
        if intent_code == "CART_CLEAR":
            return _looks_like_cart_clear(value)
        return _is_cart_context(value)

    # 默认保守放行
    return True


def _intent_from_text(text, pending_action=None):
    value = _normalize_user_text(text)
    value_compact = _compact_text(value)
    query_override = _query_intent_override(value)
    if query_override:
        return query_override
    if _looks_like_address_book_update(value):
        return "ADDRESS_UPDATE_DEFAULT"
    live_feedback_collecting = (
        isinstance(pending_action, dict)
        and pending_action.get("type") == "CREATE_FEEDBACK"
        and pending_action.get("status") == "COLLECTING"
    )
    if live_feedback_collecting and (_extract_choice_index(value) or _extract_order_ref(value)[0] or _extract_order_ref(value)[1]):
        return "CREATE_FEEDBACK"
    if _is_feedback_progress_query(value):
        return "FEEDBACK_QUERY"
    if _looks_like_order_guide_query(value):
        return "ORDER_GUIDE"
    theme_direct_tokens = {"护眼", "护眼模式", "黑夜", "黑夜模式", "夜间", "夜间模式", "深色", "深色模式", "白天", "白天模式", "浅色", "浅色模式"}
    if _has_any(value, THEME_EYE_KEYWORDS) and (
        _has_any(value, THEME_SWITCH_ACTION_KEYWORDS) or (value_compact in theme_direct_tokens)
    ):
        return "THEME_SET_EYE"
    if _has_any(value, THEME_DARK_KEYWORDS) and (
        _has_any(value, THEME_SWITCH_ACTION_KEYWORDS) or (value_compact in theme_direct_tokens)
    ):
        return "THEME_SET_DARK"
    if _has_any(value, THEME_LIGHT_KEYWORDS) and (
        _has_any(value, THEME_SWITCH_ACTION_KEYWORDS) or (value_compact in theme_direct_tokens)
    ):
        return "THEME_SET_LIGHT"
    if _has_any(value, PASSWORD_CHANGE_HINT_KEYWORDS) or "登录密码" in value:
        return "CHANGE_PASSWORD"
    if _has_any(value, NOTIFICATION_READ_ALL_KEYWORDS):
        return "NOTIFICATION_READ_ALL"
    if _has_any(value, NOTIFICATION_KEYWORDS):
        if _has_any(value, NOTIFICATION_READ_ALL_KEYWORDS):
            return "NOTIFICATION_READ_ALL"
        if _has_any(value, NOTIFICATION_READ_KEYWORDS):
            return "NOTIFICATION_READ"
        return "NOTIFICATION_QUERY"
    if _has_any(value, CAPABILITY_HELP_KEYWORDS):
        return "CAPABILITY_HELP"
    if _looks_like_alarm_device_risk_query(value):
        return "SAFETY_LEAK_CHECK"
    if "手机号" in value and _has_any(value, ["拦截", "格式", "校验", "123"]):
        return "PHONE_RULE_HELP"
    if _looks_like_cart_clear(value):
        return "CART_CLEAR"
    if _looks_like_cart_remove(value):
        return "CART_REMOVE"
    if _looks_like_cart_checkout(value):
        return "CART_CHECKOUT"
    if _looks_like_cart_add(value):
        return "CART_ADD"
    if _has_any(value, INVOICE_KEYWORDS):
        has_order_slots = bool(_extract_service_type(value) or _extract_cylinder_type(value) or _extract_quantity(value))
        has_order_phrase = _has_any(value, ["下单", "帮我下", "来一单", "给我送", "立即买", "马上买"])
        looks_like_invoice_qa = _has_any(value, ["流程", "怎么", "如何", "规则", "补开", "抬头", "税号", "企业开票"])
        if looks_like_invoice_qa or not (has_order_slots and has_order_phrase):
            return "INVOICE_HELP"

    has_order_signal_for_address = bool(
        _extract_service_type(value)
        or _extract_cylinder_type(value)
        or (_extract_quantity(value) and _has_any(value, ["下单", "送", "配送", "来一单", "订气"]))
        or ("下单" in value and "订单" not in value)
    )
    address_id_only_delete = bool(
        _has_any(value, ["删", "删除", "移除"]) and re.search(r"(?:id|ID|编号|#)\s*[:：#-]?\s*\d{1,10}", value)
    )
    address_create_pattern = re.search(r"(新增|添加|加|新建|创建|新加|建(?:个|一条)?)(?:一个|个|条)?(?:收货)?地址", value_compact or "")
    address_query_pattern = re.search(
        r"(?:我|现在|目前|当前)?(?:有多少|有几个|有哪些|有哪几个|查看|查下|查一下|看看|列出|展示)(?:收货)?地址",
        value_compact or "",
    )
    if _looks_like_inspection_query(value):
        return "CYLINDER_INSPECTION_QUERY"
    if _looks_like_price_query(value):
        return "PRICE_QUERY"
    if _looks_like_safety_leak_check_query(value):
        return "SAFETY_LEAK_CHECK"
    if _is_cart_context(value):
        return "CART_QUERY"
    if "配件" in value and _has_any(value, ["怎么买", "怎么下单", "如何下单", "流程", "规则"]):
        return "ACCESSORY_HELP"
    if _is_order_quote_intent(value):
        return "CREATE_ORDER"
    if _is_fee_detail_query(value):
        return "ORDER_FEE_DETAIL"
    if _is_safety_emergency_query(value):
        return "SAFETY_EMERGENCY"
    if _has_any(value, PROFILE_QUERY_KEYWORDS) and not _has_any(value, ["改成", "修改", "改为"]):
        return "PROFILE_QUERY"
    if (
        _has_any(value, ADDRESS_MANAGE_KEYWORDS)
        or _has_any(value, ADDRESS_DELETE_KEYWORDS)
        or (_has_any(value, ["删", "删除"]) and "地址" in value)
        or ("地址" in value and "默认" in value)
        or bool(address_query_pattern)
        or _has_any(value_compact, ["我的地址", "地址列表", "全部地址", "所有地址"])
        or _has_any(value_compact, ["新增地址", "添加地址", "加地址", "新增收货地址", "添加收货地址", "新地址", "加个地址"])
        or bool(address_create_pattern)
        or address_id_only_delete
    ) and not has_order_signal_for_address:
        if (
            _has_any(value, ["新增地址", "添加地址", "加地址", "新建地址", "创建地址", "建个地址", "新加地址", "建一条地址", "新增收货地址", "添加收货地址"])
            or _has_any(value_compact, ["新增地址", "添加地址", "加地址", "新建地址", "创建地址", "建个地址", "新加地址", "建一条地址", "新增收货地址", "添加收货地址", "新地址", "加个地址"])
            or bool(address_create_pattern)
        ):
            return "ADDRESS_CREATE"
        if _has_any(value, ["设成", "设为", "设置"]) and "默认地址" in value:
            return "ADDRESS_SET_DEFAULT"
        if _has_any(value, ["改", "修改"]) and "默认地址" in value:
            return "ADDRESS_UPDATE_DEFAULT"
        if _has_any(value, ADDRESS_DELETE_KEYWORDS) or (_has_any(value, ["删", "删除"]) and "地址" in value) or address_id_only_delete:
            return "ADDRESS_DELETE"
        return "ADDRESS_QUERY"
    if _has_any(value, ["改名", "改名字", "修改名字", "修改昵称", "改用户名", "修改用户名", "用户名改", "昵称", "显示名改", "修改显示名"]):
        return "UPDATE_PROFILE"
    if _has_any(value, ["退款", "退货", "退订单", "申请退款"]):
        return "REQUEST_REFUND"
    if (
        "取消订单" in value
        or "撤单" in value
        or ("取消" in value and ("订单" in value or "这单" in value or "那单" in value))
    ):
        return "CANCEL_ORDER"
    if _looks_like_pay_action(value):
        return "PAY_ORDER"
    if (
        "改地址" in value
        or "修改地址" in value
        or "改址" in value
        or "地址改成" in value
        or "地址改为" in value
    ) and not _looks_like_address_book_update(value):
        return "MODIFY_ADDRESS"
    if any(keyword in value for keyword in ["投诉", "建议", "反馈", "吐槽", "表扬"]):
        return "CREATE_FEEDBACK"
    if _extract_status_filter(value) and _has_any(value, ["看", "查", "筛选", "只看", "单", "订单"]):
        return "QUERY_ORDER"
    if _looks_like_query_order(value):
        return "QUERY_ORDER"
    if _has_any(value, ["没付款", "未付款", "超过30分钟", "订单过期", "废了"]) and ("单" in value or "订单" in value):
        return "QUERY_ORDER"
    if _looks_like_service_info_query(value):
        return "UNKNOWN"
    if _looks_like_accessory_info_query(value):
        return "UNKNOWN"
    service_type_guess = _extract_service_type(value)
    if service_type_guess == SERVICE_TYPE_ACCESSORIES and not _is_cart_context(value):
        if not _has_any(value, ["下单", "买", "购买", "加购物车", "加入购物车", "结算", "来一件", "来两件", "帮我下"]):
            return "UNKNOWN"
    if service_type_guess == SERVICE_TYPE_ACCESSORIES and not _is_cart_context(value):
        if _has_any(value, ["软管", "减压阀", "报警器", "自闭阀", "配件"]) and not _has_any(
            value, ["下单", "买", "购买", "要", "来一件", "来两件", "帮我下", "结算"]
        ):
            return "UNKNOWN"
    if (
        service_type_guess
        or ("下单" in value and "订单" not in value)
        or (
            _extract_cylinder_type(value)
            and (_extract_quantity(value) or _has_any(value, ["两瓶", "两罐", "来两", "送两", "整两", "先来", "来一单"]))
            and _has_any(value, ["气", "瓶", "罐"])
        )
    ):
        return "CREATE_ORDER"
    return "UNKNOWN"


def _pending_action_id():
    return f"act_{secrets.token_hex(4)}"


def _handle_create_address(run, text, portal_user_id, pending_action):
    action_id = _pending_action_id()
    payload = {}
    if pending_action and pending_action.get("type") == "CREATE_ADDRESS":
        action_id = pending_action.get("id") or action_id
        payload = dict(pending_action.get("payload") or {})

    extracted = _extract_address_payload(text)
    if not extracted.get("contact_name"):
        raw_value = (text or "").strip()
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", raw_value):
            extracted["contact_name"] = raw_value
    if extracted:
        payload.update({k: v for k, v in extracted.items() if v})

    required_fields = ["contact_name", "contact_phone", "address_full"]
    missing = [field for field in required_fields if not payload.get(field)]

    if missing:
        field_label = {
            "contact_name": "联系人姓名",
            "contact_phone": "手机号",
            "address_full": "详细地址",
        }
        recognized = [field_label[field] for field in required_fields if payload.get(field)]
        missing_labels = [field_label[field] for field in missing]
        action = {
            "id": action_id,
            "type": "CREATE_ADDRESS",
            "status": "COLLECTING",
            "payload": payload,
            "action_plan": _build_action_plan(
                "ADDRESS_CREATE",
                slots=payload,
                missing_slots=missing,
                confirm_required=False,
                user_visible_summary="继续补充地址信息",
            ),
        }
        if not payload:
            reply = (
                "可以，我来帮您新增收货地址。\n"
                "请直接发：联系人姓名 + 手机号 + 详细地址。\n"
                "例如：张三 13800138000 上海市浦东新区xx路xx号xx室。"
            )
        else:
            reply = (
                f"我先记下了：{'、'.join(recognized) if recognized else '暂无'}。\n"
                f"还需要补充：{'、'.join(missing_labels)}。\n"
                "您可以直接按“姓名 手机号 详细地址”一条发我。"
            )
        return _respond(
            run,
            reply,
            IntentEnum.UNKNOWN,
            pending_action=action,
        )

    summary = (
        f"我整理好了新地址：联系人 {payload.get('contact_name')}，"
        f"电话 {payload.get('contact_phone')}，地址 {payload.get('address_full')}。"
    )
    if payload.get("door_note"):
        summary += f"\n门牌备注：{payload.get('door_note')}。"
    summary += "\n如果信息无误，回复“确认”我就马上创建。"
    action = {
        "id": action_id,
        "type": "CREATE_ADDRESS",
        "status": "AWAIT_CONFIRM",
        "payload": payload,
        "action_plan": _build_action_plan(
            "ADDRESS_CREATE",
            slots=payload,
            missing_slots=[],
            confirm_required=True,
            user_visible_summary=summary,
        ),
    }
    return _respond(
        run,
        summary,
        IntentEnum.UNKNOWN,
        confirm_required=True,
        pending_action=action,
    )


def _handle_change_password(run, text, portal_user_id, pending_action):
    action_id = _pending_action_id()
    slot_state = {}
    if pending_action and pending_action.get("type") == "CHANGE_PASSWORD":
        action_id = pending_action.get("id") or action_id
        slot_state = dict(pending_action.get("slot_state") or {})
    secure_payload = _load_secure_action_payload(action_id)
    last_asked = str(slot_state.get("last_asked") or "")
    extracted = _extract_password_fields(text, last_asked=last_asked)
    for key in ["old_password", "new_password", "confirm_password"]:
        if extracted.get(key):
            secure_payload[key] = extracted[key]
    _save_secure_action_payload(action_id, secure_payload)

    required = ["old_password", "new_password", "confirm_password"]
    missing = [key for key in required if not secure_payload.get(key)]
    labels = {
        "old_password": "旧密码",
        "new_password": "新密码",
        "confirm_password": "确认新密码",
    }
    if missing:
        next_field = missing[0]
        slot_state.update(
            {
                "has_old_password": bool(secure_payload.get("old_password")),
                "has_new_password": bool(secure_payload.get("new_password")),
                "has_confirm_password": bool(secure_payload.get("confirm_password")),
                "last_asked": next_field,
            }
        )
        action = {
            "id": action_id,
            "type": "CHANGE_PASSWORD",
            "status": "COLLECTING",
            "slot_state": slot_state,
            "action_plan": _build_action_plan(
                "CHANGE_PASSWORD",
                slots={k: bool(secure_payload.get(k)) for k in required},
                missing_slots=missing,
                confirm_required=False,
                user_visible_summary="继续补充密码信息",
            ),
        }
        if not secure_payload:
            reply = (
                "可以，我来帮您修改登录密码。"
                "\n请先发旧密码（仅本次用于校验，不会展示）。"
            )
        else:
            done = [labels[key] for key in required if key not in missing]
            reply = (
                f"已收到：{'、'.join(done)}。"
                f"\n还需要：{labels[next_field]}。"
            )
        return _respond(
            run,
            reply,
            IntentEnum.UNKNOWN,
            pending_action=action,
        )

    if secure_payload.get("new_password") != secure_payload.get("confirm_password"):
        secure_payload.pop("confirm_password", None)
        _save_secure_action_payload(action_id, secure_payload)
        action = {
            "id": action_id,
            "type": "CHANGE_PASSWORD",
            "status": "COLLECTING",
            "slot_state": {
                "has_old_password": bool(secure_payload.get("old_password")),
                "has_new_password": bool(secure_payload.get("new_password")),
                "has_confirm_password": False,
                "last_asked": "confirm_password",
            },
            "action_plan": _build_action_plan(
                "CHANGE_PASSWORD",
                slots={"old_password": True, "new_password": True, "confirm_password": False},
                missing_slots=["confirm_password"],
                confirm_required=False,
                user_visible_summary="确认新密码不一致，需重新输入",
            ),
        }
        return _respond(
            run,
            "两次输入的新密码不一致，请再发一次确认新密码。",
            IntentEnum.UNKNOWN,
            pending_action=action,
        )

    if secure_payload.get("old_password") == secure_payload.get("new_password"):
        secure_payload.pop("new_password", None)
        secure_payload.pop("confirm_password", None)
        _save_secure_action_payload(action_id, secure_payload)
        action = {
            "id": action_id,
            "type": "CHANGE_PASSWORD",
            "status": "COLLECTING",
            "slot_state": {
                "has_old_password": True,
                "has_new_password": False,
                "has_confirm_password": False,
                "last_asked": "new_password",
            },
            "action_plan": _build_action_plan(
                "CHANGE_PASSWORD",
                slots={"old_password": True, "new_password": False, "confirm_password": False},
                missing_slots=["new_password", "confirm_password"],
                confirm_required=False,
                user_visible_summary="新密码不能与旧密码一致",
            ),
        }
        return _respond(
            run,
            "新密码不能和旧密码相同，请重新设置一个新密码。",
            IntentEnum.UNKNOWN,
            pending_action=action,
        )

    summary = (
        "我已收齐密码信息。"
        f"\n- 旧密码：{_mask_password_preview(secure_payload.get('old_password'))}"
        f"\n- 新密码：{_mask_password_preview(secure_payload.get('new_password'))}"
        "\n如果无误，回复“确认”我就立即为您修改。"
    )
    action = {
        "id": action_id,
        "type": "CHANGE_PASSWORD",
        "status": "AWAIT_CONFIRM",
        "payload": {"secure_action_id": action_id},
        "slot_state": {
            "has_old_password": True,
            "has_new_password": True,
            "has_confirm_password": True,
            "last_asked": "",
        },
        "action_plan": _build_action_plan(
            "CHANGE_PASSWORD",
            slots={"old_password": True, "new_password": True, "confirm_password": True},
            missing_slots=[],
            confirm_required=True,
            user_visible_summary="准备执行密码修改",
        ),
    }
    return _respond(
        run,
        summary,
        IntentEnum.UNKNOWN,
        confirm_required=True,
        pending_action=action,
    )


def _ensure_create_draft(run, portal_user_id, draft):
    base = dict(draft or {})
    memory = _portal_memory()
    pref = memory.get("order_pref") if isinstance(memory.get("order_pref"), dict) else {}
    if base.pop("use_default_address", False):
        for key in ["address_id", "address_full", "door_note"]:
            base.pop(key, None)

    context = execute_tool(run, "portal_get_context", {"portal_user_id": portal_user_id})
    if not isinstance(context, dict):
        context = {}
    default_address = context.get("default_address") or {}
    profile = context.get("profile") or {}
    addresses = context.get("addresses") if isinstance(context.get("addresses"), list) else []
    address_by_id = {}
    for item in addresses:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        address_by_id[item_id] = item

    selector_hint = base.pop("address_selector_hint", None)
    if isinstance(selector_hint, dict) and selector_hint:
        selector_result = _resolve_address_selector(addresses, selector_hint)
        selector_status = selector_result.get("status")
        if selector_status == "matched":
            matched = selector_result.get("match") or {}
            try:
                base["address_id"] = int(matched.get("id"))
            except (TypeError, ValueError):
                pass
            base.pop("address_full", None)
            base.pop("door_note", None)
            base["address_confirmed"] = True
            base.pop("address_candidates", None)
            base.pop("address_selector_not_found", None)
        elif selector_status == "ambiguous":
            base["address_candidates"] = list(selector_result.get("candidates") or [])
            base["address_selector_not_found"] = ""
        elif selector_status == "not_found":
            base["address_selector_not_found"] = _format_address_selector_hint(selector_hint)
            base.pop("address_candidates", None)

    if pref:
        if not base.get("address_id") and pref.get("address_id"):
            base["address_id"] = pref.get("address_id")
        if not base.get("contact_name") and pref.get("contact_name"):
            base["contact_name"] = _clean_contact_name(pref.get("contact_name"))
        if not base.get("contact_phone") and pref.get("contact_phone"):
            base["contact_phone"] = pref.get("contact_phone")
        if base.get("is_urgent") is None and pref.get("is_urgent") is True:
            base["is_urgent"] = True
        payload = base.get("service_payload") if isinstance(base.get("service_payload"), dict) else {}
        if (
            not payload.get("cylinder_type")
            and pref.get("cylinder_type")
            and base.get("service_type") in {None, "", SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}
        ):
            payload["cylinder_type"] = pref.get("cylinder_type")
        if payload:
            base["service_payload"] = payload

    try:
        current_address_id = int(base.get("address_id")) if base.get("address_id") is not None else None
    except (TypeError, ValueError):
        current_address_id = None
    bound = {}
    if current_address_id and current_address_id not in address_by_id:
        base.pop("address_id", None)
        base.pop("address_full", None)
        base.pop("door_note", None)
        base["address_confirmed"] = False
    elif current_address_id:
        base["address_id"] = current_address_id
        bound = address_by_id.get(current_address_id) or {}
        if not base.get("address_full") and bound.get("address_full"):
            base["address_full"] = bound.get("address_full")
        if not base.get("door_note") and bound.get("door_note"):
            base["door_note"] = bound.get("door_note")
        if (not base.get("contact_overridden")) and bound.get("contact_name"):
            base["contact_name"] = _clean_contact_name(bound.get("contact_name"))
        elif not base.get("contact_name"):
            base["contact_name"] = _clean_contact_name(bound.get("contact_name"))
        if (not base.get("contact_overridden")) and bound.get("contact_phone"):
            base["contact_phone"] = bound.get("contact_phone") or ""
        elif not base.get("contact_phone"):
            base["contact_phone"] = bound.get("contact_phone") or ""

    hint_address = bound if bound else default_address
    if hint_address:
        base["default_address_hint"] = {
            "id": hint_address.get("id"),
            "address_full": hint_address.get("address_full"),
            "door_note": hint_address.get("door_note"),
            "contact_name": hint_address.get("contact_name"),
            "contact_phone": hint_address.get("contact_phone"),
        }

    has_contact_address = bool(base.get("address_id")) or bool(base.get("address_full"))
    if has_contact_address and base.get("contact_name") and base.get("contact_phone"):
        base["contact_name"] = _clean_contact_name(base.get("contact_name"))
        return base

    if not base.get("address_id") and not base.get("address_full") and default_address.get("id"):
        base["address_id"] = default_address["id"]
        if "address_confirmed" not in base:
            base["address_confirmed"] = False
    if not base.get("address_full") and not base.get("address_id") and default_address.get("address_full"):
        base["address_full"] = default_address.get("address_full")
        if default_address.get("door_note"):
            base["door_note"] = default_address.get("door_note")
        if "address_confirmed" not in base:
            base["address_confirmed"] = False

    if not base.get("contact_name"):
        base["contact_name"] = _clean_contact_name(default_address.get("contact_name") or profile.get("display_name") or "")
    if not base.get("contact_phone"):
        base["contact_phone"] = default_address.get("contact_phone") or profile.get("phone") or ""
    if base.get("contact_name"):
        base["contact_name"] = _clean_contact_name(base.get("contact_name"))
    return base


def _merge_create_fields(draft, message):
    merged = dict(draft or {})
    touched = set()
    text = message or ""

    existing_candidates = list(merged.get("address_candidates") or [])
    if existing_candidates:
        choice_index = _extract_choice_index(text)
        if choice_index and 1 <= choice_index <= len(existing_candidates):
            selected = existing_candidates[choice_index - 1] or {}
            selected_id = selected.get("id")
            try:
                merged["address_id"] = int(selected_id)
            except (TypeError, ValueError):
                pass
            merged.pop("address_full", None)
            merged.pop("door_note", None)
            merged.pop("use_default_address", None)
            merged["address_confirmed"] = True
            merged.pop("address_candidates", None)
            merged.pop("address_selector_not_found", None)
            merged.pop("address_selector_hint", None)
            touched.add("address")

    previous_service_type = merged.get("service_type")
    service_type = _extract_service_type(text)
    if service_type and merged.get("service_type") != service_type:
        merged["service_type"] = service_type
        if previous_service_type and previous_service_type != service_type:
            merged["service_payload"] = {}
        touched.add("service_type")

    payload = dict(merged.get("service_payload") or {})
    current_service_type = merged.get("service_type")

    cylinder_type = _extract_cylinder_type(text)
    if cylinder_type and payload.get("cylinder_type") != cylinder_type:
        payload["cylinder_type"] = cylinder_type
        touched.add("cylinder_type")

    quantity = _extract_quantity(text)
    if quantity and payload.get("quantity") != quantity:
        payload["quantity"] = quantity
        touched.add("quantity")

    if "回收空瓶" in text or "带走空瓶" in text:
        payload["return_empty"] = True
        touched.add("return_empty")
    if "不回收空瓶" in text:
        payload["return_empty"] = False
        touched.add("return_empty")

    if current_service_type == SERVICE_TYPE_INSTALLATION:
        if "安装" in text and len(text.strip()) >= 2:
            payload["install_item"] = text.strip()
            touched.add("install_item")

    if current_service_type == SERVICE_TYPE_SAFETY_CHECK:
        if "安检" in text or "检查" in text:
            payload["check_scope"] = text.strip()
            touched.add("check_scope")

    if current_service_type == SERVICE_TYPE_REPAIR:
        if _has_any(text, ["报修", "故障", "维修", "检修", "修一下", "师傅"]):
            payload["issue_desc"] = text.strip()
            touched.add("issue_desc")

    if current_service_type == SERVICE_TYPE_ACCESSORIES:
        items = _extract_accessory_items(text)
        if items:
            payload["items"] = items
            touched.add("items")

    if payload:
        merged["service_payload"] = _filter_payload_by_service_type(current_service_type, payload)

    phone = _extract_phone(text)
    if phone and merged.get("contact_phone") != phone:
        merged["contact_phone"] = phone
        merged["contact_overridden"] = True
        touched.add("contact_phone")

    contact_name = _extract_contact_name(text)
    if contact_name and merged.get("contact_name") != contact_name:
        merged["contact_name"] = contact_name
        merged["contact_overridden"] = True
        touched.add("contact_name")

    if (
        _looks_like_yes(text)
        and not merged.get("address_id")
        and not merged.get("address_full")
        and ((merged.get("default_address_hint") or {}).get("id"))
    ):
        merged["use_default_address"] = True
        merged["address_confirmed"] = True
        touched.add("address")
    elif _looks_like_yes(text) and merged.get("address_id") and merged.get("address_confirmed") is not True:
        merged["use_default_address"] = True
        merged["address_confirmed"] = True
        touched.add("address")
    elif _looks_like_yes(text) and _has_any(text, ["默认地址", "就这个地址", "这个地址"]):
        merged["use_default_address"] = True
        merged["address_confirmed"] = True
        touched.add("address")
    elif _looks_like_no(text) and _has_any(text, ["默认地址", "地址"]):
        merged.pop("address_id", None)
        merged.pop("address_full", None)
        merged.pop("door_note", None)
        merged.pop("use_default_address", None)
        merged["address_confirmed"] = False
        touched.add("address")
    elif "使用默认地址" in text or "默认地址" in text:
        merged["use_default_address"] = True
        merged["address_confirmed"] = True
        touched.add("address")

    address = _extract_address(text)
    if address:
        merged["address_full"] = address
        merged.pop("address_id", None)
        merged.pop("use_default_address", None)
        merged["address_confirmed"] = True
        merged.pop("address_candidates", None)
        merged.pop("address_selector_not_found", None)
        merged.pop("address_selector_hint", None)
        touched.add("address")
    else:
        address_id = _extract_address_id(text)
        if address_id:
            merged["address_id"] = int(address_id)
            merged.pop("address_full", None)
            merged.pop("door_note", None)
            merged.pop("use_default_address", None)
            merged["address_confirmed"] = True
            merged.pop("address_candidates", None)
            merged.pop("address_selector_not_found", None)
            merged.pop("address_selector_hint", None)
            touched.add("address")
        else:
            selector_hint = _extract_address_selector_hint(text)
            if selector_hint:
                merged["address_selector_hint"] = selector_hint
                merged.pop("use_default_address", None)
                merged.pop("address_candidates", None)
                merged.pop("address_selector_not_found", None)
                touched.add("address")

    notes = _extract_notes(text)
    if notes:
        merged["notes"] = _merge_notes(merged.get("notes"), notes)
        touched.add("notes")
    invoice_note = _extract_invoice_note(text)
    if invoice_note:
        merged["notes"] = _merge_notes(merged.get("notes"), invoice_note)
        touched.add("notes")
    invoice_fields = _extract_invoice_fields(text)
    if invoice_fields:
        for key, val in invoice_fields.items():
            merged[key] = val
        if invoice_fields.get("need_invoice") is False:
            cleaned_notes = _strip_invoice_note_from_notes(merged.get("notes"))
            if cleaned_notes:
                merged["notes"] = cleaned_notes
            else:
                merged.pop("notes", None)
        touched.add("need_invoice")

    delivery_mode = _extract_delivery_mode(text)
    if delivery_mode:
        merged["delivery_mode"] = delivery_mode
        touched.add("delivery_mode")

    time_req = _extract_time_request(text)
    if time_req.get("asap"):
        merged.pop("eta_date", None)
        merged.pop("eta_slot", None)
        merged["delivery_mode"] = "ASAP"
        touched.add("eta")
        touched.add("delivery_mode")
    else:
        eta_date = time_req.get("eta_date")
        eta_slot = time_req.get("eta_slot")
        if eta_date and eta_slot:
            merged["eta_date"] = eta_date
            merged["eta_slot"] = eta_slot
            merged["delivery_mode"] = "SCHEDULED"
            touched.add("eta")
            touched.add("delivery_mode")

    is_urgent = _extract_urgent_flag(text)
    if is_urgent is not None:
        merged["is_urgent"] = is_urgent
        touched.add("is_urgent")

    return merged, sorted(touched)


def _create_missing_fields(draft):
    missing = []
    if draft.get("address_candidates"):
        missing.append("address_choice")
    if draft.get("address_selector_not_found"):
        missing.append("address_refine")
    service_type = draft.get("service_type")
    payload = draft.get("service_payload") or {}
    if not service_type:
        return ["service_type"]

    if service_type in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}:
        if not payload.get("cylinder_type"):
            missing.append("cylinder_type")
        if not payload.get("quantity"):
            missing.append("quantity")
        if service_type == SERVICE_TYPE_CYLINDER_EXCHANGE and "return_empty" not in payload:
            missing.append("return_empty")
    elif service_type == SERVICE_TYPE_INSTALLATION and not payload.get("install_item"):
        missing.append("install_item")
    elif service_type == SERVICE_TYPE_SAFETY_CHECK and not payload.get("check_scope"):
        missing.append("check_scope")
    elif service_type == SERVICE_TYPE_REPAIR and not payload.get("issue_desc"):
        missing.append("issue_desc")
    elif service_type == SERVICE_TYPE_ACCESSORIES and not payload.get("items"):
        missing.append("items")

    if not (draft.get("address_id") or draft.get("address_full")):
        missing.append("address")
    elif (
        draft.get("address_full")
        and not draft.get("address_id")
        and not draft.get("delivery_mode")
        and service_type in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}
    ):
        missing.append("delivery_mode")
    elif (
        draft.get("address_full")
        and not draft.get("address_id")
        and draft.get("delivery_mode") == "SCHEDULED"
        and not (draft.get("eta_date") and draft.get("eta_slot"))
    ):
        missing.append("eta")

    if not draft.get("contact_name"):
        missing.append("contact_name")
    if not draft.get("contact_phone"):
        missing.append("contact_phone")
    return missing


def _ask_missing_field(field_name, draft=None):
    draft = draft or {}
    service_type = draft.get("service_type")
    service_label = SERVICE_TYPE_LABELS.get(service_type, "")
    payload = draft.get("service_payload") or {}

    if field_name == "service_type":
        return "我来帮您下单，先确认一下您要办哪类服务：瓶装配送、换瓶、安装、安检、报修，还是配件？"
    if field_name == "cylinder_type":
        return "收到。请问您要哪种规格：5kg、15kg 还是 45kg？"
    if field_name == "quantity":
        cylinder = payload.get("cylinder_type")
        if cylinder:
            return f"{cylinder} 已记下，请问需要几瓶？"
        return "请问需要几瓶？"
    if field_name == "return_empty":
        return "换瓶服务再确认一下：是否回收空瓶？回复“是”或“否”即可。"
    if field_name == "install_item":
        return "明白。请告诉我具体安装项目（例如：灶具安装、减压阀安装）。"
    if field_name == "check_scope":
        return "收到。请告诉我安检范围（例如：厨房、后厨、整店）。"
    if field_name == "issue_desc":
        return "收到。请描述一下故障现象，我好为您安排报修。"
    if field_name == "items":
        return "好的，请告诉我配件和数量（例如：软管2件、减压阀1件）。"
    if field_name == "address":
        default_hint = draft.get("default_address_hint") or {}
        address_text = default_hint.get("address_full") or ""
        door_note = default_hint.get("door_note") or ""
        if address_text:
            detail = f"{address_text} {door_note}".strip()
            return f"我查到您的默认地址是：{detail}。这单送到默认地址吗？回复“是”，或直接发新的服务地址。"
        return "请告诉我服务地址；如果用默认地址，回复“使用默认地址”即可。"
    if field_name == "address_choice":
        candidates = list(draft.get("address_candidates") or [])
        if not candidates:
            return "我找到了多个地址，请回复“第1个/第2个”或“地址ID xxx”来确认。"
        lines = ["我找到了多个匹配地址，请回复“第N个”或“地址ID xxx”确认要切换到哪一个："]
        for idx, item in enumerate(candidates[:5], start=1):
            tag = "（默认）" if item.get("is_default") else ""
            addr = str(item.get("address_full") or "").strip()
            door = str(item.get("door_note") or "").strip()
            detail = f"{addr} {door}".strip()
            contact = f"{item.get('contact_name') or ''} {item.get('contact_phone') or ''}".strip()
            lines.append(f"{idx}. 地址ID {item.get('id')}：{detail}（{contact}）{tag}")
        return "\n".join(lines)
    if field_name == "address_refine":
        hint = str(draft.get("address_selector_not_found") or "").strip()
        prefix = f"我没定位到您说的地址（{hint}）。" if hint else "我没定位到您说的地址。"
        return f"{prefix}请补充手机号前几位、联系人姓名或地址关键词；也可以直接发完整地址。"
    if field_name == "address_confirm":
        default_hint = draft.get("default_address_hint") or {}
        address_text = default_hint.get("address_full") or "默认地址"
        door_note = default_hint.get("door_note") or ""
        contact_text = f"{default_hint.get('contact_name') or ''} {default_hint.get('contact_phone') or ''}".strip()
        detail = address_text
        if door_note:
            detail = f"{detail} {door_note}"
        if contact_text:
            detail = f"{detail}（{contact_text}）"
        return f"我这边看到您的默认地址是：{detail}。请问这单送到这里吗？回复“是”或直接发新地址都可以。"
    if field_name == "delivery_mode":
        return "配送时间再确认一下：这单您要“立即配送”还是“预约配送”？"
    if field_name == "eta":
        return "好的，您选择了预约配送。请告诉我具体时间，比如“明天 10:00-12:00”。"
    if field_name == "contact_name":
        if service_label:
            return f"{service_label}已记录。请问联系人怎么称呼？"
        return "请问联系人怎么称呼呢？"
    if field_name == "contact_phone":
        return "请留一个联系电话（11位手机号），方便服务前联系您。"
    return "好的，请继续补充下单信息。"


def _payload_human_summary(service_type, payload):
    payload = payload or {}
    if service_type in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}:
        cylinder = payload.get("cylinder_type") or "待补充"
        qty = payload.get("quantity") or "待补充"
        exchange = ""
        if service_type == SERVICE_TYPE_CYLINDER_EXCHANGE:
            if payload.get("return_empty") is True:
                exchange = "，回收空瓶"
            elif payload.get("return_empty") is False:
                exchange = "，不回收空瓶"
        return f"{cylinder} × {qty}瓶{exchange}"
    if service_type == SERVICE_TYPE_INSTALLATION:
        return payload.get("install_item") or "待补充"
    if service_type == SERVICE_TYPE_SAFETY_CHECK:
        return payload.get("check_scope") or "待补充"
    if service_type == SERVICE_TYPE_REPAIR:
        return payload.get("issue_desc") or "待补充"
    if service_type == SERVICE_TYPE_ACCESSORIES:
        items = payload.get("items") or []
        if not items:
            return "待补充"
        parts = []
        for item in items:
            sku = item.get("sku")
            label = ACCESSORY_SKU_LABELS.get(sku, sku or "配件")
            qty = item.get("quantity") or 1
            parts.append(f"{label}×{qty}")
        return "、".join(parts)
    return "待补充"


def _human_address(draft):
    if draft.get("address_full"):
        if draft.get("door_note"):
            return f"{draft.get('address_full')} {draft.get('door_note')}"
        return draft.get("address_full")
    if draft.get("address_id"):
        hint = draft.get("default_address_hint") or {}
        if isinstance(hint, dict):
            if hint.get("door_note"):
                return f"{hint.get('address_full') or '默认地址'} {hint.get('door_note')}"
            if hint.get("address_full"):
                return hint.get("address_full")
        return "默认地址"
    return "待补充"


def _human_contact(draft):
    hint = draft.get("default_address_hint") or {}
    name = draft.get("contact_name") or (hint.get("contact_name") if isinstance(hint, dict) else "") or "待补充"
    phone = draft.get("contact_phone") or (hint.get("contact_phone") if isinstance(hint, dict) else "") or "待补充"
    return f"{name} {phone}"


def _human_eta(draft):
    mode = draft.get("delivery_mode")
    eta_date = draft.get("eta_date")
    eta_slot = draft.get("eta_slot")
    if mode == "SCHEDULED" and eta_date and eta_slot:
        return f"{eta_date} {eta_slot}"
    if mode == "ASAP":
        return "立即配送（系统自动分配）"
    if eta_date and eta_slot:
        return f"{eta_date} {eta_slot}"
    return "立即配送（系统自动分配）"


def _money(value):
    try:
        amount = Decimal(str(value))
    except Exception:
        amount = Decimal("0")
    return f"¥{amount.quantize(Decimal('0.01'))}"


def _estimate_order_pricing(draft):
    service_type = draft.get("service_type")
    payload = draft.get("service_payload") or {}
    lines = []
    subtotal = Decimal("0")
    delivery_fee = Decimal("0")

    if service_type in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}:
        cylinder = payload.get("cylinder_type")
        qty = int(payload.get("quantity") or 0)
        unit = DELIVERY_PRICES.get(cylinder)
        if unit is not None and qty > 0:
            line_total = unit * Decimal(qty)
            subtotal += line_total
            lines.append(f"{cylinder} × {qty}瓶：{_money(line_total)}（单价 {_money(unit)}）")
        else:
            lines.append("气瓶规格/数量待补充")
        delivery_fee = ORDER_ESTIMATE_DELIVERY_FEE
    elif service_type == SERVICE_TYPE_INSTALLATION:
        subtotal = Decimal(str(INSTALLATION_PRICE))
        item_label = payload.get("install_item") or "安装服务"
        lines.append(f"{item_label}：{_money(subtotal)}")
    elif service_type == SERVICE_TYPE_SAFETY_CHECK:
        subtotal = Decimal(str(SAFETY_CHECK_PRICE))
        item_label = payload.get("check_scope") or "安检服务"
        lines.append(f"{item_label}：{_money(subtotal)}")
    elif service_type == SERVICE_TYPE_REPAIR:
        subtotal = Decimal(str(REPAIR_PRICE))
        item_label = payload.get("issue_desc") or "报修基础服务"
        lines.append(f"{item_label}：{_money(subtotal)}（起）")
    elif service_type == SERVICE_TYPE_ACCESSORIES:
        items = payload.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku") or "")
            qty = int(item.get("quantity") or 0)
            unit = ACCESSORY_SKUS.get(sku)
            if unit is None or qty <= 0:
                continue
            line_total = unit * Decimal(qty)
            subtotal += line_total
            lines.append(
                f"{ACCESSORY_SKU_LABELS.get(sku, sku or '配件')} × {qty}：{_money(line_total)}（单价 {_money(unit)}）"
            )
        if not lines:
            lines.append("配件清单待补充")
        delivery_fee = ORDER_ESTIMATE_DELIVERY_FEE

    urgent_fee = Decimal("0")
    if draft.get("is_urgent") and subtotal > Decimal("0"):
        urgent_fee = max(Decimal("10"), (subtotal * Decimal("0.10")))
        urgent_fee = min(Decimal("50"), urgent_fee)
        urgent_fee = urgent_fee.quantize(Decimal("0.01"))
    total = (subtotal + delivery_fee + urgent_fee).quantize(Decimal("0.01"))
    return {
        "service_lines": lines,
        "subtotal": subtotal.quantize(Decimal("0.01")),
        "delivery_fee": delivery_fee.quantize(Decimal("0.01")),
        "urgent_fee": urgent_fee,
        "total": total,
    }


def _create_summary(draft):
    service_type = draft.get("service_type") or ""
    service_label = SERVICE_TYPE_LABELS.get(service_type, "待补充")
    notes = draft.get("notes") or "无"
    urgent = "是" if draft.get("is_urgent") else "否"
    need_invoice = "是" if draft.get("need_invoice") else "否"
    pricing = _estimate_order_pricing(draft)
    pricing_lines = pricing.get("service_lines") or []
    lines = [
        "我先把订单信息整理好了，请您确认：",
        "",
        "**服务信息**",
        f"1. 服务类型：{service_label}",
        "2. 服务项目：",
    ]
    for idx, line in enumerate(pricing_lines, start=1):
        lines.append(f"   {idx}. {line}")
    lines.extend(
        [
            f"3. 服务小计：{_money(pricing.get('subtotal'))}",
            f"4. 配送费：{_money(pricing.get('delivery_fee'))}",
            f"5. 加急费：{_money(pricing.get('urgent_fee'))}",
            f"6. 预估总价：{_money(pricing.get('total'))}",
            "",
            "**上门信息**",
            f"1. 服务地址：{_human_address(draft)}",
            f"2. 联系方式：{_human_contact(draft)}",
            f"3. 预约时间：{_human_eta(draft)}",
            "",
            "**其他信息**",
            f"1. 是否加急：{urgent}",
            f"2. 是否开票：{need_invoice}",
            f"3. 备注：{notes}",
            "",
            "温馨提示：加急订单目标为 1 小时内开始服务（非服务时段将顺延到下一服务窗口）；加急单取消/改址窗口为下单后 30 分钟，普通订单以订单详情页截止时间为准。",
        ]
    )
    return "\n".join(lines)

def _tone_instruction(style):
    mapping = {
        "neutral": "语气专业、清晰、可信赖，带一点温度，避免生硬。",
        "warm": "语气礼貌、亲和，适度表达关怀，但保持简洁。",
        "direct": "语气直接、简短、步骤化，结论先行。",
    }
    return mapping.get(style or "neutral", mapping["neutral"])


def _llm_service_guardrail_prompt():
    return (
        "服务边界要求：\n"
        f"1. 仅在以下场景提及人工客服热线 {SERVICE_HOTLINE}：用户明确要求转人工/电话、明确属于人工专员处理事项、或同类办理连续失败。\n"
        "2. 严禁提供未经安全认证的拆卸、改装、绕过燃气设备的操作步骤。\n"
        f"3. 遇到泄漏、火灾等重大安全问题，必须先给人身安全步骤，再给应急电话：{EMERGENCY_HOTLINE}。\n"
        f"4. 关怀句“{SAFETY_CARE_CLOSING}”只用于高风险安全场景，不用于普通地址/账户问答。\n"
        "5. 语言要专业、清晰、友好、耐心，避免机械模板腔。"
    )


def _sanitize_polished_response(message):
    text = str(message or "").strip()
    if not text:
        return text
    banned_prefixes = [
        "好的，我为您优化一下回复",
        "我为您优化一下回复",
        "我来为您优化一下回复",
        "下面是优化后的回复",
        "以下是优化后的回复",
        "我先帮您优化一下",
    ]
    for prefix in banned_prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip("：:，,。 \n")
    text = re.sub(r"^(好的[，,。]?\s*)?(我来(帮您)?整理一下[：:]?)\s*", "", text)
    return text.strip()


def _polish_with_llm(message, *, confirm_required=False, stage="general"):
    if "test" in sys.argv:
        return message
    llm = PORTAL_LLM_CTX.get()
    tone_style = PORTAL_TONE_CTX.get()
    if not llm or not message:
        return message
    # 中文注释：结构化清单直接保留，避免被改写成一段难读文本。
    if (
        "【服务信息】" in message
        or "【上门信息】" in message
        or "**服务信息**" in message
        or "**上门信息**" in message
        or "企业开票流程如下" in message
        or "**企业开票流程**" in message
    ):
        return message
    keep_confirm_line = "必须保留“确认”“取消”两个词并保留执行提示。" if confirm_required else ""
    stage_instruction = ""
    if stage == "collecting":
        stage_instruction = "当前是补充信息阶段：每次只问一个问题，口吻自然温和，不使用列表或技术术语。"
    elif stage == "confirm":
        stage_instruction = "当前是确认阶段：先结论再动作提示，简洁清晰、礼貌友好。"
    elif stage == "success":
        stage_instruction = "当前是完成通知阶段：语气自然温暖，补充下一步可做什么。"
    elif stage == "safety":
        stage_instruction = (
            "当前是安全应急阶段：先给可执行步骤，再给提醒。"
            f"若场景危急，结尾补充：{_safety_escalation_notice()}"
        )
    system_prompt = (
        "你是LPG企业客服话术优化器。只输出中文。"
        "必须保留原始事实、数字、订单号、时间、状态，不得编造。"
        "不要暴露任何内部字段名、JSON或系统术语。"
        "禁止输出类似“字段=”“payload”“missing_fields”等内部表达。"
        f"回复要亲切、温暖、自然，像{COMPANY_NAME}的专业客服顾问，不要机械模板腔。"
        f"{_llm_service_guardrail_prompt()}"
        f"{_tone_instruction(tone_style)}"
        f"{stage_instruction}"
    )
    human_prompt = (
        "请在不改变事实的前提下，优化下面客服回复：\n"
        f"{keep_confirm_line}\n"
        "--- 原回复开始 ---\n"
        f"{message}\n"
        "--- 原回复结束 ---"
    )
    try:
        polished = _llm_invoke_text([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ])
    except Exception:
        return message
    if polished:
        cleaned = _sanitize_polished_response(polished)
        if cleaned:
            return cleaned
    return message


def _intent_code(intent):
    if hasattr(intent, "value"):
        return str(intent.value or "").upper()
    return str(intent or "").upper()


def _is_failure_response(message):
    value = str(message or "").strip()
    if not value:
        return False
    return _has_any(value, ["失败", "未成功", "没通过", "重试", "校验失败"])


def _infer_hotline_type(text, lane=None):
    value = str(text or "")
    if not value:
        return ""
    if EMERGENCY_HOTLINE in value and (_has_any(value, ["应急", "撤离", "泄漏", "漏气", "火灾"]) or lane == "safety"):
        return "emergency"
    if SERVICE_HOTLINE in value or EMERGENCY_HOTLINE in value:
        return "service"
    return ""


def _suppress_hotline_lines(message, *, allow_service=False, allow_emergency=False, allow_safety_care=False, lane="smalltalk"):
    text = str(message or "")
    if not text:
        return text
    output_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if output_lines and output_lines[-1] != "":
                output_lines.append("")
            continue
        if SAFETY_CARE_CLOSING in stripped and not allow_safety_care:
            continue
        has_hotline = SERVICE_HOTLINE in stripped or EMERGENCY_HOTLINE in stripped
        if has_hotline:
            emergency_line = _has_any(stripped, ["应急", "撤离", "泄漏", "漏气", "火灾", "安全区域"]) or lane == "safety"
            if emergency_line and not allow_emergency:
                continue
            if (not emergency_line) and not allow_service:
                continue
        output_lines.append(line)
    cleaned = "\n".join(output_lines).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def _apply_hotline_policy(run, text, message, intent, lane):
    raw = str(message or "").strip()
    if not raw:
        _set_routing_extra(hotline_suppressed=False)
        return raw

    memory = _portal_memory()
    state = memory.get("hotline_state")
    if not isinstance(state, dict):
        state = {}
    seq = int(state.get("reply_seq") or 0) + 1
    state["reply_seq"] = seq

    intent_code = _intent_code(intent) or "UNKNOWN"
    counters = memory.get("intent_failures")
    if not isinstance(counters, dict):
        counters = {}
    if _is_failure_response(raw):
        counters[intent_code] = min(9, int(counters.get(intent_code) or 0) + 1)
    else:
        counters[intent_code] = 0

    is_safety_risk = lane == "safety" or _is_high_risk_safety_query(text) or _is_safety_emergency_query(text)
    explicit_manual = _has_any(text, ["人工客服", "转人工", "转接人工", "人工电话", "客服电话"]) and not is_safety_risk
    manual_handoff = _needs_manual_handoff(text)
    allow_service = explicit_manual or manual_handoff or int(counters.get(intent_code) or 0) >= 2
    allow_emergency = bool(is_safety_risk)
    allow_safety_care = bool(is_safety_risk)

    hotline_type_raw = _infer_hotline_type(raw, lane=lane)
    last_type = str(state.get("last_hotline_type") or "")
    last_step = int(state.get("last_hotline_step") or 0)
    risk_escalated = allow_emergency and last_type != "emergency"
    if hotline_type_raw and hotline_type_raw == last_type and (seq - last_step) <= 3 and not risk_escalated:
        if hotline_type_raw == "emergency":
            allow_emergency = False
        else:
            allow_service = False

    filtered = _suppress_hotline_lines(
        raw,
        allow_service=allow_service,
        allow_emergency=allow_emergency,
        allow_safety_care=allow_safety_care,
        lane=lane or "smalltalk",
    )
    if not filtered:
        filtered = raw
    suppressed = filtered != raw
    hotline_type_final = _infer_hotline_type(filtered, lane=lane)

    if hotline_type_final:
        state["last_hotline_type"] = hotline_type_final
        state["last_hotline_step"] = seq

    _update_portal_memory(
        {
            "intent_failures": counters,
            "hotline_state": state,
            "last_response": filtered[:500],
            "last_agent_reply": filtered[:500],
        }
    )
    _set_routing_extra(hotline_suppressed=bool(suppressed))
    if hotline_type_final:
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_hotline_injected",
                "hotline_type": hotline_type_final,
                "lane": lane,
            },
        )
    elif suppressed and hotline_type_raw:
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_hotline_suppressed",
                "hotline_type": hotline_type_raw,
                "lane": lane,
            },
        )
    return filtered


def _respond(
    run,
    message,
    intent,
    *,
    confirm_required=False,
    pending_action=None,
    cleared_action_id=None,
    lane=None,
):
    if lane:
        _set_lane(lane)
    stage = "general"
    if lane == "safety":
        stage = "safety"
    elif pending_action and pending_action.get("status") == "COLLECTING":
        stage = "collecting"
    elif confirm_required:
        stage = "confirm"
    elif any(token in (message or "") for token in ["已生成", "支付成功", "已提交"]):
        stage = "success"
    polished_response = _polish_with_llm(message, confirm_required=confirm_required, stage=stage)
    active_lane = lane or PORTAL_LANE_CTX.get() or "smalltalk"
    if isinstance(pending_action, dict) and pending_action.get("type") == "BATCH_ACTION":
        _set_routing_extra(batch=True)
    elif PORTAL_ROUTING_EXTRA_CTX.get() is None or (isinstance(PORTAL_ROUTING_EXTRA_CTX.get(), dict) and "batch" not in PORTAL_ROUTING_EXTRA_CTX.get()):
        _set_routing_extra(batch=False)
    polished_response = _apply_hotline_policy(run, PORTAL_INPUT_CTX.get(), polished_response, intent, active_lane)
    polished_response = _append_manual_queue_footer_if_active(polished_response, lane=active_lane)
    routing = _routing_meta()
    output_json = {"final_response": polished_response, "routing": routing}
    if pending_action:
        output_json["pending_action"] = pending_action
    if cleared_action_id:
        output_json["pending_action_cleared"] = cleared_action_id
    if confirm_required:
        output_json["confirm_required"] = True
    _append_event(run, AgentEvent.STATE_RESPOND, output_json=output_json)
    _append_event(run, AgentEvent.STATE_DONE)
    _persist_portal_memory(intent, pending_action=pending_action)
    return AgentOutput(
        intent=intent,
        tool_calls=[],
        final_response=polished_response,
        risk_level=RiskLevelEnum.LOW,
        need_human=False,
        confirm_required=confirm_required,
        pending_action=pending_action,
        routing=routing,
    )


def _build_slot_trace(old_trace, touched_fields):
    trace = list(old_trace or [])
    now_iso = timezone.now().isoformat()
    for field in touched_fields:
        trace.append({"field": field, "at": now_iso})
    return trace[-30:]


def _build_action_plan(intent, slots=None, missing_slots=None, confirm_required=False, user_visible_summary=""):
    intent_code = str(intent or "").upper()
    missing = [str(item) for item in (missing_slots or []) if str(item).strip()]
    return {
        "intent": intent_code,
        "confidence": 0.88 if not missing else 0.72,
        "slots": slots or {},
        "missing_slots": missing,
        "confirm_required": bool(confirm_required),
        "user_visible_summary": str(user_visible_summary or "").strip(),
    }


def _extract_batch_service_type_candidates(text):
    value = _normalize_user_text(text)
    if not value:
        return []
    candidates = []
    delivery_signal = (
        _has_any(value, ["配送", "送气", "液化气", "订气", "叫气", "送煤气"])
        and (
            _extract_cylinder_type(value)
            or _extract_quantity(value)
            or _has_any(value, ["一瓶", "两瓶", "一罐", "两罐", "kg", "公斤"])
        )
    )
    if delivery_signal:
        candidates.append(SERVICE_TYPE_LPG_CYLINDER_DELIVERY)
    if _has_any(value, ["报修", "维修", "检修", "故障", "修一下", "师傅修"]) or _has_any(value, ON_SITE_SERVICE_SIGNAL_KEYWORDS):
        candidates.append(SERVICE_TYPE_REPAIR)
    elif _has_any(value, ["安检", "上门安检", "上门检查", "安全检查"]):
        candidates.append(SERVICE_TYPE_SAFETY_CHECK)
    # 回退：如果只识别到单一服务类型，沿用旧逻辑。
    if not candidates:
        service_type = _extract_service_type(value)
        if service_type in {SERVICE_TYPE_REPAIR, SERVICE_TYPE_SAFETY_CHECK, SERVICE_TYPE_LPG_CYLINDER_DELIVERY}:
            candidates.append(service_type)
    deduped = []
    seen = set()
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _detect_batch_action_request(text):
    value = _normalize_user_text(text)
    if not value:
        return None
    if not _has_any(value, BATCH_CONNECTOR_HINTS):
        return None
    cart_items = _extract_accessory_items(value)
    if not cart_items:
        return None
    if not _has_accessory_purchase_intent(value):
        return None
    service_candidates = _extract_batch_service_type_candidates(value)
    if not service_candidates:
        return None
    if len(service_candidates) == 1:
        return {"cart_items": cart_items, "service_type": service_candidates[0], "service_candidates": service_candidates}
    return {"cart_items": cart_items, "service_candidates": service_candidates}


def _batch_get_action_state(actions, action_type):
    for action in actions or []:
        if str(action.get("type") or "").upper() == action_type:
            return str(action.get("state") or "PENDING").upper()
    return "PENDING"


def _batch_is_order_action_type(action_type):
    kind = str(action_type or "").upper()
    return kind == "CREATE_ORDER" or kind.startswith("CREATE_ORDER_")


def _batch_normalize_order_drafts(order_payload):
    if isinstance(order_payload, list):
        drafts = [dict(item) for item in order_payload if isinstance(item, dict)]
    elif isinstance(order_payload, dict):
        drafts = [dict(order_payload)]
    else:
        drafts = []
    return drafts


def _batch_order_action_type(index, total):
    if total <= 1:
        return "CREATE_ORDER"
    return f"CREATE_ORDER_{index}"


def _batch_extract_order_actions(actions):
    output = []
    for action in actions or []:
        action_type = str(action.get("type") or "").upper()
        payload_or_draft = action.get("payload_or_draft")
        if not _batch_is_order_action_type(action_type):
            continue
        if not isinstance(payload_or_draft, dict):
            continue
        output.append(
            {
                "type": action_type,
                "state": str(action.get("state") or "PENDING").upper(),
                "draft": dict(payload_or_draft),
            }
        )
    return output


def _batch_set_action_state(actions, action_type, state):
    updated = []
    for action in actions or []:
        next_action = dict(action or {})
        if str(next_action.get("type") or "").upper() == str(action_type or "").upper():
            next_action["state"] = str(state or "PENDING").upper()
        updated.append(next_action)
    return updated


def _batch_apply_service_defaults(draft):
    result = dict(draft or {})
    service_type = result.get("service_type")
    payload = dict(result.get("service_payload") or {})
    if service_type == SERVICE_TYPE_SAFETY_CHECK and not payload.get("check_scope"):
        payload["check_scope"] = "整户用气安全检查"
    if service_type == SERVICE_TYPE_REPAIR and not payload.get("issue_desc"):
        payload["issue_desc"] = result.get("notes") or "按现场情况排查"
    if payload:
        result["service_payload"] = payload
    return result


def _batch_build_actions(cart_items, order_payload, existing_actions=None):
    order_drafts = _batch_normalize_order_drafts(order_payload)
    actions = [
        {
            "type": "CART_ADD",
            "payload_or_draft": {"items": cart_items or []},
            "state": _batch_get_action_state(existing_actions, "CART_ADD"),
        }
    ]
    if not order_drafts:
        actions.append(
            {
                "type": "CREATE_ORDER",
                "payload_or_draft": {},
                "state": _batch_get_action_state(existing_actions, "CREATE_ORDER"),
            }
        )
        return actions
    total = len(order_drafts)
    for idx, draft in enumerate(order_drafts, start=1):
        action_type = _batch_order_action_type(idx, total)
        actions.append(
            {
                "type": action_type,
                "payload_or_draft": dict(draft or {}),
                "state": _batch_get_action_state(existing_actions, action_type),
            }
        )
    return actions


def _batch_shared_slots(order_payload):
    order_drafts = _batch_normalize_order_drafts(order_payload)
    draft = dict(order_drafts[0] if order_drafts else {})
    return {
        "address": _human_address(draft),
        "contact": _human_contact(draft),
        "eta": _human_eta(draft),
        "is_urgent": bool(draft.get("is_urgent")),
        "notes": draft.get("notes") or "",
    }


def _batch_missing_fields(order_payload, cart_items):
    order_drafts = _batch_normalize_order_drafts(order_payload)
    missing = []
    if not cart_items:
        missing.append("items")
    if not order_drafts:
        missing.append("service_type")
    for idx, order_draft in enumerate(order_drafts, start=1):
        normalized = _batch_apply_service_defaults(order_draft)
        draft_missing = _create_missing_fields(normalized or {})
        if len(order_drafts) <= 1:
            missing.extend(draft_missing)
        else:
            missing.extend([f"order{idx}:{field}" for field in draft_missing])
    deduped = []
    seen = set()
    for field in missing:
        key = str(field or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _ask_batch_missing_field(field_name, draft=None, order_drafts=None):
    if field_name == "items":
        return "我先帮您处理配件，请告诉我配件和数量（例如：报警器1个、卡箍1套）。"
    if field_name == "service_type":
        return "请先确认本次要合并办理哪些服务单：瓶装配送、安检、报修。"
    if ":" in str(field_name or ""):
        match = re.match(r"order(\d+):(.+)", str(field_name))
        if match:
            order_index = int(match.group(1))
            slot_name = match.group(2)
            draft_list = _batch_normalize_order_drafts(order_drafts)
            target = draft_list[order_index - 1] if 0 < order_index <= len(draft_list) else {}
            service_label = SERVICE_TYPE_LABELS.get(target.get("service_type"), target.get("service_type") or f"服务单{order_index}")
            return f"关于“{service_label}”这单，{_ask_missing_field(slot_name, draft=target or {})}"
    return _ask_missing_field(field_name, draft=draft or {})


def _build_batch_confirm_summary(cart_items, order_payload, *, partial_done=False):
    order_drafts = _batch_normalize_order_drafts(order_payload)
    lines = ["我已整理好这次组合办理内容，请您确认："]
    lines.append(f"1. 配件加购：{_build_cart_items_line(cart_items) or '待补充'}")
    line_no = 2
    for idx, order_draft in enumerate(order_drafts, start=1):
        draft = _batch_apply_service_defaults(order_draft)
        service_type = draft.get("service_type")
        service_label = SERVICE_TYPE_LABELS.get(service_type, service_type or f"服务单{idx}")
        payload_summary = _payload_human_summary(service_type, draft.get("service_payload") or {})
        lines.append(f"{line_no}. 服务单{idx}：{service_label}（{payload_summary}）")
        line_no += 1
        lines.append(f"{line_no}. 地址：{_human_address(draft)}")
        line_no += 1
        lines.append(f"{line_no}. 联系方式：{_human_contact(draft)}")
        line_no += 1
        lines.append(f"{line_no}. 预约时间：{_human_eta(draft)}")
        line_no += 1
    if partial_done:
        lines.append("当前状态：已有部分动作完成，待重试未完成动作。")
        lines.append("回复“确认”后我将仅重试未完成动作。")
    else:
        lines.append("回复“确认”后我会按“先加购配件，再逐个创建服务单”顺序一次执行。")
    return "\n".join(lines)


def _batch_action_from_state(action_id, status, cart_items, order_payload, missing_fields, *, existing_actions=None, action_plan=""):
    order_drafts = _batch_normalize_order_drafts(order_payload)
    first_draft = dict(order_drafts[0] if order_drafts else {})
    action = {
        "id": action_id,
        "type": "BATCH_ACTION",
        "status": status,
        "confirm_mode": "ALL_IN_ONE",
        "actions": _batch_build_actions(cart_items, order_drafts, existing_actions=existing_actions),
        "shared_slots": _batch_shared_slots(order_drafts),
        "last_asked": (missing_fields[0] if missing_fields else ""),
        "missing_fields": list(missing_fields or []),
        "updated_at": timezone.now().isoformat(),
        "action_plan": _build_action_plan(
            "BATCH_ACTION",
            slots={
                "cart_items": cart_items or [],
                "order_draft": first_draft,
                "order_drafts": order_drafts,
            },
            missing_slots=list(missing_fields or []),
            confirm_required=status in {"AWAIT_CONFIRM", "PARTIAL_DONE"},
            user_visible_summary=action_plan,
        ),
    }
    if len(order_drafts) > 1:
        action["order_drafts"] = order_drafts
    return action


def _handle_batch_action(run, message, portal_user_id, pending_action=None, seed=None):
    action_id = _pending_action_id()
    existing_actions = []
    cart_items = []
    order_drafts = []
    service_candidates = []

    if isinstance(seed, dict):
        cart_items = list(seed.get("cart_items") or [])
        service_candidates = list(seed.get("service_candidates") or [])
        service_type = seed.get("service_type")
        if service_type in {SERVICE_TYPE_REPAIR, SERVICE_TYPE_SAFETY_CHECK, SERVICE_TYPE_LPG_CYLINDER_DELIVERY}:
            order_drafts = [{"service_type": service_type}]
        elif service_candidates:
            order_drafts = [{"service_type": item} for item in service_candidates]

    if isinstance(pending_action, dict) and pending_action.get("type") == "BATCH_ACTION":
        action_id = pending_action.get("id") or action_id
        existing_actions = list(pending_action.get("actions") or [])
        service_candidates = list(pending_action.get("service_candidates") or service_candidates)
        order_actions = _batch_extract_order_actions(existing_actions)
        if order_actions:
            order_drafts = [dict(item.get("draft") or {}) for item in order_actions]
        elif isinstance(pending_action.get("order_drafts"), list):
            order_drafts = [dict(item) for item in pending_action.get("order_drafts") if isinstance(item, dict)]
        for item in existing_actions:
            item_type = str(item.get("type") or "").upper()
            data = item.get("payload_or_draft")
            if item_type == "CART_ADD" and isinstance(data, dict):
                cart_items = list(data.get("items") or cart_items)

    text = message or ""
    invoice_update = _extract_invoice_fields(text) if _looks_like_invoice_preference_update(text) else {}
    invoice_pref_notice = ""
    if isinstance(invoice_update, dict) and "need_invoice" in invoice_update:
        invoice_pref_notice = f"已将本次组合单开票改为{'是' if invoice_update.get('need_invoice') else '否'}。"
    extracted_items = _extract_accessory_items(text)
    if extracted_items:
        cart_items = extracted_items

    detected_candidates = _extract_batch_service_type_candidates(text)
    if detected_candidates:
        service_candidates = detected_candidates
    if not order_drafts and service_candidates:
        order_drafts = [{"service_type": item} for item in service_candidates]
    if not order_drafts:
        guessed_service = _extract_batch_service_type_candidates(text)
        if guessed_service:
            order_drafts = [{"service_type": item} for item in guessed_service]

    if order_drafts:
        merged_drafts = []
        for draft in order_drafts:
            locked_service_type = draft.get("service_type")
            merged, _ = _merge_create_fields(draft, text)
            if locked_service_type:
                payload = dict(merged.get("service_payload") or {})
                if locked_service_type in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}:
                    cylinder_type = _extract_cylinder_type(text)
                    quantity = _extract_quantity(text)
                    if cylinder_type:
                        payload["cylinder_type"] = cylinder_type
                    if quantity:
                        payload["quantity"] = quantity
                    if "回收空瓶" in text or "带走空瓶" in text:
                        payload["return_empty"] = True
                    if "不回收空瓶" in text:
                        payload["return_empty"] = False
                elif locked_service_type == SERVICE_TYPE_SAFETY_CHECK and not payload.get("check_scope"):
                    payload["check_scope"] = "整户用气安全检查"
                elif locked_service_type == SERVICE_TYPE_REPAIR and not payload.get("issue_desc"):
                    payload["issue_desc"] = text.strip() or "按现场情况排查"
                merged["service_type"] = locked_service_type
                merged["service_payload"] = _filter_payload_by_service_type(locked_service_type, payload)
            merged = _ensure_create_draft(run, portal_user_id, merged)
            merged = _batch_apply_service_defaults(merged)
            merged_drafts.append(merged)
        order_drafts = merged_drafts
    else:
        one_draft, _ = _merge_create_fields({}, text)
        if one_draft.get("service_type"):
            one_draft = _ensure_create_draft(run, portal_user_id, one_draft)
            one_draft = _batch_apply_service_defaults(one_draft)
            order_drafts = [one_draft]

    missing_fields = _batch_missing_fields(order_drafts, cart_items)

    _set_routing_extra(batch=True)

    if missing_fields:
        next_field = missing_fields[0]
        action = _batch_action_from_state(
            action_id,
            "COLLECTING",
            cart_items,
            order_drafts,
            missing_fields,
            existing_actions=existing_actions,
            action_plan="继续补充配件与上门信息",
        )
        if service_candidates:
            action["service_candidates"] = service_candidates
        ask = _ask_batch_missing_field(
            next_field,
            draft=(order_drafts[0] if order_drafts else {}),
            order_drafts=order_drafts,
        )
        if next_field != "items":
            ask = f"已识别到您要“配件 + 多服务单”一起办理。{ask}"
        else:
            ask = f"已识别到您要“配件 + 多服务单”一起办理。{ask}"
        if invoice_pref_notice:
            ask = f"{invoice_pref_notice}\n{ask}"
        return _respond(
            run,
            ask,
            IntentEnum.CREATE_ORDER,
            pending_action=action,
            lane="action",
        )

    order_actions = _batch_extract_order_actions(existing_actions)
    has_partial_done = (
        _batch_get_action_state(existing_actions, "CART_ADD") == "DONE"
        and bool(order_actions)
        and any(item.get("state") != "DONE" for item in order_actions)
    )
    status = "PARTIAL_DONE" if has_partial_done else "AWAIT_CONFIRM"
    summary = _build_batch_confirm_summary(cart_items, order_drafts, partial_done=has_partial_done)
    action = _batch_action_from_state(
        action_id,
        status,
        cart_items,
        order_drafts,
        [],
        existing_actions=existing_actions,
        action_plan=summary,
    )
    if service_candidates:
        action["service_candidates"] = service_candidates
    return _respond(
        run,
        f"{(invoice_pref_notice + '\n') if invoice_pref_notice else ''}{summary}",
        IntentEnum.CREATE_ORDER,
        confirm_required=True,
        pending_action=action,
        lane="action",
    )


def _handle_create_order(run, message, portal_user_id, pending_action):
    draft = {}
    trace = []
    action_id = _pending_action_id()
    if pending_action and pending_action.get("type") == "CREATE_ORDER":
        draft = dict(pending_action.get("draft") or {})
        trace = list(pending_action.get("slot_trace") or [])
        action_id = pending_action.get("id") or action_id

    draft, touched_fields = _merge_create_fields(draft, message)
    draft = _ensure_create_draft(run, portal_user_id, draft)
    missing_fields = _create_missing_fields(draft)
    trace = _build_slot_trace(trace, touched_fields)
    invoice_pref_notice = ""
    if "need_invoice" in touched_fields:
        invoice_pref_notice = f"已将本单开票改为{'是' if draft.get('need_invoice') else '否'}。"

    if missing_fields:
        next_field = missing_fields[0]
        action_plan = _build_action_plan(
            "CREATE_ORDER",
            slots=draft,
            missing_slots=missing_fields,
            confirm_required=False,
            user_visible_summary="继续补充下单信息",
        )
        action = {
            "id": action_id,
            "type": "CREATE_ORDER",
            "status": "COLLECTING",
            "draft": draft,
            "missing_fields": missing_fields,
            "last_asked": next_field,
            "slot_trace": trace,
            "updated_at": timezone.now().isoformat(),
            "action_plan": action_plan,
        }
        question = _ask_missing_field(next_field, draft=draft)
        invalid_size = _extract_invalid_cylinder_size(message)
        if next_field == "cylinder_type" and invalid_size:
            question = (
                f"收到，{invalid_size}kg 目前不在可选规格内。"
                "我们支持 5kg、15kg、45kg，请问您选择哪一种？"
            )
        prompt_text = question
        if draft.get("service_type") and next_field != "service_type":
            service_label = SERVICE_TYPE_LABELS.get(draft.get("service_type"), draft.get("service_type"))
            if question.startswith("好的"):
                prompt_text = f"您要办理的是“{service_label}”。{question}"
            else:
                prompt_text = f"好的，您要办理的是“{service_label}”。{question}"
        if invoice_pref_notice:
            prompt_text = f"{invoice_pref_notice}\n{prompt_text}"
        return _respond(
            run,
            prompt_text,
            IntentEnum.CREATE_ORDER,
            pending_action=action,
        )

    summary = _create_summary(draft)
    action = {
        "id": action_id,
        "type": "CREATE_ORDER",
        "status": "AWAIT_CONFIRM",
        "draft": draft,
        "slot_trace": trace,
        "updated_at": timezone.now().isoformat(),
        "action_plan": _build_action_plan(
            "CREATE_ORDER",
            slots=draft,
            missing_slots=[],
            confirm_required=True,
            user_visible_summary=summary,
        ),
    }
    return _respond(
        run,
        f"{(invoice_pref_notice + '\n') if invoice_pref_notice else ''}{summary}\n\n请确认上面的订单信息是否正确。回复“确认下单”我就为您提交；如需修改，直接告诉我要改哪一项。",
        IntentEnum.CREATE_ORDER,
        confirm_required=True,
        pending_action=action,
    )


def _clean_create_payload(draft):
    payload = dict(draft or {})
    need_invoice = bool(payload.pop("need_invoice", False))
    invoice_title = (payload.pop("invoice_title", "") or "").strip()
    invoice_tax_no = (payload.pop("invoice_tax_no", "") or "").strip()
    service_payload = payload.get("service_payload") if isinstance(payload.get("service_payload"), dict) else {}
    if need_invoice:
        service_payload["invoice_required"] = True
        if invoice_title:
            service_payload["invoice_title"] = invoice_title
        if invoice_tax_no:
            service_payload["invoice_tax_no"] = invoice_tax_no
    else:
        service_payload.pop("invoice_required", None)
        service_payload.pop("invoice_title", None)
        service_payload.pop("invoice_tax_no", None)
    if service_payload:
        payload["service_payload"] = service_payload
    for key in [
        "use_default_address",
        "address_confirmed",
        "default_address_hint",
        "delivery_mode",
        "contact_overridden",
        "address_candidates",
        "address_selector_not_found",
        "address_selector_hint",
    ]:
        payload.pop(key, None)
    return payload


def _format_lead_time_text(eta_start_value):
    eta_start_text = _format_eta_text(eta_start_value)
    if not eta_start_text:
        return ""
    try:
        eta_start = datetime.fromisoformat(str(eta_start_value).replace("Z", "+00:00"))
        if eta_start.tzinfo:
            eta_start = timezone.localtime(eta_start)
        now = timezone.localtime(timezone.now())
        delta = int((eta_start - now).total_seconds() // 60)
        if delta <= 0:
            return "即将"
        if delta < 60:
            return f"约 {delta} 分钟后"
        hours = delta // 60
        mins = delta % 60
        if mins == 0:
            return f"约 {hours} 小时后"
        return f"约 {hours} 小时 {mins} 分钟后"
    except Exception:
        return ""


def _execute_pending_action(run, pending_action, portal_user_id):
    action_type = pending_action.get("type")
    draft = pending_action.get("draft") or {}

    if action_type == "BATCH_ACTION":
        actions = list(pending_action.get("actions") or [])
        cart_state = _batch_get_action_state(actions, "CART_ADD")
        cart_items = []
        for action in actions:
            action_kind = str(action.get("type") or "").upper()
            payload_or_draft = action.get("payload_or_draft")
            if action_kind == "CART_ADD" and isinstance(payload_or_draft, dict):
                cart_items = list(payload_or_draft.get("items") or [])
        order_actions = _batch_extract_order_actions(actions)
        order_drafts = [dict(item.get("draft") or {}) for item in order_actions]
        if not order_drafts and isinstance(pending_action.get("order_drafts"), list):
            order_drafts = [dict(item) for item in pending_action.get("order_drafts") if isinstance(item, dict)]
            actions = _batch_build_actions(cart_items, order_drafts, existing_actions=actions)
            order_actions = _batch_extract_order_actions(actions)
        if not order_drafts:
            return _respond(
                run,
                "组合办理里还缺少服务单信息。请告诉我要办理的服务（例如：配送15kg一瓶，或上门安检）。",
                IntentEnum.CREATE_ORDER,
                cleared_action_id=pending_action.get("id"),
                lane="action",
            )
        order_states = {item.get("type"): item.get("state") for item in order_actions}

        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_batch_action_execute",
                "cart_state": cart_state,
                "order_states": order_states,
            },
        )
        _set_routing_extra(batch=True)

        if cart_state != "DONE":
            cart_result = execute_tool(
                run,
                "portal_cart_add",
                {"portal_user_id": portal_user_id, "items": cart_items},
            )
            if cart_result.get("error"):
                failed_actions = _batch_build_actions(cart_items, order_drafts, existing_actions=actions)
                failed_actions = _batch_set_action_state(failed_actions, "CART_ADD", "FAILED")
                retry_action = _batch_action_from_state(
                    pending_action.get("id") or _pending_action_id(),
                    "AWAIT_CONFIRM",
                    cart_items,
                    order_drafts,
                    [],
                    existing_actions=failed_actions,
                    action_plan="配件加购失败，等待重试",
                )
                if isinstance(pending_action.get("service_candidates"), list):
                    retry_action["service_candidates"] = list(pending_action.get("service_candidates") or [])
                return _respond(
                    run,
                    f"配件加购失败：{cart_result.get('code') or cart_result.get('error')}。回复“确认”后我会重试整组动作。",
                    IntentEnum.CREATE_ORDER,
                    confirm_required=True,
                    pending_action=retry_action,
                    lane="action",
                )
            actions = _batch_set_action_state(actions, "CART_ADD", "DONE")
            order_actions = _batch_extract_order_actions(actions)

        created_orders = []
        for index, order_action in enumerate(order_actions):
            action_kind = str(order_action.get("type") or "").upper()
            action_state = str(order_action.get("state") or "PENDING").upper()
            order_draft = _batch_apply_service_defaults(order_action.get("draft") or {})
            if action_state == "DONE":
                continue
            create_payload = _clean_create_payload(order_draft)
            order_result = execute_tool(
                run,
                "portal_create_order",
                {"portal_user_id": portal_user_id, "payload": create_payload},
            )
            service_label = SERVICE_TYPE_LABELS.get(
                order_draft.get("service_type"), order_draft.get("service_type") or f"服务单{index + 1}"
            )
            if order_result.get("error"):
                details = order_result.get("details") if isinstance(order_result.get("details"), dict) else {}
                address_error = (
                    details.get("address_id") == "not_found"
                    or any(str(key).startswith("address_") for key in details.keys())
                )
                retry_drafts = [dict(item.get("draft") or {}) for item in _batch_extract_order_actions(actions)]
                if address_error and index < len(retry_drafts):
                    retry_draft = dict(retry_drafts[index] or {})
                    for key in ["address_id", "address_full", "door_note", "address_confirmed", "use_default_address"]:
                        retry_draft.pop(key, None)
                    retry_draft = _ensure_create_draft(run, portal_user_id, retry_draft)
                    retry_draft = _batch_apply_service_defaults(retry_draft)
                    retry_drafts[index] = retry_draft
                retry_missing = _batch_missing_fields(retry_drafts, cart_items)
                if address_error:
                    key = f"order{index + 1}:address" if len(retry_drafts) > 1 else "address"
                    if key not in retry_missing:
                        retry_missing = [key] + retry_missing
                retry_actions = _batch_build_actions(cart_items, retry_drafts, existing_actions=actions)
                retry_actions = _batch_set_action_state(retry_actions, "CART_ADD", "DONE")
                for done_item in created_orders:
                    retry_actions = _batch_set_action_state(retry_actions, done_item.get("action_type"), "DONE")
                retry_actions = _batch_set_action_state(retry_actions, action_kind, "FAILED")
                retry_status = "COLLECTING" if address_error else "PARTIAL_DONE"
                retry_action = _batch_action_from_state(
                    pending_action.get("id") or _pending_action_id(),
                    retry_status,
                    cart_items,
                    retry_drafts,
                    retry_missing if address_error else [],
                    existing_actions=retry_actions,
                    action_plan="组合动作部分失败，等待重试",
                )
                if isinstance(pending_action.get("service_candidates"), list):
                    retry_action["service_candidates"] = list(pending_action.get("service_candidates") or [])
                if address_error:
                    return _respond(
                        run,
                        f"配件已处理，但“{service_label}”地址校验失败。请确认是否继续使用默认地址，或直接发新的服务地址。",
                        IntentEnum.CREATE_ORDER,
                        pending_action=retry_action,
                        lane="action",
                    )
                return _respond(
                    run,
                    f"配件已处理成功，但“{service_label}”创建失败：{order_result.get('code') or order_result.get('error')}。回复“确认”后我只重试未完成动作。",
                    IntentEnum.CREATE_ORDER,
                    confirm_required=True,
                    pending_action=retry_action,
                    lane="action",
                )
            actions = _batch_set_action_state(actions, action_kind, "DONE")
            order_actions = _batch_extract_order_actions(actions)
            created_orders.append(
                {
                    "action_type": action_kind,
                    "order_no": order_result.get("order_no"),
                    "service_type": order_result.get("service_type") or order_draft.get("service_type"),
                    "eta_start": order_result.get("eta_start"),
                    "eta_end": order_result.get("eta_end"),
                }
            )

        has_pending_orders = any(str(item.get("state") or "").upper() != "DONE" for item in order_actions)
        if not has_pending_orders:
            if len(created_orders) <= 1:
                only = created_orders[0] if created_orders else None
                if only:
                    eta_range = _format_eta_range({"eta_start": only.get("eta_start"), "eta_end": only.get("eta_end")})
                    service_label = SERVICE_TYPE_LABELS.get(only.get("service_type"), only.get("service_type") or "服务单")
                    return _respond(
                        run,
                        f"组合需求已处理完成：配件已加入购物车，{service_label}已创建（{only.get('order_no')}），预计服务时段 {eta_range}。",
                        IntentEnum.CREATE_ORDER,
                        cleared_action_id=pending_action.get("id"),
                        lane="action",
                    )
                return _respond(
                    run,
                    "该组合动作已执行完成，如需继续办理请直接告诉我。",
                    IntentEnum.CREATE_ORDER,
                    cleared_action_id=pending_action.get("id"),
                    lane="action",
                )
            lines = ["组合需求已处理完成：配件已加入购物车，服务单已创建："]
            for idx, item in enumerate(created_orders, start=1):
                service_label = SERVICE_TYPE_LABELS.get(item.get("service_type"), item.get("service_type") or f"服务单{idx}")
                eta_range = _format_eta_range({"eta_start": item.get("eta_start"), "eta_end": item.get("eta_end")})
                lines.append(f"{idx}. {service_label}：{item.get('order_no')}（{eta_range}）")
            return _respond(
                run,
                "\n".join(lines),
                IntentEnum.CREATE_ORDER,
                cleared_action_id=pending_action.get("id"),
                lane="action",
            )

        return _respond(
            run,
            "该组合动作已执行完成，如需继续办理请直接告诉我。",
            IntentEnum.CREATE_ORDER,
            cleared_action_id=pending_action.get("id"),
            lane="action",
        )

    if action_type == "CREATE_ORDER":
        create_payload = _clean_create_payload(draft)
        result = execute_tool(run, "portal_create_order", {"portal_user_id": portal_user_id, "payload": create_payload})
        if result.get("error"):
            details = result.get("details") if isinstance(result.get("details"), dict) else {}
            address_error = (
                details.get("address_id") == "not_found"
                or any(str(key).startswith("address_") for key in details.keys())
            )
            if result.get("code") == "VALIDATION_ERROR" and address_error:
                retry_draft = dict(draft or {})
                for key in ["address_id", "address_full", "door_note", "address_confirmed", "use_default_address"]:
                    retry_draft.pop(key, None)
                retry_missing = _create_missing_fields(retry_draft)
                if "address" not in retry_missing:
                    retry_missing = ["address"] + retry_missing
                retry_action = {
                    "id": pending_action.get("id") or _pending_action_id(),
                    "type": "CREATE_ORDER",
                    "status": "COLLECTING",
                    "draft": retry_draft,
                    "missing_fields": retry_missing,
                    "last_asked": "address",
                    "slot_trace": list(pending_action.get("slot_trace") or []),
                    "updated_at": timezone.now().isoformat(),
                    "action_plan": _build_action_plan(
                        "CREATE_ORDER",
                        slots=retry_draft,
                        missing_slots=retry_missing,
                        confirm_required=False,
                        user_visible_summary="服务地址失效，请重新确认地址",
                    ),
                }
                return _respond(
                    run,
                    "刚刚这笔订单没有通过地址校验，可能是默认地址已失效。请确认是否继续使用当前默认地址，或直接发新的服务地址。",
                    IntentEnum.CREATE_ORDER,
                    pending_action=retry_action,
                )
            return _respond(
                run,
                f"下单失败：{result.get('code') or result.get('error')}。您可以继续补充信息后重试。",
                IntentEnum.CREATE_ORDER,
                cleared_action_id=pending_action.get("id"),
            )
        contact_name = (draft.get("contact_name") or "").strip()
        if not contact_name or any(ch.isdigit() for ch in contact_name):
            contact_name = "用户"
        eta_range = _format_eta_range(result)
        eta_start_text = _format_eta_text(result.get("eta_start"))
        lead_text = _format_lead_time_text(result.get("eta_start"))
        service_text = "为您配送"
        if result.get("service_type") not in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}:
            service_text = "为您上门服务"
        when_text = f"{lead_text}开始" if lead_text else f"{eta_start_text}开始"
        return _respond(
            run,
            (
                f"尊敬的{contact_name}，您的订单已生成（{result.get('order_no')}）。"
                "当前订单状态为待支付，请在30分钟内完成支付以锁定服务。"
                f"我们将于{when_text}{service_text}，预计时段为 {eta_range}。"
                "如需补充备注，请尽量在预计开始前30分钟告诉我，我会帮您追加。"
                "您可以随时让我查询订单进度，祝您生活愉快。"
            ),
            IntentEnum.CREATE_ORDER,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "CART_ADD":
        result = execute_tool(
            run,
            "portal_cart_add",
            {"portal_user_id": portal_user_id, "items": (pending_action.get("payload") or {}).get("items") or []},
        )
        if result.get("error"):
            return _respond(
                run,
                f"加购失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"已加入购物车。当前共 {result.get('selected_count') or 0} 件，合计 ¥{result.get('total_amount') or '0.00'}。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "CART_REMOVE":
        result = execute_tool(
            run,
            "portal_cart_remove",
            {"portal_user_id": portal_user_id, "items": (pending_action.get("payload") or {}).get("items") or []},
        )
        if result.get("error"):
            return _respond(
                run,
                f"移除失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"已更新购物车。当前共 {result.get('selected_count') or 0} 件，合计 ¥{result.get('total_amount') or '0.00'}。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "CART_CLEAR":
        result = execute_tool(run, "portal_cart_clear", {"portal_user_id": portal_user_id})
        if result.get("error"):
            return _respond(
                run,
                f"清空失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            "购物车已清空。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "CART_CHECKOUT":
        result = execute_tool(
            run,
            "portal_cart_checkout",
            {"portal_user_id": portal_user_id, "payload": pending_action.get("payload") or {}},
        )
        if result.get("error"):
            code = result.get("code") or result.get("error")
            if code == "ADDRESS_REQUIRED":
                return _respond(
                    run,
                    "购物车已准备好，但您还没有可用地址。请先在个人中心新增地址，我再帮您结算。",
                    IntentEnum.UNKNOWN,
                    cleared_action_id=pending_action.get("id"),
                )
            if code == "CART_EMPTY":
                return _respond(
                    run,
                    "购物车是空的，先告诉我您要加哪些配件吧。",
                    IntentEnum.UNKNOWN,
                    cleared_action_id=pending_action.get("id"),
                )
            return _respond(
                run,
                f"结算失败：{code}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        eta_range = _format_eta_range(result)
        return _respond(
            run,
            f"购物车已下单并支付成功，订单号 {result.get('order_no')}，预计服务时段 {eta_range}。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "CANCEL_ORDER":
        result = execute_tool(run, "portal_cancel_order", {"portal_user_id": portal_user_id, **(pending_action.get("payload") or {})})
        if result.get("error"):
            return _respond(run, f"取消失败：{result.get('code') or result.get('error')}。", IntentEnum.QUERY_ORDER, cleared_action_id=pending_action.get("id"))
        return _respond(run, f"订单 {result.get('order_no')} 已取消。", IntentEnum.QUERY_ORDER, cleared_action_id=pending_action.get("id"))

    if action_type == "PAY_ORDER":
        result = execute_tool(run, "portal_pay_order", {"portal_user_id": portal_user_id, **(pending_action.get('payload') or {})})
        if result.get("error"):
            return _respond(run, f"支付失败：{result.get('code') or result.get('error')}。", IntentEnum.QUERY_ORDER, cleared_action_id=pending_action.get("id"))
        return _respond(run, f"订单 {result.get('order_no')} 支付成功。", IntentEnum.QUERY_ORDER, cleared_action_id=pending_action.get("id"))

    if action_type == "MODIFY_ADDRESS":
        result = execute_tool(
            run,
            "portal_modify_order_address",
            {"portal_user_id": portal_user_id, **(pending_action.get("payload") or {})},
        )
        if result.get("error"):
            code = result.get("code") or result.get("error")
            if code == "ORDER_NOT_EDITABLE":
                deadline_text = _format_eta_text(result.get("address_edit_deadline") or result.get("cancel_deadline"))
                if deadline_text:
                    return _respond(
                        run,
                        f"改址失败：订单已超过可修改时间（截止 {deadline_text}）。",
                        IntentEnum.MODIFY_ORDER,
                        cleared_action_id=pending_action.get("id"),
                    )
            return _respond(
                run,
                f"改址失败：{code}。",
                IntentEnum.MODIFY_ORDER,
                cleared_action_id=pending_action.get("id"),
            )
        address_snapshot = result.get("address_snapshot") if isinstance(result.get("address_snapshot"), dict) else {}
        contact_snapshot = result.get("contact_snapshot") if isinstance(result.get("contact_snapshot"), dict) else {}
        address_text = (address_snapshot.get("address_full") or "").strip()
        contact_name = (contact_snapshot.get("contact_name") or "").strip()
        contact_phone = (contact_snapshot.get("contact_phone") or "").strip()
        detail_bits = []
        if address_text:
            detail_bits.append(f"新地址：{address_text}")
        if contact_name or contact_phone:
            detail_bits.append(f"联系人：{contact_name or '未提供'} {contact_phone}".strip())
        detail_text = f"（{'；'.join(detail_bits)}）" if detail_bits else ""
        return _respond(
            run,
            f"订单 {result.get('order_no')} 地址已更新{detail_text}。",
            IntentEnum.MODIFY_ORDER,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "CREATE_FEEDBACK":
        result = execute_tool(run, "portal_create_feedback", {"portal_user_id": portal_user_id, "payload": pending_action.get("payload") or {}})
        if result.get("error"):
            return _respond(run, f"提交失败：{result.get('code') or result.get('error')}。", IntentEnum.CREATE_TICKET, cleared_action_id=pending_action.get("id"))
        type_label = "投诉" if result.get("feedback_type") == "COMPLAINT" else "建议"
        return _respond(run, f"已提交{type_label}，编号 {result.get('id')}。", IntentEnum.CREATE_TICKET, cleared_action_id=pending_action.get("id"))

    if action_type == "UPDATE_PROFILE":
        result = execute_tool(
            run,
            "portal_update_profile",
            {"portal_user_id": portal_user_id, "payload": pending_action.get("payload") or {}},
        )
        if result.get("error"):
            return _respond(
                run,
                f"修改失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"好的，您的姓名已更新为“{result.get('display_name')}”。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "CREATE_ADDRESS":
        result = execute_tool(
            run,
            "portal_create_address",
            {"portal_user_id": portal_user_id, "payload": pending_action.get("payload") or {}},
        )
        if result.get("error"):
            return _respond(
                run,
                f"新增地址失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"地址已新增，地址ID {result.get('id')}。我已经同步到账户地址簿，您在个人中心刷新后即可看到。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "SET_DEFAULT_ADDRESS":
        payload = pending_action.get("payload") or {}
        result = execute_tool(
            run,
            "portal_set_default_address",
            {"portal_user_id": portal_user_id, "address_id": payload.get("address_id")},
        )
        if result.get("error"):
            return _respond(
                run,
                f"设置默认地址失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"已将地址ID {result.get('id')} 设为默认地址。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "UPDATE_ADDRESS":
        payload = pending_action.get("payload") or {}
        result = execute_tool(
            run,
            "portal_update_address",
            {
                "portal_user_id": portal_user_id,
                "address_id": payload.get("address_id"),
                "payload": payload.get("payload") or {},
            },
        )
        if result.get("error"):
            return _respond(
                run,
                f"地址修改失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"地址已更新：{result.get('address_full')}。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "DELETE_ADDRESS":
        payload = pending_action.get("payload") or {}
        result = execute_tool(
            run,
            "portal_delete_address",
            {
                "portal_user_id": portal_user_id,
                "address_id": payload.get("address_id"),
            },
        )
        if result.get("error"):
            return _respond(
                run,
                f"删除地址失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"地址已删除（ID {result.get('deleted_id')}）。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "CHANGE_PASSWORD":
        payload = pending_action.get("payload") or {}
        secure_action_id = payload.get("secure_action_id") or pending_action.get("id")
        secure_payload = _load_secure_action_payload(secure_action_id)
        result = execute_tool(
            run,
            "portal_change_password",
            {
                "portal_user_id": portal_user_id,
                "payload": {
                    "old_password": secure_payload.get("old_password"),
                    "new_password": secure_payload.get("new_password"),
                    "confirm_password": secure_payload.get("confirm_password"),
                },
            },
        )
        _clear_secure_action_payload(secure_action_id)
        if result.get("error"):
            return _respond(
                run,
                f"修改密码失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            "登录密码已修改成功。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "NOTIFICATION_READ":
        payload = pending_action.get("payload") or {}
        result = execute_tool(
            run,
            "portal_read_notification",
            {
                "portal_user_id": portal_user_id,
                "notification_id": payload.get("notification_id"),
            },
        )
        if result.get("error"):
            return _respond(
                run,
                f"标记已读失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"已将通知 {result.get('id')} 标记为已读。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "NOTIFICATION_READ_ALL":
        result = execute_tool(
            run,
            "portal_read_all_notifications",
            {
                "portal_user_id": portal_user_id,
            },
        )
        if result.get("error"):
            return _respond(
                run,
                f"批量已读失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"已全部标记为已读，共处理 {result.get('updated_count') or 0} 条消息。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    if action_type == "REQUEST_REFUND":
        payload = pending_action.get("payload") or {}
        result = execute_tool(
            run,
            "portal_request_refund",
            {
                "portal_user_id": portal_user_id,
                "order_id": payload.get("order_id"),
                "order_no": payload.get("order_no"),
                "reason": payload.get("reason"),
            },
        )
        if result.get("error"):
            return _respond(
                run,
                f"退款申请提交失败：{result.get('code') or result.get('error')}。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )
        return _respond(
            run,
            f"退款申请已提交，单号 {result.get('id')}，对应订单 {result.get('order_no')}。",
            IntentEnum.UNKNOWN,
            cleared_action_id=pending_action.get("id"),
        )

    return _respond(run, "当前待执行操作不支持。", IntentEnum.UNKNOWN)


def _prepare_confirm_action(run, action_type, summary_text, payload, intent):
    action = {
        "id": _pending_action_id(),
        "type": action_type,
        "status": "AWAIT_CONFIRM",
        "payload": payload,
        "updated_at": timezone.now().isoformat(),
        "action_plan": _build_action_plan(
            action_type,
            slots=payload,
            missing_slots=[],
            confirm_required=True,
            user_visible_summary=summary_text,
        ),
    }
    return _respond(
        run,
        f"{summary_text}\n\n确认的话回复“确认”，不执行回复“取消”。",
        intent,
        confirm_required=True,
        pending_action=action,
    )


def _build_query_order_reply(result):
    eta_start = str(result.get("eta_start", "")).replace("T", " ")[:16]
    worker = result.get("assigned_worker") if isinstance(result.get("assigned_worker"), dict) else {}
    worker_text = ""
    if worker.get("name") or worker.get("phone"):
        worker_text = f"负责人员：{worker.get('name') or '-'} {worker.get('phone') or '-'}。\n"
    return (
        f"订单 {result.get('order_no')} 当前状态：{result.get('status_label')}。\n"
        f"预计服务时间：{eta_start or '系统排期中'}。\n"
        f"{worker_text}"
        "如需继续操作（支付/取消/改址），直接告诉我。"
    )


def _build_order_fee_reply(result):
    order_no = result.get("order_no") or "-"
    currency = result.get("currency") or "CNY"
    symbol = "¥" if currency == "CNY" else f"{currency} "
    subtotal = result.get("amount_subtotal", 0)
    urgent_fee = result.get("amount_urgent_fee", 0)
    total = result.get("amount_total", 0)
    return (
        f"订单 {order_no} 费用明细：\n"
        f"1) 小计：{symbol}{subtotal}\n"
        f"2) 加急费：{symbol}{urgent_fee}\n"
        f"3) 总计：{symbol}{total}"
    )


def _build_price_fallback_reply():
    c5 = DELIVERY_PRICES.get("5kg")
    c15 = DELIVERY_PRICES.get("15kg")
    c45 = DELIVERY_PRICES.get("45kg")
    return (
        "我先按当前平台参考价给您：\n\n"
        f"1. 5kg：¥{c5}\n"
        f"2. 15kg：¥{c15}\n"
        f"3. 45kg：¥{c45}\n\n"
        "如果您告诉我规格和数量，我可以立刻帮您算出这单总价。"
    )


def _basic_safety_general_reply():
    return (
        "日常用气安全可以先记住这 5 点：\n"
        "1. 用气时保持通风，不要长时间紧闭门窗。\n"
        "2. 人离开厨房前先关灶具，再关阀门。\n"
        "3. 软管、阀门、报警器定期检查，老化及时更换。\n"
        "4. 厨房不要堆放易燃物，灶具周边保持清洁。\n"
        "5. 一旦闻到异味，先关阀开窗、撤离到安全处，再联系专业人员。\n"
        "如果您愿意，我可以再按“家用/餐饮门店”给您更具体的安全清单。"
    )


def _safety_escalation_notice():
    return f"以上为通用应急指导，您的具体情况可能更复杂，建议立即撤离到安全区域并拨打我公司24小时应急电话：{EMERGENCY_HOTLINE}。"


def _is_high_risk_safety_query(text):
    value = (text or "").strip()
    if not value:
        return False
    if _is_safety_emergency_query(value):
        return True
    high_risk_keywords = ["漏气", "泄漏", "异味", "报警", "爆炸", "起火", "刺鼻", "头晕", "中毒", "昏迷"]
    return _has_any(value, high_risk_keywords) and _has_any(value, ["怎么办", "怎么处理", "如何处理", "紧急", "马上", "立刻", "先做什么"])


def _append_safety_escalation_notice(text, reply):
    base = str(reply or "").strip()
    if not base:
        return base
    if _safety_escalation_notice() in base:
        return base
    if not _is_high_risk_safety_query(text):
        return base
    return f"{base}\n\n{_safety_escalation_notice()}"


def _safety_emergency_reply():
    return (
        "**先做这四步应急处理：**\n"
        "1. 立即关闭燃气阀门。\n"
        "2. 打开门窗通风，不要开关任何电器。\n"
        "3. 人员先撤到安全区域。\n"
        "4. 在室外拨打我司 24 小时应急电话：400-888-0000。\n\n"
        "**重要提醒：** 严禁用明火检查漏气。\n"
        "您处理完应急后回复“继续”，我再帮您安排后续服务。\n\n"
        f"{_safety_escalation_notice()}\n"
        f"{SAFETY_CARE_CLOSING}"
    )


def _safety_leak_check_reply(text=""):
    if _looks_like_alarm_device_risk_query(text):
        return (
            "**先不要自行拆卸报警器。**\n\n"
            "1. 先确认现场是否有燃气异味；若有异味，请立即关阀、开窗并撤到室外。\n"
            "2. 报警器故障或误报时，建议由专业人员上门排查后再处理，不建议私自拆除或长期断电。\n"
            f"3. 您可以直接让我为您安排{COMPANY_NAME}上门安检/检修。\n\n"
            f"{SAFETY_CARE_CLOSING}"
        )
    return (
        "接好钢瓶后，可以用下面的方法检查是否漏气：\n\n"
        "**标准操作：肥皂水试漏法**\n"
        "1. 先准备肥皂水（洗洁精/肥皂 + 清水）。\n"
        "2. 均匀涂抹在角阀接口、减压阀连接处、软管两端接口。\n"
        "3. 观察 30-60 秒：若持续起泡，基本可判断该处漏气；不冒泡通常表示连接正常。\n\n"
        "**辅助判断：**\n"
        "1. 若闻到明显燃气味，按疑似漏气处理。\n"
        "2. 若报警器持续响，也按漏气处理。\n\n"
        "**安全提醒：**\n"
        "1. 严禁用打火机、火柴等明火检漏。\n"
        f"2. 若确认漏气，请立即关阀、开窗通风、撤到室外，并拨打我司 24 小时应急电话：{EMERGENCY_HOTLINE}。\n"
        f"如果您愿意，我现在就可以帮您安排{COMPANY_NAME}上门安检。\n\n"
        f"{SAFETY_CARE_CLOSING}"
    )


def _capability_help_reply():
    return (
        "可以的，我会按最少必要信息一步步问您，不会让您一次填很多项。\n"
        "我现在能直接处理：下单、查订单、支付、取消、改址、投诉建议、修改昵称、改密码、地址增改删和购物车加减结算。\n"
        "下单时我会默认带出您的常用联系人和默认地址，您只要说需要改哪一项就行。"
    )


def _theme_switch_reply(theme_code):
    if theme_code == "eye":
        return "已为您切换到护眼模式。页面会更柔和，长时间阅读更舒服。"
    if theme_code == "dark":
        return "已为您切换到黑夜模式。夜间查看会更舒适。"
    return "已为您切换到白天模式。"


def _phone_rule_reply():
    return (
        "会拦截的。手机号需要是中国大陆 11 位手机号（1开头），像“123”这种会被判定为无效。\n"
        "如果是测试账号，只有登录手机号允许使用 123。"
    )


def _accessory_help_reply():
    return (
        "配件这边是“加购物车后统一下单”，不走单品直购。\n"
        "您可以直接说“软管2件加入购物车”“删掉报警器”或“帮我结算购物车”，我会先确认再执行。"
    )


def _order_guide_reply():
    return (
        "可以自助下单，按这 3 步就行：\n"
        "1) 选服务类型（瓶装配送/换瓶/安装/安检/报修/配件）；\n"
        "2) 填地址、联系人、时间和是否加急；\n"
        "3) 确认订单并支付。\n"
        "如果您愿意，我也可以现在直接代您完成下单。"
    )


def _build_invoice_help_reply(has_order_ref=False):
    if has_order_ref:
        return (
            "**已收到，我来帮您跟进这笔订单的开票。**\n\n"
            "请补充以下信息：\n"
            "1. 开票抬头\n"
            "2. 税号\n"
            "3. 接收方式（电子邮箱或纸票邮寄地址）\n\n"
            "您发我后，我会立即为您提交。"
        )
    return (
        "**企业开票流程**\n\n"
        "1. 下单时勾选“需要开票”。\n"
        "2. 填写开票信息：抬头、税号、接收邮箱（纸票需邮寄地址）。\n"
        "3. 正常会在 1-3 个工作日内开具。\n"
        "4. 历史订单补开，请提供订单号。\n\n"
        "如果您愿意，我现在就可以帮您登记开票信息。"
    )


def _resume_hint_for_action(pending_action):
    if not isinstance(pending_action, dict):
        return ""
    action_type = str(pending_action.get("type") or "").upper()
    hints = {
        "BATCH_ACTION": "如需继续刚才配件+检修组合办理，回复“继续办理”即可。",
        "CREATE_ORDER": "如需继续刚才下单，回复“继续下单”即可。",
        "CREATE_FEEDBACK": "如需继续刚才投诉/建议流程，回复“继续投诉”即可。",
        "CREATE_ADDRESS": "如需继续刚才新增地址，回复“继续新增地址”即可。",
        "CHANGE_PASSWORD": "如需继续刚才改密码，回复“继续改密码”即可。",
    }
    return hints.get(action_type, "")


def _append_resume_order_hint(message, pending_action=None):
    text = str(message or "").strip()
    hint = _resume_hint_for_action(pending_action)
    if not hint:
        return text
    if not text:
        return hint
    if hint in text:
        return text
    return f"{text}\n\n{hint}"


def _resume_pending_output(output, pending_action):
    if not isinstance(output, AgentOutput) or not isinstance(pending_action, dict):
        return output
    output.final_response = _append_resume_order_hint(output.final_response, pending_action)
    output.pending_action = pending_action
    if pending_action.get("status") in {"AWAIT_CONFIRM", "PARTIAL_DONE"}:
        output.confirm_required = True
    return output


def _is_order_pick_message(text):
    order_id, order_no = _extract_order_ref(text)
    return bool(_extract_choice_index(text) or order_id or order_no)


def _build_inspection_policy_reply():
    return (
        "液化石油气钢瓶通常按 4 年周期进行定期检验。\n"
        "我可以根据您的气瓶购置时间，帮您算出具体的建议年检日期。"
    )


def _build_inspection_candidates_pick_reply(items):
    lines = ["我查到您有多笔气瓶相关订单，请先选一笔用于计算年检时间："]
    for index, item in enumerate(items[:5], start=1):
        order_no = item.get("order_no") or "-"
        cylinder = item.get("cylinder_type") or "气瓶"
        order_date = item.get("order_date") or "-"
        lines.append(f"{index}. {order_no} | {cylinder} | 下单日期 {order_date}")
    lines.append("请回复“第1个”，或直接发送订单号。")
    return "\n".join(lines)


def _resolve_inspection_candidate(text, candidates):
    if not isinstance(candidates, list):
        candidates = []
    idx = _extract_choice_index(text)
    if idx and 1 <= idx <= len(candidates):
        return candidates[idx - 1]
    order_id, order_no = _extract_order_ref(text)
    if order_id:
        for item in candidates:
            if int(item.get("order_id") or 0) == int(order_id):
                return item
        return {"order_id": order_id}
    if order_no:
        for item in candidates:
            if str(item.get("order_no") or "").upper() == str(order_no).upper():
                return item
        return {"order_no": order_no}
    return None


def _build_inspection_due_calc_reply(result):
    status = result.get("status") or "NORMAL"
    status_line = "当前状态：在建议年检周期内。"
    if status == "DUE_SOON":
        status_line = "当前状态：临近年检，建议尽快预约。"
    if status == "OVERDUE":
        status_line = "当前状态：已超过建议年检时间，请尽快安排检验。"
    source_map = {
        "CYLINDER_PURCHASE_DATE": "钢瓶购置时间",
        "ORDER_PURCHASE_DATE": "下单时间（按购置时间口径估算）",
        "ORDER_SERVICE_DATE": "服务完成时间（按购置时间口径估算）",
    }
    base_source = source_map.get(str(result.get("base_source") or ""), "购置时间")
    due_date = str(result.get("next_inspection_date") or "")
    return (
        f"我已为您算好这只气瓶的年检时间（订单：{result.get('order_no')}）。\n\n"
        "**计算结果**\n"
        f"1. 气瓶规格：{result.get('cylinder_type')}\n"
        f"2. 购置基准时间：{result.get('base_date')}（{base_source}）\n"
        f"3. 建议年检完成日期：{due_date}\n\n"
        f"请您尽量在 **{due_date}** 前完成年检。\n"
        f"{status_line}\n"
        "如需的话，我可以继续帮您直接预约安检。"
    )


def _build_inspection_due_all_reply(result):
    items = result.get("items") if isinstance(result.get("items"), list) else []
    if not items:
        return "我这边还没查到您的气瓶配送/换瓶订单记录。您可以先下单，之后我会自动帮您计算年检时间。"
    source_map = {
        "CYLINDER_PURCHASE_DATE": "购置时间",
        "ORDER_PURCHASE_DATE": "下单时间估算",
        "ORDER_SERVICE_DATE": "服务时间估算",
    }
    lines = [
        "我帮您整理了全部气瓶的年检时间（按到期先后排序）：",
        "",
        "**年检清单**",
    ]
    for idx, item in enumerate(items, start=1):
        status = str(item.get("status") or "NORMAL")
        if status == "OVERDUE":
            status_text = "已逾期"
        elif status == "DUE_SOON":
            status_text = "即将到期"
        else:
            status_text = "周期内"
        lines.append(
            f"{idx}. 订单 {item.get('order_no')}（{item.get('cylinder_type')}）"
            f"\n   基准日期：{item.get('base_date')}（{source_map.get(str(item.get('base_source') or ''), '购置时间')}）"
            f"\n   下次年检：{item.get('next_inspection_date')}（{status_text}）"
        )
    overdue = int(result.get("overdue_count") or 0)
    due_soon = int(result.get("due_soon_count") or 0)
    lines.extend(
        [
            "",
            f"汇总：共 {result.get('total') or 0} 只气瓶，逾期 {overdue} 只，即将到期 {due_soon} 只。",
            "建议您尽量在到期日前完成年检；需要的话我可以直接帮您预约安检。",
        ]
    )
    return "\n".join(lines)


def _handle_inspection_collecting(run, text, portal_user_id, pending_action):
    picks = pending_action.get("candidates") if isinstance(pending_action.get("candidates"), list) else []
    selected = _resolve_inspection_candidate(text, picks)
    if not selected:
        return _respond(
            run,
            "我还没识别到您选择的是哪一单，请回复“第1个”或直接发订单号。",
            IntentEnum.QUERY_ORDER,
            pending_action=pending_action,
            lane="rag",
        )
    result = execute_tool(
        run,
        "portal_calc_inspection_due",
        {
            "portal_user_id": portal_user_id,
            "order_id": selected.get("order_id"),
            "order_no": selected.get("order_no"),
        },
    )
    if result.get("error"):
        return _respond(
            run,
            "这笔订单暂时无法计算年检时间，您可以换一笔订单，或直接把订单号再发我一次。",
            IntentEnum.QUERY_ORDER,
            pending_action=pending_action,
            lane="rag",
        )
    return _respond(
        run,
        _build_inspection_due_calc_reply(result),
        IntentEnum.QUERY_ORDER,
        cleared_action_id=pending_action.get("id"),
        lane="rag",
    )


def _handle_inspection_query(run, text, portal_user_id):
    if _looks_like_inspection_policy_question(text):
        return _respond(run, _build_inspection_policy_reply(), IntentEnum.QUERY_ORDER, lane="rag")
    result = execute_tool(
        run,
        "portal_calc_all_inspection_due",
        {"portal_user_id": portal_user_id},
    )
    if result.get("error"):
        return _respond(
            run,
            "暂时没能算出年检时间，您稍后再试，我也可以先帮您预约安检。",
            IntentEnum.QUERY_ORDER,
            lane="rag",
        )
    return _respond(run, _build_inspection_due_all_reply(result), IntentEnum.QUERY_ORDER, lane="rag")


def _format_order_brief_line(index, item):
    eta = _format_eta_text(item.get("eta_start")) or "待排期"
    return (
        f"{index}. {item.get('order_no')} | {item.get('service_type_label')} | "
        f"{item.get('status_label')} | 预计 {eta}"
    )


def _build_list_orders_reply(result):
    items = result.get("items") or []
    if not items:
        return "没有找到符合条件的订单。"
    lines = ["给您查到这些订单："]
    for index, item in enumerate(items, start=1):
        lines.append(_format_order_brief_line(index, item))
    lines.append("要看某一单详情，直接把订单号发我。")
    return "\n".join(lines)


def _build_order_detail_snapshot_reply(result):
    order_no = result.get("order_no") or "-"
    status_label = result.get("status_label") or "-"
    eta_range = _format_eta_range(result)
    address_snapshot = result.get("address_snapshot") or {}
    contact_snapshot = result.get("contact_snapshot") or {}
    worker = result.get("assigned_worker") if isinstance(result.get("assigned_worker"), dict) else {}
    worker_line = ""
    if worker.get("name") or worker.get("phone"):
        worker_line = f"上门人员：{worker.get('name') or '-'} {worker.get('phone') or '-'}\n"
    return (
        f"订单 {order_no} 当前为“{status_label}”。\n"
        f"服务时间：{eta_range}\n"
        f"{worker_line}"
        f"地址快照：{address_snapshot.get('address_full') or '无'}\n"
        f"联系人快照：{contact_snapshot.get('contact_name') or '-'} {contact_snapshot.get('contact_phone') or '-'}\n"
        "如需改址或取消，我可以继续帮您处理。"
    )


def _build_profile_reply(context):
    profile = (context or {}).get("profile") or {}
    display_name = profile.get("display_name") or "未设置"
    phone = profile.get("phone") or "-"
    return f"您当前资料：姓名/昵称“{display_name}”，手机号 {phone}。如需修改，直接告诉我要改成什么。"


def _build_address_overview_reply(context, include_meta=False):
    addresses = (context or {}).get("addresses") or []
    addresses_limit = int((context or {}).get("addresses_limit") or 10)
    addresses_truncated = bool((context or {}).get("addresses_truncated"))
    render_mode = "default_only"
    if not addresses:
        message = "您当前还没有地址。可直接说：新增地址 张三 13800138000 上海市浦东新区xx路xx号。"
        if include_meta:
            return message, {"render_mode": "empty", "count": 0, "truncated": False}
        return message
    lines = [f"我帮您查到 {len(addresses)} 条地址（当前最多展示最近 {addresses_limit} 条）："]
    for idx, item in enumerate(addresses, start=1):
        default_tag = "（默认）" if item.get("is_default") else ""
        address_full = item.get("address_full") or "-"
        door_note = item.get("door_note") or ""
        contact = f"{item.get('contact_name') or '-'} {item.get('contact_phone') or '-'}".strip()
        detail = f"{address_full} {door_note}".strip()
        lines.append(f"{idx}. 地址ID {item.get('id')} {default_tag}")
        lines.append(f"   地址：{detail}")
        lines.append(f"   联系人：{contact}")
    if addresses_truncated or len(addresses) >= addresses_limit:
        lines.append(f"当前最多展示最近 {addresses_limit} 条地址，更多请到地址管理页查看。")
        render_mode = "list_top_n_truncated"
    else:
        render_mode = "list_top_n"
    lines.append("如需切换默认地址，告诉我“把地址ID 12 设为默认地址”即可。")
    message = "\n".join(lines)
    if include_meta:
        return message, {"render_mode": render_mode, "count": len(addresses), "truncated": bool(addresses_truncated)}
    return message


def _handle_query_intent(run, text, portal_user_id, intent):
    intent_code = str(intent or "").upper()
    entity = _query_entity_from_intent(intent_code)
    _set_lane("action")
    _clear_clarify_state()
    _clear_topic_followup_state()
    _set_routing_extra(
        query_first_applied=True,
        clarify_needed=False,
        clarify_topic=None,
        clarify_round=0,
    )
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={
            "event": "portal_query_executed",
            "intent": intent_code,
            "entity": entity,
        },
    )
    if intent_code == "ADDRESS_QUERY":
        context = execute_tool(run, "portal_get_context", {"portal_user_id": portal_user_id})
        reply, meta = _build_address_overview_reply(context, include_meta=True)
        if _wants_address_and_order_query(text):
            order_result = execute_tool(
                run,
                "portal_list_orders",
                {"portal_user_id": portal_user_id, "page": 1, "page_size": 5},
            )
            order_items = order_result.get("items") or []
            if order_items:
                order_reply = _build_list_orders_reply(order_result)
            else:
                order_reply = "我再帮您看了最近订单：目前还没有查到订单记录。"
            reply = f"{reply}\n\n另外，我再给您看下最近订单：\n{order_reply}"
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_query_render_mode",
                "intent": intent_code,
                "render_mode": meta.get("render_mode"),
                "count": meta.get("count"),
                "truncated": meta.get("truncated"),
            },
        )
        return _respond(run, reply, IntentEnum.UNKNOWN, lane="action")
    if intent_code == "PROFILE_QUERY":
        context = execute_tool(run, "portal_get_context", {"portal_user_id": portal_user_id})
        return _respond(run, _build_profile_reply(context), IntentEnum.UNKNOWN, lane="action")
    if intent_code == "NOTIFICATION_QUERY":
        only_unread = _has_any(text, ["未读", "没读"])
        result = execute_tool(
            run,
            "portal_list_notifications",
            {"portal_user_id": portal_user_id, "page": 1, "page_size": 5, "only_unread": only_unread},
        )
        if result.get("error"):
            return _respond(run, "暂时没查到通知列表，您可以稍后再试。", IntentEnum.UNKNOWN, lane="action")
        items = result.get("items") or []
        if not items:
            return _respond(run, "当前没有通知消息。", IntentEnum.UNKNOWN, lane="action")
        lines = [f"我帮您查到 {result.get('unread_count') or 0} 条未读消息："]
        for idx, item in enumerate(items[:5], start=1):
            read_tag = "已读" if item.get("is_read") else "未读"
            lines.append(f"{idx}. 通知ID {item.get('id')}（{read_tag}）：{item.get('title')}")
        lines.append("您可以回复“把通知ID 123 标记已读”或“全部已读”。")
        return _respond(run, "\n".join(lines), IntentEnum.UNKNOWN, lane="action")
    return None


def _build_inspection_due_reply(portal_user_id):
    try:
        from customer_portal.constants import SERVICE_TYPE_CYLINDER_EXCHANGE, SERVICE_TYPE_LPG_CYLINDER_DELIVERY
        from customer_portal.models import Order as PortalOrder
    except Exception:
        return None

    orders = (
        PortalOrder.objects.filter(
            user_id=portal_user_id,
            service_type__in=[SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE],
        )
        .order_by("-created_at")[:12]
    )
    records = []
    for order in orders:
        payload = order.service_payload if isinstance(order.service_payload, dict) else {}
        next_inspection = (
            payload.get("next_inspection_date")
            or payload.get("inspection_due_date")
            or payload.get("next_check_date")
        )
        if not next_inspection:
            continue
        records.append(
            {
                "order_no": order.order_no,
                "cylinder_type": payload.get("cylinder_type") or "气瓶",
                "next_inspection_date": str(next_inspection),
            }
        )
        if len(records) >= 3:
            break

    if not records:
        return None

    lines = ["我帮您查了最近的气瓶记录，年检时间如下："]
    for idx, item in enumerate(records, start=1):
        lines.append(f"{idx}. {item['cylinder_type']}：建议在 {item['next_inspection_date']} 前完成年检")
    lines.append("如果您愿意，我可以现在直接帮您预约安检上门。")
    return "\n".join(lines)


def _build_feedback_order_pick_reply(run, portal_user_id):
    result = execute_tool(
        run,
        "portal_list_orders",
        {"portal_user_id": portal_user_id, "page": 1, "page_size": 5},
    )
    items = result.get("items") or []
    if not items:
        return "您当前没有可关联的历史订单。投诉需要关联具体订单，您可以先提供订单号或先查询订单。", []
    lines = ["为了准确处理投诉，请先选择要投诉的订单："]
    picks = []
    for idx, item in enumerate(items, start=1):
        order_no = item.get("order_no")
        service_label = item.get("service_type_label")
        status_label = item.get("status_label")
        lines.append(
            f"{idx}. {order_no} | {service_label} | {status_label}"
        )
        picks.append(
            {
                "order_id": item.get("id"),
                "order_no": order_no,
                "label": f"{order_no} | {service_label} | {status_label}",
            }
        )
    lines.append("请回复“第1个”或直接发订单号。")
    return "\n".join(lines), picks


def _build_feedback_list_reply(result):
    items = result.get("items") or []
    if not items:
        return "我这边暂时还没有查到您的反馈记录。您需要的话，我可以现在帮您提交一条建议或投诉。"

    status_map = {
        "NEW": "待处理",
        "PROCESSING": "处理中",
        "CLOSED": "已处理",
    }
    type_map = {
        "COMPLAINT": "投诉",
        "SUGGESTION": "建议",
    }
    target_map = {
        "ORDER_SERVICE": "订单服务",
        "ONLINE_SERVICE": "线上服务",
    }

    lines = ["我帮您查到最近反馈进度："]
    for idx, item in enumerate(items[:5], start=1):
        created_at = _format_eta_text(item.get("created_at"))
        status_text = status_map.get(item.get("status"), item.get("status") or "-")
        type_text = type_map.get(item.get("feedback_type"), item.get("feedback_type") or "-")
        target_text = target_map.get(item.get("target_type"), item.get("target_type") or "-")
        order_no = item.get("order_no") or "-"
        lines.append(
            f"{idx}. 反馈#{item.get('id')} | {type_text}/{target_text} | {status_text} | {created_at or '-'} | 关联订单：{order_no}"
        )
    lines.append("如果您希望我继续跟进某一条，直接告诉我反馈编号即可。")
    return "\n".join(lines)


def _build_feedback_collecting_action(feedback_type, content, picks, contact_phone="", require_order=True):
    action = {
        "id": _pending_action_id(),
        "type": "CREATE_FEEDBACK",
        "status": "COLLECTING",
        "feedback_type": feedback_type,
        "content": content,
        "picks": picks,
        "updated_at": timezone.now().isoformat(),
        "ui_hint": "ORDER_PICK_LIST",
        "action_plan": _build_action_plan(
            "CREATE_FEEDBACK",
            slots={"feedback_type": feedback_type, "content": content},
            missing_slots=["order_id"] if require_order else [],
            confirm_required=False,
            user_visible_summary=("先选择关联订单后再提交反馈" if require_order else "补充反馈后提交"),
        ),
    }
    if contact_phone:
        action["contact_phone"] = contact_phone
    return action


def _handle_feedback_collecting(run, text, portal_user_id, pending_action):
    picks = pending_action.get("picks") if isinstance(pending_action.get("picks"), list) else []
    feedback_type = pending_action.get("feedback_type") or "COMPLAINT"
    content = pending_action.get("content") or text
    phone = _extract_phone(text) or pending_action.get("contact_phone")
    order_id, order_no = _extract_order_ref(text)

    if not order_id and not order_no:
        index = _extract_choice_index(text)
        if index and 0 < index <= len(picks):
            selected = picks[index - 1] or {}
            try:
                order_id = int(selected.get("order_id"))
            except (TypeError, ValueError):
                order_id = None
            order_no = selected.get("order_no")

    if not order_id and order_no:
        resolved = execute_tool(
            run,
            "portal_get_order",
            {"portal_user_id": portal_user_id, "order_no": order_no},
        )
        if not resolved.get("error"):
            try:
                order_id = int(resolved.get("id"))
            except (TypeError, ValueError):
                order_id = None

    if not order_id:
        return _respond(
            run,
            "还没识别到您选择的订单，请点击列表项或回复“第1个/订单号”。",
            IntentEnum.CREATE_TICKET,
            pending_action=pending_action,
        )

    payload = {
        "feedback_type": feedback_type,
        "target_type": "ORDER_SERVICE",
        "title": "用户反馈",
        "content": content,
        "order_id": order_id,
    }
    if phone:
        payload["contact_phone"] = phone

    summary = f"将提交一条{'投诉' if feedback_type == 'COMPLAINT' else '建议'}反馈（关联订单 {order_no or order_id}）。"
    return _prepare_confirm_action(run, "CREATE_FEEDBACK", summary, payload, IntentEnum.CREATE_TICKET)


def _fallback_guidance_reply(text):
    value = (text or "").strip()
    safety_kind = _safety_kind_from_text(value)
    if safety_kind != "none":
        reply = _safety_typed_fallback_reply(value, safety_kind)
        if safety_kind == "emergency":
            return _append_safety_escalation_notice(value, reply)
        return reply
    if _looks_like_query_order(value) or _extract_order_ref(value)[0] or _extract_order_ref(value)[1]:
        return "可以，我马上帮您查订单。您直接发订单号，或说“查最近订单”就行。"
    if _is_cart_context(value):
        return "可以，我能直接帮您操作购物车。您可以说“软管2件加入购物车”“删掉减压阀”“结算购物车”。"
    if _extract_service_type(value) or any(k in value for k in ["下单", "订气", "叫气", "来气"]):
        return "没问题，我可以直接帮您下单。您先说服务类型或规格数量，我会一步步确认后再提交。"
    if any(k in value for k in ["地址", "个人资料", "昵称", "用户名"]):
        return "我可以帮您处理账户和地址。您可以说“看我的资料”“新增地址”或“把地址ID 12 设为默认”。"
    if any(k in value for k in ["投诉", "建议"]):
        return "可以，我能帮您提交投诉或建议。您把情况和诉求告诉我，我先整理给您确认。"
    if _has_any(value, ["地址", "收货地址", "默认地址"]):
        return "您这边是要我帮您“查地址列表”，还是“新增/修改地址”？直接回我其中一个方向，我马上处理。"
    if _has_any(value, ["订单", "这单", "那单"]):
        return "您是要“查询订单状态”，还是“对订单执行操作（支付/取消/改址）”？我按您的方向直接办。"
    if _is_safety_overview_request(value):
        return _basic_safety_general_reply()
    return (
        "我可能还没完全理解您的目标。您是想让我：\n"
        "1. 查询信息（订单/地址/资料）\n"
        "2. 直接办理（下单/改址/支付等）\n"
        "3. 咨询用气安全建议\n"
        "您回我一个方向，我马上接着处理。"
    )


def _format_eta_text(value):
    text = str(value or "")
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = timezone.localtime(dt)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return text.replace("T", " ")[:16]


def _format_eta_range(result):
    start_text = _format_eta_text(result.get("eta_start"))
    end_text = _format_eta_text(result.get("eta_end"))
    if start_text and end_text:
        return f"{start_text} - {end_text}"
    return start_text or end_text or "系统排期中"


def _is_price_bullet(text):
    value = str(text or "").strip().lower()
    if not value:
        return False
    if any(token in value for token in ["¥", "元", "单价", "报价", "收费", "价格", "价目", "总价"]):
        return True
    return bool(re.search(r"\d+(?:\.\d+)?\s*(?:元|块|rmb|cny)", value))


def _infer_kb_topic(text, domain=""):
    value = str(text or "")
    if _looks_like_price_query(value):
        return "price"
    if _has_any(value, INVOICE_KEYWORDS):
        return "invoice"
    if _looks_like_inspection_query(value):
        return "inspection"
    if _looks_like_safety_leak_check_query(value):
        return "safety_leak"
    if domain == "safety":
        return "safety_general"
    if domain == "biz":
        return "policy"
    return "none"


def _low_hit_clarify_reply(text, domain="", topic=""):
    current_topic = topic or _infer_kb_topic(text, domain=domain)
    if current_topic == "price":
        return _build_price_fallback_reply()
    if current_topic == "invoice":
        order_id, order_no = _extract_order_ref(text)
        return _build_invoice_help_reply(has_order_ref=bool(order_id or order_no))
    if current_topic == "inspection":
        return "我可以按您的历史订单计算具体年检日期。您回复“查年检”，我会先列出可选订单让您确认。"
    if current_topic == "safety_leak":
        return _append_safety_escalation_notice(text, _safety_leak_check_reply(text))
    if domain == "safety":
        safety_kind = _safety_kind_from_text(text)
        if safety_kind == "none":
            safety_kind = "general_qa"
        return _safety_typed_fallback_reply(text, safety_kind)
    return "我先帮您把这件事说清楚。您可以再补一句具体场景，我会直接给可执行结论。"


def _is_fact_kb_query(text):
    value = _normalize_user_text(text)
    if not value:
        return False
    if _looks_like_price_query(value) or _looks_like_inspection_query(value):
        return True
    if _has_any(value, INVOICE_KEYWORDS):
        return True
    return False


def _should_direct_llm_answer(text, router_plan=None):
    value = _normalize_user_text(text)
    if not value:
        return False
    safety_kind = _safety_kind_from_text(value)
    if safety_kind == "emergency":
        return False
    if _query_intent_override(value) or _looks_like_query_order(value):
        return False
    if _is_fact_kb_query(value):
        return False
    intent_hint = _intent_from_text(value)
    if _is_write_intent(intent_hint):
        return False
    if intent_hint in QUERY_INTENT_CODES or intent_hint in {"QUERY_ORDER", "PRICE_QUERY", "INVOICE_HELP", "CYLINDER_INSPECTION_QUERY"}:
        return False
    if isinstance(router_plan, dict):
        lane = str(router_plan.get("lane") or "").lower()
        if lane == "action":
            return False
        if bool(router_plan.get("needs_kb")):
            topic = str(router_plan.get("kb_topic") or "none").lower()
            domain = str(router_plan.get("kb_domain") or "none").lower()
            if topic in {"price", "invoice", "inspection", "safety_leak"}:
                return False
            if domain == "safety" and safety_kind == "emergency":
                return False
    return True


def _should_use_ambiguity_clarify(text, stage0_signal=None):
    value = _normalize_user_text(text)
    if not value:
        return False
    if _has_any(value, ["还没想好", "还是想问这个", "还是这个问题", "先这样"]):
        return False
    if _is_user_dissatisfied(value):
        return False
    if "?" in value or "？" in value:
        return False
    if _has_any(value, ["燃气", "煤气", "液化气", "设施", "责任", "赔偿", "谁负责", "谁承担"]):
        return False
    if len(value) <= 4:
        return True
    if not _has_any(
        value,
        [
            "我有个问题",
            "我想问个事",
            "想问一下",
            "咨询一下",
            "帮我看看",
            "看下这个",
            "这个怎么弄",
            "怎么处理这个",
        ],
    ):
        return False
    if isinstance(stage0_signal, dict):
        try:
            confidence = float(stage0_signal.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        return confidence < 0.45 and bool(stage0_signal.get("clarify_needed"))
    return True


def _answer_price_query(run, text):
    rag_cfg = _rag_settings()
    _set_rag_topic("price")
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={"event": "portal_rag_topic_selected", "topic": "price"},
    )
    routed_query = text
    rewritten_query = (
        _rewrite_kb_query(run, text, "biz", seed_query=routed_query)
        if rag_cfg.get("enable_rewrite")
        else routed_query
    )
    kb_hits = _collect_kb_hits(
        run,
        "biz",
        rewritten_query,
        top_k=rag_cfg.get("top_k", KB_TOP_K),
        min_score=rag_cfg.get("min_score", KB_MIN_SCORE),
        max_bullets=rag_cfg.get("max_bullets", KB_MAX_BULLETS),
    )
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={
            "route": "portal_price_query",
            "query": rewritten_query,
            "accepted_count": kb_hits.get("accepted_count"),
            "best_score": kb_hits.get("best_score"),
            "avg_score": kb_hits.get("avg_score"),
            "error": kb_hits.get("error"),
            "rag_cfg": rag_cfg,
        },
    )
    _set_routing_extra(
        retrieval_quality={
            "accepted_count": kb_hits.get("accepted_count"),
            "best_score": kb_hits.get("best_score"),
            "avg_score": kb_hits.get("avg_score"),
        }
    )
    bullets = kb_hits.get("bullets") or []
    price_bullets = [item for item in bullets if _is_price_bullet(item)]
    if kb_hits.get("accepted_count", 0) >= rag_cfg.get("min_hits", KB_MIN_ACCEPTED_HITS) and price_bullets:
        llm_reply = _llm_compose_kb_reply(run, text, price_bullets, kb_meta=kb_hits)
        if llm_reply:
            return _respond(run, llm_reply, IntentEnum.UNKNOWN, lane="rag")
        lines = ["我查到以下价格信息供您参考："]
        for idx, bullet in enumerate(price_bullets[:4], start=1):
            lines.append(f"{idx}. {bullet}")
        lines.append("如果您告诉我规格和数量，我可以马上帮您算这单总价。")
        return _respond(run, "\n".join(lines), IntentEnum.UNKNOWN, lane="rag")

    return _respond(run, _build_price_fallback_reply(), IntentEnum.UNKNOWN, lane="rag")


def _answer_non_actionable_query(run, text, router_plan=None):
    rag_cfg = _rag_settings()
    stage0_signal = router_plan if isinstance(router_plan, dict) else PORTAL_STAGE0_CTX.get()
    safety_kind = _safety_kind_from_text(text)
    _set_routing_extra(safety_kind=safety_kind if safety_kind in {"emergency", "leak_assess", "general_qa"} else "none")
    direct_reply = _direct_chat_reply(text)
    if direct_reply:
        _clear_clarify_state()
        _set_routing_extra(clarify_needed=False, clarify_topic=None, clarify_round=0, llm_fallback=False)
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={"route": "portal_non_actionable_direct"},
        )
        return _respond(run, direct_reply, IntentEnum.UNKNOWN, lane="smalltalk")

    followup_state = _get_topic_followup_state()
    if followup_state and followup_state.get("topic") == "safety_general" and followup_state.get("expected_slot") == "scene":
        scene_slot = _extract_safety_scene_slot(text)
        if scene_slot:
            _clear_topic_followup_state()
            _clear_clarify_state()
            _set_routing_extra(clarify_needed=False, clarify_topic=None, clarify_round=0)
            _set_rag_topic("safety_general")
            scene_prompt = (
                f"用户补充了场景：{scene_slot}。"
                "请直接给这个场景的燃气安全可执行建议，避免再次反问“查询还是办理”。"
            )
            llm_scene_reply = _llm_general_reply(run, scene_prompt, stage0_signal=stage0_signal)
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={
                    "event": "portal_topic_followup_scene",
                    "topic": "safety_general",
                    "scene": scene_slot,
                    "llm_hit": bool(llm_scene_reply),
                },
            )
            if llm_scene_reply:
                _set_routing_extra(safety_kind="general_qa", answer_source="llm_direct", llm_fallback=False)
                return _respond(run, llm_scene_reply, IntentEnum.SAFETY_GUIDE, lane="smalltalk")
            _set_routing_extra(safety_kind="general_qa", answer_source="typed_fallback", llm_fallback=True)
            return _respond(run, _safety_scene_fallback_reply(scene_slot), IntentEnum.SAFETY_GUIDE, lane="smalltalk")
        _clear_topic_followup_state()

    if _is_ambiguous_request(text) and _should_use_ambiguity_clarify(text, stage0_signal):
        clarify_topic = _clarify_topic_from_text(text)
        state = _get_clarify_state() or {}
        previous_round = int(state.get("round") or 0) if state.get("topic") == clarify_topic else 0
        next_round = previous_round + 1
        if next_round > 2:
            _clear_clarify_state()
            _set_routing_extra(clarify_needed=False, clarify_topic=None, clarify_round=0)
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={
                    "event": "portal_ambiguity_clarify",
                    "topic": clarify_topic,
                    "round": 3,
                    "action": "fallback",
                    "text": text,
                },
            )
            return _respond(run, _ambiguity_fallback_reply(clarify_topic), IntentEnum.UNKNOWN, lane="smalltalk")
        _set_clarify_state(clarify_topic, next_round, text)
        _set_routing_extra(clarify_needed=True, clarify_topic=clarify_topic, clarify_round=next_round)
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_ambiguity_clarify",
                "topic": clarify_topic,
                "round": next_round,
                "action": "ask",
                "text": text,
            },
        )
        return _respond(run, _ambiguity_clarify_reply(clarify_topic, round_no=next_round), IntentEnum.UNKNOWN, lane="smalltalk")
    _clear_clarify_state()
    _set_routing_extra(clarify_needed=False, clarify_topic=None, clarify_round=0)

    if safety_kind == "emergency":
        _clear_topic_followup_state()
        _set_rag_topic("safety_leak")
        _set_routing_extra(answer_source="emergency_template", llm_fallback=False)
        return _respond(
            run,
            _append_safety_escalation_notice(text, _safety_emergency_reply()),
            IntentEnum.SAFETY_GUIDE,
            lane="safety",
        )

    if safety_kind in {"leak_assess", "general_qa"}:
        if _should_set_safety_scene_followup(text, safety_kind):
            _set_topic_followup_state("safety_general", "scene")
        else:
            _clear_topic_followup_state()
        _set_rag_topic("safety_leak" if safety_kind == "leak_assess" else "safety_general")
        llm_safety_direct = _llm_general_reply(run, text, stage0_signal=stage0_signal)
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_non_actionable_llm_direct",
                "llm_hit": bool(llm_safety_direct),
                "source": "safety_direct",
                "safety_kind": safety_kind,
            },
        )
        if llm_safety_direct:
            _set_routing_extra(answer_source="llm_direct", llm_fallback=False)
            return _respond(run, llm_safety_direct, IntentEnum.SAFETY_GUIDE, lane="smalltalk")
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_safety_llm_miss_fallback",
                "safety_kind": safety_kind,
                "fallback_mode": "typed_short",
                "reason": "empty_or_exception",
            },
        )
        _set_routing_extra(answer_source="typed_fallback", llm_fallback=True)
        return _respond(run, _safety_typed_fallback_reply(text, safety_kind), IntentEnum.SAFETY_GUIDE, lane="smalltalk")

    if _should_direct_llm_answer(text, router_plan=stage0_signal):
        llm_general_direct = _llm_general_reply(run, text, stage0_signal=stage0_signal)
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_non_actionable_llm_direct",
                "llm_hit": bool(llm_general_direct),
                "source": "stage0_direct",
                "safety_kind": safety_kind,
            },
        )
        if llm_general_direct:
            _set_routing_extra(answer_source="llm_direct", llm_fallback=False)
            return _respond(run, llm_general_direct, IntentEnum.UNKNOWN, lane="smalltalk")
        if safety_kind in {"leak_assess", "general_qa"}:
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={
                    "event": "portal_safety_llm_miss_fallback",
                    "safety_kind": safety_kind,
                    "fallback_mode": "typed_short",
                    "reason": "empty_or_exception",
                },
            )
            _set_routing_extra(answer_source="typed_fallback", llm_fallback=True)
            return _respond(run, _safety_typed_fallback_reply(text, safety_kind), IntentEnum.SAFETY_GUIDE, lane="smalltalk")
        return _respond(run, _fallback_guidance_reply(text), IntentEnum.UNKNOWN, lane="smalltalk")

    kb_plan = None
    if isinstance(stage0_signal, dict) and "needs_kb" in stage0_signal:
        kb_plan = {
            "need_kb": bool(stage0_signal.get("needs_kb")),
            "domain": str(stage0_signal.get("kb_domain") or "none"),
            "topic": str(stage0_signal.get("kb_topic") or "none"),
            "query": str(stage0_signal.get("kb_query") or text),
        }
    kb_plan = kb_plan or _llm_decide_kb_route(run, text) or _heuristic_kb_route(text)
    heuristic_plan = _heuristic_kb_route(text)
    if not kb_plan:
        kb_plan = {"need_kb": False, "domain": "none", "topic": "none", "query": text}
    # 中文注释：仅保留轻纠偏，避免因模型偶发误判导致明显跑偏。
    if heuristic_plan.get("need_kb") and not kb_plan.get("need_kb"):
        if _has_any(text, ["漏气", "异味", "燃气报警", "煤气报警", "价格", "发票", "年检", "检验"]):
            kb_plan = heuristic_plan
    if kb_plan.get("need_kb") and kb_plan.get("domain") == "safety":
        strict_topic = _safety_topic_from_text(text)
        if strict_topic in {"safety_leak", "safety_general"}:
            kb_plan["topic"] = strict_topic
    if not kb_plan.get("topic"):
        kb_plan["topic"] = _infer_kb_topic(text, domain=kb_plan.get("domain"))
    _set_rag_topic(kb_plan.get("topic"))
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={"event": "portal_rag_topic_selected", "topic": kb_plan.get("topic")},
    )
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={"route": "portal_non_actionable_route", "kb_plan": kb_plan},
    )

    if kb_plan.get("need_kb"):
        domain = kb_plan.get("domain")
        topic = kb_plan.get("topic") or _infer_kb_topic(text, domain=domain)
        routed_query = kb_plan.get("query") or text
        rewritten_query = (
            _rewrite_kb_query(run, text, domain, seed_query=routed_query)
            if rag_cfg.get("enable_rewrite")
            else routed_query
        )
        kb_hits = _collect_kb_hits(
            run,
            domain,
            rewritten_query,
            top_k=rag_cfg.get("top_k", KB_TOP_K),
            min_score=rag_cfg.get("min_score", KB_MIN_SCORE),
            max_bullets=rag_cfg.get("max_bullets", KB_MAX_BULLETS),
        )
        retrieval_meta = {
            "accepted_count": kb_hits.get("accepted_count"),
            "best_score": kb_hits.get("best_score"),
            "avg_score": kb_hits.get("avg_score"),
        }
        _set_routing_extra(retrieval_quality=retrieval_meta)
        _set_rag_topic(topic)
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "route": "portal_non_actionable_retrieval",
                "domain": domain,
                "topic": topic,
                "query": rewritten_query,
                "accepted_count": kb_hits.get("accepted_count"),
                "best_score": kb_hits.get("best_score"),
                "avg_score": kb_hits.get("avg_score"),
                "error": kb_hits.get("error"),
                "rag_cfg": rag_cfg,
            },
        )
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={"event": "portal_rag_topic_selected", "topic": topic},
        )
        bullets = kb_hits.get("bullets") or []
        candidate_bullets = bullets
        if topic == "price":
            candidate_bullets = [item for item in bullets if _is_price_bullet(item)]
        if kb_hits.get("accepted_count", 0) >= rag_cfg.get("min_hits", KB_MIN_ACCEPTED_HITS) and candidate_bullets:
            llm_reply = _llm_compose_kb_reply(run, text, candidate_bullets, kb_meta=kb_hits)
            if llm_reply:
                return _respond(run, llm_reply, IntentEnum.UNKNOWN, lane="rag")
            lines = ["我查到以下信息供您参考："]
            for idx, bullet in enumerate(candidate_bullets[:4], start=1):
                lines.append(f"{idx}. {bullet}")
            lines.append("如果您愿意，我可以继续直接帮您办理相关业务。")
            return _respond(run, "\n".join(lines), IntentEnum.UNKNOWN, lane="rag")
        # 弱命中场景：强事实问题继续证据优先，其它问题允许 LLM 自由回答（通用建议口径）。
        if topic in {"price", "invoice", "inspection"}:
            clarify = _low_hit_clarify_reply(text, domain=domain, topic=topic)
            lane = "safety" if domain == "safety" else "rag"
            intent = IntentEnum.SAFETY_GUIDE if lane == "safety" else IntentEnum.UNKNOWN
            return _respond(run, clarify, intent, lane=lane)
        if domain == "safety":
            if topic == "safety_leak" or _is_high_risk_safety_query(text) or _is_safety_emergency_query(text):
                clarify = _low_hit_clarify_reply(text, domain=domain, topic=topic)
                _set_routing_extra(answer_source="rag", llm_fallback=False, safety_kind="emergency")
                return _respond(run, clarify, IntentEnum.SAFETY_GUIDE, lane="safety")
            llm_safety = _llm_general_reply(run, text, stage0_signal=stage0_signal)
            if llm_safety:
                _append_event(
                    run,
                    AgentEvent.STATE_PLANNING,
                    output_json={"event": "portal_rag_fallback_to_llm", "topic": topic, "domain": domain},
                )
                _set_routing_extra(answer_source="llm_direct", llm_fallback=False, safety_kind="general_qa")
                return _respond(run, llm_safety, IntentEnum.SAFETY_GUIDE, lane="smalltalk")
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={"event": "portal_rag_fallback_to_llm", "topic": topic, "domain": domain},
            )
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={
                    "event": "portal_safety_llm_miss_fallback",
                    "safety_kind": "general_qa",
                    "fallback_mode": "typed_short",
                    "reason": "empty_or_exception",
                },
            )
            _set_routing_extra(answer_source="typed_fallback", llm_fallback=True, safety_kind="general_qa")
            return _respond(run, _safety_typed_fallback_reply(text, "general_qa"), IntentEnum.SAFETY_GUIDE, lane="smalltalk")
        llm_general_low_hit = _llm_general_reply(run, text, stage0_signal=stage0_signal)
        if llm_general_low_hit:
            message = str(llm_general_low_hit).strip()
            if "通用建议" not in message:
                message = (
                    f"{message}\n\n"
                    "以上先按通用建议给您判断；如果您愿意，我可以再结合您的订单与场景给出更具体的处理方案。"
                )
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={"event": "portal_rag_fallback_to_llm", "topic": topic, "domain": domain},
            )
            return _respond(run, message, IntentEnum.UNKNOWN, lane="smalltalk")
        clarify = _low_hit_clarify_reply(text, domain=domain, topic=topic)
        return _respond(run, clarify, IntentEnum.UNKNOWN, lane="smalltalk")

    llm_general = _llm_general_reply(run, text, stage0_signal=stage0_signal)
    if llm_general:
        return _respond(run, llm_general, IntentEnum.UNKNOWN, lane="smalltalk")

    return _respond(run, _fallback_guidance_reply(text), IntentEnum.UNKNOWN, lane="smalltalk")


def _answer_side_query_while_order_pending(run, text, portal_user_id, intent):
    if intent in {"ADDRESS_QUERY", "PROFILE_QUERY", "NOTIFICATION_QUERY"}:
        query_output = _handle_query_intent(run, text, portal_user_id, intent)
        if query_output is not None:
            return query_output
    if intent == "QUERY_ORDER":
        result = execute_tool(
            run,
            "portal_list_orders",
            {"portal_user_id": portal_user_id, "page": 1, "page_size": 5},
        )
        if not (result.get("items") or []):
            return _respond(run, "目前还没有查到订单记录。", IntentEnum.QUERY_ORDER, lane="action")
        return _respond(run, _build_list_orders_reply(result), IntentEnum.QUERY_ORDER, lane="action")
    if intent == "ORDER_GUIDE":
        return _respond(run, _order_guide_reply(), IntentEnum.UNKNOWN, lane="smalltalk")
    if intent == "PRICE_QUERY":
        return _answer_price_query(run, text)
    if intent == "SAFETY_LEAK_CHECK":
        _set_rag_topic("safety_leak")
        _set_routing_extra(safety_kind="leak_assess", answer_source="typed_fallback", llm_fallback=True)
        return _respond(run, _append_safety_escalation_notice(text, _safety_leak_check_reply(text)), IntentEnum.SAFETY_GUIDE, lane="safety")
    if intent == "SAFETY_EMERGENCY":
        _set_rag_topic("safety_leak")
        _set_routing_extra(safety_kind="emergency", answer_source="emergency_template", llm_fallback=False)
        return _respond(run, _append_safety_escalation_notice(text, _safety_emergency_reply()), IntentEnum.SAFETY_GUIDE, lane="safety")
    if intent == "INVOICE_HELP":
        _set_rag_topic("invoice")
        order_id, order_no = _extract_order_ref(text)
        return _respond(
            run,
            _build_invoice_help_reply(has_order_ref=bool(order_id or order_no)),
            IntentEnum.UNKNOWN,
            lane="rag",
        )
    if intent == "CAPABILITY_HELP":
        return _respond(run, _capability_help_reply(), IntentEnum.UNKNOWN, lane="smalltalk")
    if intent == "THEME_SET_EYE":
        _set_routing_extra(ui_theme="eye")
        return _respond(run, _theme_switch_reply("eye"), IntentEnum.UNKNOWN, lane="smalltalk")
    if intent == "THEME_SET_DARK":
        _set_routing_extra(ui_theme="dark")
        return _respond(run, _theme_switch_reply("dark"), IntentEnum.UNKNOWN, lane="smalltalk")
    if intent == "THEME_SET_LIGHT":
        _set_routing_extra(ui_theme="light")
        return _respond(run, _theme_switch_reply("light"), IntentEnum.UNKNOWN, lane="smalltalk")
    if intent == "CYLINDER_INSPECTION_QUERY":
        _set_rag_topic("inspection")
        return _handle_inspection_query(run, text, portal_user_id)
    return _answer_non_actionable_query(run, text)

def run_portal_orchestrator(
    run,
    message,
    portal_user_id,
    llm=None,
    tone_style="warm",
    rag_config=None,
    memory=None,
    route_mode="v2",
    write_allowed=True,
    degraded_reason=None,
    model_source="none",
):
    PORTAL_LLM_CTX.set(llm)
    PORTAL_TONE_CTX.set(tone_style or "warm")
    PORTAL_RAG_CTX.set(rag_config or {})
    PORTAL_MEMORY_CTX.set(memory or {})
    PORTAL_USER_CTX.set(portal_user_id)
    PORTAL_ROUTE_MODE_CTX.set(route_mode or "v2")
    PORTAL_MODEL_SOURCE_CTX.set(model_source or "none")
    PORTAL_WRITE_ALLOWED_CTX.set(bool(write_allowed))
    PORTAL_DEGRADED_REASON_CTX.set(degraded_reason or None)
    PORTAL_STAGE0_CTX.set(None)
    _set_lane("smalltalk")
    _clear_routing_extra()
    _set_routing_extra(
        batch=False,
        hotline_suppressed=False,
        manual_handoff=False,
        default_order_selected=False,
        query_first_applied=False,
        clarify_needed=False,
        clarify_round=0,
        rag_topic_selected="none",
        safety_kind="none",
        answer_source="none",
        llm_fallback=False,
    )
    raw_text = (message or "").strip()
    text = _normalize_user_text(raw_text)
    PORTAL_INPUT_CTX.set(raw_text)
    pending_action = _latest_pending_action(run)
    context_stale = _is_run_context_stale(run)
    if context_stale:
        if isinstance(pending_action, dict) and pending_action.get("type") == "CHANGE_PASSWORD":
            _clear_secure_action_payload(pending_action.get("id"))
        pending_action = None
        _set_routing_extra(context_reset=True)
    forbidden = _detect_forbidden_ops(text)
    if forbidden:
        return _respond(
            run,
            _build_forbidden_reply(text, forbidden),
            IntentEnum.UNKNOWN,
            lane="policy_guard",
        )
    if _is_forbidden_unsafe_instruction_query(text):
        return _respond(
            run,
            _unsafe_instruction_block_reply(),
            IntentEnum.SAFETY_GUIDE,
            lane="policy_guard",
        )
    queue_state = _get_manual_queue_state()
    if queue_state and _is_manual_queue_cancel_request(text):
        _cancel_manual_queue(run)
        return _respond(
            run,
            "已为您取消人工排队。您可以继续直接告诉我需求，我先帮您处理。",
            IntentEnum.UNKNOWN,
            lane="smalltalk",
        )
    if _is_manual_contact_request(text):
        if queue_state:
            queue_state = _advance_manual_queue(run, queue_state)
        else:
            queue_state = _start_manual_queue(run)
        _set_manual_queue_routing_extra(queue_state)
        return _respond(run, _build_manual_queue_reply(queue_state), IntentEnum.UNKNOWN, lane="smalltalk")
    if queue_state:
        queue_state = _advance_manual_queue(run, queue_state)
        _set_manual_queue_routing_extra(queue_state)
    else:
        _set_manual_queue_routing_extra(None)
    if _needs_manual_handoff(text):
        return _respond(
            run,
            _manual_handoff_reply(),
            IntentEnum.UNKNOWN,
            lane="policy_guard",
        )
    llm_route = _llm_route_turn(run, text, pending_action=pending_action)
    if isinstance(llm_route, dict):
        _set_routing_extra(
            llm_router={
                "lane": llm_route.get("lane"),
                "confidence": llm_route.get("confidence"),
                "why": llm_route.get("why"),
                "needs_kb": llm_route.get("needs_kb"),
            }
        )
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={"route": "portal_llm_router", "router": llm_route},
        )

    heuristic_intent = _intent_from_text(text, pending_action=pending_action)
    current_intent = heuristic_intent
    task_signal = _compute_task_entity_signal(text, pending_action=pending_action)
    if isinstance(task_signal, dict):
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={"event": "portal_task_entity_signal", "signal": task_signal},
        )
    signal_strength = str((task_signal or {}).get("strength") or "").upper()
    signal_intent = str((task_signal or {}).get("intent") or "").upper()
    query_strong_intent = None
    if signal_strength == "SAFETY_HIGH_RISK" and signal_intent:
        current_intent = signal_intent
    if signal_strength == "QUERY_STRONG" and signal_intent in QUERY_INTENT_CODES:
        query_strong_intent = signal_intent
    if not query_strong_intent:
        fallback_query_intent = _query_intent_override(text)
        if fallback_query_intent:
            query_strong_intent = fallback_query_intent
    if query_strong_intent:
        current_intent = query_strong_intent
        _set_routing_extra(query_first_applied=True)
        _append_event(
            run,
            AgentEvent.STATE_PLANNING,
            output_json={
                "event": "portal_query_intent_selected",
                "intent": query_strong_intent,
                "source": "signal" if signal_strength == "QUERY_STRONG" else "override",
            },
        )
    else:
        _set_routing_extra(query_first_applied=False)

    if isinstance(llm_route, dict) and not query_strong_intent:
        llm_intent = str(llm_route.get("intent") or "UNKNOWN").upper()
        try:
            llm_confidence = float(llm_route.get("confidence"))
        except Exception:
            llm_confidence = 0.0
        if (
            llm_intent != "UNKNOWN"
            and llm_confidence >= LLM_ROUTE_HIGH_CONF
            and _allow_llm_intent_override(text, llm_intent)
        ):
            current_intent = llm_intent
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={
                    "route": "portal_llm_router_override",
                    "intent": llm_intent,
                    "confidence": llm_confidence,
                    "why": llm_route.get("why") or "",
                },
            )
        elif llm_confidence < LLM_ROUTE_LOW_CONF:
            corrected = _apply_low_confidence_corrector(text, heuristic_intent)
            current_intent = corrected
            if corrected != heuristic_intent:
                _append_event(
                    run,
                    AgentEvent.STATE_PLANNING,
                    output_json={
                        "route": "portal_heuristic_corrector",
                        "from": heuristic_intent,
                        "to": corrected,
                        "llm_confidence": llm_confidence,
                    },
                )
        elif heuristic_intent == "UNKNOWN" and llm_intent != "UNKNOWN" and _allow_llm_intent_override(text, llm_intent):
            current_intent = llm_intent
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={
                    "route": "portal_llm_router_fill_unknown",
                    "intent": llm_intent,
                    "confidence": llm_confidence,
                },
            )
    if current_intent in QUERY_INTENT_CODES or _is_write_intent(current_intent):
        _clear_clarify_state()
        _clear_topic_followup_state()
        _set_routing_extra(clarify_needed=False, clarify_topic=None, clarify_round=0)

    batch_seed = None
    if not pending_action:
        batch_seed = _detect_batch_action_request(text)
        if isinstance(batch_seed, dict):
            current_intent = "BATCH_ACTION"
            _set_routing_extra(batch=True)
            _append_event(
                run,
                AgentEvent.STATE_PLANNING,
                output_json={
                    "event": "portal_batch_action_detected",
                    "service_type": batch_seed.get("service_type"),
                    "service_candidates": batch_seed.get("service_candidates") or [],
                    "cart_items": batch_seed.get("cart_items") or [],
                },
            )

    stage0_signal = _build_stage0_signal(
        text,
        pending_action=pending_action,
        llm_route=llm_route,
        task_signal=task_signal,
        heuristic_intent=heuristic_intent,
        current_intent=current_intent,
    )
    PORTAL_STAGE0_CTX.set(stage0_signal)
    _set_routing_extra(stage0=_compact_stage0_for_routing(stage0_signal))
    _append_event(
        run,
        AgentEvent.STATE_PLANNING,
        output_json={"event": "portal_stage0_signal", "stage0": stage0_signal},
    )

    if context_stale and (_is_confirm_message(text) or _is_reject_message(text)):
        return _respond(
            run,
            "距离上次会话已超过30分钟，之前流程已自动结束。请直接告诉我您现在要办理的事项，我马上继续帮您。",
            IntentEnum.UNKNOWN,
            lane="smalltalk",
        )

    if not write_allowed:
        if _is_write_pending_action(pending_action):
            return _respond(
                run,
                _readonly_fallback_reply(),
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
                lane="fallback_readonly",
            )
        if _is_write_intent(current_intent):
            return _respond(
                run,
                _readonly_fallback_reply(),
                IntentEnum.UNKNOWN,
                lane="fallback_readonly",
            )

    if pending_action:
        if _is_write_pending_action(pending_action):
            _set_lane("action")
        if pending_action.get("type") == "CREATE_ADDRESS":
            if current_intent == "ADDRESS_CREATE" and _has_any(
                text,
                ["新增地址", "添加地址", "加地址", "新增收货地址", "添加收货地址", "新建地址", "重新新增地址"],
            ):
                # 中文注释：用户明确再次发起“新增地址”时，重置本轮收集，避免沿用旧槽位。
                return _handle_create_address(run, text, portal_user_id, None)
        if _is_reject_message(text):
            if pending_action.get("type") == "CHANGE_PASSWORD":
                _clear_secure_action_payload(pending_action.get("id"))
            return _respond(
                run,
                "已取消当前操作。您可以继续告诉我新的需求。",
                IntentEnum.UNKNOWN,
                cleared_action_id=pending_action.get("id"),
            )

        if pending_action.get("type") == "CREATE_ORDER" and _looks_like_invoice_preference_update(text):
            return _handle_create_order(run, text, portal_user_id, pending_action)

        if pending_action.get("type") == "BATCH_ACTION" and _looks_like_invoice_preference_update(text):
            return _handle_batch_action(run, text, portal_user_id, pending_action)

        if (
            pending_action.get("type") == "CREATE_ORDER"
            and current_intent in PENDING_ORDER_SIDE_QUERY_INTENTS
        ):
            side_output = _answer_side_query_while_order_pending(run, text, portal_user_id, current_intent)
            return _resume_pending_output(side_output, pending_action)

        if (
            pending_action.get("type") == "BATCH_ACTION"
            and current_intent in PENDING_ORDER_SIDE_QUERY_INTENTS
        ):
            side_output = _answer_side_query_while_order_pending(run, text, portal_user_id, current_intent)
            return _resume_pending_output(side_output, pending_action)

        if (
            pending_action.get("type") == "CREATE_FEEDBACK"
            and pending_action.get("status") == "COLLECTING"
            and current_intent in PENDING_FEEDBACK_SIDE_QUERY_INTENTS
            and not _is_order_pick_message(text)
        ):
            # 中文注释：投诉待选订单阶段允许先处理侧向咨询，避免“所有问题都被锁在选订单”。
            side_output = _answer_side_query_while_order_pending(run, text, portal_user_id, current_intent)
            return _resume_pending_output(side_output, pending_action)

        if pending_action.get("status") in {"AWAIT_CONFIRM", "PARTIAL_DONE"}:
            if _is_confirm_message(text):
                return _execute_pending_action(run, pending_action, portal_user_id)
            if pending_action.get("type") == "BATCH_ACTION":
                return _handle_batch_action(run, text, portal_user_id, pending_action)
            if pending_action.get("type") == "CREATE_ORDER":
                # 中文注释：允许用户在确认阶段继续修改字段
                return _handle_create_order(run, text, portal_user_id, pending_action)
            if pending_action.get("type") == "CREATE_ADDRESS":
                # 中文注释：允许用户在确认前继续补充或修改地址字段
                return _handle_create_address(run, text, portal_user_id, pending_action)
            if pending_action.get("type") == "CHANGE_PASSWORD":
                return _handle_change_password(run, text, portal_user_id, pending_action)
            return _respond(
                run,
                "这一步待您确认。回复“确认”我就执行；回复“取消”就不执行。",
                IntentEnum.UNKNOWN,
                confirm_required=True,
                pending_action=pending_action,
            )

        if pending_action.get("type") == "CREATE_FEEDBACK" and pending_action.get("status") == "COLLECTING":
            return _handle_feedback_collecting(run, text, portal_user_id, pending_action)

        if pending_action.get("type") == "CREATE_ADDRESS" and pending_action.get("status") == "COLLECTING":
            return _handle_create_address(run, text, portal_user_id, pending_action)

        if pending_action.get("type") == "CHANGE_PASSWORD" and pending_action.get("status") == "COLLECTING":
            return _handle_change_password(run, text, portal_user_id, pending_action)

        if pending_action.get("type") == "INSPECTION_QUERY" and pending_action.get("status") == "COLLECTING":
            return _handle_inspection_collecting(run, text, portal_user_id, pending_action)

        if pending_action.get("type") == "BATCH_ACTION":
            return _handle_batch_action(run, text, portal_user_id, pending_action)

        if pending_action.get("type") == "CREATE_ORDER":
            return _handle_create_order(run, text, portal_user_id, pending_action)

    intent = current_intent

    if intent == "BATCH_ACTION":
        _set_lane("action")
        return _handle_batch_action(run, text, portal_user_id, None, seed=batch_seed)

    if intent == "CREATE_ORDER":
        _set_lane("action")
        return _handle_create_order(run, text, portal_user_id, None)

    if intent == "ORDER_GUIDE":
        _set_lane("smalltalk")
        return _respond(run, _order_guide_reply(), IntentEnum.UNKNOWN)

    if intent in {"ADDRESS_QUERY", "PROFILE_QUERY", "NOTIFICATION_QUERY"}:
        query_output = _handle_query_intent(run, text, portal_user_id, intent)
        if query_output is not None:
            return query_output

    if intent == "QUERY_ORDER":
        _set_lane("action")
        status_filter = _extract_status_filter(text)
        page = _extract_page(text) or 1
        order_id, order_no = _extract_order_ref(text)
        if order_id or order_no:
            result = execute_tool(run, "portal_get_order", {"portal_user_id": portal_user_id, "order_id": order_id, "order_no": order_no})
            if result.get("error"):
                return _respond(run, "没找到这笔订单，请您核对一下订单号后再发我。", IntentEnum.QUERY_ORDER)
            if _has_any(text, ["快照", "地址快照", "联系人快照", "送达窗口", "预计送达", "谁接", "开始服务"]):
                return _respond(run, _build_order_detail_snapshot_reply(result), IntentEnum.QUERY_ORDER)
            return _respond(run, _build_query_order_reply(result), IntentEnum.QUERY_ORDER)

        if _has_any(text, ["这单", "那单", "昨天那单", "这笔单", "这笔订单", "预计送达", "送达窗口", "到哪一步"]):
            latest = execute_tool(run, "portal_list_orders", {"portal_user_id": portal_user_id, "page": 1, "page_size": 1})
            latest_items = latest.get("items") or []
            if latest_items:
                latest_id = latest_items[0].get("id")
                result = execute_tool(run, "portal_get_order", {"portal_user_id": portal_user_id, "order_id": latest_id})
                if not result.get("error"):
                    if _has_any(text, ["快照", "地址快照", "联系人快照", "送达窗口", "预计送达", "谁接", "开始服务"]):
                        return _respond(run, _build_order_detail_snapshot_reply(result), IntentEnum.QUERY_ORDER)
                    return _respond(run, _build_query_order_reply(result), IntentEnum.QUERY_ORDER)

        if "统计" in text and "状态" in text:
            status_pairs = [
                ("待支付", ORDER_STATUS_PENDING_PAYMENT),
                ("已支付", ORDER_STATUS_PAID),
                ("已预约", ORDER_STATUS_SCHEDULED),
                ("服务中", ORDER_STATUS_IN_SERVICE),
                ("已完成", ORDER_STATUS_COMPLETED),
                ("已取消", ORDER_STATUS_CANCELED),
                ("已过期", ORDER_STATUS_EXPIRED),
            ]
            lines = ["按状态统计如下："]
            for label, code in status_pairs:
                one = execute_tool(
                    run,
                    "portal_list_orders",
                    {"portal_user_id": portal_user_id, "status": code, "page": 1, "page_size": 1},
                )
                lines.append(f"- {label}：{one.get('total', 0)} 单")
            return _respond(run, "\n".join(lines), IntentEnum.QUERY_ORDER)

        if "没完成" in text:
            open_statuses = [ORDER_STATUS_PENDING_PAYMENT, ORDER_STATUS_PAID, ORDER_STATUS_SCHEDULED, ORDER_STATUS_IN_SERVICE]
            total_open = 0
            for code in open_statuses:
                one = execute_tool(
                    run,
                    "portal_list_orders",
                    {"portal_user_id": portal_user_id, "status": code, "page": 1, "page_size": 1},
                )
                total_open += int(one.get("total") or 0)
            return _respond(run, f"您当前还有 {total_open} 笔未完成订单。", IntentEnum.QUERY_ORDER)

        result = execute_tool(
            run,
            "portal_list_orders",
            {"portal_user_id": portal_user_id, "status": status_filter, "page": page, "page_size": 5},
        )
        items = result.get("items") or []
        if not items:
            if _has_any(text, ["快照", "地址快照", "联系人快照"]):
                return _respond(
                    run,
                    "目前还没有查到订单记录，所以暂时无法展示地址快照和联系人快照。要不要我先帮您创建一笔新订单？",
                    IntentEnum.QUERY_ORDER,
                )
            return _respond(run, "目前还没有查到订单记录。要不要我现在帮您下第一单？", IntentEnum.QUERY_ORDER)
        return _respond(run, _build_list_orders_reply(result), IntentEnum.QUERY_ORDER)

    if intent == "ORDER_FEE_DETAIL":
        _set_lane("action")
        if _is_cart_context(text):
            return _respond(
                run,
                "您问的是购物车金额。当前聊天侧还不能直接读取实时购物车总价，建议在商城页底部购物车查看；如果您愿意，我可以马上帮您把配件清单整理成可下单内容。",
                IntentEnum.UNKNOWN,
            )
        order_id, order_no = _extract_order_ref(text)
        used_latest_order = False
        if not order_id and not order_no:
            latest = execute_tool(run, "portal_list_orders", {"portal_user_id": portal_user_id, "page": 1, "page_size": 1})
            latest_items = latest.get("items") or []
            if not latest_items:
                return _respond(run, "您当前还没有可查询的订单。", IntentEnum.QUERY_ORDER)
            order_id = latest_items[0].get("id")
            order_no = latest_items[0].get("order_no")
            used_latest_order = True
        result = execute_tool(
            run,
            "portal_get_order",
            {"portal_user_id": portal_user_id, "order_id": order_id, "order_no": order_no},
        )
        if result.get("error"):
            return _respond(run, "没找到这笔订单，请您核对一下订单号后再发我。", IntentEnum.QUERY_ORDER)
        reply = _build_order_fee_reply(result)
        if used_latest_order:
            reply = f"我先按您最近一笔订单给您拆分：\n{reply}\n如果您想看其他订单，直接告诉我订单号即可。"
        return _respond(run, reply, IntentEnum.QUERY_ORDER)

    if intent == "CART_QUERY":
        _set_lane("action")
        result = execute_tool(run, "portal_get_cart", {"portal_user_id": portal_user_id})
        return _respond(run, _build_cart_summary_reply(result), IntentEnum.UNKNOWN)

    if intent == "CART_ADD":
        _set_lane("action")
        items = _extract_accessory_items(text)
        if not items:
            return _respond(
                run,
                "可以，我来帮您加购。请直接告诉我配件和数量，例如：软管2件、减压阀1件。",
                IntentEnum.UNKNOWN,
            )
        summary = f"将加入购物车：{_build_cart_items_line(items)}。"
        return _prepare_confirm_action(
            run,
            "CART_ADD",
            summary,
            {"items": items},
            IntentEnum.UNKNOWN,
        )

    if intent == "CART_REMOVE":
        _set_lane("action")
        items = _extract_accessory_items(text)
        if not items:
            return _respond(
                run,
                "请告诉我要移除哪个配件，例如：把软管删掉，或删掉报警器1个。",
                IntentEnum.UNKNOWN,
            )
        summary = f"将从购物车移除：{_build_cart_items_line(items)}。"
        return _prepare_confirm_action(
            run,
            "CART_REMOVE",
            summary,
            {"items": items},
            IntentEnum.UNKNOWN,
        )

    if intent == "CART_CLEAR":
        _set_lane("action")
        return _prepare_confirm_action(
            run,
            "CART_CLEAR",
            "将清空当前购物车。",
            {},
            IntentEnum.UNKNOWN,
        )

    if intent == "CART_CHECKOUT":
        _set_lane("action")
        cart_result = execute_tool(run, "portal_get_cart", {"portal_user_id": portal_user_id})
        if not (cart_result.get("items") or []):
            return _respond(run, "购物车还是空的，先告诉我要加哪些配件吧。", IntentEnum.UNKNOWN)

        context = execute_tool(run, "portal_get_context", {"portal_user_id": portal_user_id})
        default_address = (context or {}).get("default_address") or {}
        if not default_address.get("id"):
            return _respond(
                run,
                "您还没有默认地址，请先在个人中心新增地址，我再帮您一键结算。",
                IntentEnum.UNKNOWN,
            )

        eta_request = _extract_time_request(text)
        invoice_note = _extract_invoice_note(text)
        notes = "客服代结算购物车"
        if invoice_note:
            notes = _merge_notes(notes, invoice_note)

        payload = {
            "address_id": default_address.get("id"),
            "eta_date": eta_request.get("eta_date") if eta_request else "",
            "eta_slot": eta_request.get("eta_slot") if eta_request else "",
            "is_urgent": bool(_extract_urgent_flag(text)),
            "notes": notes,
            "need_invoice": bool(invoice_note),
        }
        summary = (
            f"将按默认地址为您结算并支付购物车（{_build_cart_items_line(cart_result.get('items') or [])}）。"
        )
        return _prepare_confirm_action(
            run,
            "CART_CHECKOUT",
            summary,
            payload,
            IntentEnum.UNKNOWN,
        )

    if intent == "FEEDBACK_QUERY":
        _set_lane("action")
        status_filter = _extract_feedback_status(text)
        result = execute_tool(
            run,
            "portal_list_feedbacks",
            {"portal_user_id": portal_user_id, "status": status_filter, "limit": 5},
        )
        if result.get("error"):
            return _respond(run, "暂时没能查到反馈进度，您稍后再试，我也可以先帮您新建一条反馈。", IntentEnum.CREATE_TICKET)
        return _respond(run, _build_feedback_list_reply(result), IntentEnum.CREATE_TICKET)

    if intent == "INVOICE_HELP":
        _set_lane("rag")
        _set_rag_topic("invoice")
        order_id, order_no = _extract_order_ref(text)
        return _respond(
            run,
            _build_invoice_help_reply(has_order_ref=bool(order_id or order_no or _has_any(text, ["补开", "历史订单", "之前订单"]))),
            IntentEnum.UNKNOWN,
        )

    if intent == "SAFETY_LEAK_CHECK":
        _set_lane("safety")
        _set_rag_topic("safety_leak")
        _set_routing_extra(safety_kind="leak_assess", answer_source="typed_fallback", llm_fallback=True)
        return _respond(run, _append_safety_escalation_notice(text, _safety_leak_check_reply(text)), IntentEnum.SAFETY_GUIDE, lane="safety")

    if intent == "SAFETY_EMERGENCY":
        _set_lane("safety")
        _set_rag_topic("safety_leak")
        _set_routing_extra(safety_kind="emergency", answer_source="emergency_template", llm_fallback=False)
        return _respond(run, _append_safety_escalation_notice(text, _safety_emergency_reply()), IntentEnum.SAFETY_GUIDE, lane="safety")

    if intent == "CAPABILITY_HELP":
        _set_lane("smalltalk")
        return _respond(run, _capability_help_reply(), IntentEnum.UNKNOWN)

    if intent == "THEME_SET_EYE":
        _set_lane("smalltalk")
        _set_routing_extra(ui_theme="eye")
        return _respond(run, _theme_switch_reply("eye"), IntentEnum.UNKNOWN)

    if intent == "THEME_SET_DARK":
        _set_lane("smalltalk")
        _set_routing_extra(ui_theme="dark")
        return _respond(run, _theme_switch_reply("dark"), IntentEnum.UNKNOWN)

    if intent == "THEME_SET_LIGHT":
        _set_lane("smalltalk")
        _set_routing_extra(ui_theme="light")
        return _respond(run, _theme_switch_reply("light"), IntentEnum.UNKNOWN)

    if intent == "PHONE_RULE_HELP":
        _set_lane("smalltalk")
        return _respond(run, _phone_rule_reply(), IntentEnum.UNKNOWN)

    if intent == "ACCESSORY_HELP":
        _set_lane("smalltalk")
        return _respond(run, _accessory_help_reply(), IntentEnum.UNKNOWN)

    if intent == "CYLINDER_INSPECTION_QUERY":
        _set_lane("rag")
        _set_rag_topic("inspection")
        return _handle_inspection_query(run, text, portal_user_id)

    if intent == "PRICE_QUERY":
        _set_lane("rag")
        return _answer_price_query(run, text)

    if intent == "ADDRESS_CREATE":
        _set_lane("action")
        return _handle_create_address(run, text, portal_user_id, None)

    if intent == "ADDRESS_SET_DEFAULT":
        _set_lane("action")
        address_id = _extract_address_id(text)
        context = execute_tool(run, "portal_get_context", {"portal_user_id": portal_user_id})
        addresses = (context or {}).get("addresses") or []
        if not address_id and "刚加" in text:
            non_default = [item for item in addresses if not item.get("is_default")]
            if non_default:
                non_default.sort(key=lambda item: int(item.get("id") or 0), reverse=True)
                address_id = non_default[0].get("id")
        if not address_id:
            return _respond(run, "请告诉我要设为默认的地址ID，例如：把地址ID 12 设为默认地址。", IntentEnum.UNKNOWN)
        return _prepare_confirm_action(
            run,
            "SET_DEFAULT_ADDRESS",
            f"将把地址ID {address_id} 设为默认地址。",
            {"address_id": address_id},
            IntentEnum.UNKNOWN,
        )

    if intent == "ADDRESS_UPDATE_DEFAULT":
        _set_lane("action")
        address_id = _extract_address_id(text)
        context = execute_tool(run, "portal_get_context", {"portal_user_id": portal_user_id})
        addresses = (context or {}).get("addresses") or []
        default_address = (context or {}).get("default_address") or {}
        if not address_id:
            address_id = default_address.get("id")
        if not address_id:
            return _respond(run, "您当前还没有默认地址，请先新增一个地址。", IntentEnum.UNKNOWN)
        target = next((item for item in addresses if int(item.get("id") or 0) == int(address_id)), None)
        if not target:
            return _respond(run, f"没有找到地址ID {address_id}，请先确认地址ID。", IntentEnum.UNKNOWN)

        payload = _extract_address_payload(text)
        if not payload:
            contact_name = _extract_contact_name(text)
            if contact_name:
                payload["contact_name"] = contact_name
            contact_phone = _extract_phone(text)
            if contact_phone:
                payload["contact_phone"] = contact_phone
            address_full = _extract_address(text)
            if address_full:
                payload["address_full"] = address_full
        if not payload:
            return _respond(run, "请告诉我需要修改的字段，例如：把地址ID 12 改成上海市浦东新区xx路xx号，联系人王姐，电话13800138000。", IntentEnum.UNKNOWN)

        changed_fields = []
        if payload.get("address_full"):
            changed_fields.append("详细地址")
        if payload.get("contact_name"):
            changed_fields.append("联系人")
        if payload.get("contact_phone"):
            changed_fields.append("联系电话")
        if payload.get("door_note"):
            changed_fields.append("门牌备注")
        fields_text = "、".join(changed_fields) if changed_fields else "地址信息"

        return _prepare_confirm_action(
            run,
            "UPDATE_ADDRESS",
            f"将修改地址ID {address_id} 的{fields_text}。",
            {"address_id": address_id, "payload": payload},
            IntentEnum.UNKNOWN,
        )

    if intent == "ADDRESS_DELETE":
        _set_lane("action")
        address_id = _extract_address_id(text)
        context = execute_tool(run, "portal_get_context", {"portal_user_id": portal_user_id})
        addresses = (context or {}).get("addresses") or []
        default_address = (context or {}).get("default_address") or {}
        if not address_id and "默认地址" in text and default_address.get("id"):
            address_id = default_address.get("id")
        if not address_id and "刚加" in text:
            non_default = [item for item in addresses if not item.get("is_default")]
            if non_default:
                non_default.sort(key=lambda item: int(item.get("id") or 0), reverse=True)
                address_id = non_default[0].get("id")
        if not address_id:
            if not addresses:
                return _respond(run, "您当前还没有地址记录。", IntentEnum.UNKNOWN)
            lines = ["请告诉我要删除的地址ID，例如：删除地址ID 12。", "可选地址："]
            for item in addresses[:5]:
                lines.append(f"- ID {item.get('id')}：{item.get('address_full')}")
            return _respond(run, "\n".join(lines), IntentEnum.UNKNOWN)
        return _prepare_confirm_action(
            run,
            "DELETE_ADDRESS",
            f"将删除地址ID {address_id}。",
            {"address_id": address_id},
            IntentEnum.UNKNOWN,
        )

    if intent == "CANCEL_ORDER":
        _set_lane("action")
        order_id, order_no = _extract_order_ref(text)
        if not order_id and not order_no:
            if _has_any(text, ["这单", "那单", "这笔单"]):
                latest = execute_tool(run, "portal_list_orders", {"portal_user_id": portal_user_id, "page": 1, "page_size": 1})
                latest_items = latest.get("items") or []
                if latest_items:
                    order_id = latest_items[0].get("id")
                    order_no = latest_items[0].get("order_no")
            if not order_id and not order_no:
                return _respond(
                    run,
                    "按规则，服务开始前至少 1 小时才能取消。把订单号发我，我马上帮您判断是否可取消。",
                    IntentEnum.QUERY_ORDER,
                )
        return _prepare_confirm_action(run, "CANCEL_ORDER", f"将取消订单 {order_no or order_id}。", {"order_id": order_id, "order_no": order_no}, IntentEnum.QUERY_ORDER)

    if intent == "PAY_ORDER":
        _set_lane("action")
        order_id, order_no = _extract_order_ref(text)
        if not order_id and not order_no:
            if _has_any(text, ["这单", "这笔单", "那单"]):
                latest = execute_tool(run, "portal_list_orders", {"portal_user_id": portal_user_id, "page": 1, "page_size": 1})
                latest_items = latest.get("items") or []
                if latest_items:
                    order_id = latest_items[0].get("id")
                    order_no = latest_items[0].get("order_no")
            if not order_id and not order_no:
                return _respond(run, "请把要支付的订单号发我（例如：LPG2026020912345678），我马上处理。", IntentEnum.QUERY_ORDER)
        return _prepare_confirm_action(run, "PAY_ORDER", f"将为订单 {order_no or order_id} 发起支付（mock）。", {"order_id": order_id, "order_no": order_no}, IntentEnum.QUERY_ORDER)

    if intent == "MODIFY_ADDRESS":
        _set_lane("action")
        order_id, order_no = _extract_order_ref(text)
        raw_address = _extract_address(text)
        address_full = _sanitize_modify_address_text(raw_address)
        if not order_id and not order_no:
            chosen = _pick_default_modifiable_order(run, portal_user_id)
            if chosen:
                order_id = chosen.get("id")
                order_no = chosen.get("order_no")
                _set_routing_extra(default_order_selected=True, default_order_no=order_no or "")
                _append_event(
                    run,
                    AgentEvent.STATE_PLANNING,
                    output_json={
                        "event": "portal_modify_order_default_selected",
                        "order_no": order_no,
                        "status": chosen.get("status"),
                        "source": "auto_unshipped",
                    },
                )
            if not order_id and not order_no:
                return _respond(
                    run,
                    "未找到可修改的未配送订单，请补充订单号（例如：LPG2026020912345678）。",
                    IntentEnum.MODIFY_ORDER,
                )
        if not address_full:
            context = execute_tool(run, "portal_get_context", {"portal_user_id": portal_user_id})
            default_address = (context or {}).get("default_address") or {}
            if default_address.get("id"):
                summary = f"将订单 {order_no or order_id} 改为默认地址（{default_address.get('address_full')}）。"
                payload = {"order_id": order_id, "order_no": order_no, "payload": {"address_id": default_address.get("id")}}
                return _prepare_confirm_action(run, "MODIFY_ADDRESS", summary, payload, IntentEnum.MODIFY_ORDER)
            return _respond(run, "请提供新地址，例如：把地址改为上海市浦东新区xx路xx号。", IntentEnum.MODIFY_ORDER)
        payload = {"address_full": address_full}
        phone = _extract_phone(text)
        if phone:
            payload["contact_phone"] = phone
        contact_name = _extract_contact_name(text)
        if contact_name:
            payload["contact_name"] = contact_name
        summary = f"将订单 {order_no or order_id} 改址为：{address_full}。"
        return _prepare_confirm_action(run, "MODIFY_ADDRESS", summary, {"order_id": order_id, "order_no": order_no, "payload": payload}, IntentEnum.MODIFY_ORDER)

    if intent == "CREATE_FEEDBACK":
        _set_lane("action")
        order_id, order_no = _extract_order_ref(text)
        has_explicit_order_ref = bool(order_id or order_no)
        feedback_type = "SUGGESTION" if (("建议" in text or "表扬" in text) and "投诉" not in text) else "COMPLAINT"
        order_related_topic = _is_order_service_feedback_topic(text)
        online_related_topic = _is_online_feedback_topic(text)
        require_order = bool(has_explicit_order_ref or order_related_topic)

        # “建议/表扬”默认按线上反馈处理，除非用户明确指定订单号。
        if feedback_type == "SUGGESTION" and not has_explicit_order_ref:
            require_order = False
        elif feedback_type == "COMPLAINT" and online_related_topic and not order_related_topic and not (order_id or order_no):
            require_order = False

        if require_order and not order_id and order_no:
            resolved = execute_tool(
                run,
                "portal_get_order",
                {"portal_user_id": portal_user_id, "order_no": order_no},
            )
            if not resolved.get("error"):
                try:
                    order_id = int(resolved.get("id"))
                except (TypeError, ValueError):
                    order_id = None

        if require_order and not order_id:
            reply, picks = _build_feedback_order_pick_reply(run, portal_user_id)
            action = _build_feedback_collecting_action(
                feedback_type=feedback_type,
                content=text,
                picks=picks,
                contact_phone=_extract_phone(text) or "",
                require_order=True,
            )
            return _respond(run, reply, IntentEnum.CREATE_TICKET, pending_action=action)

        target_type = "ORDER_SERVICE" if require_order else "ONLINE_SERVICE"
        payload = {
            "feedback_type": feedback_type,
            "target_type": target_type,
            "title": "用户反馈",
            "content": text,
        }
        if order_id:
            payload["order_id"] = order_id
        phone = _extract_phone(text)
        if phone:
            payload["contact_phone"] = phone
        if payload.get("order_id"):
            summary = f"将提交一条{'投诉' if feedback_type == 'COMPLAINT' else '建议'}反馈（关联订单 {order_id or order_no}）。"
        else:
            summary = f"将提交一条{'投诉' if feedback_type == 'COMPLAINT' else '建议'}反馈（线上服务）。"
        return _prepare_confirm_action(run, "CREATE_FEEDBACK", summary, payload, IntentEnum.CREATE_TICKET)

    if intent == "UPDATE_PROFILE":
        _set_lane("action")
        display_name = _extract_display_name(text)
        if not display_name:
            return _respond(
                run,
                "可以的。请告诉我您要修改成的姓名或昵称（2-32个字符）。",
                IntentEnum.UNKNOWN,
            )
        return _prepare_confirm_action(
            run,
            "UPDATE_PROFILE",
            f"将把您的姓名修改为“{display_name}”。",
            {"display_name": display_name},
            IntentEnum.UNKNOWN,
        )

    if intent == "REQUEST_REFUND":
        _set_lane("action")
        order_id, order_no = _extract_order_ref(text)
        if not order_id and not order_no:
            return _respond(
                run,
                "请提供要申请退款的订单号，例如：申请退款 LPG2026020912345678。",
                IntentEnum.UNKNOWN,
            )
        reason = text.strip()
        summary = f"将为订单 {order_no or order_id} 提交退款申请。"
        payload = {"order_id": order_id, "order_no": order_no, "reason": reason}
        return _prepare_confirm_action(run, "REQUEST_REFUND", summary, payload, IntentEnum.UNKNOWN)

    if intent == "CHANGE_PASSWORD":
        _set_lane("action")
        return _handle_change_password(run, text, portal_user_id, pending_action if isinstance(pending_action, dict) else None)

    if intent == "NOTIFICATION_READ":
        _set_lane("action")
        notification_id = _extract_notification_id(text)
        if not notification_id:
            unread = execute_tool(
                run,
                "portal_list_notifications",
                {"portal_user_id": portal_user_id, "page": 1, "page_size": 1, "only_unread": True},
            )
            unread_items = unread.get("items") or []
            if unread_items:
                notification_id = unread_items[0].get("id")
        if not notification_id:
            return _respond(run, "请告诉我要标记已读的通知ID，例如：通知ID 23 设为已读。", IntentEnum.UNKNOWN)
        return _prepare_confirm_action(
            run,
            "NOTIFICATION_READ",
            f"将把通知ID {notification_id} 标记为已读。",
            {"notification_id": notification_id},
            IntentEnum.UNKNOWN,
        )

    if intent == "NOTIFICATION_READ_ALL":
        _set_lane("action")
        return _prepare_confirm_action(
            run,
            "NOTIFICATION_READ_ALL",
            "将把当前账号所有未读通知标记为已读。",
            {},
            IntentEnum.UNKNOWN,
        )

    return _answer_non_actionable_query(run, text, router_plan=stage0_signal)


def run_portal_orchestrator_legacy(run, message, portal_user_id, llm=None, tone_style="neutral", rag_config=None, memory=None):
    return run_portal_orchestrator(
        run,
        message,
        portal_user_id,
        llm=llm,
        tone_style=tone_style or "neutral",
        rag_config=rag_config,
        memory=memory,
        route_mode="legacy",
        write_allowed=True,
        degraded_reason=None,
        model_source="none",
    )







