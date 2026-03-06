import json

from django.test import Client, TestCase


class FormProtocolTests(TestCase):
    def setUp(self):
        self.client = Client()

    def _post_chat(self, message):
        response = self.client.post(
            "/api/chat",
            data=json.dumps({"message": message}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content.decode("utf-8"))

    def test_order_create_form(self):
        data = self._post_chat("我要订气")
        self.assertEqual(data.get("ui_action"), "SHOW_FORM")
        self.assertEqual(data.get("form", {}).get("form_id"), "order_create_v1")

    def test_order_create_prefill(self):
        data = self._post_chat("我要订2瓶15kg")
        prefill = data.get("form", {}).get("prefill", {})
        self.assertEqual(prefill.get("quantity"), 2)
        self.assertEqual(prefill.get("cylinder_type"), "15kg")

    def test_complaint_form(self):
        data = self._post_chat("送气师傅态度很差")
        self.assertEqual(data.get("ui_action"), "SHOW_FORM")
        self.assertEqual(data.get("form", {}).get("form_id"), "ticket_complaint_v1")

    def test_modify_address_no_form_when_complete(self):
        data = self._post_chat("我要改地址，订单10002341改成xx路99号")
        self.assertNotIn("ui_action", data)

    def test_order_query_form(self):
        data = self._post_chat("我想查订单")
        self.assertEqual(data.get("ui_action"), "SHOW_FORM")
        self.assertEqual(data.get("form", {}).get("form_id"), "order_query_v1")

    def test_safety_service_form(self):
        data = self._post_chat("预约上门安检，地址xx小区")
        self.assertEqual(data.get("ui_action"), "SHOW_FORM")
        self.assertEqual(data.get("form", {}).get("form_id"), "safety_service_request_v1")
