import random
from datetime import datetime, timedelta, timezone


_SEED = 42
_CACHE = None


def _mask_name(name):
    if not name:
        return "张*"
    return f"{name[0]}*"


def _mask_phone(phone):
    if not phone or len(phone) < 11:
        return "138****2211"
    return f"{phone[:3]}****{phone[-4:]}"


def _build_timeline(status, created_at):
    # 中文注释：时间线用于模拟真实物流轨迹，至少提供 4 个节点
    points = []
    base = created_at
    points.append({"status": "CREATED", "time": base.isoformat()})
    points.append({"status": "CONFIRMED", "time": (base + timedelta(hours=1)).isoformat()})
    points.append({"status": "DISPATCHED", "time": (base + timedelta(hours=4)).isoformat()})
    if status in {"DELIVERING", "DONE"}:
        points.append({"status": "DELIVERING", "time": (base + timedelta(hours=6)).isoformat()})
    if status == "DONE":
        points.append({"status": "DONE", "time": (base + timedelta(hours=8)).isoformat()})
    if status == "CANCELLED":
        points.append({"status": "CANCELLED", "time": (base + timedelta(hours=2)).isoformat()})
    if len(points) < 4:
        points.append({"status": status, "time": (base + timedelta(hours=3)).isoformat()})
    return points[:5]


def _build_order(order_id, status, rng, now, phone):
    # 中文注释：构造单条订单，字段结构尽量贴近真实订单系统
    name_pool = ["张三", "李四", "王五", "赵六", "刘强", "周敏"]
    city_pool = [
        "上海市浦东新区世纪大道",
        "北京市朝阳区建国路",
        "广州市天河区体育西路",
        "深圳市南山区科技园",
        "杭州市西湖区文三路",
        "成都市高新区天府大道",
    ]
    product_types = ["15kg", "5kg"]
    risk_flags_pool = [["NONE"], ["DELAYED"], ["ADDRESS_CHANGED"]]

    created_at = now - timedelta(days=rng.randint(0, 25), hours=rng.randint(0, 23))
    eta = created_at + timedelta(hours=rng.randint(4, 24))
    courier_phone = _mask_phone(f"13{rng.randint(0, 9)}{rng.randint(0, 9)}{rng.randint(0, 9)}{rng.randint(1000, 9999)}")
    courier = {
        "name": _mask_name(rng.choice(["陈峰", "何东", "高楠", "孙宁"])),
        "phone_masked": courier_phone,
        "plate": f"沪A{rng.randint(1000, 9999)}",
    }
    return {
        "order_id": order_id,
        "customer": {
            "name": _mask_name(rng.choice(name_pool)),
            "phone_masked": _mask_phone(phone),
            "phone_full": phone,
        },
        "address": f"{rng.choice(city_pool)}{rng.randint(1, 200)}号",
        "product": {
            "type": rng.choice(product_types),
            "quantity": rng.randint(1, 4),
        },
        "status": status,
        "created_at": created_at.isoformat(),
        "eta": eta.isoformat(),
        "courier": courier,
        "timeline": _build_timeline(status, created_at),
        "risk_flags": rng.choice(risk_flags_pool),
    }


def generate_mock_orders(force=False):
    # 中文注释：固定随机种子，保证 mock 数据可重复，便于演示与测试
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE

    from core.models import Order

    rng = random.Random(_SEED)
    now = datetime.now(timezone.utc)
    statuses = (
        [Order.STATUS_DONE] * 36
        + [Order.STATUS_DELIVERING] * 9
        + [Order.STATUS_DISPATCHED] * 6
        + [Order.STATUS_CONFIRMED] * 6
        + [Order.STATUS_CANCELLED] * 3
    )
    rng.shuffle(statuses)

    phones = [
        "13800112211",
        "13911112222",
        "13722223333",
        "13633334444",
        "13544445555",
    ]
    orders = []
    base_order_id = 10002300
    for index, status in enumerate(statuses):
        order_id = base_order_id + index
        phone = rng.choice(phones)
        orders.append(_build_order(order_id, status, rng, now, phone))

    _CACHE = orders
    return _CACHE


def reset_mock_orders():
    # 中文注释：用于演示时重置数据源
    return generate_mock_orders(force=True)
