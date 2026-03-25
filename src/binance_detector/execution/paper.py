from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from binance_detector.domain.market import PolymarketQuote


@dataclass(slots=True)
class PaperExecutionConfig:
    cooldown_seconds: int = 30
    max_slippage_bps: float = 150.0
    min_entry_confidence: float = 0.55
    no_entry_last_seconds: int = 10

    @classmethod
    def from_json(cls, path: Path) -> "PaperExecutionConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(**payload)


@dataclass(slots=True)
class PaperExecutionDecision:
    allowed: bool
    side: str
    taker_price: float
    passive_price: float
    expected_slippage_bps: float
    block_reasons: tuple[str, ...]


class PaperExecutionEngine:
    def __init__(self, config: PaperExecutionConfig | None = None) -> None:
        self.config = config or PaperExecutionConfig()

    def evaluate_entry(
        self,
        *,
        side: str,
        confidence: float,
        quote: PolymarketQuote,
        time_left_seconds: int,
        last_entry_ts: datetime | None = None,
        now: datetime | None = None,
    ) -> PaperExecutionDecision:
        current_time = now or quote.ts
        block_reasons: list[str] = []
        taker_price = quote.ask_price(side)
        passive_price = quote.bid_price(side)
        midpoint = (taker_price + passive_price) / 2 if taker_price > 0 and passive_price > 0 else taker_price
        expected_slippage_bps = 0.0
        if midpoint > 0 and taker_price > 0 and passive_price > 0:
            expected_slippage_bps = ((taker_price - passive_price) / midpoint) * 10_000

        if confidence < self.config.min_entry_confidence:
            block_reasons.append("low_confidence")
        if time_left_seconds <= self.config.no_entry_last_seconds:
            block_reasons.append("no_entry_last_seconds")
        if expected_slippage_bps > self.config.max_slippage_bps:
            block_reasons.append("slippage_too_high")
        if last_entry_ts is not None and (current_time - last_entry_ts).total_seconds() < self.config.cooldown_seconds:
            block_reasons.append("cooldown")

        return PaperExecutionDecision(
            allowed=not block_reasons,
            side=side,
            taker_price=taker_price,
            passive_price=passive_price,
            expected_slippage_bps=expected_slippage_bps,
            block_reasons=tuple(block_reasons),
        )
