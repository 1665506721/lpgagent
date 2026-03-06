from django.utils import timezone

from .models import CustomerNotification


def build_target_route(target_type, target_id=None):
    if target_type == CustomerNotification.TARGET_ORDER and target_id:
        return f"#/portal/orders/{int(target_id)}"
    if target_type == CustomerNotification.TARGET_FEEDBACK:
        return "#/portal/profile"
    if target_type == CustomerNotification.TARGET_PROFILE:
        return "#/portal/profile"
    if target_type == CustomerNotification.TARGET_ADDRESS:
        return "#/portal/profile"
    if target_type == CustomerNotification.TARGET_CHAT:
        return "#/portal/chat"
    return ""


def create_notification(
    *,
    user,
    category,
    event_code,
    title,
    content,
    level=CustomerNotification.LEVEL_INFO,
    target_type=CustomerNotification.TARGET_NONE,
    target_id=None,
    target_route="",
    meta_json=None,
):
    route = (target_route or "").strip() or build_target_route(target_type, target_id)
    return CustomerNotification.objects.create(
        user=user,
        category=category,
        event_code=event_code,
        title=(title or "").strip()[:120],
        content=(content or "").strip(),
        level=level,
        target_type=target_type,
        target_id=target_id,
        target_route=route,
        meta_json=meta_json or {},
    )


def mark_read(user, notification_id):
    item = CustomerNotification.objects.filter(id=notification_id, user=user).first()
    if not item:
        return None
    if not item.is_read:
        item.is_read = True
        item.read_at = timezone.now()
        item.save(update_fields=["is_read", "read_at"])
    return item


def mark_all_read(user):
    now = timezone.now()
    updated = CustomerNotification.objects.filter(user=user, is_read=False).update(
        is_read=True,
        read_at=now,
    )
    return int(updated)

