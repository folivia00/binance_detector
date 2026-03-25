from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


SignalTier = Literal["weak", "medium", "strong", "very_strong"]
RoundWinner = Literal["YES", "NO", "FLAT"]
ResolutionSource = Literal["settle_reference", "forced_close", "market_fallback"]


@dataclass(slots=True)
class MarketRound:
    round_id: str
    market_slug: str
    starts_at: datetime
    ends_at: datetime
    round_open_price: float
    last_market_price: float
    round_close_ref_price: float | None = None
    settled_at: datetime | None = None

    def t_left_seconds(self, now: datetime) -> int:
        now_utc = now.astimezone(timezone.utc)
        end_utc = self.ends_at.astimezone(timezone.utc)
        return max(0, int((end_utc - now_utc).total_seconds()))

    def mark_market_price(self, price: float) -> None:
        self.last_market_price = price

    def finalize(self, settle_price: float, settled_at: datetime) -> None:
        self.round_close_ref_price = settle_price
        self.settled_at = settled_at.astimezone(timezone.utc)


@dataclass(slots=True)
class RoundResult:
    round_id: str
    market_slug: str
    open_price: float
    settle_price: float
    winner: RoundWinner
    resolved_at: datetime
    resolution_source: ResolutionSource
    forced_close: bool = False


@dataclass(slots=True)
class RoundFeatures:
    distance_to_open_bps: float
    distance_bucket: str
    time_left_bucket: str
    time_left_seconds: int
    velocity_short: float
    queue_imbalance: float
    microprice_delta: float
    volatility_recent: float
    wall_pull_score: float = 0.0
    major_drop_score: float = 0.0
    full_remove_score: float = 0.0
    absorption_score: float = 0.0
    resilience_score: float = 0.0
    detector_bias: float = 0.0

    def as_dict(self) -> dict[str, float | str]:
        return {
            "distance_to_open_bps": self.distance_to_open_bps,
            "distance_bucket": self.distance_bucket,
            "time_left_bucket": self.time_left_bucket,
            "time_left_seconds": self.time_left_seconds,
            "velocity_short": self.velocity_short,
            "queue_imbalance": self.queue_imbalance,
            "microprice_delta": self.microprice_delta,
            "volatility_recent": self.volatility_recent,
            "wall_pull_score": self.wall_pull_score,
            "major_drop_score": self.major_drop_score,
            "full_remove_score": self.full_remove_score,
            "absorption_score": self.absorption_score,
            "resilience_score": self.resilience_score,
            "detector_bias": self.detector_bias,
        }


@dataclass(slots=True)
class RoundPrediction:
    round_id: str
    p_up_total: float
    p_down_total: float
    signal_tier: SignalTier
    model_name: str
    created_at: datetime
    features: RoundFeatures
    calibration_version: str = ""
    debug_components: dict[str, float | str] = field(default_factory=dict)

    @property
    def probability_yes(self) -> float:
        return self.p_up_total

    @property
    def probability_edge(self) -> float:
        return abs(self.p_up_total - 0.5)
