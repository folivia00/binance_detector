from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from binance_detector.domain.market import PolymarketQuote, SettleReference


def _basis_bps(market_price: float, reference_price: float) -> float:
    if reference_price <= 0:
        return 0.0
    return ((market_price - reference_price) / reference_price) * 10_000


@dataclass(slots=True)
class BasisGuardConfig:
    max_basis_bps: float = 15.0
    max_settle_age_seconds: float = 3.0
    max_pm_quote_age_seconds: float = 2.0
    min_book_liquidity: float = 150.0
    max_spread_bps: float = 80.0
    min_entry_t_left_seconds: int = 20
    no_entry_last_seconds: int = 10

    @classmethod
    def from_json(cls, path: Path) -> "BasisGuardConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(**payload)


@dataclass(slots=True)
class GuardDecision:
    allowed: bool
    block_reasons: tuple[str, ...]
    basis_bps: float


def evaluate_entry_guards(
    *,
    current_market_price: float,
    settle_reference: SettleReference,
    pm_quote: PolymarketQuote,
    time_left_seconds: int,
    side: str,
    config: BasisGuardConfig,
) -> GuardDecision:
    block_reasons: list[str] = []
    basis_bps = _basis_bps(current_market_price, settle_reference.price)

    if abs(basis_bps) > config.max_basis_bps:
        block_reasons.append("max_basis")
    if settle_reference.age_seconds > config.max_settle_age_seconds:
        block_reasons.append("stale_settle_reference")
    if pm_quote.quote_age_seconds > config.max_pm_quote_age_seconds:
        block_reasons.append("stale_pm_quote")
    if pm_quote.book_liquidity < config.min_book_liquidity:
        block_reasons.append("illiquid_pm_book")
    if pm_quote.spread_bps(side) > config.max_spread_bps:
        block_reasons.append("spread_too_wide")
    if time_left_seconds < config.min_entry_t_left_seconds:
        block_reasons.append("min_entry_tleft")
    if time_left_seconds <= config.no_entry_last_seconds:
        block_reasons.append("no_entry_last_seconds")

    return GuardDecision(not block_reasons, tuple(block_reasons), basis_bps)
