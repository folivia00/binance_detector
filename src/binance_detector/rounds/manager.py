from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from binance_detector.domain.rounds import MarketRound, RoundResult
from binance_detector.utils.time import floor_to_5m


def winner_for_prices(open_price: float, settle_price: float) -> str:
    if settle_price > open_price:
        return "YES"
    if settle_price < open_price:
        return "NO"
    return "FLAT"


@dataclass(slots=True)
class CanonicalRoundManager:
    round_seconds: int = 300
    _active_rounds: dict[str, MarketRound] = field(default_factory=dict, init=False)
    _closed_rounds: dict[str, RoundResult] = field(default_factory=dict, init=False)

    def canonical_round_bounds(self, ts: datetime) -> tuple[datetime, datetime]:
        start = floor_to_5m(ts.astimezone(timezone.utc))
        return start, start + timedelta(seconds=self.round_seconds)

    def canonical_round_id(self, ts: datetime, market_slug: str) -> str:
        start, _ = self.canonical_round_bounds(ts)
        return f"{market_slug}:{start.strftime('%Y%m%dT%H%M%SZ')}"

    def track(self, market_slug: str, ts: datetime, current_market_price: float) -> MarketRound:
        round_id = self.canonical_round_id(ts=ts, market_slug=market_slug)
        start, end = self.canonical_round_bounds(ts)
        active = self._active_rounds.get(market_slug)
        if active is None or active.round_id != round_id:
            active = MarketRound(
                round_id=round_id,
                market_slug=market_slug,
                starts_at=start,
                ends_at=end,
                round_open_price=current_market_price,
                last_market_price=current_market_price,
            )
            self._active_rounds[market_slug] = active
            return active

        active.mark_market_price(current_market_price)
        return active

    def resolve(
        self,
        market_slug: str,
        settle_price: float,
        resolved_at: datetime,
        resolution_source: str = "settle_reference",
        forced_close: bool = False,
    ) -> RoundResult | None:
        active = self._active_rounds.get(market_slug)
        if active is None:
            return None
        active.finalize(settle_price=settle_price, settled_at=resolved_at)
        result = RoundResult(
            round_id=active.round_id,
            market_slug=market_slug,
            open_price=active.round_open_price,
            settle_price=settle_price,
            winner=winner_for_prices(active.round_open_price, settle_price),
            resolved_at=resolved_at.astimezone(timezone.utc),
            resolution_source=resolution_source,
            forced_close=forced_close,
        )
        self._closed_rounds[active.round_id] = result
        del self._active_rounds[market_slug]
        return result

    def active_round(self, market_slug: str) -> MarketRound | None:
        return self._active_rounds.get(market_slug)

    def closed_round(self, round_id: str) -> RoundResult | None:
        return self._closed_rounds.get(round_id)
