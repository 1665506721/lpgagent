import json

from django.test import TestCase
from django.urls import reverse

from core.models import AgentEvent, AgentRun


class ToolsApiTests(TestCase):
    def test_create_order_missing_user_id(self):
        response = self.client.post(
            reverse("create-order"),
            data=json.dumps({"product_type": "15kg", "quantity": 2, "address": "xx"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("error"), "user_id is required")

        run = AgentRun.objects.order_by("-created_at").first()
        self.assertIsNotNone(run)
        event = AgentEvent.objects.get(run=run, tool_name="create_order")
        self.assertEqual(event.state, AgentEvent.STATE_TOOL_EXEC)
        self.assertEqual(event.policy_result.get("allow"), False)
        self.assertIn("missing_user_id", event.policy_result.get("reasons", []))

    def test_query_order_not_found(self):
        response = self.client.post(
            reverse("query-order"),
            data=json.dumps({"order_id": 999999}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

        event = AgentEvent.objects.filter(tool_name="query_order").order_by("-created_at").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.state, AgentEvent.STATE_TOOL_EXEC)
        self.assertEqual(event.policy_result.get("allow"), False)
