from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ReverseExitRecord:
    round_id: str
    signal_tier: str
    time_left_bucket: str
    distance_bucket: str
    saved_loss: float
    cut_winner: float
    infra_failed: bool
    counterfactual_hold_to_settle: float


def analyze_reverse_exit(
    *,
    round_id: str,
    signal_tier: str,
    time_left_bucket: str,
    distance_bucket: str,
    realized_exit_pnl: float,
    hold_to_settle_pnl: float,
    infra_failed: bool = False,
) -> ReverseExitRecord:
    return ReverseExitRecord(
        round_id=round_id,
        signal_tier=signal_tier,
        time_left_bucket=time_left_bucket,
        distance_bucket=distance_bucket,
        saved_loss=max(realized_exit_pnl - hold_to_settle_pnl, 0.0),
        cut_winner=max(hold_to_settle_pnl - realized_exit_pnl, 0.0),
        infra_failed=infra_failed,
        counterfactual_hold_to_settle=hold_to_settle_pnl,
    )
