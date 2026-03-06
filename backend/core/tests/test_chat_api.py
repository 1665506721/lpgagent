import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AgentEvent, AgentRun
from customer_portal.models import CustomerAuthToken, CustomerChatMessage, CustomerConversationMemory, CustomerProfile


User = get_user_model()


class ChatApiTests(TestCase):
    def _dummy_output(self, text="ok"):
        return SimpleNamespace(
            final_response=text,
            intent=SimpleNamespace(value="GENERAL"),
            risk_level=SimpleNamespace(value="LOW"),
            need_human=False,
            ui_action=None,
            form=None,
            confirm_required=False,
            pending_action=None,
            model_dump=lambda mode="json": {},
        )

    def test_chat_creates_run_and_init_event(self):
        response = self.client.post(
            reverse("chat"),
            data=json.dumps({"message": "hello"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for key in [
            "run_id",
            "final_response",
            "state",
            "intent",
            "risk_level",
            "need_human",
            "events_preview",
        ]:
            self.assertIn(key, payload)

        self.assertTrue(payload["run_id"])
        self.assertEqual(payload["events_preview"][0]["state"], "INIT")

        run = AgentRun.objects.get(id=payload["run_id"])
        event = AgentEvent.objects.get(run=run, state=AgentEvent.STATE_INIT)
        self.assertEqual(event.step_index, 1)

    def test_portal_mode_reuses_latest_run_without_run_id(self):
        user = User.objects.create_user(username="13800110011", password="12345678")
        CustomerProfile.objects.create(user=user, phone="13800110011", display_name="PortalUser")
        token = CustomerAuthToken.rotate_token(user).token

        headers = {"HTTP_AUTHORIZATION": f"Token {token}"}
        payload1 = {"message": "查最近订单", "portal_mode": True, "model_provider": "OLLAMA"}
        payload2 = {"message": "再查一次", "portal_mode": True, "model_provider": "OLLAMA"}

        r1 = self.client.post(reverse("chat"), data=json.dumps(payload1), content_type="application/json", **headers)
        self.assertEqual(r1.status_code, 200)
        run1 = r1.json().get("run_id")
        self.assertTrue(run1)

        r2 = self.client.post(reverse("chat"), data=json.dumps(payload2), content_type="application/json", **headers)
        self.assertEqual(r2.status_code, 200)
        run2 = r2.json().get("run_id")
        self.assertEqual(run1, run2)

    def test_portal_mode_run_continues_after_simulated_page_switch(self):
        user = User.objects.create_user(username="13800110021", password="12345678")
        CustomerProfile.objects.create(user=user, phone="13800110021", display_name="PortalUserSwitch")
        token = CustomerAuthToken.rotate_token(user).token
        headers = {"HTTP_AUTHORIZATION": f"Token {token}"}

        first_payload = {
            "message": "\u6211\u8981\u4e0b\u5355 15kg \u4e24\u74f6",
            "portal_mode": True,
            "model_provider": "OLLAMA",
        }
        second_payload = {
            "message": "\u7528\u9ed8\u8ba4\u5730\u5740",
            "portal_mode": True,
            "model_provider": "OLLAMA",
        }

        r1 = self.client.post(reverse("chat"), data=json.dumps(first_payload), content_type="application/json", **headers)
        self.assertEqual(r1.status_code, 200)
        run1 = r1.json().get("run_id")
        self.assertTrue(run1)

        # 模拟“切换页面再回来”：不传 run_id，后端应复用该账号最近 run。
        r2 = self.client.post(reverse("chat"), data=json.dumps(second_payload), content_type="application/json", **headers)
        self.assertEqual(r2.status_code, 200)
        run2 = r2.json().get("run_id")
        self.assertEqual(run1, run2)

    def test_portal_mode_force_new_run_creates_new_run(self):
        user = User.objects.create_user(username="13800110012", password="12345678")
        CustomerProfile.objects.create(user=user, phone="13800110012", display_name="PortalUser2")
        token = CustomerAuthToken.rotate_token(user).token
        headers = {"HTTP_AUTHORIZATION": f"Token {token}"}

        payload1 = {"message": "查最近订单", "portal_mode": True, "model_provider": "OLLAMA"}
        payload2 = {
            "message": "开启新会话",
            "portal_mode": True,
            "model_provider": "OLLAMA",
            "force_new_run": True,
        }

        r1 = self.client.post(reverse("chat"), data=json.dumps(payload1), content_type="application/json", **headers)
        self.assertEqual(r1.status_code, 200)
        run1 = r1.json().get("run_id")
        self.assertTrue(run1)

        r2 = self.client.post(reverse("chat"), data=json.dumps(payload2), content_type="application/json", **headers)
        self.assertEqual(r2.status_code, 200)
        run2 = r2.json().get("run_id")
        self.assertTrue(run2)
        self.assertNotEqual(run1, run2)

    def test_portal_mode_run_expires_after_30_minutes(self):
        user = User.objects.create_user(username="13800110014", password="12345678")
        CustomerProfile.objects.create(user=user, phone="13800110014", display_name="PortalUserExpire")
        token = CustomerAuthToken.rotate_token(user).token
        headers = {"HTTP_AUTHORIZATION": f"Token {token}"}

        first_payload = {"message": "我要下单 15kg 一瓶", "portal_mode": True, "model_provider": "OLLAMA"}
        r1 = self.client.post(reverse("chat"), data=json.dumps(first_payload), content_type="application/json", **headers)
        self.assertEqual(r1.status_code, 200)
        run1 = r1.json().get("run_id")
        self.assertTrue(run1)

        run_obj = AgentRun.objects.get(id=run1)
        stale_time = timezone.now() - timedelta(minutes=31)
        AgentEvent.objects.filter(run=run_obj).update(created_at=stale_time)

        second_payload = {"message": "继续", "portal_mode": True, "model_provider": "OLLAMA"}
        r2 = self.client.post(reverse("chat"), data=json.dumps(second_payload), content_type="application/json", **headers)
        self.assertEqual(r2.status_code, 200)
        run2 = r2.json().get("run_id")
        self.assertTrue(run2)
        self.assertNotEqual(run1, run2)

    def test_portal_chat_messages_are_persisted_and_queryable(self):
        user = User.objects.create_user(username="13800110013", password="12345678")
        CustomerProfile.objects.create(user=user, phone="13800110013", display_name="PortalUser3")
        token = CustomerAuthToken.rotate_token(user).token
        headers = {"HTTP_AUTHORIZATION": f"Token {token}"}

        payload = {"message": "查最近订单", "portal_mode": True, "model_provider": "OLLAMA"}
        chat_resp = self.client.post(reverse("chat"), data=json.dumps(payload), content_type="application/json", **headers)
        self.assertEqual(chat_resp.status_code, 200)

        rows = CustomerChatMessage.objects.filter(user=user).order_by("created_at")
        self.assertGreaterEqual(rows.count(), 2)
        self.assertEqual(rows.first().role, "user")
        self.assertEqual(rows.first().content, "查最近订单")
        self.assertEqual(rows.last().role, "assistant")

        history_resp = self.client.get("/api/portal/chat/history?limit=50", **headers)
        self.assertEqual(history_resp.status_code, 200)
        data = history_resp.json().get("data") or {}
        items = data.get("items") or []
        self.assertGreaterEqual(len(items), 2)
        self.assertEqual(items[0].get("role"), "user")

    def test_portal_clear_chat_history_also_clears_memory(self):
        user = User.objects.create_user(username="13800110015", password="12345678")
        CustomerProfile.objects.create(user=user, phone="13800110015", display_name="PortalUserClear")
        token = CustomerAuthToken.rotate_token(user).token
        headers = {"HTTP_AUTHORIZATION": f"Token {token}"}

        CustomerConversationMemory.objects.update_or_create(
            user=user,
            defaults={"memory_json": {"draft_order": {"service_type": "LPG_CYLINDER_DELIVERY"}}},
        )
        CustomerChatMessage.objects.create(user=user, role="user", content="我要下单")
        CustomerChatMessage.objects.create(user=user, role="assistant", content="请先选择规格")

        clear_resp = self.client.post("/api/portal/chat/history/clear", **headers)
        self.assertEqual(clear_resp.status_code, 200)
        payload = clear_resp.json().get("data") or {}
        self.assertGreaterEqual(int(payload.get("deleted_count") or 0), 2)
        self.assertIn("memory_cleared", payload)

        memory = CustomerConversationMemory.objects.filter(user=user).first()
        self.assertIsNotNone(memory)
        self.assertEqual(memory.memory_json or {}, {})

    @mock.patch("core.views.run_orchestrator")
    def test_openai_compat_provider_maps_to_openai_run_provider(self, mock_run_orchestrator):
        mock_run_orchestrator.return_value = self._dummy_output("ok")
        response = self.client.post(
            reverse("chat"),
            data=json.dumps(
                {
                    "message": "hello",
                    "model_provider": "OPENAI_COMPAT",
                    "provider_type": "OPENAI_COMPAT",
                    "force_new_run": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        run = AgentRun.objects.get(id=response.json().get("run_id"))
        self.assertEqual(run.model_provider, AgentRun.PROVIDER_OPENAI)
