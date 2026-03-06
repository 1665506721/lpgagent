import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from agent import portal_orchestrator as portal_orch
from core.models import AgentRun
from customer_portal.constants import (
    DEFAULT_CURRENCY,
    ORDER_STATUS_PAID,
    ORDER_STATUS_SCHEDULED,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
)
from customer_portal.models import (
    CustomerAddress,
    CustomerAuthToken,
    CustomerModelProviderProfile,
    Order as PortalOrder,
    CustomerProfile,
)
from customer_portal.security import encrypt_api_key, mask_api_key


User = get_user_model()


class PortalModeChatRagMemoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="13800990011", password="12345678")
        CustomerProfile.objects.create(user=self.user, phone="13800990011", display_name="RagTester")
        CustomerAddress.objects.create(
            user=self.user,
            contact_name="RagTester",
            contact_phone="13800990011",
            address_full="Shanghai Pudong New Area 1",
            door_note="Room 101",
            is_default=True,
        )
        api_key = "sk-test-portal-rag"
        CustomerModelProviderProfile.objects.create(
            user=self.user,
            name="test-cloud",
            provider_type=CustomerModelProviderProfile.PROVIDER_OPENAI_COMPAT,
            api_base_url="https://api-inference.modelscope.cn/v1",
            model_name="qwen-plus",
            api_key_ciphertext=encrypt_api_key(api_key),
            api_key_masked=mask_api_key(api_key),
            is_active=True,
        )
        self.token = CustomerAuthToken.rotate_token(self.user).token

    def _chat(self, message, run_id=None, force_new_run=False):
        payload = {"message": message, "portal_mode": True, "model_provider": "OLLAMA"}
        if run_id:
            payload["run_id"] = run_id
        if force_new_run:
            payload["force_new_run"] = True
        response = self.client.post(
            "/api/chat",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.token}",
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_price_query_not_misrouted_to_create_order(self):
        data = self._chat("娑插寲姘旂幇鍦ㄥ灏戦挶锛屾渶杩戞湁娑ㄤ环鍚楋紵")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertNotIn("鍝瑙勬牸", data.get("final_response", ""))
        from customer_portal.models import CustomerConversationMemory

        memory = CustomerConversationMemory.objects.filter(user=self.user).first()
        self.assertIsNotNone(memory)
        self.assertIn("last_intent", memory.memory_json or {})

    def test_inspection_query_returns_personal_record_style_reply(self):
        from customer_portal.models import Order
        from customer_portal.constants import (
            DEFAULT_CURRENCY,
            ORDER_STATUS_COMPLETED,
            SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
        )
        from decimal import Decimal
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.localtime(timezone.now())
        Order.objects.create(
            order_no="LPG2026021901018801",
            user=self.user,
            service_type=SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            status=ORDER_STATUS_COMPLETED,
            eta_start=now - timedelta(days=2),
            eta_end=now - timedelta(days=2) + timedelta(hours=2),
            cancel_deadline=now - timedelta(days=2, hours=1),
            address_edit_deadline=now - timedelta(days=2, hours=1),
            is_urgent=False,
            notes="",
            amount_subtotal=Decimal("120.00"),
            amount_urgent_fee=Decimal("0.00"),
            amount_total=Decimal("120.00"),
            currency=DEFAULT_CURRENCY,
            address_snapshot={"address_full": "Shanghai Pudong New Area 1", "door_note": "Room 101"},
            contact_snapshot={"contact_name": "RagTester", "contact_phone": "13800990011"},
            service_payload={
                "cylinder_type": "15kg",
                "quantity": 1,
                "last_inspection_date": "2026-01-15",
                "inspection_cycle_months": 12,
                "next_inspection_date": "2027-01-15",
            },
            expires_at=now + timedelta(minutes=30),
        )

        data = self._chat("\u6211\u7684\u6c14\u74f6\u5e74\u68c0\u4ec0\u4e48\u65f6\u5019\u5230\u671f\uff1f")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertIn("\u5e74\u68c0", data.get("final_response", ""))

    def test_complaint_requires_order_selection(self):
        from customer_portal.models import Order
        from customer_portal.constants import (
            DEFAULT_CURRENCY,
            ORDER_STATUS_COMPLETED,
            SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
        )
        from decimal import Decimal
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.localtime(timezone.now())
        Order.objects.create(
            order_no="LPG2026021901019901",
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
            address_snapshot={"address_full": "Shanghai Pudong New Area 1", "door_note": "Room 101"},
            contact_snapshot={"contact_name": "RagTester", "contact_phone": "13800990011"},
            service_payload={"cylinder_type": "15kg", "quantity": 1},
            expires_at=now + timedelta(minutes=30),
        )
        first = self._chat("\u6211\u8981\u6295\u8bc9\uff0c\u9001\u8d27\u6001\u5ea6\u5f88\u5dee")
        self.assertFalse(first.get("confirm_required"))
        self.assertIn("\u8ba2\u5355", first.get("final_response", ""))
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CREATE_FEEDBACK")
        self.assertEqual((first.get("pending_action") or {}).get("status"), "COLLECTING")

        second = self._chat("第1个", run_id=first.get("run_id"))
        self.assertTrue(second.get("confirm_required"))
        self.assertEqual((second.get("pending_action") or {}).get("type"), "CREATE_FEEDBACK")

    def test_online_complaint_does_not_require_order_selection(self):
        data = self._chat("我要投诉在线客服回复太慢。")
        self.assertTrue(data.get("confirm_required"))
        self.assertEqual((data.get("pending_action") or {}).get("type"), "CREATE_FEEDBACK")
        self.assertEqual((data.get("pending_action") or {}).get("status"), "AWAIT_CONFIRM")
        self.assertNotIn("选择要投诉的订单", data.get("final_response", ""))

    def test_online_suggestion_does_not_require_order_selection(self):
        data = self._chat("我要提个建议：页面按钮太多，能不能简化。")
        self.assertTrue(data.get("confirm_required"))
        self.assertEqual((data.get("pending_action") or {}).get("type"), "CREATE_FEEDBACK")
        self.assertEqual((data.get("pending_action") or {}).get("status"), "AWAIT_CONFIRM")
        self.assertNotIn("选择要投诉的订单", data.get("final_response", ""))

    def test_recent_context_builder_includes_cross_run_dialog_history(self):
        first = self._chat("\u6211\u8981\u4e0b\u5355 15kg \u4e00\u74f6", force_new_run=True)
        self.assertTrue(first.get("run_id"))
        second = self._chat("\u6211\u521a\u624d\u8bf4\u5230\u54ea\u4e86", force_new_run=True)
        self.assertTrue(second.get("run_id"))

        run = AgentRun.objects.get(id=second.get("run_id"))
        context_text = portal_orch._build_recent_context_for_llm(
            run,
            self.user.id,
            run_limit=4,
            account_limit=12,
            within_hours=24,
            max_chars=1500,
        )
        self.assertIn("\u6211\u8981\u4e0b\u5355 15kg \u4e00\u74f6", context_text)
        self.assertIn("\u6211\u521a\u624d\u8bf4\u5230\u54ea\u4e86", context_text)

    def test_hotline_dedup_suppression_across_turns(self):
        first = self._chat("我要开户申请", force_new_run=True)
        self.assertIn("400-888-0000", first.get("final_response", ""))
        second = self._chat("还是要开户申请", run_id=first.get("run_id"))
        self.assertNotIn("400-888-0000", second.get("final_response", ""))
        self.assertTrue(bool((second.get("routing") or {}).get("hotline_suppressed")))

    def test_risk_escalation_allows_hotline_again(self):
        first = self._chat("我要开户申请", force_new_run=True)
        self.assertIn("400-888-0000", first.get("final_response", ""))
        second = self._chat("还是要开户申请", run_id=first.get("run_id"))
        self.assertNotIn("400-888-0000", second.get("final_response", ""))
        third = self._chat("闻到煤气味，先做什么最稳妥", run_id=first.get("run_id"))
        self.assertIn("400-888-0000", third.get("final_response", ""))
        self.assertIn("最牵挂", third.get("final_response", ""))

    def test_manual_queue_progress_across_turns(self):
        first = self._chat("我要联系客服", force_new_run=True)
        queue1 = ((first.get("routing") or {}).get("manual_queue") or {})
        ahead1 = int(queue1.get("ahead_count") or 0)
        second = self._chat("帮我看下通知", run_id=first.get("run_id"))
        queue2 = ((second.get("routing") or {}).get("manual_queue") or {})
        ahead2 = int(queue2.get("ahead_count") or 0)
        self.assertTrue(bool((second.get("routing") or {}).get("manual_handoff")))
        self.assertLessEqual(ahead2, ahead1)
        self.assertIn(queue2.get("status"), {"WAITING", "CONNECTING"})

    def test_manual_queue_cancel_stops_queue_state(self):
        first = self._chat("我要联系客服", force_new_run=True)
        second = self._chat("取消人工排队", run_id=first.get("run_id"))
        routing = second.get("routing") or {}
        self.assertFalse(bool(routing.get("manual_handoff")))
        self.assertFalse(bool(routing.get("manual_queue")))

    def test_pending_order_invoice_toggle_persists_across_turns(self):
        first = self._chat("我要下单 15kg 1瓶", force_new_run=True)
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CREATE_ORDER")

        second = self._chat("开票改成是", run_id=first.get("run_id"))
        self.assertTrue(bool(((second.get("pending_action") or {}).get("draft") or {}).get("need_invoice")))

        third = self._chat("不开票了", run_id=first.get("run_id"))
        self.assertFalse(bool(((third.get("pending_action") or {}).get("draft") or {}).get("need_invoice")))

    def test_modify_address_auto_selected_order_stays_stable_until_confirm(self):
        now = timezone.localtime(timezone.now())
        older_paid = PortalOrder.objects.create(
            order_no="LPG2026030600110001",
            user=self.user,
            service_type=SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            status=ORDER_STATUS_PAID,
            eta_start=now + timedelta(hours=4),
            eta_end=now + timedelta(hours=6),
            cancel_deadline=now + timedelta(hours=3),
            address_edit_deadline=now + timedelta(hours=3),
            is_urgent=False,
            notes="",
            amount_subtotal=Decimal("120.00"),
            amount_urgent_fee=Decimal("0.00"),
            amount_total=Decimal("120.00"),
            currency=DEFAULT_CURRENCY,
            address_snapshot={"address_full": "Shanghai Pudong New Area 1", "door_note": "Room 101"},
            contact_snapshot={"contact_name": "RagTester", "contact_phone": "13800990011"},
            service_payload={"cylinder_type": "15kg", "quantity": 1},
            expires_at=now + timedelta(minutes=30),
        )
        newer_scheduled = PortalOrder.objects.create(
            order_no="LPG2026030600110002",
            user=self.user,
            service_type=SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            status=ORDER_STATUS_SCHEDULED,
            eta_start=now + timedelta(hours=5),
            eta_end=now + timedelta(hours=7),
            cancel_deadline=now + timedelta(hours=4),
            address_edit_deadline=now + timedelta(hours=4),
            is_urgent=False,
            notes="",
            amount_subtotal=Decimal("120.00"),
            amount_urgent_fee=Decimal("0.00"),
            amount_total=Decimal("120.00"),
            currency=DEFAULT_CURRENCY,
            address_snapshot={"address_full": "Shanghai Pudong New Area 1", "door_note": "Room 101"},
            contact_snapshot={"contact_name": "RagTester", "contact_phone": "13800990011"},
            service_payload={"cylinder_type": "15kg", "quantity": 1},
            expires_at=now + timedelta(minutes=30),
        )
        PortalOrder.objects.filter(id=older_paid.id).update(created_at=now - timedelta(hours=3), updated_at=now - timedelta(hours=3))
        PortalOrder.objects.filter(id=newer_scheduled.id).update(
            created_at=now - timedelta(minutes=20),
            updated_at=now - timedelta(minutes=20),
        )

        first = self._chat("把这单改址到上海市徐汇区漕溪北路9号，联系人Tester，电话13800990011", force_new_run=True)
        pending = first.get("pending_action") or {}
        routing = first.get("routing") or {}
        self.assertEqual(pending.get("type"), "MODIFY_ADDRESS")
        self.assertTrue(bool(routing.get("default_order_selected")))
        selected_order_no = routing.get("default_order_no") or ((pending.get("payload") or {}).get("order_no") or "")
        self.assertEqual(selected_order_no, newer_scheduled.order_no)

        second = self._chat("确认", run_id=first.get("run_id"))
        self.assertIn(selected_order_no, second.get("final_response", ""))
        newer_scheduled.refresh_from_db()
        self.assertIn("上海市徐汇区漕溪北路9号", (newer_scheduled.address_snapshot or {}).get("address_full", ""))

    def test_heuristic_route_general_safety_not_forced_to_leak(self):
        plan = portal_orch._heuristic_kb_route("使用煤气怎么注意安全")
        self.assertTrue(bool(plan.get("need_kb")))
        self.assertEqual(plan.get("domain"), "safety")
        self.assertEqual(plan.get("topic"), "safety_general")

    def test_ambiguity_prefers_direct_reply_over_multi_round_clarify(self):
        first = self._chat("我想问个事", force_new_run=True)
        self.assertFalse(bool((first.get("routing") or {}).get("clarify_needed")))
        second = self._chat("还是想问这个", run_id=first.get("run_id"))
        self.assertFalse(bool((second.get("routing") or {}).get("clarify_needed")))
        third = self._chat("还没想好", run_id=first.get("run_id"))
        self.assertFalse(bool((third.get("routing") or {}).get("clarify_needed")))
        self.assertIn((third.get("routing") or {}).get("lane"), {"smalltalk", "rag"})

    def test_high_risk_safety_does_not_enter_clarify_rounds(self):
        data = self._chat("闻到煤气味了怎么办", force_new_run=True)
        routing = data.get("routing") or {}
        self.assertIn(routing.get("lane"), {"safety", "rag"})
        self.assertFalse(bool(routing.get("clarify_needed")))
        self.assertIn((routing.get("clarify_round") or 0), {0, None})

    def test_safety_general_and_leak_assess_keep_typed_or_llm_answer_source(self):
        first = self._chat("燃气软管多久更换", force_new_run=True)
        routing1 = first.get("routing") or {}
        self.assertEqual(routing1.get("safety_kind"), "general_qa")
        self.assertIn(routing1.get("answer_source"), {"llm_direct", "typed_fallback"})
        self.assertNotIn("日常用气安全可以先记住这 5 点", first.get("final_response", ""))

        second = self._chat("如何判断燃气是否泄漏", run_id=first.get("run_id"))
        routing2 = second.get("routing") or {}
        self.assertEqual(routing2.get("safety_kind"), "leak_assess")
        self.assertIn(routing2.get("answer_source"), {"llm_direct", "typed_fallback"})
        self.assertNotIn("日常用气安全可以先记住这 5 点", second.get("final_response", ""))

    def test_safety_scene_short_followup_uses_topic_continuation(self):
        first = self._chat("燃气安全", force_new_run=True)
        second = self._chat("餐饮", run_id=first.get("run_id"))
        routing = second.get("routing") or {}
        text = second.get("final_response", "")
        self.assertFalse(bool(routing.get("clarify_needed")))
        self.assertEqual(routing.get("safety_kind"), "general_qa")
        self.assertIn(routing.get("answer_source"), {"llm_direct", "typed_fallback"})
        self.assertNotIn("查询信息", text)
        self.assertNotIn("直接办理业务", text)

    def test_safety_risk_upgrade_from_leak_assess_to_emergency(self):
        first = self._chat("如何判断燃气是否泄漏", force_new_run=True)
        self.assertEqual((first.get("routing") or {}).get("safety_kind"), "leak_assess")
        second = self._chat("现在闻到煤气味了先做什么", run_id=first.get("run_id"))
        routing = second.get("routing") or {}
        self.assertEqual(routing.get("safety_kind"), "emergency")
        self.assertEqual(routing.get("answer_source"), "emergency_template")
        self.assertIn("400-888-0000", second.get("final_response", ""))


