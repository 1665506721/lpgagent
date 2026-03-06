import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from .constants import (
    CN_PHONE_PATTERN,
    DEFAULT_CURRENCY,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING_PAYMENT,
    ORDER_STATUS_SCHEDULED,
    PAYMENT_METHOD_MOCK,
    PAYMENT_STATUS_MOCK,
    SERVICE_TYPE_CYLINDER_EXCHANGE,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
    SERVICE_TYPE_SAFETY_CHECK,
    TEST_ACCOUNT_PASSWORD,
    TEST_ACCOUNT_PHONE,
)
from .models import CustomerAddress, CustomerProfile, Order, OrderEvent, PaymentTransaction


def normalize_phone(phone):
    return (phone or "").strip()


def is_valid_phone(phone):
    normalized = normalize_phone(phone)
    if normalized == TEST_ACCOUNT_PHONE:
        return True
    return bool(re.fullmatch(CN_PHONE_PATTERN, normalized))


def _ensure_test_addresses(user):
    addresses = list(CustomerAddress.objects.filter(user=user).order_by("-is_default", "-created_at"))
    if addresses:
        if not any(item.is_default for item in addresses):
            first = addresses[0]
            first.is_default = True
            first.save(update_fields=["is_default"])
        return next((item for item in addresses if item.is_default), addresses[0])

    default_addr = CustomerAddress.objects.create(
        user=user,
        contact_name="测试用户",
        contact_phone=TEST_ACCOUNT_PHONE,
        address_full="上海市浦东新区张江路 88 号",
        door_note="3号楼 402",
        is_default=True,
    )
    CustomerAddress.objects.create(
        user=user,
        contact_name="测试用户",
        contact_phone=TEST_ACCOUNT_PHONE,
        address_full="上海市徐汇区漕河泾开发区 99 号",
        door_note="A座 1205",
        is_default=False,
    )
    return default_addr


def _seed_order_events(order, status):
    if not OrderEvent.objects.filter(order=order, event_type="CREATED").exists():
        OrderEvent.objects.create(order=order, event_type="CREATED", payload={"status": ORDER_STATUS_PENDING_PAYMENT})
    if status in {ORDER_STATUS_PAID, ORDER_STATUS_SCHEDULED, ORDER_STATUS_COMPLETED}:
        if not OrderEvent.objects.filter(order=order, event_type="PAID").exists():
            OrderEvent.objects.create(order=order, event_type="PAID", payload={"status": ORDER_STATUS_PAID})
    if status == ORDER_STATUS_COMPLETED:
        if not OrderEvent.objects.filter(order=order, event_type="COMPLETED").exists():
            OrderEvent.objects.create(order=order, event_type="COMPLETED", payload={"status": ORDER_STATUS_COMPLETED})


def _seed_test_orders(user, default_address):
    now = timezone.localtime(timezone.now())
    snapshot_address = {"address_full": default_address.address_full, "door_note": default_address.door_note}
    snapshot_contact = {"contact_name": default_address.contact_name, "contact_phone": default_address.contact_phone}

    seeds = [
        {
            "order_no": "LPG2024020109001101",
            "service_type": SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            "status": ORDER_STATUS_COMPLETED,
            "days_ago": 380,
            "eta_start_hour": 10,
            "subtotal": Decimal("240.00"),
            "urgent_fee": Decimal("0.00"),
            "service_payload": {
                "cylinder_type": "15kg",
                "quantity": 2,
                "cylinder_serials": ["SH15-A1001", "SH15-A1002"],
                "last_inspection_date": "2024-01-28",
                "inspection_cycle_months": 12,
                "next_inspection_date": "2025-01-28",
            },
            "notes": "企业食堂备气",
        },
        {
            "order_no": "LPG2024101510301102",
            "service_type": SERVICE_TYPE_CYLINDER_EXCHANGE,
            "status": ORDER_STATUS_COMPLETED,
            "days_ago": 125,
            "eta_start_hour": 14,
            "subtotal": Decimal("120.00"),
            "urgent_fee": Decimal("10.00"),
            "service_payload": {
                "cylinder_type": "15kg",
                "quantity": 1,
                "return_empty": True,
                "cylinder_serials": ["SH15-B2008"],
                "last_inspection_date": "2025-10-10",
                "inspection_cycle_months": 12,
                "next_inspection_date": "2026-10-10",
            },
            "notes": "旧瓶置换",
        },
        {
            "order_no": "LPG2024113016001103",
            "service_type": SERVICE_TYPE_SAFETY_CHECK,
            "status": ORDER_STATUS_COMPLETED,
            "days_ago": 80,
            "eta_start_hour": 16,
            "subtotal": Decimal("99.00"),
            "urgent_fee": Decimal("0.00"),
            "service_payload": {
                "check_scope": "气瓶与减压阀年度安检",
                "inspection_result": "PASS",
                "next_inspection_date": "2026-11-30",
            },
            "notes": "年度安检完成",
        },
        {
            "order_no": "LPG2026020111001104",
            "service_type": SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            "status": ORDER_STATUS_SCHEDULED,
            "days_ago": 2,
            "eta_start_hour": 11,
            "subtotal": Decimal("120.00"),
            "urgent_fee": Decimal("0.00"),
            "service_payload": {
                "cylinder_type": "15kg",
                "quantity": 1,
                "cylinder_serials": ["SH15-C3011"],
                "last_inspection_date": "2026-01-15",
                "inspection_cycle_months": 12,
                "next_inspection_date": "2027-01-15",
            },
            "notes": "常规配送",
        },
        {
            "order_no": "LPG2026021909451105",
            "service_type": SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            "status": ORDER_STATUS_PENDING_PAYMENT,
            "days_ago": 0,
            "eta_start_hour": 15,
            "subtotal": Decimal("60.00"),
            "urgent_fee": Decimal("0.00"),
            "service_payload": {
                "cylinder_type": "5kg",
                "quantity": 1,
                "cylinder_serials": ["SH05-D4112"],
                "last_inspection_date": "2025-12-20",
                "inspection_cycle_months": 12,
                "next_inspection_date": "2026-12-20",
            },
            "notes": "测试待支付订单",
        },
    ]

    for item in seeds:
        if Order.objects.filter(order_no=item["order_no"]).exists():
            continue

        created_at = now - timedelta(days=item["days_ago"])
        eta_start = created_at.replace(hour=item["eta_start_hour"], minute=0, second=0, microsecond=0)
        eta_end = eta_start + timedelta(hours=2)
        total = item["subtotal"] + item["urgent_fee"]
        expires_at = created_at + timedelta(minutes=30)
        if item["status"] != ORDER_STATUS_PENDING_PAYMENT:
            expires_at = created_at + timedelta(minutes=5)

        order = Order.objects.create(
            order_no=item["order_no"],
            user=user,
            service_type=item["service_type"],
            status=item["status"],
            eta_start=eta_start,
            eta_end=eta_end,
            cancel_deadline=eta_start - timedelta(hours=1),
            address_edit_deadline=eta_start - timedelta(hours=1),
            is_urgent=item["urgent_fee"] > 0,
            notes=item["notes"],
            amount_subtotal=item["subtotal"],
            amount_urgent_fee=item["urgent_fee"],
            amount_total=total,
            currency=DEFAULT_CURRENCY,
            address_snapshot=snapshot_address,
            contact_snapshot=snapshot_contact,
            service_payload=item["service_payload"],
            expires_at=expires_at,
        )
        Order.objects.filter(id=order.id).update(created_at=created_at, updated_at=created_at)

        if item["status"] in {ORDER_STATUS_PAID, ORDER_STATUS_SCHEDULED, ORDER_STATUS_COMPLETED}:
            PaymentTransaction.objects.create(
                order=order,
                status=PAYMENT_STATUS_MOCK,
                method=PAYMENT_METHOD_MOCK,
                paid_at=created_at + timedelta(minutes=3),
            )
        _seed_order_events(order, item["status"])


def ensure_test_account():
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(username=TEST_ACCOUNT_PHONE)
    if not user.check_password(TEST_ACCOUNT_PASSWORD):
        user.set_password(TEST_ACCOUNT_PASSWORD)
        user.save(update_fields=["password"])

    profile, _ = CustomerProfile.objects.get_or_create(
        user=user,
        defaults={"phone": TEST_ACCOUNT_PHONE, "display_name": "Test User"},
    )
    if not profile.display_name:
        profile.display_name = "Test User"
        profile.save(update_fields=["display_name"])

    default_address = _ensure_test_addresses(user)
    _seed_test_orders(user, default_address)
    return user
