import json

from django.test import TestCase
from django.urls import reverse


class HealthAndRunsTests(TestCase):
    def test_health_endpoint_returns_expected_shape(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for key in ["status", "db", "kb", "model", "time"]:
            self.assertIn(key, payload)

    def test_runs_list_returns_items(self):
        response = self.client.post(
            reverse("chat"),
            data=json.dumps({"message": "hello"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        runs_response = self.client.get(f"{reverse('runs-list')}?limit=20")
        self.assertEqual(runs_response.status_code, 200)
        payload = runs_response.json()
        self.assertIn("items", payload)
        self.assertTrue(payload["items"])
        item = payload["items"][0]
        for key in ["run_id", "created_at", "model_provider", "event_count", "last_state"]:
            self.assertIn(key, item)
