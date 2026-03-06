from datetime import date

from django.utils import timezone

from customer_portal.constants import (
    INSPECTION_POLICY_DISCLAIMER,
    SERVICE_TYPE_CYLINDER_EXCHANGE,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
)
from customer_portal.inspection_rules import get_inspection_rule
from customer_portal.models import Order


def _add_months(value, months):
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    if month == 2:
        leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        max_day = 29 if leap else 28
    elif month in {4, 6, 9, 11}:
        max_day = 30
    else:
        max_day = 31
    day = min(value.day, max_day)
    return date(year, month, day)


def _safe_parse_date(raw_value):
    if isinstance(raw_value, date):
        return raw_value
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _order_base_date(order):
    payload = order.service_payload if isinstance(order.service_payload, dict) else {}
    purchase_date = _safe_parse_date(
        payload.get("cylinder_purchase_date")
        or payload.get("purchase_date")
        or payload.get("cylinder_bought_at")
    )
    if purchase_date:
        return purchase_date, "CYLINDER_PURCHASE_DATE"

    if order.eta_end:
        return timezone.localtime(order.eta_end).date(), "ORDER_SERVICE_DATE"
    return timezone.localtime(order.created_at).date(), "ORDER_PURCHASE_DATE"


def _inspection_status(next_inspection_date):
    today = timezone.localtime(timezone.now()).date()
    delta_days = (next_inspection_date - today).days
    if delta_days < 0:
        return "OVERDUE"
    if delta_days <= 30:
        return "DUE_SOON"
    return "NORMAL"


def list_inspection_candidates(user, limit=6):
    rows = (
        Order.objects.filter(
            user=user,
            service_type__in=[SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE],
        )
        .order_by("-created_at")[: max(1, int(limit or 6))]
    )
    items = []
    for item in rows:
        payload = item.service_payload if isinstance(item.service_payload, dict) else {}
        base_date, base_source = _order_base_date(item)
        cylinder_type = payload.get("cylinder_type") or "15kg"
        items.append(
            {
                "order_id": item.id,
                "order_no": item.order_no,
                "service_type": item.service_type,
                "cylinder_type": cylinder_type,
                "base_date": base_date.isoformat(),
                "base_source": base_source,
                "order_date": timezone.localtime(item.created_at).date().isoformat(),
            }
        )
    return {"items": items, "total": len(items)}


def calculate_inspection_due(user, order_id=None, order_no=""):
    qs = Order.objects.filter(
        user=user,
        service_type__in=[SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE],
    )
    order = None
    if order_id:
        try:
            order = qs.filter(id=int(order_id)).first()
        except (TypeError, ValueError):
            order = None
    if not order and order_no:
        order = qs.filter(order_no=str(order_no).strip()).first()
    if not order:
        return {"error": "order not found", "code": "ORDER_NOT_FOUND"}

    payload = order.service_payload if isinstance(order.service_payload, dict) else {}
    cylinder_type = payload.get("cylinder_type") or "15kg"
    rule = get_inspection_rule(cylinder_type)
    base_date, base_source = _order_base_date(order)
    next_inspection_date = _add_months(base_date, int(rule["cycle_months"]))
    status = _inspection_status(next_inspection_date)

    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "service_type": order.service_type,
        "cylinder_type": rule["cylinder_type"],
        "cycle_months": rule["cycle_months"],
        "base_date": base_date.isoformat(),
        "base_source": base_source,
        "next_inspection_date": next_inspection_date.isoformat(),
        "status": status,
        "policy_version": rule["policy_version"],
        "source_ref": rule["source_ref"],
        "disclaimer": INSPECTION_POLICY_DISCLAIMER,
    }


def calculate_all_inspection_due(user):
    rows = (
        Order.objects.filter(
            user=user,
            service_type__in=[SERVICE_TYPE_LPG_CYLINDER_DELIVERY, SERVICE_TYPE_CYLINDER_EXCHANGE],
        )
        .order_by("-created_at")
    )
    items = []
    overdue_count = 0
    due_soon_count = 0

    for order in rows:
        payload = order.service_payload if isinstance(order.service_payload, dict) else {}
        cylinder_type = payload.get("cylinder_type") or "15kg"
        rule = get_inspection_rule(cylinder_type)
        base_date, base_source = _order_base_date(order)
        next_inspection_date = _add_months(base_date, int(rule["cycle_months"]))
        status = _inspection_status(next_inspection_date)
        if status == "OVERDUE":
            overdue_count += 1
        elif status == "DUE_SOON":
            due_soon_count += 1
        items.append(
            {
                "order_id": order.id,
                "order_no": order.order_no,
                "service_type": order.service_type,
                "cylinder_type": rule["cylinder_type"],
                "cycle_months": rule["cycle_months"],
                "base_date": base_date.isoformat(),
                "base_source": base_source,
                "next_inspection_date": next_inspection_date.isoformat(),
                "status": status,
                "policy_version": rule["policy_version"],
                "source_ref": rule["source_ref"],
                "disclaimer": INSPECTION_POLICY_DISCLAIMER,
            }
        )

    status_rank = {"OVERDUE": 0, "DUE_SOON": 1, "NORMAL": 2}
    items.sort(
        key=lambda item: (
            status_rank.get(str(item.get("status") or "NORMAL"), 3),
            str(item.get("next_inspection_date") or ""),
            -int(item.get("order_id") or 0),
        )
    )
    return {
        "items": items,
        "total": len(items),
        "overdue_count": overdue_count,
        "due_soon_count": due_soon_count,
    }
