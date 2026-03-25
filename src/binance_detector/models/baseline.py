from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp

from binance_detector.config.settings import settings
from binance_detector.config.tier_calibration import TierCalibrationConfig
from binance_detector.domain.rounds import RoundFeatures, RoundPrediction, SignalTier


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + exp(-value))
    exp_value = exp(value)
    return exp_value / (1 + exp_value)


def _tier_for_probability(probability_up: float, config: TierCalibrationConfig) -> SignalTier:
    edge = abs(probability_up - 0.5)
    if edge < config.medium_min_edge:
        return "weak"
    if edge < config.strong_min_edge:
        return "medium"
    if edge < config.very_strong_min_edge:
        return "strong"
    if config.very_strong_cap_enabled and edge > config.very_strong_cap_edge:
        return "strong"
    return "very_strong"


@dataclass(slots=True)
class BaselineProbabilityModel:
    name: str = "baseline-probability-v1"
    tier_calibration: TierCalibrationConfig | None = None

    def __post_init__(self) -> None:
        if self.tier_calibration is None:
            self.tier_calibration = TierCalibrationConfig.from_json(settings.tier_calibration_path)

    def predict(self, features: RoundFeatures, round_id: str) -> RoundPrediction:
        distance_component = _clamp(features.distance_to_open_bps / 7.5, -3.0, 3.0)
        velocity_component = _clamp(features.velocity_short * 1.4, -2.0, 2.0)
        imbalance_component = _clamp(features.queue_imbalance * 0.9, -1.5, 1.5)
        microprice_component = _clamp(features.microprice_delta * 85.0, -1.5, 1.5)
        volatility_penalty = _clamp(features.volatility_recent * 40.0, 0.0, 1.2)
        wall_pull_component = _clamp(features.wall_pull_score * 1.1, -1.2, 1.2)
        major_drop_component = _clamp(features.major_drop_score * 0.8, -1.0, 1.0)
        full_remove_component = _clamp(features.full_remove_score * 0.7, -0.8, 0.8)
        absorption_component = _clamp(features.absorption_score * 0.9, -1.0, 1.0)
        resilience_component = _clamp(features.resilience_score * 0.7, -0.8, 0.8)
        detector_bias_component = _clamp(features.detector_bias * 1.3, -1.3, 1.3)
        time_bias = {
            "early": 0.85,
            "mid": 1.0,
            "late": 1.15,
            "final": 1.25,
        }.get(features.time_left_bucket, 1.0)

        raw_score = (
            distance_component
            + velocity_component
            + imbalance_component
            + microprice_component
            + wall_pull_component
            + major_drop_component
            + full_remove_component
            + absorption_component
            + resilience_component
            + detector_bias_component
            - volatility_penalty
        ) * time_bias
        probability_up = _clamp(_sigmoid(raw_score), 0.01, 0.99)
        edge = abs(probability_up - 0.5)
        return RoundPrediction(
            round_id=round_id,
            p_up_total=probability_up,
            p_down_total=1 - probability_up,
            signal_tier=_tier_for_probability(probability_up, self.tier_calibration),
            model_name=self.name,
            created_at=datetime.now(timezone.utc),
            features=features,
            calibration_version=self.tier_calibration.version,
            debug_components={
                "distance_component": distance_component,
                "velocity_component": velocity_component,
                "imbalance_component": imbalance_component,
                "microprice_component": microprice_component,
                "wall_pull_component": wall_pull_component,
                "major_drop_component": major_drop_component,
                "full_remove_component": full_remove_component,
                "absorption_component": absorption_component,
                "resilience_component": resilience_component,
                "detector_bias_component": detector_bias_component,
                "volatility_penalty": volatility_penalty,
                "time_bias": time_bias,
                "raw_score": raw_score,
                "probability_edge": edge,
                "tier_calibration_version": self.tier_calibration.version,
            },
        )
