import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from customer_portal.models import CustomerAuthToken, CustomerFeedback, CustomerNotification, CustomerProfile


User = get_user_model()


class PortalNotificationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="13800110101", password="12345678")
        self.user2 = User.objects.create_user(username="13800110102", password="12345678")
        CustomerProfile.objects.create(user=self.user, phone="13800110101", display_name="A")
        CustomerProfile.objects.create(user=self.user2, phone="13800110102", display_name="B")
        self.token = CustomerAuthToken.rotate_token(self.user).token
        self.token2 = CustomerAuthToken.rotate_token(self.user2).token
        self.headers = {"HTTP_AUTHORIZATION": f"Token {self.token}"}
        self.headers2 = {"HTTP_AUTHORIZATION": f"Token {self.token2}"}

    def _create_address(self):
        payload = {
            "contact_name": "张三",
            "contact_phone": "13800110101",
            "address_full": "上海市浦东新区测试路 100 号",
            "door_note": "2 单元 502",
            "is_default": True,
        }
        resp = self.client.post(
            "/api/portal/addresses",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        return (resp.json() or {}).get("data") or {}

    def _create_order(self, address_id):
        payload = {
            "service_type": "LPG_CYLINDER_DELIVERY",
            "service_payload": {"cylinder_type": "15kg", "quantity": 1},
            "address_id": address_id,
            "notes": "请提前联系",
        }
        resp = self.client.post(
            "/api/portal/orders",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        return (resp.json() or {}).get("data") or {}

    def test_order_create_and_pay_emit_notifications(self):
        address = self._create_address()
        order = self._create_order(address["id"])

        self.assertTrue(
            CustomerNotification.objects.filter(
                user=self.user,
                event_code="ORDER_CREATED",
                target_id=order["id"],
            ).exists()
        )

        pay_resp = self.client.post(f"/api/portal/orders/{order['id']}/pay", **self.headers)
        self.assertEqual(pay_resp.status_code, 200)
        self.assertTrue(
            CustomerNotification.objects.filter(
                user=self.user,
                event_code="ORDER_PAID",
                target_id=order["id"],
            ).exists()
        )

        list_resp = self.client.get("/api/portal/notifications?page=1&page_size=20", **self.headers)
        self.assertEqual(list_resp.status_code, 200)
        data = (list_resp.json() or {}).get("data") or {}
        self.assertGreaterEqual(int(data.get("unread_count") or 0), 2)
        self.assertGreaterEqual(len(data.get("items") or []), 2)

    def test_feedback_create_emits_notification(self):
        payload = {
            "feedback_type": "COMPLAINT",
            "target_type": "ONLINE_SERVICE",
            "title": "页面响应慢",
            "content": "客服页面偶发卡顿",
            "contact_phone": "13800110101",
        }
        resp = self.client.post(
            "/api/portal/feedbacks",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        feedback = CustomerFeedback.objects.filter(user=self.user).order_by("-id").first()
        self.assertIsNotNone(feedback)
        self.assertTrue(
            CustomerNotification.objects.filter(
                user=self.user,
                event_code="FEEDBACK_CREATED",
                target_id=feedback.id,
            ).exists()
        )

    def test_mark_single_and_read_all(self):
        CustomerNotification.objects.create(
            user=self.user,
            category=CustomerNotification.CATEGORY_PROFILE,
            event_code="PROFILE_UPDATED",
            title="资料已更新",
            content="昵称已修改",
            target_type=CustomerNotification.TARGET_PROFILE,
            target_route="#/portal/profile",
        )
        CustomerNotification.objects.create(
            user=self.user,
            category=CustomerNotification.CATEGORY_ADDRESS,
            event_code="ADDRESS_CREATED",
            title="地址已新增",
            content="新增地址成功",
            target_type=CustomerNotification.TARGET_ADDRESS,
            target_route="#/portal/profile",
        )
        first = CustomerNotification.objects.filter(user=self.user).order_by("id").first()
        self.assertIsNotNone(first)

        read_resp = self.client.post(f"/api/portal/notifications/{first.id}/read", **self.headers)
        self.assertEqual(read_resp.status_code, 200)
        first.refresh_from_db()
        self.assertTrue(first.is_read)

        read_all_resp = self.client.post("/api/portal/notifications/read-all", **self.headers)
        self.assertEqual(read_all_resp.status_code, 200)
        updated = ((read_all_resp.json() or {}).get("data") or {}).get("updated_count")
        self.assertGreaterEqual(int(updated or 0), 1)
        self.assertEqual(CustomerNotification.objects.filter(user=self.user, is_read=False).count(), 0)

    def test_read_notification_requires_ownership(self):
        other = CustomerNotification.objects.create(
            user=self.user2,
            category=CustomerNotification.CATEGORY_ORDER,
            event_code="ORDER_CREATED",
            title="订单已创建",
            content="测试",
            target_type=CustomerNotification.TARGET_ORDER,
            target_id=99,
            target_route="#/portal/orders/99",
        )
        resp = self.client.post(f"/api/portal/notifications/{other.id}/read", **self.headers)
        self.assertEqual(resp.status_code, 404)
        payload = resp.json() or {}
        self.assertEqual(((payload.get("error") or {}).get("code")), "NOTIFICATION_NOT_FOUND")
