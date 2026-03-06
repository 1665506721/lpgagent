from decimal import Decimal
from datetime import time


CN_PHONE_PATTERN = r"^1[3-9]\d{9}$"
TEST_ACCOUNT_PHONE = "123"
TEST_ACCOUNT_PASSWORD = "123"

SERVICE_TYPE_LPG_CYLINDER_DELIVERY = "LPG_CYLINDER_DELIVERY"
SERVICE_TYPE_CYLINDER_EXCHANGE = "CYLINDER_EXCHANGE"
SERVICE_TYPE_INSTALLATION = "INSTALLATION"
SERVICE_TYPE_SAFETY_CHECK = "SAFETY_CHECK"
SERVICE_TYPE_REPAIR = "REPAIR"
SERVICE_TYPE_ACCESSORIES = "ACCESSORIES"

SERVICE_TYPE_CHOICES = [
    (SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_LPG_CYLINDER_DELIVERY),
    (SERVICE_TYPE_CYLINDER_EXCHANGE, SERVICE_TYPE_CYLINDER_EXCHANGE),
    (SERVICE_TYPE_INSTALLATION, SERVICE_TYPE_INSTALLATION),
    (SERVICE_TYPE_SAFETY_CHECK, SERVICE_TYPE_SAFETY_CHECK),
    (SERVICE_TYPE_REPAIR, SERVICE_TYPE_REPAIR),
    (SERVICE_TYPE_ACCESSORIES, SERVICE_TYPE_ACCESSORIES),
]

SERVICE_TYPE_LABELS = {
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY: "瓶装配送",
    SERVICE_TYPE_CYLINDER_EXCHANGE: "换瓶",
    SERVICE_TYPE_INSTALLATION: "安装",
    SERVICE_TYPE_SAFETY_CHECK: "安检",
    SERVICE_TYPE_REPAIR: "报修",
    SERVICE_TYPE_ACCESSORIES: "配件",
}

ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_PAID = "PAID"
ORDER_STATUS_SCHEDULED = "SCHEDULED"
ORDER_STATUS_IN_SERVICE = "IN_SERVICE"
ORDER_STATUS_COMPLETED = "COMPLETED"
ORDER_STATUS_CANCELED = "CANCELED"
ORDER_STATUS_EXPIRED = "EXPIRED"

ORDER_STATUS_CHOICES = [
    (ORDER_STATUS_PENDING_PAYMENT, ORDER_STATUS_PENDING_PAYMENT),
    (ORDER_STATUS_PAID, ORDER_STATUS_PAID),
    (ORDER_STATUS_SCHEDULED, ORDER_STATUS_SCHEDULED),
    (ORDER_STATUS_IN_SERVICE, ORDER_STATUS_IN_SERVICE),
    (ORDER_STATUS_COMPLETED, ORDER_STATUS_COMPLETED),
    (ORDER_STATUS_CANCELED, ORDER_STATUS_CANCELED),
    (ORDER_STATUS_EXPIRED, ORDER_STATUS_EXPIRED),
]

ORDER_STATUS_LABELS = {
    ORDER_STATUS_PENDING_PAYMENT: "待支付",
    ORDER_STATUS_PAID: "已支付",
    ORDER_STATUS_SCHEDULED: "已预约",
    ORDER_STATUS_IN_SERVICE: "服务中",
    ORDER_STATUS_COMPLETED: "已完成",
    ORDER_STATUS_CANCELED: "已取消",
    ORDER_STATUS_EXPIRED: "已过期",
}

PAYMENT_STATUS_SUCCESS = "SUCCESS"
PAYMENT_STATUS_FAILED = "FAILED"
PAYMENT_STATUS_MOCK = "MOCK"

PAYMENT_STATUS_CHOICES = [
    (PAYMENT_STATUS_SUCCESS, PAYMENT_STATUS_SUCCESS),
    (PAYMENT_STATUS_FAILED, PAYMENT_STATUS_FAILED),
    (PAYMENT_STATUS_MOCK, PAYMENT_STATUS_MOCK),
]

PAYMENT_METHOD_MOCK = "MOCK"

SERVICE_WINDOW_START = time(9, 0)
SERVICE_WINDOW_END = time(21, 0)
WINDOW_GRANULARITY_MINUTES = 120

ASAP_START_OFFSET_MINUTES = 60
ASAP_END_OFFSET_MINUTES = 180

OUTSIDE_WINDOW_START = time(9, 0)
OUTSIDE_WINDOW_END = time(11, 0)

URGENT_START_ADVANCE_MINUTES = 30
URGENT_END_ADVANCE_MINUTES = 60
URGENT_MIN_START_OFFSET_MINUTES = 30
URGENT_MIN_END_AFTER_START_MINUTES = 60
URGENT_START_WITHIN_MINUTES = 60
URGENT_EDIT_CANCEL_WINDOW_MINUTES = 30
URGENT_FEE_RATE = Decimal("0.10")
URGENT_FEE_MIN = Decimal("10")
URGENT_FEE_CAP = Decimal("50")

DEFAULT_CURRENCY = "CNY"

DELIVERY_PRICES = {
    "5kg": Decimal("60"),
    "15kg": Decimal("120"),
    "45kg": Decimal("280"),
}

INSTALLATION_PRICE = Decimal("199")
SAFETY_CHECK_PRICE = Decimal("99")
REPAIR_PRICE = Decimal("99")

ACCESSORY_CATALOG = {
    "HOSE": {
        "name": "耐高温燃气软管（2m）",
        "category": "管件",
        "tag": "常备",
        "desc": "多层防爆结构，适配常见家商用接口",
        "price": Decimal("35"),
    },
    "REGULATOR": {
        "name": "安全减压阀",
        "category": "阀门",
        "tag": "热卖",
        "desc": "稳定调压，适用于瓶装液化气场景",
        "price": Decimal("80"),
    },
    "ALARM": {
        "name": "燃气报警器",
        "category": "安防",
        "tag": "推荐",
        "desc": "燃气异常浓度自动声光报警",
        "price": Decimal("120"),
    },
    "VALVE": {
        "name": "自闭阀",
        "category": "阀门",
        "tag": "安全",
        "desc": "异常断气自闭保护，提升用气安全",
        "price": Decimal("68"),
    },
    "STOVE_1B": {
        "name": "单眼燃气灶",
        "category": "灶具",
        "tag": "新品",
        "desc": "小型厨房/后厨适用，火力稳定",
        "price": Decimal("259"),
    },
    "STOVE_2B": {
        "name": "双眼燃气灶",
        "category": "灶具",
        "tag": "经典",
        "desc": "家用主流规格，兼顾效率与稳定",
        "price": Decimal("499"),
    },
    "IGNITER": {
        "name": "点火器",
        "category": "配件",
        "tag": "易耗",
        "desc": "燃气灶点火更灵敏，兼容主流型号",
        "price": Decimal("45"),
    },
    "SEAL_TAPE": {
        "name": "密封生料带",
        "category": "管件",
        "tag": "辅材",
        "desc": "接口密封防渗漏，安装维修常用",
        "price": Decimal("15"),
    },
    "CLAMP_SET": {
        "name": "卡箍套装（4只）",
        "category": "管件",
        "tag": "辅材",
        "desc": "软管紧固固定，提升连接可靠性",
        "price": Decimal("22"),
    },
}

ACCESSORY_SKUS = {
    sku: meta["price"]
    for sku, meta in ACCESSORY_CATALOG.items()
}

ACCESSORY_SKU_LABELS = {
    sku: meta["name"]
    for sku, meta in ACCESSORY_CATALOG.items()
}

# 监管法检口径（MVP）
# 说明：用于客服“年检时间查询”的后端可验证计算。实际执行仍以当地监管与检验机构结论为准。
INSPECTION_POLICY_VERSION = "CN_TSG23_2021_V1"
INSPECTION_POLICY_SOURCE_REF = "TSG 23-2021 §9.3（液化石油气钢瓶定期检验周期）"
INSPECTION_POLICY_DISCLAIMER = "以上为平台按监管口径计算的参考时间，最终以当地监管部门和检验机构结论为准。"

# LPG 气瓶周期口径（按规格可配置；当前统一 4 年一检）
INSPECTION_RULES = {
    "5kg": {
        "cycle_months": 48,
        "design_service_life_months": 96,
        "max_service_life_months": 144,
    },
    "15kg": {
        "cycle_months": 48,
        "design_service_life_months": 96,
        "max_service_life_months": 144,
    },
    "45kg": {
        "cycle_months": 48,
        "design_service_life_months": 96,
        "max_service_life_months": 144,
    },
}
