from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

from binance_detector.config.market_registry import get_market_spec
from binance_detector.config.settings import settings
from binance_detector.connectors.binance.client import BinanceClient
from binance_detector.connectors.polymarket.client import PolymarketClient


class FailingBinanceClient(BinanceClient):
    def _get_json(self, *, path: str, params: dict[str, object]) -> dict | list:
        raise RuntimeError("forced failure")


class MarketRegistryAndFallbackTests(unittest.TestCase):
    def test_dynamic_btc_5m_slug_resolves_from_round_start_epoch(self) -> None:
        spec = get_market_spec(settings.pm_market_registry_path, "btc_updown_5m")
        self.assertIsNotNone(spec)
        client = PolymarketClient(market_slug="btc-updown-5m")
        slug = client.resolve_market_slug_for_spec(
            spec,
            datetime(2026, 3, 24, 11, 5, 37, tzinfo=timezone.utc),
        )
        self.assertEqual(slug, "btc-updown-5m-1774350300")

    def test_binance_demo_fallback_is_marked_explicitly(self) -> None:
        snapshot = FailingBinanceClient().fetch_signal_snapshot()
        self.assertEqual(snapshot.snapshot_source, "demo")
        self.assertIn("forced failure", snapshot.fallback_reason)


if __name__ == "__main__":
    unittest.main()
