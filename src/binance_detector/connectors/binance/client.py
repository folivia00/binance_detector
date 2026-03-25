from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from statistics import fmean
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from binance_detector.domain.market import BinanceSignalSnapshot


def _clip(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass(slots=True)
class BinanceClient:
    """Public Binance Spot REST client for live snapshots and historical candles."""

    symbol: str = "BTCUSDT"
    base_url: str = "https://api.binance.com"
    timeout_seconds: float = 5.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.4
    _previous_bid_depth_top: float | None = field(default=None, init=False)
    _previous_ask_depth_top: float | None = field(default=None, init=False)
    _previous_market_price: float | None = field(default=None, init=False)
    last_snapshot_source: str = field(default="unknown", init=False)
    last_fallback_reason: str = field(default="", init=False)

    def fetch_recent_candles(self, interval: str = "1m", limit: int = 30) -> list[dict]:
        payload = self._get_json(
            path="/api/v3/klines",
            params={"symbol": self.symbol, "interval": interval, "limit": limit},
        )
        candles: list[dict] = []
        for item in payload:
            candles.append(
                {
                    "open_time": item[0],
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "close_time": item[6],
                    "quote_volume": float(item[7]),
                    "trade_count": item[8],
                    "taker_buy_base": float(item[9]),
                    "taker_buy_quote": float(item[10]),
                }
            )
        return candles

    def fetch_signal_snapshot(self, *, allow_demo_fallback: bool = True) -> BinanceSignalSnapshot:
        try:
            order_book = self._get_json(
                path="/api/v3/depth",
                params={"symbol": self.symbol, "limit": 20},
            )
            trades = self._get_json(
                path="/api/v3/trades",
                params={"symbol": self.symbol, "limit": 50},
            )
            candles = self.fetch_recent_candles(interval="1m", limit=5)
            snapshot = self._build_live_snapshot(order_book=order_book, trades=trades, candles=candles)
            self.last_snapshot_source = "live"
            self.last_fallback_reason = ""
            return snapshot
        except Exception as exc:
            self.last_snapshot_source = "demo"
            self.last_fallback_reason = f"{type(exc).__name__}: {exc}"
            if not allow_demo_fallback:
                raise RuntimeError(self.last_fallback_reason) from exc
            return self._build_demo_snapshot(self.last_fallback_reason)

    def _build_live_snapshot(
        self,
        *,
        order_book: dict,
        trades: list[dict],
        candles: list[dict],
    ) -> BinanceSignalSnapshot:
        bids = [(float(price), float(qty)) for price, qty in order_book.get("bids", [])]
        asks = [(float(price), float(qty)) for price, qty in order_book.get("asks", [])]
        if not bids or not asks:
            raise ValueError("empty order book")

        best_bid, best_bid_qty = bids[0]
        best_ask, best_ask_qty = asks[0]
        mid_price = (best_bid + best_ask) / 2
        microprice = ((best_ask * best_bid_qty) + (best_bid * best_ask_qty)) / max(
            best_bid_qty + best_ask_qty, 1e-9
        )
        bid_depth_top = sum(qty for _, qty in bids[:5])
        ask_depth_top = sum(qty for _, qty in asks[:5])
        queue_imbalance = (bid_depth_top - ask_depth_top) / max(bid_depth_top + ask_depth_top, 1e-9)

        trade_prices = [float(item["price"]) for item in trades]
        velocity_short = 0.0
        if len(trade_prices) >= 2 and trade_prices[0] > 0:
            velocity_short = ((trade_prices[-1] - trade_prices[0]) / trade_prices[0]) * 100

        aggressive_buy_flow = sum(
            float(item["qty"]) for item in trades if not bool(item.get("isBuyerMaker", False))
        )
        aggressive_sell_flow = sum(
            float(item["qty"]) for item in trades if bool(item.get("isBuyerMaker", False))
        )

        recent_closes = [float(item["close"]) for item in candles] if candles else [mid_price]
        recent_mean = fmean(recent_closes)
        volatility_recent = (
            fmean(abs(price - recent_mean) / recent_mean for price in recent_closes)
            if recent_mean > 0 and recent_closes
            else 0.0
        )
        rebound_strength = 0.0
        if len(recent_closes) >= 2 and recent_closes[0] > 0:
            rebound_strength = _clip((recent_closes[-1] - min(recent_closes)) / recent_closes[0], -1.0, 1.0)

        bid_wall_change = 0.0 if self._previous_bid_depth_top is None else bid_depth_top - self._previous_bid_depth_top
        ask_wall_change = 0.0 if self._previous_ask_depth_top is None else ask_depth_top - self._previous_ask_depth_top
        bid_full_remove = (
            1.0
            if self._previous_bid_depth_top is not None and bid_depth_top < self._previous_bid_depth_top * 0.25
            else 0.0
        )
        ask_full_remove = (
            1.0
            if self._previous_ask_depth_top is not None and ask_depth_top < self._previous_ask_depth_top * 0.25
            else 0.0
        )

        self._previous_bid_depth_top = bid_depth_top
        self._previous_ask_depth_top = ask_depth_top
        self._previous_market_price = mid_price

        return BinanceSignalSnapshot(
            ts=datetime.now(timezone.utc),
            market_price=mid_price,
            best_bid=best_bid,
            best_ask=best_ask,
            microprice=microprice,
            queue_imbalance=_clip(queue_imbalance, -1.0, 1.0),
            velocity_short=_clip(velocity_short, -1.0, 1.0),
            microprice_delta=((microprice - mid_price) / mid_price) if mid_price > 0 else 0.0,
            volatility_recent=volatility_recent,
            bid_depth_top=bid_depth_top,
            ask_depth_top=ask_depth_top,
            bid_wall_change=bid_wall_change,
            ask_wall_change=ask_wall_change,
            bid_full_remove=bid_full_remove,
            ask_full_remove=ask_full_remove,
            aggressive_buy_flow=aggressive_buy_flow,
            aggressive_sell_flow=aggressive_sell_flow,
            rebound_strength=rebound_strength,
            snapshot_source="live",
            fallback_reason="",
        )

    def _build_demo_snapshot(self, fallback_reason: str) -> BinanceSignalSnapshot:
        now = datetime.now(timezone.utc)
        return BinanceSignalSnapshot(
            ts=now,
            market_price=100_000.0,
            best_bid=99_999.5,
            best_ask=100_000.5,
            microprice=100_000.1,
            queue_imbalance=0.1,
            velocity_short=0.02,
            microprice_delta=0.00015,
            volatility_recent=0.001,
            bid_depth_top=140.0,
            ask_depth_top=120.0,
            bid_wall_change=6.0,
            ask_wall_change=-4.0,
            bid_full_remove=0.0,
            ask_full_remove=0.0,
            aggressive_buy_flow=4.0,
            aggressive_sell_flow=2.5,
            rebound_strength=0.2,
            snapshot_source="demo",
            fallback_reason=fallback_reason,
        )

    def _get_json(self, *, path: str, params: dict[str, object]) -> dict | list:
        url = f"{self.base_url}{path}?{urlencode(params)}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(url, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_backoff_seconds * (attempt + 1))
        raise RuntimeError(f"unreachable _get_json failure: {last_error}")
