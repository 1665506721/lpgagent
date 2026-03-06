from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from customer_portal.constants import (
    DEFAULT_CURRENCY,
    ORDER_STATUS_COMPLETED,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
)
from customer_portal.inspection_service import (
    calculate_all_inspection_due,
    calculate_inspection_due,
    list_inspection_candidates,
)
from customer_portal.models import Order


User = get_user_model()


class InspectionServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="13911112222", password="12345678")

    def _create_order(self, order_no, cylinder_type="15kg", payload_extra=None):
        now = timezone.localtime(timezone.now())
        payload = {"cylinder_type": cylinder_type, "quantity": 1}
        if isinstance(payload_extra, dict):
            payload.update(payload_extra)
        return Order.objects.create(
            order_no=order_no,
            user=self.user,
            service_type=SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            status=ORDER_STATUS_COMPLETED,
            eta_start=now - timedelta(days=1),
            eta_end=now - timedelta(days=1) + timedelta(hours=2),
            cancel_deadline=now - timedelta(days=1, hours=1),
            address_edit_deadline=now - timedelta(days=1, hours=1),
            is_urgent=False,
            notes="",
            amount_subtotal=Decimal("120.00"),
            amount_urgent_fee=Decimal("0.00"),
            amount_total=Decimal("120.00"),
            currency=DEFAULT_CURRENCY,
            address_snapshot={"address_full": "上海市浦东新区测试路100号", "door_note": "2楼"},
            contact_snapshot={"contact_name": "张三", "contact_phone": "13911112222"},
            service_payload=payload,
            expires_at=now + timedelta(minutes=30),
        )

    def test_due_date_calculation_for_different_cylinder_types(self):
        order = self._create_order(
            "LPG2026022700010001",
            cylinder_type="5kg",
            payload_extra={"cylinder_purchase_date": "2025-01-15"},
        )
        result = calculate_inspection_due(user=self.user, order_id=order.id)
        self.assertNotIn("error", result)
        self.assertEqual(result["cylinder_type"], "5kg")
        self.assertEqual(result["base_source"], "CYLINDER_PURCHASE_DATE")
        self.assertEqual(result["next_inspection_date"], "2029-01-15")

    def test_missing_inspection_fields_fallback_to_order_time(self):
        order = self._create_order("LPG2026022700010002", cylinder_type="45kg")
        result = calculate_inspection_due(user=self.user, order_id=order.id)
        self.assertNotIn("error", result)
        self.assertIn(result["base_source"], {"ORDER_SERVICE_DATE", "ORDER_PURCHASE_DATE"})
        self.assertTrue(result.get("next_inspection_date"))

    def test_policy_version_and_source_present(self):
        order = self._create_order("LPG2026022700010003", cylinder_type="15kg")
        result = calculate_inspection_due(user=self.user, order_id=order.id)
        self.assertNotIn("error", result)
        self.assertTrue(result.get("policy_version"))
        self.assertTrue(result.get("source_ref"))
        self.assertTrue(result.get("disclaimer"))

        candidates = list_inspection_candidates(user=self.user, limit=5)
        self.assertGreaterEqual(candidates.get("total", 0), 1)
        self.assertTrue((candidates.get("items") or [])[0].get("order_no"))

    def test_calculate_all_due_sorted_and_counts(self):
        self._create_order(
            "LPG2026022700090001",
            cylinder_type="15kg",
            payload_extra={"cylinder_purchase_date": "2020-01-10"},
        )
        self._create_order(
            "LPG2026022700090002",
            cylinder_type="15kg",
            payload_extra={"cylinder_purchase_date": "2023-12-01"},
        )
        self._create_order(
            "LPG2026022700090003",
            cylinder_type="45kg",
            payload_extra={"cylinder_purchase_date": "2026-01-01"},
        )
        result = calculate_all_inspection_due(user=self.user)
        self.assertEqual(result.get("total"), 3)
        self.assertGreaterEqual(result.get("overdue_count", 0), 1)
        items = result.get("items") or []
        self.assertEqual(len(items), 3)
        status_rank = {"OVERDUE": 0, "DUE_SOON": 1, "NORMAL": 2}
        ranked = [status_rank.get(item.get("status"), 99) for item in items]
        self.assertEqual(ranked, sorted(ranked))
