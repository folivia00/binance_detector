from __future__ import annotations

from binance_detector.domain.market import BinanceSignalSnapshot
from binance_detector.domain.rounds import MarketRound, RoundFeatures
from binance_detector.signals.detectors import DetectorState


def _distance_bucket(distance_bps: float) -> str:
    distance_abs = abs(distance_bps)
    if distance_abs < 2:
        return "at_open"
    if distance_abs < 7:
        return "near"
    if distance_abs < 15:
        return "far"
    return "stretched"


def _time_bucket(t_left_seconds: int) -> str:
    if t_left_seconds > 180:
        return "early"
    if t_left_seconds > 90:
        return "mid"
    if t_left_seconds > 30:
        return "late"
    return "final"


def build_round_features(
    round_state: MarketRound,
    snapshot: BinanceSignalSnapshot,
    detector_state: DetectorState | None = None,
) -> RoundFeatures:
    if round_state.round_open_price <= 0:
        distance_to_open_bps = 0.0
    else:
        distance_to_open_bps = (
            (snapshot.market_price - round_state.round_open_price) / round_state.round_open_price
        ) * 10_000

    t_left_seconds = round_state.t_left_seconds(snapshot.ts)
    return RoundFeatures(
        distance_to_open_bps=distance_to_open_bps,
        distance_bucket=_distance_bucket(distance_to_open_bps),
        time_left_bucket=_time_bucket(t_left_seconds),
        time_left_seconds=t_left_seconds,
        velocity_short=snapshot.velocity_short,
        queue_imbalance=snapshot.queue_imbalance,
        microprice_delta=snapshot.microprice_delta,
        volatility_recent=snapshot.volatility_recent,
        wall_pull_score=0.0 if detector_state is None else detector_state.wall_pull_score,
        major_drop_score=0.0 if detector_state is None else detector_state.major_drop_score,
        full_remove_score=0.0 if detector_state is None else detector_state.full_remove_score,
        absorption_score=0.0 if detector_state is None else detector_state.absorption_score,
        resilience_score=0.0 if detector_state is None else detector_state.resilience_score,
        detector_bias=0.0 if detector_state is None else detector_state.detector_bias,
    )
