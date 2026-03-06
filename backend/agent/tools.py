from django.contrib.auth import get_user_model
from django.db.models import Max, Q
from django.utils import timezone

from core.models import AgentEvent, Order, Ticket
from external.order_provider import get_order_provider
from knowledge_base.retriever import retrieve_by_domain, search_safety

from customer_portal.constants import ACCESSORY_SKU_LABELS, ORDER_STATUS_PENDING_PAYMENT
from customer_portal.models import (
    CustomerAddress,
    CustomerConversationMemory,
    CustomerFeedback,
    CustomerNotification,
    CustomerProfile,
    Order as PortalOrder,
)
from customer_portal.notifications import create_notification
from customer_portal.inspection_service import (
    calculate_all_inspection_due as portal_calculate_all_inspection_due,
    calculate_inspection_due as portal_calculate_inspection_due,
    list_inspection_candidates as portal_list_inspection_candidates,
)
from customer_portal.notifications import mark_all_read as portal_mark_all_notifications_read
from customer_portal.notifications import mark_read as portal_mark_notification_read
from customer_portal.serializers import (
    AddressCreateUpdateSerializer,
    ChangePasswordSerializer,
    CustomerNotificationSerializer,
    FeedbackCreateSerializer,
    OrderCreateSerializer,
    OrderListSerializer,
    OrderModifyAddressSerializer,
    OrderSerializer,
)
from customer_portal.services import (
    add_cart_items as portal_add_cart_items,
    apply_expiration_if_needed,
    cancel_order as portal_cancel_order,
    cart_summary as portal_cart_summary,
    checkout_cart as portal_checkout_cart,
    clear_cart_items as portal_clear_cart_items,
    create_order as portal_create_order,
    get_now as portal_now,
    modify_order_address as portal_modify_order_address,
    pay_order as portal_pay_order,
    remove_cart_items as portal_remove_cart_items,
)


User = get_user_model()


def _next_step_index(run):
    current = AgentEvent.objects.filter(run=run).aggregate(Max("step_index")).get("step_index__max")
    return (current or 0) + 1


def _record_tool_event(run, tool_name, tool_input, tool_output, policy_result=None):
    if policy_result is None:
        policy_result = {"allow": True, "reasons": []}
    AgentEvent.objects.create(
        run=run,
        step_index=_next_step_index(run),
        state=AgentEvent.STATE_TOOL_EXEC,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        policy_result=policy_result,
        created_at=timezone.now(),
    )


def _portal_user_or_error(portal_user_id):
    user = User.objects.filter(id=portal_user_id).first()
    if not user:
        return None, {"error": "portal user not found", "code": "AUTH_REQUIRED"}
    return user, None


def _serialize_notification_item(item):
    return CustomerNotificationSerializer(item).data


def _portal_order_brief(order):
    return {
        "id": order.id,
        "order_no": order.order_no,
        "service_type": order.service_type,
        "status": order.status,
        "amount_total": str(order.amount_total),
        "currency": order.currency,
        "eta_start": order.eta_start.isoformat(),
        "eta_end": order.eta_end.isoformat(),
    }


def _resolve_portal_order(user, tool_input):
    order_id = tool_input.get("order_id")
    order_no = (tool_input.get("order_no") or "").strip()
    qs = PortalOrder.objects.filter(user=user)
    order = None
    if order_id:
        try:
            order = qs.filter(id=int(order_id)).first()
        except (TypeError, ValueError):
            order = None
    if not order and order_no:
        order = qs.filter(order_no=order_no).first()
    return order


def _exec_portal_get_context(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    profile, _ = CustomerProfile.objects.get_or_create(
        user=user,
        defaults={"phone": user.username, "display_name": user.username},
    )
    addresses_limit = 10
    base_qs = CustomerAddress.objects.filter(user=user).order_by("-is_default", "-created_at")
    total_addresses = base_qs.count()
    addresses = list(base_qs[:addresses_limit])
    default_address = next((item for item in addresses if item.is_default), addresses[0] if addresses else None)
    output = {
        "profile": {
            "phone": profile.phone,
            "display_name": profile.display_name,
        },
        "default_address": (
            {
                "id": default_address.id,
                "contact_name": default_address.contact_name,
                "contact_phone": default_address.contact_phone,
                "address_full": default_address.address_full,
                "door_note": default_address.door_note,
                "is_default": default_address.is_default,
            }
            if default_address
            else None
        ),
        "addresses": [
            {
                "id": item.id,
                "contact_name": item.contact_name,
                "contact_phone": item.contact_phone,
                "address_full": item.address_full,
                "door_note": item.door_note,
                "is_default": item.is_default,
            }
            for item in addresses
        ],
        "addresses_limit": addresses_limit,
        "addresses_truncated": bool(total_addresses > addresses_limit),
    }
    memory = CustomerConversationMemory.objects.filter(user=user).first()
    if memory and isinstance(memory.memory_json, dict):
        output["memory"] = memory.memory_json
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_list_orders(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    status_filter = (tool_input.get("status") or "").strip()
    keyword = (tool_input.get("keyword") or "").strip()
    page = max(1, int(tool_input.get("page") or 1))
    page_size = max(1, min(20, int(tool_input.get("page_size") or 5)))

    now = portal_now()
    for item in PortalOrder.objects.filter(user=user, status=ORDER_STATUS_PENDING_PAYMENT, expires_at__lte=now):
        apply_expiration_if_needed(item, now=now)

    qs = PortalOrder.objects.filter(user=user)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if keyword:
        qs = qs.filter(
            Q(order_no__icontains=keyword)
            | Q(service_type__icontains=keyword)
            | Q(notes__icontains=keyword)
        )
    total = qs.count()
    offset = (page - 1) * page_size
    items = qs.order_by("-created_at")[offset : offset + page_size]
    output = {
        "items": OrderListSerializer(items, many=True).data,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_get_order(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    order = _resolve_portal_order(user, tool_input)
    if not order:
        output = {"error": "order not found", "code": "ORDER_NOT_FOUND"}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["order_not_found"]})
        return output

    apply_expiration_if_needed(order)
    output = OrderSerializer(order).data
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_get_inspection_candidates(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err
    limit = tool_input.get("limit", 6)
    try:
        limit = max(1, min(12, int(limit)))
    except (TypeError, ValueError):
        limit = 6
    output = portal_list_inspection_candidates(user=user, limit=limit)
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_calc_inspection_due(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err
    output = portal_calculate_inspection_due(
        user=user,
        order_id=tool_input.get("order_id"),
        order_no=tool_input.get("order_no"),
    )
    if output.get("error"):
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": [str(output.get("code") or "inspection_failed").lower()]},
        )
        return output
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_calc_all_inspection_due(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err
    output = portal_calculate_all_inspection_due(user=user)
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _build_snapshots_for_create(user, validated_data):
    address_id = validated_data.get("address_id")
    if address_id:
        address = CustomerAddress.objects.filter(id=address_id, user=user).first()
        if not address:
            return None, None, {"error": "address not found", "code": "VALIDATION_ERROR", "details": {"address_id": "not_found"}}
        address_snapshot = {
            "address_full": address.address_full,
            "door_note": address.door_note,
        }
        contact_snapshot = {
            "contact_name": validated_data.get("contact_name") or address.contact_name,
            "contact_phone": validated_data.get("contact_phone") or address.contact_phone,
        }
        return address_snapshot, contact_snapshot, None

    address_snapshot = {
        "address_full": validated_data.get("address_full", ""),
        "door_note": validated_data.get("door_note", ""),
    }
    contact_snapshot = {
        "contact_name": validated_data.get("contact_name", ""),
        "contact_phone": validated_data.get("contact_phone", ""),
    }
    return address_snapshot, contact_snapshot, None


def _exec_portal_create_order(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    payload = tool_input.get("payload")
    if not isinstance(payload, dict):
        output = {"error": "payload is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["missing_payload"]})
        return output

    serializer = OrderCreateSerializer(data=payload)
    if not serializer.is_valid():
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": serializer.errors}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["invalid_payload"]})
        return output

    data = serializer.validated_data
    address_snapshot, contact_snapshot, snapshot_error = _build_snapshots_for_create(user, data)
    if snapshot_error:
        _record_tool_event(run, tool_name, tool_input, snapshot_error, policy_result={"allow": False, "reasons": ["invalid_address"]})
        return snapshot_error

    try:
        order = portal_create_order(
            user=user,
            service_type=data["service_type"],
            service_payload=data["service_payload"],
            contact_snapshot=contact_snapshot,
            address_snapshot=address_snapshot,
            eta_date=data.get("eta_date"),
            eta_slot=data.get("eta_slot"),
            is_urgent=data.get("is_urgent", False),
            notes=data.get("notes", ""),
        )
    except ValueError as exc:
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": {"detail": str(exc)}}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["domain_validation_failed"]})
        return output

    output = {
        "message": "order created",
        **_portal_order_brief(order),
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_pay_order(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    order = _resolve_portal_order(user, tool_input)
    if not order:
        output = {"error": "order not found", "code": "ORDER_NOT_FOUND"}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["order_not_found"]})
        return output

    updated, code = portal_pay_order(order)
    if code:
        output = {"error": "pay failed", "code": code, "order_no": order.order_no}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": [code.lower()]})
        return output

    output = {"message": "paid", **_portal_order_brief(updated)}
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_cancel_order(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    order = _resolve_portal_order(user, tool_input)
    if not order:
        output = {"error": "order not found", "code": "ORDER_NOT_FOUND"}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["order_not_found"]})
        return output

    updated, code = portal_cancel_order(order)
    if code:
        output = {"error": "cancel failed", "code": code, "order_no": order.order_no}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": [code.lower()]})
        return output

    output = {"message": "canceled", **_portal_order_brief(updated)}
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_modify_address(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    order = _resolve_portal_order(user, tool_input)
    if not order:
        output = {"error": "order not found", "code": "ORDER_NOT_FOUND"}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["order_not_found"]})
        return output

    payload = tool_input.get("payload")
    if not isinstance(payload, dict):
        output = {"error": "payload is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["missing_payload"]})
        return output

    serializer = OrderModifyAddressSerializer(data=payload)
    if not serializer.is_valid():
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": serializer.errors}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["invalid_payload"]})
        return output

    data = serializer.validated_data
    if data.get("address_id"):
        address = CustomerAddress.objects.filter(id=data["address_id"], user=user).first()
        if not address:
            output = {"error": "address not found", "code": "VALIDATION_ERROR", "details": {"address_id": "not_found"}}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["address_not_found"]})
            return output
        address_snapshot = {
            "address_full": address.address_full,
            "door_note": address.door_note,
        }
        contact_snapshot = {
            "contact_name": data.get("contact_name") or address.contact_name,
            "contact_phone": data.get("contact_phone") or address.contact_phone,
        }
    else:
        address_snapshot = {
            "address_full": data.get("address_full", ""),
            "door_note": data.get("door_note", ""),
        }
        contact_snapshot = {
            "contact_name": data.get("contact_name", ""),
            "contact_phone": data.get("contact_phone", ""),
        }

    updated, code = portal_modify_order_address(order, address_snapshot, contact_snapshot)
    if code:
        output = {"error": "modify address failed", "code": code, "order_no": order.order_no}
        if code in {"ORDER_NOT_EDITABLE", "ORDER_EXPIRED"}:
            output["address_snapshot"] = dict(order.address_snapshot or {})
            output["contact_snapshot"] = dict(order.contact_snapshot or {})
            output["address_edit_deadline"] = (
                order.address_edit_deadline.isoformat() if getattr(order, "address_edit_deadline", None) else None
            )
            output["cancel_deadline"] = order.cancel_deadline.isoformat() if getattr(order, "cancel_deadline", None) else None
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": [code.lower()]})
        return output

    output = {
        "message": "address updated",
        **_portal_order_brief(updated),
        "address_snapshot": dict(updated.address_snapshot or {}),
        "contact_snapshot": dict(updated.contact_snapshot or {}),
        "address_edit_deadline": (
            updated.address_edit_deadline.isoformat() if getattr(updated, "address_edit_deadline", None) else None
        ),
        "cancel_deadline": updated.cancel_deadline.isoformat() if getattr(updated, "cancel_deadline", None) else None,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_create_feedback(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    payload = tool_input.get("payload")
    if not isinstance(payload, dict):
        output = {"error": "payload is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["missing_payload"]})
        return output

    serializer = FeedbackCreateSerializer(data=payload)
    if not serializer.is_valid():
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": serializer.errors}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["invalid_payload"]})
        return output

    data = serializer.validated_data
    order = None
    if data.get("order_id"):
        order = PortalOrder.objects.filter(id=data["order_id"], user=user).first()
        if not order:
            output = {"error": "order not found", "code": "ORDER_NOT_FOUND"}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["order_not_found"]})
            return output

    feedback = CustomerFeedback.objects.create(
        user=user,
        order=order,
        feedback_type=data["feedback_type"],
        target_type=data["target_type"],
        title=data["title"].strip(),
        content=data["content"].strip(),
        contact_phone=data.get("contact_phone", ""),
    )
    feedback_label = "投诉" if feedback.feedback_type == CustomerFeedback.TYPE_COMPLAINT else "建议"
    create_notification(
        user=user,
        category=CustomerNotification.CATEGORY_FEEDBACK,
        event_code="FEEDBACK_CREATED",
        title=f"{feedback_label}已提交",
        content=f"{feedback_label}已提交（编号 #{feedback.id}），当前状态：{feedback.status}。",
        level=CustomerNotification.LEVEL_SUCCESS,
        target_type=CustomerNotification.TARGET_FEEDBACK,
        target_id=feedback.id,
        target_route="#/portal/profile",
        meta_json={"feedback_id": feedback.id, "feedback_type": feedback.feedback_type},
    )
    output = {
        "message": "feedback created",
        "id": feedback.id,
        "feedback_type": feedback.feedback_type,
        "target_type": feedback.target_type,
        "status": feedback.status,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_list_feedbacks(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err

    limit = tool_input.get("limit", 5)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(20, limit))

    status_filter = str(tool_input.get("status") or "").strip().upper()
    qs = CustomerFeedback.objects.filter(user=user)
    if status_filter:
        qs = qs.filter(status=status_filter)

    rows = qs.order_by("-created_at")[:limit]
    items = []
    for item in rows:
        items.append(
            {
                "id": item.id,
                "feedback_type": item.feedback_type,
                "target_type": item.target_type,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
                "order_no": item.order.order_no if item.order else "",
            }
        )
    output = {"items": items, "limit": limit, "status": status_filter}
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_get_cart(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err
    summary = portal_cart_summary(user)
    output = {
        "items": [
            {
                "sku": item.get("sku"),
                "name": item.get("name") or ACCESSORY_SKU_LABELS.get(item.get("sku"), item.get("sku")),
                "category": item.get("category") or "閰嶄欢",
                "quantity": int(item.get("quantity") or 0),
                "price": str(item.get("price") or "0"),
                "amount": str(item.get("amount") or "0"),
            }
            for item in (summary.get("items") or [])
        ],
        "selected_count": int(summary.get("selected_count") or 0),
        "total_amount": str(summary.get("total_amount") or "0"),
        "currency": summary.get("currency") or "CNY",
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_cart_add(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err
    items = tool_input.get("items")
    try:
        portal_add_cart_items(user, items)
    except ValueError as exc:
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": {"detail": str(exc)}}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["invalid_payload"]})
        return output
    summary = portal_cart_summary(user)
    output = {
        "message": "cart updated",
        "selected_count": int(summary.get("selected_count") or 0),
        "total_amount": str(summary.get("total_amount") or "0"),
        "currency": summary.get("currency") or "CNY",
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_cart_remove(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err
    items = tool_input.get("items")
    try:
        portal_remove_cart_items(user, items)
    except ValueError as exc:
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": {"detail": str(exc)}}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["invalid_payload"]})
        return output
    summary = portal_cart_summary(user)
    output = {
        "message": "cart updated",
        "selected_count": int(summary.get("selected_count") or 0),
        "total_amount": str(summary.get("total_amount") or "0"),
        "currency": summary.get("currency") or "CNY",
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_cart_clear(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err
    deleted = portal_clear_cart_items(user)
    output = {"message": "cart cleared", "deleted_count": deleted}
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_cart_checkout(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(run, tool_name, tool_input, err, policy_result={"allow": False, "reasons": ["auth_required"]})
        return err
    payload = tool_input.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        order = portal_checkout_cart(
            user,
            address_id=payload.get("address_id"),
            eta_date=payload.get("eta_date"),
            eta_slot=payload.get("eta_slot"),
            is_urgent=bool(payload.get("is_urgent")),
            notes=payload.get("notes") or "",
            invoice_required=bool(payload.get("need_invoice")),
            invoice_title=payload.get("invoice_title") or "",
            invoice_tax_no=payload.get("invoice_tax_no") or "",
            auto_pay=bool(payload.get("auto_pay", True)),
        )
    except ValueError as exc:
        detail = str(exc)
        code = "VALIDATION_ERROR"
        if detail == "cart_empty":
            code = "CART_EMPTY"
        elif detail == "address_required":
            code = "ADDRESS_REQUIRED"
        elif detail in {"ORDER_EXPIRED", "ORDER_NOT_EDITABLE"}:
            code = detail
        output = {"error": "checkout failed", "code": code, "details": {"detail": detail}}
        _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": [code.lower()]})
        return output

    output = {
        "message": "checkout success",
        **_portal_order_brief(order),
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_update_profile(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    payload = tool_input.get("payload")
    if not isinstance(payload, dict):
        output = {"error": "payload is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["missing_payload"]},
        )
        return output

    display_name = str(payload.get("display_name") or "").strip()
    if len(display_name) < 2 or len(display_name) > 64:
        output = {
            "error": "invalid payload",
            "code": "VALIDATION_ERROR",
            "details": {"display_name": "length_2_64"},
        }
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["invalid_display_name"]},
        )
        return output

    profile, _ = CustomerProfile.objects.get_or_create(
        user=user,
        defaults={"phone": user.username, "display_name": user.username},
    )
    profile.display_name = display_name
    profile.save(update_fields=["display_name"])
    create_notification(
        user=user,
        category=CustomerNotification.CATEGORY_PROFILE,
        event_code="PROFILE_UPDATED",
        title="个人资料已更新",
        content=f"您的昵称已更新为 {profile.display_name}。",
        level=CustomerNotification.LEVEL_INFO,
        target_type=CustomerNotification.TARGET_PROFILE,
        target_route="#/portal/profile",
        meta_json={"display_name": profile.display_name},
    )
    output = {
        "message": "profile updated",
        "phone": profile.phone,
        "display_name": profile.display_name,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_create_address(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    payload = tool_input.get("payload")
    if not isinstance(payload, dict):
        output = {"error": "payload is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["missing_payload"]},
        )
        return output

    serializer = AddressCreateUpdateSerializer(data=payload)
    if not serializer.is_valid():
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": serializer.errors}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["invalid_payload"]},
        )
        return output

    is_default = bool(serializer.validated_data.get("is_default", False))
    if not CustomerAddress.objects.filter(user=user).exists():
        is_default = True
    address = serializer.save(user=user, is_default=is_default)
    if is_default:
        CustomerAddress.objects.filter(user=user).exclude(id=address.id).update(is_default=False)
    create_notification(
        user=user,
        category=CustomerNotification.CATEGORY_ADDRESS,
        event_code="ADDRESS_CREATED",
        title="地址已新增",
        content=f"已新增地址：{address.address_full}",
        level=CustomerNotification.LEVEL_INFO,
        target_type=CustomerNotification.TARGET_ADDRESS,
        target_id=address.id,
        target_route="#/portal/profile",
        meta_json={"address_id": address.id},
    )
    output = {
        "message": "address created",
        "id": address.id,
        "contact_name": address.contact_name,
        "contact_phone": address.contact_phone,
        "address_full": address.address_full,
        "door_note": address.door_note,
        "is_default": address.is_default,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_update_address(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    address_id = tool_input.get("address_id")
    try:
        address_id = int(address_id)
    except (TypeError, ValueError):
        address_id = None
    if not address_id:
        output = {"error": "address_id is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["missing_address_id"]},
        )
        return output

    address = CustomerAddress.objects.filter(id=address_id, user=user).first()
    if not address:
        output = {"error": "address not found", "code": "VALIDATION_ERROR", "details": {"address_id": "not_found"}}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["address_not_found"]},
        )
        return output

    payload = tool_input.get("payload")
    if not isinstance(payload, dict):
        output = {"error": "payload is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["missing_payload"]},
        )
        return output

    serializer = AddressCreateUpdateSerializer(address, data=payload, partial=True)
    if not serializer.is_valid():
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": serializer.errors}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["invalid_payload"]},
        )
        return output

    is_default = serializer.validated_data.get("is_default", address.is_default)
    updated = serializer.save(is_default=is_default)
    if updated.is_default:
        CustomerAddress.objects.filter(user=user).exclude(id=updated.id).update(is_default=False)
    create_notification(
        user=user,
        category=CustomerNotification.CATEGORY_ADDRESS,
        event_code="ADDRESS_UPDATED",
        title="地址已更新",
        content=f"地址已更新为：{updated.address_full}",
        level=CustomerNotification.LEVEL_INFO,
        target_type=CustomerNotification.TARGET_ADDRESS,
        target_id=updated.id,
        target_route="#/portal/profile",
        meta_json={"address_id": updated.id},
    )

    output = {
        "message": "address updated",
        "id": updated.id,
        "contact_name": updated.contact_name,
        "contact_phone": updated.contact_phone,
        "address_full": updated.address_full,
        "door_note": updated.door_note,
        "is_default": updated.is_default,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_set_default_address(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    address_id = tool_input.get("address_id")
    try:
        address_id = int(address_id)
    except (TypeError, ValueError):
        address_id = None
    if not address_id:
        output = {"error": "address_id is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["missing_address_id"]},
        )
        return output

    address = CustomerAddress.objects.filter(id=address_id, user=user).first()
    if not address:
        output = {"error": "address not found", "code": "VALIDATION_ERROR", "details": {"address_id": "not_found"}}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["address_not_found"]},
        )
        return output

    CustomerAddress.objects.filter(user=user).exclude(id=address.id).update(is_default=False)
    address.is_default = True
    address.save(update_fields=["is_default"])
    create_notification(
        user=user,
        category=CustomerNotification.CATEGORY_ADDRESS,
        event_code="ADDRESS_SET_DEFAULT",
        title="默认地址已更新",
        content=f"已将默认地址设置为：{address.address_full}",
        level=CustomerNotification.LEVEL_INFO,
        target_type=CustomerNotification.TARGET_ADDRESS,
        target_id=address.id,
        target_route="#/portal/profile",
        meta_json={"address_id": address.id},
    )
    output = {
        "message": "default address updated",
        "id": address.id,
        "contact_name": address.contact_name,
        "contact_phone": address.contact_phone,
        "address_full": address.address_full,
        "door_note": address.door_note,
        "is_default": address.is_default,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_delete_address(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    address_id = tool_input.get("address_id")
    try:
        address_id = int(address_id)
    except (TypeError, ValueError):
        address_id = None
    if not address_id:
        output = {"error": "address_id is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["missing_address_id"]},
        )
        return output

    address = CustomerAddress.objects.filter(id=address_id, user=user).first()
    if not address:
        output = {"error": "address not found", "code": "VALIDATION_ERROR", "details": {"address_id": "not_found"}}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["address_not_found"]},
        )
        return output

    deleted_id = address.id
    deleted_text = address.address_full
    was_default = bool(address.is_default)
    address.delete()

    next_default = None
    if was_default:
        next_default = CustomerAddress.objects.filter(user=user).order_by("-created_at").first()
        if next_default:
            CustomerAddress.objects.filter(user=user).exclude(id=next_default.id).update(is_default=False)
            next_default.is_default = True
            next_default.save(update_fields=["is_default"])

    create_notification(
        user=user,
        category=CustomerNotification.CATEGORY_ADDRESS,
        event_code="ADDRESS_DELETED",
        title="地址已删除",
        content=f"地址已删除：{deleted_text}",
        level=CustomerNotification.LEVEL_INFO,
        target_type=CustomerNotification.TARGET_ADDRESS,
        target_route="#/portal/profile",
        meta_json={
            "deleted_id": deleted_id,
            "was_default": was_default,
            "new_default_id": next_default.id if next_default else None,
        },
    )
    output = {
        "message": "address deleted",
        "deleted_id": deleted_id,
        "was_default": was_default,
        "new_default_id": next_default.id if next_default else None,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_change_password(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    safe_tool_input = {
        "portal_user_id": tool_input.get("portal_user_id"),
        "payload": {"old_password": "***", "new_password": "***", "confirm_password": "***"},
    }
    if err:
        _record_tool_event(
            run,
            tool_name,
            safe_tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    payload = tool_input.get("payload")
    if not isinstance(payload, dict):
        output = {"error": "payload is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(
            run,
            tool_name,
            safe_tool_input,
            output,
            policy_result={"allow": False, "reasons": ["missing_payload"]},
        )
        return output

    serializer = ChangePasswordSerializer(data=payload)
    if not serializer.is_valid():
        output = {"error": "invalid payload", "code": "VALIDATION_ERROR", "details": serializer.errors}
        _record_tool_event(
            run,
            tool_name,
            safe_tool_input,
            output,
            policy_result={"allow": False, "reasons": ["invalid_payload"]},
        )
        return output

    old_password = serializer.validated_data["old_password"]
    new_password = serializer.validated_data["new_password"]
    if not user.check_password(old_password):
        output = {"error": "old password invalid", "code": "VALIDATION_ERROR", "details": {"old_password": "invalid"}}
        _record_tool_event(
            run,
            tool_name,
            safe_tool_input,
            output,
            policy_result={"allow": False, "reasons": ["invalid_old_password"]},
        )
        return output

    user.set_password(new_password)
    user.save(update_fields=["password"])
    create_notification(
        user=user,
        category=CustomerNotification.CATEGORY_PROFILE,
        event_code="PASSWORD_CHANGED",
        title="登录密码已修改",
        content="您的登录密码已修改成功。",
        level=CustomerNotification.LEVEL_INFO,
        target_type=CustomerNotification.TARGET_PROFILE,
        target_route="#/portal/profile",
    )
    output = {"message": "password changed"}
    _record_tool_event(run, tool_name, safe_tool_input, {"message": "password changed"})
    return output


def _exec_portal_list_notifications(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    try:
        page = int(tool_input.get("page") or 1)
        page_size = int(tool_input.get("page_size") or 10)
    except (TypeError, ValueError):
        page = 1
        page_size = 10
    page = max(1, page)
    page_size = max(1, min(50, page_size))
    only_unread = bool(tool_input.get("only_unread"))

    qs = CustomerNotification.objects.filter(user=user)
    unread_count = qs.filter(is_read=False).count()
    if only_unread:
        qs = qs.filter(is_read=False)
    total = qs.count()
    offset = (page - 1) * page_size
    items = qs.order_by("-created_at")[offset : offset + page_size]
    output = {
        "items": [_serialize_notification_item(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
        "unread_count": unread_count,
        "only_unread": only_unread,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_read_notification(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    notification_id = tool_input.get("notification_id")
    try:
        notification_id = int(notification_id)
    except (TypeError, ValueError):
        notification_id = None
    if not notification_id:
        output = {"error": "notification_id is required", "code": "VALIDATION_ERROR"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["missing_notification_id"]},
        )
        return output

    item = portal_mark_notification_read(user, notification_id)
    if not item:
        output = {"error": "notification not found", "code": "NOTIFICATION_NOT_FOUND"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["notification_not_found"]},
        )
        return output
    output = _serialize_notification_item(item)
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_read_all_notifications(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err
    updated_count = portal_mark_all_notifications_read(user)
    output = {"updated_count": int(updated_count)}
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def _exec_portal_request_refund(run, tool_name, tool_input):
    user, err = _portal_user_or_error(tool_input.get("portal_user_id"))
    if err:
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            err,
            policy_result={"allow": False, "reasons": ["auth_required"]},
        )
        return err

    order = _resolve_portal_order(user, tool_input)
    if not order:
        output = {"error": "order not found", "code": "ORDER_NOT_FOUND"}
        _record_tool_event(
            run,
            tool_name,
            tool_input,
            output,
            policy_result={"allow": False, "reasons": ["order_not_found"]},
        )
        return output

    reason = str(tool_input.get("reason") or "").strip()
    if not reason:
        reason = "用户通过客服申请退款"

    feedback = CustomerFeedback.objects.create(
        user=user,
        order=order,
        feedback_type=CustomerFeedback.TYPE_COMPLAINT,
        target_type=CustomerFeedback.TARGET_ORDER,
        title="退款申请",
        content=reason,
        contact_phone=(order.contact_snapshot or {}).get("contact_phone", ""),
    )
    create_notification(
        user=user,
        category=CustomerNotification.CATEGORY_FEEDBACK,
        event_code="REFUND_REQUEST_CREATED",
        title="退款申请已提交",
        content=f"订单 {order.order_no} 的退款申请已提交（编号 #{feedback.id}）。",
        level=CustomerNotification.LEVEL_INFO,
        target_type=CustomerNotification.TARGET_FEEDBACK,
        target_id=feedback.id,
        target_route="#/portal/profile",
        meta_json={"feedback_id": feedback.id, "order_no": order.order_no},
    )
    output = {
        "message": "refund request submitted",
        "id": feedback.id,
        "order_no": order.order_no,
        "status": feedback.status,
    }
    _record_tool_event(run, tool_name, tool_input, output)
    return output


def execute_tool(run, tool_name, tool_input):
    if tool_name == "create_order":
        order = Order.objects.create(
            user_id=tool_input.get("user_id"),
            product_type=tool_input.get("product_type", ""),
            quantity=int(tool_input.get("quantity") or 1),
            address=tool_input.get("address", ""),
            status=Order.STATUS_CREATED,
        )
        output = {"order_id": order.id, "status": order.status, "message": "Order created"}
        _record_tool_event(run, tool_name, tool_input, output)
        return output

    if tool_name == "create_ticket":
        ticket = Ticket.objects.create(
            user_id=tool_input.get("user_id"),
            order_id=tool_input.get("order_id"),
            category=tool_input.get("category", Ticket.CATEGORY_OTHER),
            description=tool_input.get("description", ""),
            status=Ticket.STATUS_OPEN,
        )
        output = {"ticket_id": ticket.id, "status": ticket.status, "message": "Ticket created"}
        _record_tool_event(run, tool_name, tool_input, output)
        return output

    if tool_name == "modify_order_address":
        order_id = tool_input.get("order_id")
        new_address = tool_input.get("new_address")
        if not order_id or not new_address:
            output = {"error": "order_id and new_address are required"}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["missing_params"]})
            return output
        order = Order.objects.filter(id=order_id).first()
        if not order:
            output = {"error": "order not found"}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["order_not_found"]})
            return output
        old_address = order.address
        order.address = new_address
        order.save(update_fields=["address", "updated_at"])
        output = {
            "order_id": order.id,
            "old_address": old_address,
            "new_address": new_address,
            "status": order.status,
            "message": "address updated",
        }
        _record_tool_event(run, tool_name, tool_input, output)
        return output

    if tool_name == "query_order":
        order_id = tool_input.get("order_id")
        order = Order.objects.filter(id=order_id).first()
        if not order:
            output = {"error": "order not found"}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["order_not_found"]})
            return output
        output = {
            "order_id": order.id,
            "status": order.status,
            "product_type": order.product_type,
            "quantity": order.quantity,
            "address": order.address,
            "created_at": order.created_at.isoformat(),
        }
        _record_tool_event(run, tool_name, tool_input, output)
        return output

    if tool_name == "external_query_order":
        order_id = tool_input.get("order_id")
        if not order_id:
            output = {"error": "order_id is required"}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["missing_order_id"]})
            return output
        provider = get_order_provider()
        order = provider.get_order(order_id)
        if not order:
            output = {"error": "order not found"}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["order_not_found"]})
            return output
        _record_tool_event(run, tool_name, tool_input, order)
        return order

    if tool_name == "external_query_orders_by_phone":
        phone = tool_input.get("phone")
        if not phone:
            output = {"error": "phone is required"}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["missing_phone"]})
            return output
        limit = tool_input.get("limit", 10)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        provider = get_order_provider()
        results = provider.list_orders_by_phone(phone, limit=limit)
        output = {"phone": phone, "results": results}
        _record_tool_event(run, tool_name, tool_input, output)
        return output

    if tool_name == "safety_search":
        query = tool_input.get("query", "")
        top_k = tool_input.get("top_k", 4)
        output = {"query": query, "results": search_safety(query, top_k=top_k)}
        _record_tool_event(run, tool_name, tool_input, output)
        return output

    if tool_name == "kb_search":
        domain = tool_input.get("domain")
        query = tool_input.get("query", "")
        if not domain or not query:
            output = {"error": "domain and query are required"}
            _record_tool_event(run, tool_name, tool_input, output, policy_result={"allow": False, "reasons": ["missing_params"]})
            return output
        output = {"domain": domain, "query": query, "results": retrieve_by_domain(domain, query, top_k=tool_input.get("top_k", 4))}
        _record_tool_event(run, tool_name, tool_input, output)
        return output

    if tool_name == "portal_get_context":
        return _exec_portal_get_context(run, tool_name, tool_input)
    if tool_name == "portal_list_orders":
        return _exec_portal_list_orders(run, tool_name, tool_input)
    if tool_name == "portal_get_order":
        return _exec_portal_get_order(run, tool_name, tool_input)
    if tool_name == "portal_get_inspection_candidates":
        return _exec_portal_get_inspection_candidates(run, tool_name, tool_input)
    if tool_name == "portal_calc_inspection_due":
        return _exec_portal_calc_inspection_due(run, tool_name, tool_input)
    if tool_name == "portal_calc_all_inspection_due":
        return _exec_portal_calc_all_inspection_due(run, tool_name, tool_input)
    if tool_name == "portal_create_order":
        return _exec_portal_create_order(run, tool_name, tool_input)
    if tool_name == "portal_pay_order":
        return _exec_portal_pay_order(run, tool_name, tool_input)
    if tool_name == "portal_cancel_order":
        return _exec_portal_cancel_order(run, tool_name, tool_input)
    if tool_name == "portal_modify_order_address":
        return _exec_portal_modify_address(run, tool_name, tool_input)
    if tool_name == "portal_create_feedback":
        return _exec_portal_create_feedback(run, tool_name, tool_input)
    if tool_name == "portal_list_feedbacks":
        return _exec_portal_list_feedbacks(run, tool_name, tool_input)
    if tool_name == "portal_get_cart":
        return _exec_portal_get_cart(run, tool_name, tool_input)
    if tool_name == "portal_cart_add":
        return _exec_portal_cart_add(run, tool_name, tool_input)
    if tool_name == "portal_cart_remove":
        return _exec_portal_cart_remove(run, tool_name, tool_input)
    if tool_name == "portal_cart_clear":
        return _exec_portal_cart_clear(run, tool_name, tool_input)
    if tool_name == "portal_cart_checkout":
        return _exec_portal_cart_checkout(run, tool_name, tool_input)
    if tool_name == "portal_update_profile":
        return _exec_portal_update_profile(run, tool_name, tool_input)
    if tool_name == "portal_create_address":
        return _exec_portal_create_address(run, tool_name, tool_input)
    if tool_name == "portal_update_address":
        return _exec_portal_update_address(run, tool_name, tool_input)
    if tool_name == "portal_set_default_address":
        return _exec_portal_set_default_address(run, tool_name, tool_input)
    if tool_name == "portal_delete_address":
        return _exec_portal_delete_address(run, tool_name, tool_input)
    if tool_name == "portal_change_password":
        return _exec_portal_change_password(run, tool_name, tool_input)
    if tool_name == "portal_list_notifications":
        return _exec_portal_list_notifications(run, tool_name, tool_input)
    if tool_name == "portal_read_notification":
        return _exec_portal_read_notification(run, tool_name, tool_input)
    if tool_name == "portal_read_all_notifications":
        return _exec_portal_read_all_notifications(run, tool_name, tool_input)
    if tool_name == "portal_request_refund":
        return _exec_portal_request_refund(run, tool_name, tool_input)

    output = {"error": "unsupported tool"}
    _record_tool_event(
        run,
        tool_name,
        tool_input,
        output,
        policy_result={"allow": False, "reasons": ["unsupported_tool"]},
    )
    return output

