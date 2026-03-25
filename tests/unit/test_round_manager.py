from __future__ import annotations

from datetime import datetime, timezone
import unittest

from binance_detector.rounds.manager import CanonicalRoundManager


class RoundManagerTests(unittest.TestCase):
    def test_open_price_is_fixed_once_per_round(self) -> None:
        manager = CanonicalRoundManager()
        ts = datetime(2026, 3, 24, 10, 0, 2, tzinfo=timezone.utc)

        round_a = manager.track("btc-5m", ts, 100_000.0)
        round_b = manager.track("btc-5m", ts.replace(second=40), 100_010.0)

        self.assertEqual(round_a.round_id, round_b.round_id)
        self.assertEqual(round_b.round_open_price, 100_000.0)
        self.assertEqual(round_b.last_market_price, 100_010.0)

    def test_round_id_changes_on_next_five_minute_boundary(self) -> None:
        manager = CanonicalRoundManager()
        first = manager.track("btc-5m", datetime(2026, 3, 24, 10, 4, 59, tzinfo=timezone.utc), 1.0)
        second = manager.track("btc-5m", datetime(2026, 3, 24, 10, 5, 0, tzinfo=timezone.utc), 1.1)

        self.assertNotEqual(first.round_id, second.round_id)


if __name__ == "__main__":
    unittest.main()
