from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


PositionSide = Literal["YES", "NO"]


@dataclass(slots=True)
class BinanceSignalSnapshot:
    ts: datetime
    market_price: float
    best_bid: float
    best_ask: float
    microprice: float
    queue_imbalance: float
    velocity_short: float
    microprice_delta: float
    volatility_recent: float
    bid_depth_top: float = 0.0
    ask_depth_top: float = 0.0
    bid_wall_change: float = 0.0
    ask_wall_change: float = 0.0
    bid_full_remove: float = 0.0
    ask_full_remove: float = 0.0
    aggressive_buy_flow: float = 0.0
    aggressive_sell_flow: float = 0.0
    rebound_strength: float = 0.0
    snapshot_source: str = "live"
    fallback_reason: str = ""

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2


@dataclass(slots=True)
class SettleReference:
    price: float
    age_seconds: float


@dataclass(slots=True)
class PolymarketQuote:
    ts: datetime
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    book_liquidity: float
    quote_age_seconds: float = 0.0

    def ask_price(self, side: PositionSide) -> float:
        return self.yes_ask if side == "YES" else self.no_ask

    def bid_price(self, side: PositionSide) -> float:
        return self.yes_bid if side == "YES" else self.no_bid

    def spread_bps(self, side: PositionSide) -> float:
        bid = self.bid_price(side)
        ask = self.ask_price(side)
        midpoint = (bid + ask) / 2
        if midpoint <= 0:
            return 0.0
        return ((ask - bid) / midpoint) * 10_000
