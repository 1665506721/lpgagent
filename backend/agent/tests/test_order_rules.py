import unittest
from datetime import datetime, timedelta, timezone

from agent import rules


class OrderRulesTests(unittest.TestCase):
    def test_overdue_severe(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        eta = now - timedelta(hours=3)
        level = rules.overdue_level(now, eta, "DISPATCHED")
        self.assertEqual(level, rules.OVERDUE_LEVEL_SEVERE)

    def test_overdue_mild(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        eta = now - timedelta(minutes=40)
        level = rules.overdue_level(now, eta, "DELIVERING")
        self.assertEqual(level, rules.OVERDUE_LEVEL_MILD)

    def test_overdue_not_applicable(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        eta = now - timedelta(hours=5)
        self.assertEqual(rules.overdue_level(now, eta, "CREATED"), rules.OVERDUE_LEVEL_NONE)
        self.assertEqual(rules.overdue_level(now, eta, "DONE"), rules.OVERDUE_LEVEL_NONE)

    def test_overdue_unknown(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        level = rules.overdue_level(now, None, "DELIVERING")
        self.assertEqual(level, rules.OVERDUE_LEVEL_UNKNOWN)

    def test_can_modify_address(self):
        self.assertTrue(rules.can_modify_address("CONFIRMED"))
        self.assertFalse(rules.can_modify_address("DELIVERING"))

    def test_status_display_and_explain(self):
        display = rules.status_display("DISPATCHED")
        explain = rules.status_explain("DISPATCHED")
        self.assertTrue(display)
        self.assertTrue(explain)
