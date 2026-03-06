from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from customer_portal.constants import (
    DEFAULT_CURRENCY,
    ORDER_STATUS_PAID,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
    SERVICE_TYPE_REPAIR,
    SERVICE_WINDOW_START,
)
from customer_portal.models import Order
from customer_portal.services import can_cancel, can_edit_address, create_order


User = get_user_model()


class PortalOrderServiceRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="13800119999", password="12345678")

    def _aware_dt(self, year, month, day, hour, minute):
        return timezone.make_aware(datetime(year, month, day, hour, minute), timezone.get_current_timezone())

    def test_create_urgent_order_within_service_window_starts_within_one_hour_and_30m_deadline(self):
        now = self._aware_dt(2026, 3, 6, 10, 0)
        with patch("customer_portal.services.get_now", return_value=now):
            order = create_order(
                user=self.user,
                service_type=SERVICE_TYPE_REPAIR,
                service_payload={"issue_desc": "stove not working"},
                contact_snapshot={"contact_name": "Tester", "contact_phone": "13800119999"},
                address_snapshot={"address_full": "Shanghai Pudong Test Road 100", "door_note": "2F"},
                is_urgent=True,
            )

        self.assertLessEqual(order.eta_start, now + timedelta(minutes=60))
        self.assertEqual(order.cancel_deadline, now + timedelta(minutes=30))
        self.assertEqual(order.address_edit_deadline, now + timedelta(minutes=30))

    def test_create_urgent_order_outside_service_window_defers_to_next_service_window(self):
        now = self._aware_dt(2026, 3, 6, 23, 30)
        with patch("customer_portal.services.get_now", return_value=now):
            order = create_order(
                user=self.user,
                service_type=SERVICE_TYPE_REPAIR,
                service_payload={"issue_desc": "valve issue"},
                contact_snapshot={"contact_name": "Tester", "contact_phone": "13800119999"},
                address_snapshot={"address_full": "Shanghai Xuhui Test Road 88", "door_note": "1F"},
                is_urgent=True,
            )

        self.assertEqual(order.eta_start.time().replace(second=0, microsecond=0), SERVICE_WINDOW_START)
        self.assertEqual(order.eta_start.date(), (now + timedelta(days=1)).date())
        self.assertEqual(order.cancel_deadline, now + timedelta(minutes=30))
        self.assertEqual(order.address_edit_deadline, now + timedelta(minutes=30))

    def test_cancel_and_edit_use_deadline_fields_instead_of_eta_minus_60(self):
        now = self._aware_dt(2026, 3, 6, 11, 0)
        order = Order.objects.create(
            order_no="LPG2026030611000011",
            user=self.user,
            service_type=SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            status=ORDER_STATUS_PAID,
            eta_start=now + timedelta(minutes=70),
            eta_end=now + timedelta(minutes=190),
            cancel_deadline=now - timedelta(minutes=1),
            address_edit_deadline=now - timedelta(minutes=1),
            is_urgent=False,
            notes="",
            amount_subtotal=Decimal("120.00"),
            amount_urgent_fee=Decimal("0.00"),
            amount_total=Decimal("120.00"),
            currency=DEFAULT_CURRENCY,
            address_snapshot={"address_full": "Shanghai Pudong Test Road 100", "door_note": "2F"},
            contact_snapshot={"contact_name": "Tester", "contact_phone": "13800119999"},
            service_payload={"cylinder_type": "15kg", "quantity": 1},
            expires_at=now + timedelta(minutes=30),
        )

        self.assertFalse(can_cancel(order, now=now))
        self.assertFalse(can_edit_address(order, now=now))

        order.cancel_deadline = now + timedelta(minutes=10)
        order.address_edit_deadline = now + timedelta(minutes=10)
        order.save(update_fields=["cancel_deadline", "address_edit_deadline", "updated_at"])

        self.assertTrue(can_cancel(order, now=now))
        self.assertTrue(can_edit_address(order, now=now))
