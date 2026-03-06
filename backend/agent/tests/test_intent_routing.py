import unittest

from agent.intent import intent_router


class IntentRoutingTests(unittest.TestCase):
    def test_greeting_intent(self):
        result = intent_router("你好")
        self.assertEqual(result["intent"], "GREETING")

    def test_identity_intent(self):
        result = intent_router("你是谁")
        self.assertEqual(result["intent"], "IDENTITY")

    def test_order_query_intent(self):
        result = intent_router("查一下订单 10002341")
        self.assertEqual(result["intent"], "ORDER_QUERY")
        self.assertEqual(result["slots"].get("order_id"), 10002341)

    def test_order_urge_intent(self):
        result = intent_router("订单 10002341 超时了，帮我催一下")
        self.assertEqual(result["intent"], "ORDER_URGE")
        self.assertEqual(result["slots"].get("order_id"), 10002341)

    def test_complaint_intent(self):
        result = intent_router("送气师傅态度很差")
        self.assertEqual(result["intent"], "TICKET_COMPLAINT")

    def test_modify_address_intent(self):
        result = intent_router("把订单 10002341 地址改成 北京朝阳xx路99号")
        self.assertEqual(result["intent"], "ORDER_MODIFY_ADDRESS")
        self.assertEqual(result["slots"].get("order_id"), 10002341)
        self.assertIn("北京朝阳xx路99号", result["slots"].get("new_address", ""))

    def test_safety_high_intent(self):
        result = intent_router("煤气泄漏了怎么办")
        self.assertEqual(result["intent"], "SAFETY_HIGH")

    def test_safety_low_intent(self):
        result = intent_router("燃气软管多久换一次")
        self.assertEqual(result["intent"], "SAFETY_LOW")
