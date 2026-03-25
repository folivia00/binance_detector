from __future__ import annotations

import unittest

from binance_detector.domain.rounds import RoundFeatures
from binance_detector.models.baseline import BaselineProbabilityModel


class BaselineModelTests(unittest.TestCase):
    def test_probability_increases_when_distance_and_velocity_increase(self) -> None:
        model = BaselineProbabilityModel()
        base = RoundFeatures(
            distance_to_open_bps=1.0,
            distance_bucket="at_open",
            time_left_bucket="mid",
            time_left_seconds=150,
            velocity_short=0.02,
            queue_imbalance=0.05,
            microprice_delta=0.0001,
            volatility_recent=0.0005,
        )
        stronger = RoundFeatures(
            distance_to_open_bps=12.0,
            distance_bucket="far",
            time_left_bucket="mid",
            time_left_seconds=150,
            velocity_short=0.18,
            queue_imbalance=0.35,
            microprice_delta=0.0005,
            volatility_recent=0.0005,
        )

        self.assertGreater(model.predict(stronger, "r1").p_up_total, model.predict(base, "r1").p_up_total)


if __name__ == "__main__":
    unittest.main()
