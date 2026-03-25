from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TradingSignal:
    action: str
    confidence: float
    reason: str
    round_id: str = ""
    signal_tier: str = ""
    time_bucket: str = ""
    distance_bucket: str = ""
    snapshot_source: str = ""
    fallback_reason: str = ""
    policy_reason: str = ""
    guard_reasons: tuple[str, ...] = field(default_factory=tuple)
    paper_reasons: tuple[str, ...] = field(default_factory=tuple)
    should_enter: bool = False
    market_price: float = 0.0
    round_open_price: float = 0.0
    basis_bps: float = 0.0
    pm_quote_age_seconds: float = 0.0
    pm_book_liquidity: float = 0.0
    pm_spread_bps: float = 0.0
    expected_slippage_bps: float = 0.0
    raw_score: float = 0.0
    probability_edge: float = 0.0
    calibration_version: str = ""
