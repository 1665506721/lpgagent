from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import random

from django.db import transaction
from django.utils import timezone

from .constants import (
    ACCESSORY_CATALOG,
    ACCESSORY_SKUS,
    ASAP_END_OFFSET_MINUTES,
    ASAP_START_OFFSET_MINUTES,
    DEFAULT_CURRENCY,
    DELIVERY_PRICES,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING_PAYMENT,
    ORDER_STATUS_SCHEDULED,
    OUTSIDE_WINDOW_END,
    OUTSIDE_WINDOW_START,
    PAYMENT_METHOD_MOCK,
    PAYMENT_STATUS_MOCK,
    REPAIR_PRICE,
    SAFETY_CHECK_PRICE,
    SERVICE_TYPE_ACCESSORIES,
    SERVICE_TYPE_CYLINDER_EXCHANGE,
    SERVICE_TYPE_INSTALLATION,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
    SERVICE_TYPE_REPAIR,
    SERVICE_TYPE_SAFETY_CHECK,
    SERVICE_WINDOW_END,
    SERVICE_WINDOW_START,
    WINDOW_GRANULARITY_MINUTES,
    URGENT_EDIT_CANCEL_WINDOW_MINUTES,
    URGENT_FEE_CAP,
    URGENT_FEE_MIN,
    URGENT_FEE_RATE,
    URGENT_START_WITHIN_MINUTES,
    INSTALLATION_PRICE,
)
from .models import Order, OrderEvent, PaymentTransaction
from .models import CustomerAddress, CustomerCartItem
from .notifications import create_notification


ASSIGNED_WORKER_POOL = [
    {"name": "王建国", "phone": "13800001101"},
    {"name": "李师傅", "phone": "13800001102"},
    {"name": "陈师傅", "phone": "13800001103"},
    {"name": "赵师傅", "phone": "13800001104"},
]


def get_now():
    return timezone.localtime(timezone.now())


def _quantize(amount):
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def is_within_service_window(now):
    now_time = now.time()
    return SERVICE_WINDOW_START <= now_time < SERVICE_WINDOW_END


def _next_service_window_start(now):
    if now.time() < SERVICE_WINDOW_START:
        start_date = now.date()
    else:
        start_date = (now + timedelta(days=1)).date()
    return datetime.combine(start_date, SERVICE_WINDOW_START, tzinfo=now.tzinfo)


def calculate_eta(now, is_urgent):
    if is_urgent:
        if is_within_service_window(now):
            eta_start = now + timedelta(minutes=URGENT_START_WITHIN_MINUTES)
        else:
            eta_start = _next_service_window_start(now)
        eta_end = eta_start + timedelta(minutes=WINDOW_GRANULARITY_MINUTES)
        return eta_start, eta_end

    if is_within_service_window(now):
        eta_start = now + timedelta(minutes=ASAP_START_OFFSET_MINUTES)
        eta_end = now + timedelta(minutes=ASAP_END_OFFSET_MINUTES)
    else:
        next_day = (now + timedelta(days=1)).date()
        eta_start = datetime.combine(next_day, OUTSIDE_WINDOW_START, tzinfo=now.tzinfo)
        eta_end = datetime.combine(next_day, OUTSIDE_WINDOW_END, tzinfo=now.tzinfo)

    return eta_start, eta_end


def _parse_eta_slot(slot_text):
    try:
        start_text, end_text = slot_text.split("-", 1)
        start_time = datetime.strptime(start_text.strip(), "%H:%M").time()
        end_time = datetime.strptime(end_text.strip(), "%H:%M").time()
    except (ValueError, TypeError):
        raise ValueError("invalid eta_slot")
    if start_time >= end_time:
        raise ValueError("invalid eta_slot")
    return start_time, end_time


def calculate_eta_with_request(now, is_urgent, eta_date=None, eta_slot=None):
    if is_urgent:
        return calculate_eta(now, True)

    if eta_date and eta_slot:
        try:
            date_value = datetime.strptime(eta_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise ValueError("invalid eta_date")
        start_time, end_time = _parse_eta_slot(eta_slot)
        if start_time < SERVICE_WINDOW_START or end_time > SERVICE_WINDOW_END:
            raise ValueError("eta_slot_out_of_window")
        start_dt = datetime.combine(date_value, start_time, tzinfo=now.tzinfo)
        end_dt = datetime.combine(date_value, end_time, tzinfo=now.tzinfo)
        if end_dt - start_dt != timedelta(minutes=WINDOW_GRANULARITY_MINUTES):
            raise ValueError("eta_slot_invalid_span")
        if start_dt < now:
            raise ValueError("eta_slot_in_past")
        eta_start, eta_end = start_dt, end_dt
    else:
        eta_start, eta_end = calculate_eta(now, False)

    return eta_start, eta_end


def calculate_urgent_fee(subtotal, is_urgent):
    if not is_urgent:
        return Decimal("0")
    fee = subtotal * URGENT_FEE_RATE
    fee = max(URGENT_FEE_MIN, fee)
    fee = min(URGENT_FEE_CAP, fee)
    return _quantize(fee)


def calculate_subtotal(service_type, service_payload):
    if service_type in {SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE}:
        cylinder_type = service_payload.get("cylinder_type")
        quantity = service_payload.get("quantity", 1)
        unit_price = DELIVERY_PRICES.get(cylinder_type)
        if unit_price is None:
            raise ValueError("invalid cylinder_type")
        return _quantize(unit_price * Decimal(quantity))
    if service_type == SERVICE_TYPE_INSTALLATION:
        return _quantize(INSTALLATION_PRICE)
    if service_type == SERVICE_TYPE_SAFETY_CHECK:
        return _quantize(SAFETY_CHECK_PRICE)
    if service_type == SERVICE_TYPE_REPAIR:
        return _quantize(REPAIR_PRICE)
    if service_type == SERVICE_TYPE_ACCESSORIES:
        items = service_payload.get("items", [])
        total = Decimal("0")
        for item in items:
            sku = item.get("sku")
            quantity = item.get("quantity", 1)
            unit_price = ACCESSORY_SKUS.get(sku)
            if unit_price is None:
                raise ValueError("invalid accessory sku")
            total += unit_price * Decimal(quantity)
        return _quantize(total)
    raise ValueError("invalid service_type")


def generate_order_no():
    now = get_now()
    base = now.strftime("LPG%Y%m%d%H%M%S")
    return f"{base}{random.randint(1000, 9999)}"


def assign_worker_snapshot(service_type):
    if service_type not in {
        SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
        SERVICE_TYPE_CYLINDER_EXCHANGE,
        SERVICE_TYPE_INSTALLATION,
        SERVICE_TYPE_SAFETY_CHECK,
        SERVICE_TYPE_REPAIR,
        SERVICE_TYPE_ACCESSORIES,
    }:
        return {}
    return dict(random.choice(ASSIGNED_WORKER_POOL))


def log_order_event(order, event_type, payload):
    OrderEvent.objects.create(order=order, event_type=event_type, payload=payload)


def apply_expiration_if_needed(order, now=None):
    now = now or get_now()
    if order.status == ORDER_STATUS_PENDING_PAYMENT and order.expires_at <= now:
        order.status = ORDER_STATUS_EXPIRED
        order.save(update_fields=["status", "updated_at"])
        log_order_event(order, "EXPIRED", {"at": now.isoformat()})
    return order


def can_cancel(order, now=None):
    now = now or get_now()
    if order.status not in {ORDER_STATUS_PENDING_PAYMENT, ORDER_STATUS_PAID, ORDER_STATUS_SCHEDULED}:
        return False
    deadline = order.cancel_deadline
    if not deadline:
        deadline = order.eta_start - timedelta(minutes=60)
    if now > deadline:
        return False
    return True


def can_edit_address(order, now=None):
    now = now or get_now()
    if order.status not in {ORDER_STATUS_PENDING_PAYMENT, ORDER_STATUS_PAID, ORDER_STATUS_SCHEDULED}:
        return False
    deadline = order.address_edit_deadline
    if not deadline:
        deadline = order.eta_start - timedelta(minutes=60)
    if now > deadline:
        return False
    return True


@transaction.atomic
def create_order(
    user,
    service_type,
    service_payload,
    contact_snapshot,
    address_snapshot,
    eta_date=None,
    eta_slot=None,
    is_urgent=False,
    notes="",
):
    now = get_now()
    eta_start, eta_end = calculate_eta_with_request(now, is_urgent, eta_date, eta_slot)
    if is_urgent:
        cancel_deadline = now + timedelta(minutes=URGENT_EDIT_CANCEL_WINDOW_MINUTES)
    else:
        cancel_deadline = eta_start - timedelta(minutes=60)
    expires_at = now + timedelta(minutes=30)
    normalized_service_payload = dict(service_payload or {})
    if not isinstance(normalized_service_payload.get("assigned_worker"), dict):
        worker = assign_worker_snapshot(service_type)
        if worker:
            normalized_service_payload["assigned_worker"] = worker

    subtotal = calculate_subtotal(service_type, normalized_service_payload)
    urgent_fee = calculate_urgent_fee(subtotal, is_urgent)
    total = _quantize(subtotal + urgent_fee)

    order_no = generate_order_no()
    while Order.objects.filter(order_no=order_no).exists():
        order_no = generate_order_no()

    order = Order.objects.create(
        order_no=order_no,
        user=user,
        service_type=service_type,
        status=ORDER_STATUS_PENDING_PAYMENT,
        eta_start=eta_start,
        eta_end=eta_end,
        cancel_deadline=cancel_deadline,
        address_edit_deadline=cancel_deadline,
        is_urgent=is_urgent,
        notes=notes or "",
        amount_subtotal=subtotal,
        amount_urgent_fee=urgent_fee,
        amount_total=total,
        currency=DEFAULT_CURRENCY,
        address_snapshot=address_snapshot,
        contact_snapshot=contact_snapshot,
        service_payload=normalized_service_payload,
        expires_at=expires_at,
    )
    log_order_event(
        order,
        "CREATED",
        {
            "status": order.status,
            "eta_start": eta_start.isoformat(),
            "eta_end": eta_end.isoformat(),
            "is_urgent": is_urgent,
            "assigned_worker": normalized_service_payload.get("assigned_worker"),
        },
    )
    create_notification(
        user=user,
        category="ORDER",
        event_code="ORDER_CREATED",
        title="订单已创建",
        content=(
            f"订单 {order.order_no} 已创建，预计服务时段 "
            f"{eta_start.strftime('%Y-%m-%d %H:%M')} - {eta_end.strftime('%H:%M')}。"
        ),
        level="SUCCESS",
        target_type="ORDER",
        target_id=order.id,
        meta_json={"order_no": order.order_no, "status": order.status},
    )
    return order


@transaction.atomic
def pay_order(order):
    now = get_now()
    apply_expiration_if_needed(order, now=now)
    if order.status == ORDER_STATUS_EXPIRED:
        return None, "ORDER_EXPIRED"
    if order.status == ORDER_STATUS_PAID:
        return order, None
    if order.status != ORDER_STATUS_PENDING_PAYMENT:
        return None, "ORDER_NOT_EDITABLE"

    order.status = ORDER_STATUS_PAID
    order.save(update_fields=["status", "updated_at"])
    PaymentTransaction.objects.create(
        order=order,
        status=PAYMENT_STATUS_MOCK,
        method=PAYMENT_METHOD_MOCK,
        paid_at=now,
    )
    log_order_event(order, "PAID", {"at": now.isoformat()})
    create_notification(
        user=order.user,
        category="PAYMENT",
        event_code="ORDER_PAID",
        title="订单支付成功",
        content=f"订单 {order.order_no} 已支付成功，服务即将安排。",
        level="SUCCESS",
        target_type="ORDER",
        target_id=order.id,
        meta_json={"order_no": order.order_no, "status": order.status},
    )
    return order, None


@transaction.atomic
def cancel_order(order):
    now = get_now()
    apply_expiration_if_needed(order, now=now)
    if order.status == ORDER_STATUS_EXPIRED:
        return None, "ORDER_EXPIRED"
    if not can_cancel(order, now=now):
        return None, "ORDER_NOT_CANCELABLE"
    order.status = ORDER_STATUS_CANCELED
    order.save(update_fields=["status", "updated_at"])
    log_order_event(order, "CANCELED", {"at": now.isoformat()})
    create_notification(
        user=order.user,
        category="ORDER",
        event_code="ORDER_CANCELED",
        title="订单已取消",
        content=f"订单 {order.order_no} 已取消，如需继续服务可重新下单。",
        level="WARNING",
        target_type="ORDER",
        target_id=order.id,
        meta_json={"order_no": order.order_no, "status": order.status},
    )
    return order, None


@transaction.atomic
def modify_order_address(order, new_address_snapshot, new_contact_snapshot):
    now = get_now()
    apply_expiration_if_needed(order, now=now)
    if order.status == ORDER_STATUS_EXPIRED:
        return None, "ORDER_EXPIRED"
    if not can_edit_address(order, now=now):
        return None, "ORDER_NOT_EDITABLE"
    order.address_snapshot = new_address_snapshot
    order.contact_snapshot = new_contact_snapshot
    order.save(update_fields=["address_snapshot", "contact_snapshot", "updated_at"])
    log_order_event(order, "ADDRESS_UPDATED", {"at": now.isoformat()})
    create_notification(
        user=order.user,
        category="ADDRESS",
        event_code="ORDER_ADDRESS_UPDATED",
        title="订单地址已更新",
        content=f"订单 {order.order_no} 地址已更新为：{(new_address_snapshot or {}).get('address_full', '')}。",
        level="INFO",
        target_type="ORDER",
        target_id=order.id,
        meta_json={"order_no": order.order_no},
    )
    return order, None


def list_cart_items(user):
    return CustomerCartItem.objects.filter(user=user, selected=True).order_by("-updated_at", "-id")


def set_cart_item(user, sku, quantity):
    if sku not in ACCESSORY_SKUS:
        raise ValueError("invalid_sku")
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        raise ValueError("invalid_quantity")
    if qty < 0:
        raise ValueError("invalid_quantity")
    if qty == 0:
        CustomerCartItem.objects.filter(user=user, sku=sku).delete()
        return None
    item, _ = CustomerCartItem.objects.update_or_create(
        user=user,
        sku=sku,
        defaults={"quantity": qty, "selected": True},
    )
    return item


def add_cart_items(user, items):
    if not isinstance(items, list) or not items:
        raise ValueError("invalid_items")
    merged = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid_items")
        sku = str(item.get("sku") or "").strip().upper()
        if sku not in ACCESSORY_SKUS:
            raise ValueError("invalid_sku")
        try:
            qty = int(item.get("quantity"))
        except (TypeError, ValueError):
            raise ValueError("invalid_quantity")
        if qty <= 0:
            raise ValueError("invalid_quantity")
        merged[sku] = merged.get(sku, 0) + qty

    for sku, qty in merged.items():
        row = CustomerCartItem.objects.filter(user=user, sku=sku).first()
        next_qty = qty + (row.quantity if row else 0)
        set_cart_item(user, sku, next_qty)

    return list_cart_items(user)


def remove_cart_items(user, items):
    if not isinstance(items, list) or not items:
        raise ValueError("invalid_items")
    changed = False
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid_items")
        sku = str(item.get("sku") or "").strip().upper()
        if sku not in ACCESSORY_SKUS:
            raise ValueError("invalid_sku")
        quantity = item.get("quantity")
        row = CustomerCartItem.objects.filter(user=user, sku=sku).first()
        if not row:
            continue
        if quantity is None:
            row.delete()
            changed = True
            continue
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            raise ValueError("invalid_quantity")
        if qty <= 0:
            row.delete()
            changed = True
            continue
        next_qty = row.quantity - qty
        if next_qty <= 0:
            row.delete()
        else:
            row.quantity = next_qty
            row.save(update_fields=["quantity", "updated_at"])
        changed = True
    if changed:
        return list_cart_items(user)
    return list_cart_items(user)


def clear_cart_items(user):
    deleted, _ = CustomerCartItem.objects.filter(user=user).delete()
    return deleted


def cart_summary(user):
    rows = list(list_cart_items(user))
    total_count = 0
    total_amount = Decimal("0")
    items = []
    for row in rows:
        price = ACCESSORY_SKUS.get(row.sku, Decimal("0"))
        amount = _quantize(price * row.quantity)
        total_count += row.quantity
        total_amount += amount
        items.append(
            {
                "sku": row.sku,
                "name": (ACCESSORY_CATALOG.get(row.sku) or {}).get("name", row.sku),
                "category": (ACCESSORY_CATALOG.get(row.sku) or {}).get("category", "配件"),
                "quantity": row.quantity,
                "price": _quantize(price),
                "amount": amount,
                "updated_at": row.updated_at,
            }
        )
    return {
        "items": items,
        "selected_count": total_count,
        "total_amount": _quantize(total_amount),
        "currency": DEFAULT_CURRENCY,
    }


@transaction.atomic
def checkout_cart(
    user,
    *,
    address_id=None,
    eta_date=None,
    eta_slot=None,
    is_urgent=False,
    notes="",
    invoice_required=False,
    invoice_title="",
    invoice_tax_no="",
    auto_pay=True,
):
    rows = list(list_cart_items(user))
    if not rows:
        raise ValueError("cart_empty")

    if address_id:
        address = CustomerAddress.objects.filter(id=address_id, user=user).first()
    else:
        address = CustomerAddress.objects.filter(user=user, is_default=True).first() or CustomerAddress.objects.filter(
            user=user
        ).order_by("-created_at").first()
    if not address:
        raise ValueError("address_required")

    items = [{"sku": row.sku, "quantity": row.quantity} for row in rows]
    service_payload = {
        "items": items,
        "invoice_required": bool(invoice_required),
        "invoice_title": (invoice_title or "").strip() if invoice_required else "",
        "invoice_tax_no": (invoice_tax_no or "").strip() if invoice_required else "",
    }

    order = create_order(
        user=user,
        service_type=SERVICE_TYPE_ACCESSORIES,
        service_payload=service_payload,
        contact_snapshot={
            "contact_name": address.contact_name,
            "contact_phone": address.contact_phone,
        },
        address_snapshot={
            "address_full": address.address_full,
            "door_note": address.door_note,
        },
        eta_date=eta_date,
        eta_slot=eta_slot,
        is_urgent=bool(is_urgent),
        notes=notes or "配件购物车下单",
    )

    if auto_pay:
        paid, code = pay_order(order)
        if code:
            raise ValueError(code)
        order = paid

    clear_cart_items(user)
    return order
