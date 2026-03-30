from __future__ import annotations

import unittest
from datetime import datetime, timezone

from binance_detector.connectors.polymarket.client import PolymarketClient


def _make_book(asks_desc: list[float], bids_asc: list[float], ts: str = "0") -> dict:
    """Build a mock CLOB order book.

    asks_desc: prices in DESCENDING order (as returned by PM CLOB API)
    bids_asc:  prices in ASCENDING order (as returned by PM CLOB API)
    """
    return {
        "asks": [{"price": str(p), "size": "100"} for p in asks_desc],
        "bids": [{"price": str(p), "size": "100"} for p in bids_asc],
        "timestamp": ts,
    }


class TestBuildQuoteAskOrder(unittest.TestCase):
    """Verify _build_quote correctly handles PM CLOB sort order.

    PM CLOB returns:
      asks: DESCENDING  (highest price first → worst ask at [0], best ask at [-1])
      bids: ASCENDING   (lowest price first  → worst bid at [0], best bid at [-1])
    """

    def _client(self) -> PolymarketClient:
        return PolymarketClient(market_slug="btc-updown-5m-test")

    def test_best_ask_is_last_element(self):
        """asks[0]=0.99 (worst), asks[-1]=0.55 (best) → yes_ask must be 0.55."""
        yes_book = _make_book(asks_desc=[0.99, 0.80, 0.70, 0.60, 0.55], bids_asc=[0.01, 0.02, 0.03, 0.04, 0.45])
        no_book  = _make_book(asks_desc=[0.99, 0.80, 0.70, 0.60, 0.40], bids_asc=[0.01, 0.02, 0.03, 0.04, 0.35])
        client = self._client()
        quote = client._build_quote(yes_book=yes_book, no_book=no_book)

        self.assertAlmostEqual(quote.yes_ask, 0.55, places=4)
        self.assertAlmostEqual(quote.no_ask, 0.40, places=4)

    def test_best_bid_is_last_element(self):
        """bids[-1]=0.45 (best) → yes_bid must be 0.45."""
        yes_book = _make_book(asks_desc=[0.99, 0.55], bids_asc=[0.01, 0.20, 0.35, 0.45])
        no_book  = _make_book(asks_desc=[0.99, 0.40], bids_asc=[0.01, 0.20, 0.30, 0.35])
        client = self._client()
        quote = client._build_quote(yes_book=yes_book, no_book=no_book)

        self.assertAlmostEqual(quote.yes_bid, 0.45, places=4)
        self.assertAlmostEqual(quote.no_bid, 0.35, places=4)

    def test_binary_market_ask_sum_reasonable(self):
        """yes_ask + no_ask should be in [1.00, 1.15] for a typical binary market."""
        yes_book = _make_book(asks_desc=[0.99, 0.80, 0.62], bids_asc=[0.01, 0.55, 0.58])
        no_book  = _make_book(asks_desc=[0.99, 0.80, 0.43], bids_asc=[0.01, 0.35, 0.39])
        client = self._client()
        quote = client._build_quote(yes_book=yes_book, no_book=no_book)

        ask_sum = quote.yes_ask + quote.no_ask
        self.assertGreaterEqual(ask_sum, 1.00, f"ask_sum={ask_sum} too low")
        self.assertLessEqual(ask_sum, 1.15, f"ask_sum={ask_sum} too high")

    def test_not_stuck_at_worst_ask(self):
        """Before the fix asks[0]=0.99 was used — verify that never happens when better asks exist."""
        yes_book = _make_book(asks_desc=[0.99, 0.98, 0.97, 0.65], bids_asc=[0.60])
        no_book  = _make_book(asks_desc=[0.99, 0.98, 0.97, 0.35], bids_asc=[0.30])
        client = self._client()
        quote = client._build_quote(yes_book=yes_book, no_book=no_book)

        self.assertLess(quote.yes_ask, 0.95, f"yes_ask={quote.yes_ask} looks like worst ask was used")
        self.assertLess(quote.no_ask,  0.95, f"no_ask={quote.no_ask} looks like worst ask was used")

    def test_empty_asks_fallback(self):
        """Empty ask list → fallback to 1.0 (no market)."""
        yes_book = {"asks": [], "bids": [{"price": "0.50", "size": "100"}], "timestamp": "0"}
        no_book  = {"asks": [], "bids": [{"price": "0.40", "size": "100"}], "timestamp": "0"}
        client = self._client()
        quote = client._build_quote(yes_book=yes_book, no_book=no_book)

        self.assertEqual(quote.yes_ask, 1.0)
        self.assertEqual(quote.no_ask,  1.0)

    def test_empty_bids_fallback(self):
        """Empty bid list → fallback to 0.0."""
        yes_book = {"asks": [{"price": "0.60", "size": "100"}], "bids": [], "timestamp": "0"}
        no_book  = {"asks": [{"price": "0.40", "size": "100"}], "bids": [], "timestamp": "0"}
        client = self._client()
        quote = client._build_quote(yes_book=yes_book, no_book=no_book)

        self.assertEqual(quote.yes_bid, 0.0)
        self.assertEqual(quote.no_bid,  0.0)

    def test_spread_bps_reasonable(self):
        """spread_bps should be < 500 bps for a normally-priced binary market."""
        yes_book = _make_book(asks_desc=[0.99, 0.61], bids_asc=[0.59])
        no_book  = _make_book(asks_desc=[0.99, 0.41], bids_asc=[0.39])
        client = self._client()
        quote = client._build_quote(yes_book=yes_book, no_book=no_book)

        yes_spread = quote.spread_bps("YES")
        no_spread  = quote.spread_bps("NO")
        self.assertLess(yes_spread, 500, f"YES spread {yes_spread:.0f} bps seems too wide")
        self.assertLess(no_spread,  500, f"NO spread {no_spread:.0f} bps seems too wide")


if __name__ == "__main__":
    unittest.main()
