from __future__ import annotations

import unittest

from binance_detector.config.settings import settings
from binance_detector.strategy.entry_policy import EntryPolicy


class EntryPolicyTests(unittest.TestCase):
    def test_active_v2_policy_whitelists_only_selected_buckets(self) -> None:
        policy = EntryPolicy.from_json(settings.entry_policy_path)

        self.assertEqual(policy.allowed_tiers_for("early", "near"), ())
        self.assertEqual(policy.allowed_tiers_for("early", "stretched"), ("very_strong",))
        self.assertEqual(policy.allowed_tiers_for("mid", "stretched"), ("strong", "very_strong"))
        self.assertEqual(policy.allowed_tiers_for("late", "far"), ("strong", "very_strong"))
        self.assertEqual(policy.allowed_tiers_for("late", "stretched"), ("very_strong",))
        self.assertEqual(policy.allowed_tiers_for("final", "far"), ("very_strong",))
        self.assertEqual(policy.allowed_tiers_for("final", "near"), ("very_strong",))


if __name__ == "__main__":
    unittest.main()
