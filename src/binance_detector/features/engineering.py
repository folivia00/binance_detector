from __future__ import annotations

from collections.abc import Sequence


def build_feature_row(candles: Sequence[dict]) -> dict[str, float]:
    """Build a minimal feature vector from Binance candles."""
    if not candles:
        return {
            "return_1m": 0.0,
            "range_mean": 0.0,
            "volume_sum": 0.0,
        }

    first_open = float(candles[0].get("open", 0.0))
    last_close = float(candles[-1].get("close", 0.0))
    volume_sum = sum(float(candle.get("volume", 0.0)) for candle in candles)
    range_mean = sum(
        float(candle.get("high", 0.0)) - float(candle.get("low", 0.0))
        for candle in candles
    ) / len(candles)
    price_return = 0.0 if first_open == 0 else (last_close - first_open) / first_open

    return {
        "return_1m": price_return,
        "range_mean": range_mean,
        "volume_sum": volume_sum,
    }

