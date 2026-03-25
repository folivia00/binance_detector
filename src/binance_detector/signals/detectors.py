from __future__ import annotations

from dataclasses import dataclass

from binance_detector.domain.market import BinanceSignalSnapshot


def _clip(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


@dataclass(slots=True)
class DetectorState:
    velocity_score: float
    queue_imbalance_score: float
    microprice_score: float
    wall_pull_score: float
    major_drop_score: float
    full_remove_score: float
    absorption_score: float
    resilience_score: float
    detector_bias: float

    def debug_columns(self) -> dict[str, float]:
        return {
            "detector_velocity": self.velocity_score,
            "detector_queue_imbalance": self.queue_imbalance_score,
            "detector_microprice": self.microprice_score,
            "detector_wall_pull": self.wall_pull_score,
            "detector_major_drop": self.major_drop_score,
            "detector_full_remove": self.full_remove_score,
            "detector_absorption": self.absorption_score,
            "detector_resilience": self.resilience_score,
            "detector_bias": self.detector_bias,
        }


def compute_detector_state(
    current: BinanceSignalSnapshot,
    previous: BinanceSignalSnapshot | None = None,
) -> DetectorState:
    price_change_bps = 0.0
    if previous is not None and previous.market_price > 0:
        price_change_bps = ((current.market_price - previous.market_price) / previous.market_price) * 10_000

    depth_total = max(current.bid_depth_top + current.ask_depth_top, 1.0)
    depth_imbalance = (current.bid_depth_top - current.ask_depth_top) / depth_total
    wall_pull_score = _clip((current.bid_wall_change - current.ask_wall_change) / depth_total)
    major_drop_score = _clip(price_change_bps / 6.0)
    full_remove_score = _clip(current.bid_full_remove - current.ask_full_remove)
    trade_flow_imbalance = current.aggressive_buy_flow - current.aggressive_sell_flow
    absorption_score = _clip((trade_flow_imbalance - (price_change_bps / 12.0)) / 2.0)
    resilience_score = _clip(current.rebound_strength + (0.25 if price_change_bps > 0 else -0.25 if price_change_bps < 0 else 0.0))
    velocity_score = _clip(current.velocity_short)
    queue_imbalance_score = _clip((current.queue_imbalance + depth_imbalance) / 2)
    microprice_score = _clip(current.microprice_delta * 180.0)
    detector_bias = _clip(
        (
            velocity_score * 0.20
            + queue_imbalance_score * 0.18
            + microprice_score * 0.16
            + wall_pull_score * 0.14
            + major_drop_score * 0.10
            + full_remove_score * 0.08
            + absorption_score * 0.08
            + resilience_score * 0.06
        )
    )
    return DetectorState(
        velocity_score=velocity_score,
        queue_imbalance_score=queue_imbalance_score,
        microprice_score=microprice_score,
        wall_pull_score=wall_pull_score,
        major_drop_score=major_drop_score,
        full_remove_score=full_remove_score,
        absorption_score=absorption_score,
        resilience_score=resilience_score,
        detector_bias=detector_bias,
    )
