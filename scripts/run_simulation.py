from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.analytics.simulator import RoundSimulator, SimulationTick
from binance_detector.config.settings import settings
from binance_detector.execution.paper import PaperExecutionConfig, PaperExecutionEngine
from binance_detector.models.baseline import BaselineProbabilityModel
from binance_detector.strategy.entry_policy import EntryPolicy
from binance_detector.strategy.guards import BasisGuardConfig


def build_synthetic_ticks(rounds: int = 120, seed: int = 7) -> list[SimulationTick]:
    rng = random.Random(seed)
    start = datetime(2026, 3, 24, 0, 0, tzinfo=timezone.utc)
    ticks: list[SimulationTick] = []
    base_price = 100_000.0
    for round_index in range(rounds):
        round_start = start + timedelta(minutes=5 * round_index)
        drift = rng.uniform(-18.0, 18.0)
        reversal_round = round_index % 5 == 0
        for step in range(10):
            ts = round_start + timedelta(seconds=step * 30)
            progress = step / 9
            noise = rng.uniform(-3.5, 3.5)
            phase_drift = drift
            if reversal_round and progress >= 0.6:
                reversal_progress = (progress - 0.6) / 0.4
                phase_drift = drift - (drift * 2.1 * reversal_progress)
            market_price = base_price + phase_drift * progress + noise
            final_drift = -drift * 0.8 if reversal_round else drift
            settle_reference_price = base_price + final_drift + rng.uniform(-1.0, 1.0)
            velocity_short = (phase_drift / 25.0) + rng.uniform(-0.08, 0.08)
            queue_imbalance = max(-1.0, min(1.0, (phase_drift / 20.0) + rng.uniform(-0.25, 0.25)))
            microprice_delta = ((market_price - base_price) / base_price) + rng.uniform(-0.0002, 0.0002)
            volatility_recent = abs(noise) / 10_000
            directional_bias = 1 if phase_drift >= 0 else -1
            bid_depth_top = 120 + max(0.0, phase_drift) * 4 + rng.uniform(-20, 20)
            ask_depth_top = 120 + max(0.0, -phase_drift) * 4 + rng.uniform(-20, 20)
            bid_wall_change = directional_bias * rng.uniform(4, 18)
            ask_wall_change = -directional_bias * rng.uniform(4, 18)
            if reversal_round and progress >= 0.6:
                bid_wall_change *= -0.7
                ask_wall_change *= -0.7
            bid_full_remove = 1.0 if directional_bias < 0 and rng.random() < 0.20 else 0.0
            ask_full_remove = 1.0 if directional_bias > 0 and rng.random() < 0.20 else 0.0
            aggressive_buy_flow = max(0.0, phase_drift / 6 + rng.uniform(0.0, 1.5))
            aggressive_sell_flow = max(0.0, -phase_drift / 6 + rng.uniform(0.0, 1.5))
            rebound_strength = rng.uniform(-0.4, 0.4)
            if reversal_round and progress >= 0.7:
                rebound_strength += -0.5 if phase_drift < 0 else 0.5
            yes_mid = max(0.05, min(0.95, 0.5 + (market_price - base_price) / 100))
            spread = 0.03 if step < 8 else 0.05
            yes_bid = max(0.01, yes_mid - spread / 2)
            yes_ask = min(0.99, yes_mid + spread / 2)
            no_mid = 1 - yes_mid
            no_bid = max(0.01, no_mid - spread / 2)
            no_ask = min(0.99, no_mid + spread / 2)
            ticks.append(
                SimulationTick(
                    ts=ts,
                    market_price=market_price,
                    best_bid=market_price - 0.5,
                    best_ask=market_price + 0.5,
                    microprice=market_price + rng.uniform(-0.3, 0.3),
                    queue_imbalance=queue_imbalance,
                    velocity_short=velocity_short,
                    microprice_delta=microprice_delta,
                    volatility_recent=volatility_recent,
                    settle_reference_price=settle_reference_price,
                    settle_reference_age_seconds=rng.uniform(0.0, 1.0),
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    no_ask=no_ask,
                    pm_book_liquidity=rng.uniform(180.0, 420.0),
                    pm_quote_age_seconds=rng.uniform(0.0, 1.2),
                    bid_depth_top=bid_depth_top,
                    ask_depth_top=ask_depth_top,
                    bid_wall_change=bid_wall_change,
                    ask_wall_change=ask_wall_change,
                    bid_full_remove=bid_full_remove,
                    ask_full_remove=ask_full_remove,
                    aggressive_buy_flow=aggressive_buy_flow,
                    aggressive_sell_flow=aggressive_sell_flow,
                    rebound_strength=rebound_strength,
                )
            )
        base_price += drift
    return ticks


if __name__ == "__main__":
    policy = EntryPolicy.from_json(settings.entry_policy_path)
    guard_config = BasisGuardConfig.from_json(settings.basis_guards_path)
    simulator = RoundSimulator(
        market_slug="bitcoin-up-or-down-5m",
        model=BaselineProbabilityModel(),
        policy=policy,
        guard_config=guard_config,
        paper_engine=PaperExecutionEngine(PaperExecutionConfig.from_json(settings.paper_execution_path)),
        enable_reverse_exit=True,
    )
    report = simulator.run(build_synthetic_ticks())
    print(report.metrics())
    print(
        f"round_summaries={len(report.round_summaries)} "
        f"events={len(report.events)} "
        f"reverse_exit={len(report.reverse_exit_records)}"
    )
