import json

from django.test import TestCase
from django.urls import reverse


class ResponseQualityTests(TestCase):
    def _post_chat(self, message):
        # 中文注释：统一封装 chat 请求，便于复用
        return self.client.post(
            reverse("chat"),
            data=json.dumps({"message": message}),
            content_type="application/json",
        )

    def test_order_query_no_repeat_prompt(self):
        response = self._post_chat("用手机号 13800112211 查订单")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        text = payload.get("final_response", "")
        self.assertNotIn("请提供订单号", text)
        self.assertNotIn("订单号或手机号", text)

    def test_show_form_response_fixed(self):
        response = self._post_chat("我要订气")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("ui_action"), "SHOW_FORM")
        text = payload.get("final_response", "")
        self.assertNotIn("请提供订单号", text)
        self.assertNotIn("订单号或手机号", text)

    def test_safety_medium_no_order_terms(self):
        response = self._post_chat("热水器点火失败怎么办")
        self.assertEqual(response.status_code, 200)
        text = response.json().get("final_response", "")
        self.assertNotIn("订单", text)
        self.assertNotIn("手机号", text)

    def test_safety_high_self_repair(self):
        response = self._post_chat("我能自己修漏气吗")
        self.assertEqual(response.status_code, 200)
        text = response.json().get("final_response", "")
        self.assertIn("不建议", text)
        self.assertIn("应急", text)

    def test_safety_high_mixed(self):
        response = self._post_chat("煤气泄漏了还能帮我查订单吗")
        self.assertEqual(response.status_code, 200)
        text = response.json().get("final_response", "")
        self.assertIn("先处理安全", text)
