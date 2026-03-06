import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from customer_portal.constants import (
    DEFAULT_CURRENCY,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_PENDING_PAYMENT,
    ORDER_STATUS_PAID,
    ORDER_STATUS_SCHEDULED,
    SERVICE_TYPE_ACCESSORIES,
    SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
    SERVICE_TYPE_REPAIR,
    SERVICE_TYPE_SAFETY_CHECK,
)
from customer_portal.models import (
    CustomerAddress,
    CustomerAuthToken,
    CustomerCartItem,
    CustomerConversationMemory,
    CustomerFeedback,
    CustomerModelProviderProfile,
    CustomerNotification,
    CustomerProfile,
    Order as PortalOrder,
)
from customer_portal.security import encrypt_api_key, mask_api_key


User = get_user_model()


class PortalModeChatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="13800112233", password="12345678")
        CustomerProfile.objects.create(user=self.user, phone="13800112233", display_name="张三")
        CustomerAddress.objects.create(
            user=self.user,
            contact_name="张三",
            contact_phone="13800112233",
            address_full="上海市浦东新区测试路100号",
            door_note="2层",
            is_default=True,
        )
        api_key = "sk-test-portal-chat"
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

    def _create_sample_order(
        self,
        order_no="LPG2026022500010001",
        payload_extra=None,
        *,
        status=ORDER_STATUS_COMPLETED,
        eta_start=None,
        eta_end=None,
        cancel_deadline=None,
        address_edit_deadline=None,
        is_urgent=False,
    ):
        now = timezone.localtime(timezone.now())
        resolved_eta_start = eta_start or (now - timedelta(days=1))
        resolved_eta_end = eta_end or (resolved_eta_start + timedelta(hours=2))
        resolved_cancel_deadline = cancel_deadline or (resolved_eta_start - timedelta(hours=1))
        resolved_address_edit_deadline = address_edit_deadline or resolved_cancel_deadline
        service_payload = {"cylinder_type": "15kg", "quantity": 1}
        if isinstance(payload_extra, dict):
            service_payload.update(payload_extra)
        return PortalOrder.objects.create(
            order_no=order_no,
            user=self.user,
            service_type=SERVICE_TYPE_LPG_CYLINDER_DELIVERY,
            status=status,
            eta_start=resolved_eta_start,
            eta_end=resolved_eta_end,
            cancel_deadline=resolved_cancel_deadline,
            address_edit_deadline=resolved_address_edit_deadline,
            is_urgent=is_urgent,
            notes="",
            amount_subtotal=Decimal("120.00"),
            amount_urgent_fee=Decimal("0.00"),
            amount_total=Decimal("120.00"),
            currency=DEFAULT_CURRENCY,
            address_snapshot={"address_full": "上海市浦东新区测试路100号", "door_note": "2层"},
            contact_snapshot={"contact_name": "张三", "contact_phone": "13800112233"},
            service_payload=service_payload,
            expires_at=now + timedelta(minutes=30),
        )

    def test_order_guide_not_misrouted_to_create_order(self):
        data = self._chat("如何自助下单")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")

    def test_price_query_routes_to_rag_not_order_collect(self):
        data = self._chat("今日液化气价格")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertIn((data.get("routing") or {}).get("lane"), {"rag", "smalltalk"})

    def test_invoice_help_returns_fixed_enterprise_flow(self):
        data = self._chat("企业开票流程")
        text = data.get("final_response", "")
        self.assertIn("开票", text)
        self.assertIn("订单号", text)

    def test_pending_order_allows_side_query_then_resume_hint(self):
        first = self._chat("我要下单 15kg")
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        second = self._chat("今日液化气价格", run_id=first.get("run_id"))
        self.assertEqual((second.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertIn("继续下单", second.get("final_response", ""))

    def test_pending_order_invoice_toggle_updates_current_draft(self):
        first = self._chat("我要下单 15kg 1瓶", force_new_run=True)
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CREATE_ORDER")

        second = self._chat("开票改成是", run_id=first.get("run_id"))
        pending2 = second.get("pending_action") or {}
        draft2 = pending2.get("draft") or {}
        self.assertEqual(pending2.get("type"), "CREATE_ORDER")
        self.assertTrue(bool(draft2.get("need_invoice")))
        self.assertIn("发票信息", str(draft2.get("notes") or ""))
        self.assertIn("已将本单开票改为是", second.get("final_response", ""))
        self.assertNotIn("企业开票流程", second.get("final_response", ""))

        third = self._chat("不开票了", run_id=first.get("run_id"))
        pending3 = third.get("pending_action") or {}
        draft3 = pending3.get("draft") or {}
        self.assertEqual(pending3.get("type"), "CREATE_ORDER")
        self.assertFalse(bool(draft3.get("need_invoice")))
        self.assertNotIn("发票信息", str(draft3.get("notes") or ""))
        self.assertIn("已将本单开票改为否", third.get("final_response", ""))

    def test_modify_address_without_order_no_auto_selects_latest_unshipped(self):
        now = timezone.localtime(timezone.now())
        self._create_sample_order(
            order_no="LPG2026030600010001",
            status=ORDER_STATUS_COMPLETED,
            eta_start=now - timedelta(days=2),
            eta_end=now - timedelta(days=2) + timedelta(hours=2),
        )
        paid = self._create_sample_order(
            order_no="LPG2026030600010002",
            status=ORDER_STATUS_PAID,
            eta_start=now + timedelta(hours=5),
            eta_end=now + timedelta(hours=7),
            cancel_deadline=now + timedelta(hours=4),
            address_edit_deadline=now + timedelta(hours=4),
        )
        scheduled = self._create_sample_order(
            order_no="LPG2026030600010003",
            status=ORDER_STATUS_SCHEDULED,
            eta_start=now + timedelta(hours=8),
            eta_end=now + timedelta(hours=10),
            cancel_deadline=now + timedelta(hours=7),
            address_edit_deadline=now + timedelta(hours=7),
        )
        PortalOrder.objects.filter(id=paid.id).update(created_at=now - timedelta(hours=2), updated_at=now - timedelta(hours=2))
        PortalOrder.objects.filter(id=scheduled.id).update(created_at=now - timedelta(minutes=30), updated_at=now - timedelta(minutes=30))

        data = self._chat("把这单改址到上海市徐汇区天钥桥路18号", force_new_run=True)
        pending = data.get("pending_action") or {}
        routing = data.get("routing") or {}
        payload = pending.get("payload") or {}

        self.assertEqual(pending.get("type"), "MODIFY_ADDRESS")
        self.assertTrue(bool(data.get("confirm_required")))
        self.assertTrue(bool(routing.get("default_order_selected")))
        self.assertEqual(routing.get("default_order_no"), "LPG2026030600010003")
        self.assertEqual(payload.get("order_no"), "LPG2026030600010003")
        self.assertEqual((payload.get("payload") or {}).get("address_full"), "上海市徐汇区天钥桥路18号")
        self.assertNotIn("把这单改址到", data.get("final_response", ""))

    def test_modify_address_success_reply_contains_address_snapshot(self):
        now = timezone.localtime(timezone.now())
        order = self._create_sample_order(
            order_no="LPG2026030600010004",
            status=ORDER_STATUS_PENDING_PAYMENT,
            eta_start=now + timedelta(hours=3),
            eta_end=now + timedelta(hours=5),
            cancel_deadline=now + timedelta(hours=2),
            address_edit_deadline=now + timedelta(hours=2),
        )
        first = self._chat(
            f"把订单号 {order.order_no} 改址到上海市长宁区仙霞路99号，联系人李华，电话18200001234",
            force_new_run=True,
        )
        self.assertEqual((first.get("pending_action") or {}).get("type"), "MODIFY_ADDRESS")
        self.assertTrue(bool(first.get("confirm_required")))

        second = self._chat("确认", run_id=first.get("run_id"))
        text = second.get("final_response", "")
        self.assertIn("地址已更新", text)
        self.assertIn("上海市长宁区仙霞路99号", text)
        self.assertIn("李华", text)
        self.assertIn("18200001234", text)

        order.refresh_from_db()
        self.assertIn("上海市长宁区仙霞路99号", (order.address_snapshot or {}).get("address_full", ""))
        self.assertEqual((order.contact_snapshot or {}).get("contact_name"), "李华")
        self.assertEqual((order.contact_snapshot or {}).get("contact_phone"), "18200001234")

    def test_inspection_query_returns_all_without_order_pick(self):
        self._create_sample_order(order_no="LPG2026022501110001")
        self._create_sample_order(
            order_no="LPG2026022501110002",
            payload_extra={"cylinder_purchase_date": "2022-03-18"},
        )
        data = self._chat("气瓶年检时间查询")
        self.assertIsNone(data.get("pending_action"))
        text = data.get("final_response", "")
        self.assertIn("LPG2026022501110001", text)
        self.assertIn("LPG2026022501110002", text)
        self.assertIn("下次年检", text)

    def test_inspection_reply_contains_concrete_due_dates(self):
        self._create_sample_order(
            order_no="LPG2026022501110003",
            payload_extra={"cylinder_purchase_date": "2021-02-10"},
        )
        data = self._chat("查询所有气瓶年检")
        self.assertIsNone(data.get("pending_action"))
        text = data.get("final_response", "")
        self.assertRegex(text, r"\d{4}-\d{2}-\d{2}")
        self.assertIn("建议您尽量在到期日前完成年检", text)

    def test_hose_question_not_misrouted_to_create_order(self):
        data = self._chat("软管多久需要更换一次？")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertFalse(bool(data.get("confirm_required")))
        routing = data.get("routing") or {}
        self.assertEqual(routing.get("safety_kind"), "general_qa")
        self.assertIn(routing.get("answer_source"), {"llm_direct", "typed_fallback"})
        self.assertNotIn("日常用气安全可以先记住这 5 点", data.get("final_response", ""))

    def test_repair_info_query_not_misrouted_to_create_order(self):
        data = self._chat("报修一般多久上门？")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertFalse(bool(data.get("confirm_required")))

    def test_installation_info_query_not_misrouted_to_create_order(self):
        data = self._chat("安装服务都包含哪些项目？")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertFalse(bool(data.get("confirm_required")))

    def test_exchange_info_query_not_misrouted_to_create_order(self):
        data = self._chat("换瓶流程是什么，旧瓶怎么处理？")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertFalse(bool(data.get("confirm_required")))

    def test_on_site_visit_request_routes_to_create_order(self):
        data = self._chat("喊个人上门看看")
        self.assertEqual((data.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertIn("安检", data.get("final_response", ""))

    def test_accessory_natural_sentence_routes_to_cart_add(self):
        data = self._chat("帮我下两个燃气灶和一个胶管")
        self.assertEqual((data.get("pending_action") or {}).get("type"), "CART_ADD")
        self.assertTrue(bool(data.get("confirm_required")))
        self.assertIn("购物车", data.get("final_response", ""))

    def test_accessory_quantity_sentence_routes_to_cart_add(self):
        data = self._chat("我要2个燃气报警器和3套卡箍", force_new_run=True)
        self.assertEqual((data.get("pending_action") or {}).get("type"), "CART_ADD")
        self.assertTrue(bool(data.get("confirm_required")))
        self.assertIn("购物车", data.get("final_response", ""))

    def test_alarm_fault_question_not_misrouted_to_cart_add(self):
        data = self._chat("报警器坏了，我可以拆下来吗")
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CART_ADD")
        text = data.get("final_response", "")
        self.assertTrue(("不要" in text and "拆" in text) or ("严禁" in text))

    def test_theme_switch_intent_sets_ui_theme(self):
        data = self._chat("切换黑夜模式")
        self.assertEqual(((data.get("routing") or {}).get("ui_theme")), "dark")
        self.assertIn("黑夜模式", data.get("final_response", ""))
        data2 = self._chat("白天模式")
        self.assertEqual(((data2.get("routing") or {}).get("ui_theme")), "light")
        self.assertIn("白天模式", data2.get("final_response", ""))

    def test_safety_leak_check_phrase_routes_to_safety_reply(self):
        data = self._chat("接好钢瓶后怎么检查漏气")
        self.assertIn((data.get("routing") or {}).get("lane"), {"safety", "rag"})
        self.assertEqual((data.get("routing") or {}).get("safety_kind"), "leak_assess")
        self.assertIn("肥皂水", data.get("final_response", ""))

    def test_safety_leak_assess_question_not_fallback_to_general_five_points(self):
        data = self._chat("如何判断燃气是否泄漏", force_new_run=True)
        routing = data.get("routing") or {}
        text = data.get("final_response", "")
        self.assertEqual(routing.get("safety_kind"), "leak_assess")
        self.assertIn(routing.get("answer_source"), {"llm_direct", "typed_fallback"})
        self.assertTrue(("肥皂水" in text) or ("泄漏" in text and "判断" in text))
        self.assertNotIn("日常用气安全可以先记住这 5 点", text)

    def test_cylinder_flat_question_not_fallback_to_general_five_points(self):
        data = self._chat("液化气瓶可以平放吗", force_new_run=True)
        routing = data.get("routing") or {}
        text = data.get("final_response", "")
        self.assertEqual(routing.get("safety_kind"), "general_qa")
        self.assertIn(routing.get("answer_source"), {"llm_direct", "typed_fallback"})
        self.assertTrue(("不建议平放" in text) or ("不可以平放" in text) or ("保持直立" in text))
        self.assertNotIn("日常用气安全可以先记住这 5 点", text)

    def test_address_delete_via_chat_with_confirm(self):
        addr = CustomerAddress.objects.create(
            user=self.user,
            contact_name="李四",
            contact_phone="13900001111",
            address_full="北京市朝阳区测试路88号",
            door_note="3层",
            is_default=False,
        )
        first = self._chat(f"删除地址ID {addr.id}")
        self.assertTrue(first.get("confirm_required"))
        self.assertEqual((first.get("pending_action") or {}).get("type"), "DELETE_ADDRESS")
        second = self._chat("确认", run_id=first.get("run_id"))
        self.assertIn("地址已删除", second.get("final_response", ""))
        self.assertFalse(CustomerAddress.objects.filter(id=addr.id).exists())

    def test_address_delete_accepts_id_colon_format(self):
        addr = CustomerAddress.objects.create(
            user=self.user,
            contact_name="王五",
            contact_phone="13900002222",
            address_full="上海市杨浦区测试路66号",
            door_note="5层",
            is_default=False,
        )
        first = self._chat(f"删除地址ID: {addr.id}", force_new_run=True)
        self.assertTrue(first.get("confirm_required"))
        self.assertEqual((first.get("pending_action") or {}).get("type"), "DELETE_ADDRESS")
        second = self._chat("确认", run_id=first.get("run_id"))
        self.assertIn("地址已删除", second.get("final_response", ""))
        self.assertFalse(CustomerAddress.objects.filter(id=addr.id).exists())

    def test_address_delete_accepts_delete_id_without_address_word(self):
        addr = CustomerAddress.objects.create(
            user=self.user,
            contact_name="赵六",
            contact_phone="13900003333",
            address_full="上海市普陀区测试路77号",
            door_note="6层",
            is_default=False,
        )
        first = self._chat(f"删除ID{addr.id}", force_new_run=True)
        self.assertTrue(first.get("confirm_required"))
        self.assertEqual((first.get("pending_action") or {}).get("type"), "DELETE_ADDRESS")
        second = self._chat("确认", run_id=first.get("run_id"))
        self.assertIn("地址已删除", second.get("final_response", ""))
        self.assertFalse(CustomerAddress.objects.filter(id=addr.id).exists())

    def test_change_password_via_chat_with_confirm(self):
        first = self._chat("我要改密码")
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CHANGE_PASSWORD")
        run_id = first.get("run_id")
        self._chat("旧密码 12345678", run_id=run_id)
        self._chat("新密码 123456789", run_id=run_id)
        fourth = self._chat("确认新密码 123456789", run_id=run_id)
        self.assertTrue(fourth.get("confirm_required"))
        fifth = self._chat("确认", run_id=run_id)
        self.assertIn("密码已修改", fifth.get("final_response", ""))

    def test_notification_read_all_via_chat(self):
        CustomerNotification.objects.create(
            user=self.user,
            category=CustomerNotification.CATEGORY_ORDER,
            event_code="ORDER_CREATED",
            title="订单已创建",
            content="订单 LPG202602260000001 已创建",
            target_type=CustomerNotification.TARGET_ORDER,
            target_route="#/portal/orders/1",
            is_read=False,
        )
        CustomerNotification.objects.create(
            user=self.user,
            category=CustomerNotification.CATEGORY_FEEDBACK,
            event_code="FEEDBACK_CREATED",
            title="投诉已提交",
            content="反馈 #1001 已提交",
            target_type=CustomerNotification.TARGET_FEEDBACK,
            target_route="#/portal/profile",
            is_read=False,
        )
        first = self._chat("全部已读")
        self.assertTrue(first.get("confirm_required"))
        self.assertEqual((first.get("pending_action") or {}).get("type"), "NOTIFICATION_READ_ALL")
        second = self._chat("确认", run_id=first.get("run_id"))
        self.assertIn("全部标记为已读", second.get("final_response", ""))
        self.assertEqual(CustomerNotification.objects.filter(user=self.user, is_read=False).count(), 0)

    def test_cart_add_query_and_checkout_flow(self):
        first = self._chat("把软管2件加入购物车")
        self.assertTrue(first.get("confirm_required"))
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CART_ADD")
        run_id = first.get("run_id")

        second = self._chat("确认", run_id=run_id)
        self.assertIn("购物车", second.get("final_response", ""))
        self.assertEqual(CustomerCartItem.objects.filter(user=self.user, sku="HOSE").first().quantity, 2)

        third = self._chat("结算购物车", run_id=run_id)
        self.assertTrue(third.get("confirm_required"))
        self.assertEqual((third.get("pending_action") or {}).get("type"), "CART_CHECKOUT")

        fourth = self._chat("确认", run_id=run_id)
        self.assertIn("下单并支付成功", fourth.get("final_response", ""))
        latest = PortalOrder.objects.filter(user=self.user).order_by("-created_at").first()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.service_type, SERVICE_TYPE_ACCESSORIES)
        self.assertEqual(latest.status, ORDER_STATUS_PAID)

    def test_forbidden_modify_cart_item_price_blocked(self):
        data = self._chat("把购物车里软管价格改成1元", force_new_run=True)
        routing = data.get("routing") or {}
        self.assertEqual(routing.get("lane"), "policy_guard")
        self.assertIsNone(data.get("pending_action"))
        self.assertIn("不能", data.get("final_response", ""))

    def test_forbidden_modify_historical_order_blocked(self):
        data = self._chat("把历史订单LPG202402010001价格改掉", force_new_run=True)
        routing = data.get("routing") or {}
        self.assertEqual(routing.get("lane"), "policy_guard")
        self.assertIsNone(data.get("pending_action"))
        self.assertIn("不能", data.get("final_response", ""))

    def test_pending_feedback_not_reused_without_live_pending_action(self):
        CustomerConversationMemory.objects.update_or_create(
            user=self.user,
            defaults={
                "memory_json": {
                    "pending_feedback": {
                        "feedback_type": "COMPLAINT",
                        "content": "模拟残留",
                    }
                }
            },
        )
        data = self._chat("帮我看下LPG202402010001这单的费用明细", force_new_run=True)
        self.assertNotEqual((data.get("pending_action") or {}).get("type"), "CREATE_FEEDBACK")

    def test_pending_feedback_allows_side_query_then_resume_hint(self):
        self._create_sample_order(order_no="LPG2026022600990001")
        first = self._chat("我要投诉这次上门服务态度不好", force_new_run=True)
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CREATE_FEEDBACK")
        second = self._chat("今日液化气价格", run_id=first.get("run_id"))
        self.assertEqual((second.get("pending_action") or {}).get("type"), "CREATE_FEEDBACK")
        self.assertIn("继续投诉", second.get("final_response", ""))
        self.assertNotIn("还没识别到您选择的订单", second.get("final_response", ""))

    def test_batch_action_detects_accessory_plus_repair(self):
        data = self._chat("帮我弄个燃气报警器和一个卡箍，再喊个师傅来检修", force_new_run=True)
        pending = data.get("pending_action") or {}
        self.assertEqual(pending.get("type"), "BATCH_ACTION")
        self.assertEqual(pending.get("confirm_mode"), "ALL_IN_ONE")
        self.assertTrue(bool(data.get("confirm_required")))
        self.assertTrue(bool((data.get("routing") or {}).get("batch")))

    def test_batch_action_executes_with_single_confirm(self):
        first = self._chat("帮我弄个燃气报警器和一个卡箍，再喊个师傅来检修", force_new_run=True)
        self.assertEqual((first.get("pending_action") or {}).get("type"), "BATCH_ACTION")
        self.assertTrue(bool(first.get("confirm_required")))
        second = self._chat("确认", run_id=first.get("run_id"))
        text = second.get("final_response", "")
        self.assertIn("组合需求已处理完成", text)
        self.assertTrue(CustomerCartItem.objects.filter(user=self.user, sku="ALARM").exists())
        self.assertTrue(CustomerCartItem.objects.filter(user=self.user, sku="CLAMP_SET").exists())
        repair_order = PortalOrder.objects.filter(user=self.user, service_type=SERVICE_TYPE_REPAIR).order_by("-created_at").first()
        self.assertIsNotNone(repair_order)

    def test_address_create_synonyms_route_to_create(self):
        for phrase in ["新建地址", "创建地址", "建个地址"]:
            data = self._chat(phrase, force_new_run=True)
            self.assertEqual((data.get("pending_action") or {}).get("type"), "CREATE_ADDRESS")

    def test_address_query_phrase_routes_to_tool_query(self):
        data = self._chat("我有哪些地址", force_new_run=True)
        routing = data.get("routing") or {}
        text = data.get("final_response", "")
        self.assertEqual(routing.get("lane"), "action")
        self.assertTrue(bool(routing.get("query_first_applied")))
        self.assertIn("地址ID", text)
        self.assertIn("联系人：", text)

    def test_address_query_variant_routes_to_tool_query(self):
        data = self._chat("帮我看下我现在有几个收货地址", force_new_run=True)
        routing = data.get("routing") or {}
        self.assertEqual(routing.get("lane"), "action")
        self.assertTrue(bool(routing.get("query_first_applied")))
        self.assertIn("地址ID", data.get("final_response", ""))

    def test_address_query_synonym_group_all_hit_query_first(self):
        phrases = [
            "我的地址",
            "地址列表",
            "全部地址",
            "所有地址",
            "收货地址有几个",
            "帮我列下地址",
        ]
        for phrase in phrases:
            data = self._chat(phrase, force_new_run=True)
            routing = data.get("routing") or {}
            self.assertEqual(routing.get("lane"), "action")
            self.assertTrue(bool(routing.get("query_first_applied")))
            self.assertIn("地址ID", data.get("final_response", ""))

    def test_address_query_limit_notice_when_reaching_top_n(self):
        for idx in range(2, 14):
            CustomerAddress.objects.create(
                user=self.user,
                contact_name=f"联系人{idx}",
                contact_phone=f"1390000{idx:04d}",
                address_full=f"上海市浦东新区测试路{idx}号",
                door_note=f"{idx}层",
                is_default=False,
            )
        data = self._chat("给我列一下地址", force_new_run=True)
        text = data.get("final_response", "")
        self.assertEqual((data.get("routing") or {}).get("lane"), "action")
        self.assertIn("当前最多展示最近 10 条地址", text)
        self.assertIn("10. 地址ID", text)
        self.assertNotIn("11. 地址ID", text)

    def test_address_query_and_write_intent_are_separated(self):
        query_data = self._chat("我地址有哪些", force_new_run=True)
        self.assertTrue(bool((query_data.get("routing") or {}).get("query_first_applied")))
        write_data = self._chat("把这单改址", force_new_run=True)
        self.assertFalse(bool((write_data.get("routing") or {}).get("query_first_applied")))
        self.assertIn("订单号", write_data.get("final_response", ""))

    def test_address_update_by_id_routes_to_address_update(self):
        target = CustomerAddress.objects.create(
            user=self.user,
            contact_name="李四",
            contact_phone="13900001111",
            address_full="北京市朝阳区测试路88号",
            door_note="3层",
            is_default=False,
        )
        first = self._chat(
            f"把地址ID {target.id} 改成深圳市南山区科技园2号，联系人赵六，电话13800002223",
            force_new_run=True,
        )
        pending = first.get("pending_action") or {}
        self.assertEqual(pending.get("type"), "UPDATE_ADDRESS")
        self.assertTrue(bool(first.get("confirm_required")))
        second = self._chat("确认", run_id=first.get("run_id"))
        self.assertIn("地址已更新", second.get("final_response", ""))
        target.refresh_from_db()
        self.assertEqual(target.contact_name, "赵六")
        self.assertEqual(target.contact_phone, "13800002223")
        self.assertIn("深圳市南山区科技园2号", target.address_full)

    def test_order_query_synonym_hits_query_flow(self):
        self._create_sample_order(order_no="LPG2026030400010001")
        data = self._chat("我有哪些订单", force_new_run=True)
        routing = data.get("routing") or {}
        self.assertEqual(routing.get("lane"), "action")
        self.assertTrue(bool(routing.get("query_first_applied")))
        self.assertFalse(bool(routing.get("clarify_needed")))
        self.assertIn("订单", data.get("final_response", ""))

    def test_combined_address_and_order_query_returns_both_sections(self):
        self._create_sample_order(order_no="LPG2026030400010002")
        data = self._chat("帮我查下地址并看最近订单", force_new_run=True)
        text = data.get("final_response", "")
        self.assertEqual((data.get("routing") or {}).get("lane"), "action")
        self.assertIn("地址ID", text)
        self.assertIn("订单", text)

    def test_batch_action_with_multiple_service_candidates_executes_in_one_confirm(self):
        data = self._chat("一次帮我下单：配送一瓶15kg，再来一个报警器，并安排上门安检", force_new_run=True)
        pending = data.get("pending_action") or {}
        self.assertEqual(pending.get("type"), "BATCH_ACTION")
        self.assertTrue(bool(data.get("confirm_required")))
        text = data.get("final_response", "")
        self.assertIn("服务单1", text)
        self.assertIn("服务单2", text)
        second = self._chat("确认", run_id=data.get("run_id"))
        second_text = second.get("final_response", "")
        self.assertIn("组合需求已处理完成", second_text)
        self.assertTrue(CustomerCartItem.objects.filter(user=self.user, sku="ALARM").exists())
        delivery = PortalOrder.objects.filter(user=self.user, service_type=SERVICE_TYPE_LPG_CYLINDER_DELIVERY).order_by("-created_at").first()
        safety = PortalOrder.objects.filter(user=self.user, service_type=SERVICE_TYPE_SAFETY_CHECK).order_by("-created_at").first()
        self.assertIsNotNone(delivery)
        self.assertIsNotNone(safety)

    def test_hotline_is_suppressed_for_normal_address_consulting(self):
        first = self._chat("我想看下地址信息", force_new_run=True)
        second = self._chat("地址有点不对，帮我看看", run_id=first.get("run_id"))
        self.assertNotIn("400-888-0000", first.get("final_response", ""))
        self.assertNotIn("400-888-0000", second.get("final_response", ""))
        self.assertNotIn("最牵挂", first.get("final_response", ""))
        self.assertNotIn("最牵挂", second.get("final_response", ""))

    def test_safety_high_risk_still_keeps_hotline_and_care_closing(self):
        data = self._chat("闻到燃气味了怎么办，先做什么", force_new_run=True)
        text = data.get("final_response", "")
        routing = data.get("routing") or {}
        self.assertIn("400-888-0000", text)
        self.assertIn("最牵挂", text)
        self.assertEqual(routing.get("rag_topic_selected"), "safety_leak")
        self.assertEqual(routing.get("safety_kind"), "emergency")
        self.assertEqual(routing.get("answer_source"), "emergency_template")

    def test_manual_contact_request_enters_queue_state(self):
        data = self._chat("我要联系客服", force_new_run=True)
        routing = data.get("routing") or {}
        queue = routing.get("manual_queue") or {}
        text = data.get("final_response", "")
        self.assertTrue(bool(routing.get("manual_handoff")))
        self.assertIn(queue.get("status"), {"WAITING", "CONNECTING"})
        self.assertIsNotNone(queue.get("ahead_count"))
        self.assertIsNotNone(queue.get("eta_minutes"))
        self.assertIn("正在为您排队接入人工客服", text)

    def test_manual_queue_allows_side_query_and_keeps_queue(self):
        first = self._chat("我要联系客服", force_new_run=True)
        second = self._chat("我有哪些地址", run_id=first.get("run_id"))
        routing = second.get("routing") or {}
        queue = routing.get("manual_queue") or {}
        text = second.get("final_response", "")
        self.assertEqual(routing.get("lane"), "action")
        self.assertTrue(bool(routing.get("manual_handoff")))
        self.assertIn(queue.get("status"), {"WAITING", "CONNECTING"})
        self.assertIn("地址ID", text)

    def test_manual_queue_can_be_canceled(self):
        first = self._chat("我要联系客服", force_new_run=True)
        second = self._chat("取消人工排队", run_id=first.get("run_id"))
        routing = second.get("routing") or {}
        self.assertFalse(bool(routing.get("manual_handoff")))
        self.assertFalse(bool(routing.get("manual_queue")))
        self.assertIn("取消人工排队", second.get("final_response", ""))

    def test_unknown_non_ambiguous_prefers_smalltalk_direct_answer(self):
        data = self._chat("你觉得客服对话还能怎么优化体验", force_new_run=True)
        routing = data.get("routing") or {}
        self.assertEqual(routing.get("lane"), "smalltalk")
        self.assertFalse(bool(routing.get("clarify_needed")))

    def test_unknown_intent_prefers_direct_answer_without_clarify(self):
        data = self._chat("我想问个事", force_new_run=True)
        routing = data.get("routing") or {}
        text = data.get("final_response", "")
        self.assertFalse(bool(routing.get("clarify_needed")))
        self.assertIn(routing.get("lane"), {"smalltalk", "rag"})
        self.assertTrue(bool(text.strip()))

    def test_ambiguity_does_not_loop_on_repeated_turns(self):
        first = self._chat("我想问个事", force_new_run=True)
        self.assertFalse(bool((first.get("routing") or {}).get("clarify_needed")))
        second = self._chat("还是这个问题", run_id=first.get("run_id"))
        self.assertFalse(bool((second.get("routing") or {}).get("clarify_needed")))
        third = self._chat("我这个要怎么弄", run_id=first.get("run_id"))
        self.assertFalse(bool((third.get("routing") or {}).get("clarify_needed")))
        self.assertTrue(bool(third.get("final_response", "").strip()))

    def test_query_flow_still_works_after_ambiguous_opening(self):
        first = self._chat("我有个问题", force_new_run=True)
        self.assertFalse(bool((first.get("routing") or {}).get("clarify_needed")))
        second = self._chat("我有哪些地址", run_id=first.get("run_id"))
        routing = second.get("routing") or {}
        self.assertEqual(routing.get("lane"), "action")
        self.assertTrue(bool(routing.get("query_first_applied")))
        self.assertFalse(bool(routing.get("clarify_needed")))
        self.assertEqual(routing.get("clarify_round"), 0)

    def test_general_safety_question_not_shifted_to_leak_check(self):
        data = self._chat("使用煤气怎么注意安全", force_new_run=True)
        text = data.get("final_response", "")
        routing = data.get("routing") or {}
        self.assertIn("安全", text)
        self.assertNotIn("肥皂水", text)
        self.assertEqual(routing.get("rag_topic_selected"), "safety_general")
        self.assertEqual(routing.get("safety_kind"), "general_qa")
        self.assertIn(routing.get("answer_source"), {"llm_direct", "typed_fallback"})

    def test_safety_scene_short_followup_bypasses_general_ambiguity(self):
        first = self._chat("燃气安全", force_new_run=True)
        second = self._chat("餐饮", run_id=first.get("run_id"))
        routing = second.get("routing") or {}
        text = second.get("final_response", "")
        self.assertFalse(bool(routing.get("clarify_needed")))
        self.assertEqual(routing.get("safety_kind"), "general_qa")
        self.assertIn(routing.get("answer_source"), {"llm_direct", "typed_fallback"})
        self.assertNotIn("查询信息", text)
        self.assertNotIn("直接办理业务", text)

    def test_safety_overview_request_can_use_general_five_points_template(self):
        data = self._chat("日常用气安全注意事项", force_new_run=True)
        text = data.get("final_response", "")
        routing = data.get("routing") or {}
        self.assertEqual(routing.get("safety_kind"), "general_qa")
        self.assertIn(routing.get("answer_source"), {"llm_direct", "typed_fallback"})
        if routing.get("answer_source") == "typed_fallback":
            self.assertIn("日常用气安全可以先记住这 5 点", text)

    def test_pending_order_side_query_address_then_resume_hint(self):
        first = self._chat("我要下单 15kg", force_new_run=True)
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        second = self._chat("我的地址列表", run_id=first.get("run_id"))
        self.assertEqual((second.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        self.assertIn("地址ID", second.get("final_response", ""))
        self.assertIn("继续下单", second.get("final_response", ""))

    def test_create_order_switch_address_by_contact_name_fragment(self):
        target = CustomerAddress.objects.create(
            user=self.user,
            contact_name="李华",
            contact_phone="18200001234",
            address_full="上海市闵行区虹桥路200号",
            door_note="3层",
            is_default=False,
        )
        first = self._chat("我要下单 15kg 1瓶", force_new_run=True)
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        second = self._chat("改成地址是李华的那个", run_id=first.get("run_id"))
        pending = second.get("pending_action") or {}
        self.assertEqual(pending.get("type"), "CREATE_ORDER")
        draft = pending.get("draft") or {}
        self.assertEqual(int(draft.get("address_id") or 0), target.id)
        self.assertIn("李华", second.get("final_response", ""))

    def test_create_order_switch_address_by_phone_prefix_with_ambiguity_then_choose(self):
        CustomerAddress.objects.create(
            user=self.user,
            contact_name="赵一",
            contact_phone="18212340001",
            address_full="上海市黄浦区延安东路100号",
            door_note="A座",
            is_default=False,
        )
        CustomerAddress.objects.create(
            user=self.user,
            contact_name="赵二",
            contact_phone="18212349999",
            address_full="上海市徐汇区漕溪北路200号",
            door_note="B座",
            is_default=False,
        )
        first = self._chat("我要下单 15kg 1瓶", force_new_run=True)
        self.assertEqual((first.get("pending_action") or {}).get("type"), "CREATE_ORDER")
        second = self._chat("地址改成182那个", run_id=first.get("run_id"))
        pending2 = second.get("pending_action") or {}
        self.assertEqual(pending2.get("type"), "CREATE_ORDER")
        self.assertEqual(pending2.get("status"), "COLLECTING")
        self.assertIn("多个匹配地址", second.get("final_response", ""))
        candidates = (pending2.get("draft") or {}).get("address_candidates") or []
        self.assertGreaterEqual(len(candidates), 2)
        expected_id = int(candidates[1].get("id"))

        third = self._chat("第2个", run_id=first.get("run_id"))
        pending3 = third.get("pending_action") or {}
        self.assertEqual(pending3.get("type"), "CREATE_ORDER")
        self.assertEqual(pending3.get("status"), "AWAIT_CONFIRM")
        draft3 = pending3.get("draft") or {}
        self.assertEqual(int(draft3.get("address_id") or 0), expected_id)


class PortalModeFallbackReadonlyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="13900112233", password="12345678")
        CustomerProfile.objects.create(user=self.user, phone="13900112233", display_name="测试用户")
        CustomerAddress.objects.create(
            user=self.user,
            contact_name="测试用户",
            contact_phone="13900112233",
            address_full="上海市徐汇区测试路99号",
            door_note="1层",
            is_default=True,
        )
        self.token = CustomerAuthToken.rotate_token(self.user).token

    def _chat(self, message):
        response = self.client.post(
            "/api/chat",
            data=json.dumps({"message": message, "portal_mode": True, "model_provider": "OLLAMA"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.token}",
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_write_intent_blocked_in_readonly_mode(self):
        data = self._chat("我要下单 15kg 两瓶")
        pending = data.get("pending_action")
        self.assertIsNone(pending)
        routing = data.get("routing") or {}
        self.assertEqual(routing.get("lane"), "fallback_readonly")
        self.assertIn("只读", data.get("final_response", ""))
