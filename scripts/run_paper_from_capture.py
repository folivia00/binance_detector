from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.analytics.reporting import render_markdown_report, write_markdown_report
from binance_detector.analytics.simulator import RoundSimulator, SimulationTick
from binance_detector.config.market_registry import get_market_spec
from binance_detector.config.settings import settings
from binance_detector.execution.paper import PaperExecutionConfig, PaperExecutionEngine
from binance_detector.models.baseline import BaselineProbabilityModel
from binance_detector.strategy.entry_policy import EntryPolicy
from binance_detector.strategy.guards import BasisGuardConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run paper simulation from captured live JSONL snapshots.")
    parser.add_argument("capture_file")
    parser.add_argument("--market-key", default="btc_updown_5m")
    return parser.parse_args()


def load_ticks(path: Path) -> list[SimulationTick]:
    ticks: list[SimulationTick] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        ts = datetime.fromisoformat(record["ts"])
        binance = record["binance"]
        polymarket = record["polymarket"]
        ticks.append(
            SimulationTick(
                ts=ts,
                market_price=float(binance["market_price"]),
                best_bid=float(binance["best_bid"]),
                best_ask=float(binance["best_ask"]),
                microprice=float(binance["microprice"]),
                queue_imbalance=float(binance["queue_imbalance"]),
                velocity_short=float(binance["velocity_short"]),
                microprice_delta=float(binance["microprice_delta"]),
                volatility_recent=float(binance["volatility_recent"]),
                settle_reference_price=float(binance["market_price"]),
                settle_reference_age_seconds=0.0,
                yes_bid=float(polymarket["yes_bid"]),
                yes_ask=float(polymarket["yes_ask"]),
                no_bid=float(polymarket["no_bid"]),
                no_ask=float(polymarket["no_ask"]),
                pm_book_liquidity=float(polymarket["book_liquidity"]),
                pm_quote_age_seconds=float(polymarket["quote_age_seconds"]),
                bid_depth_top=float(binance["bid_depth_top"]),
                ask_depth_top=float(binance["ask_depth_top"]),
                bid_wall_change=float(binance["bid_wall_change"]),
                ask_wall_change=float(binance["ask_wall_change"]),
                bid_full_remove=float(binance["bid_full_remove"]),
                ask_full_remove=float(binance["ask_full_remove"]),
                aggressive_buy_flow=float(binance["aggressive_buy_flow"]),
                aggressive_sell_flow=float(binance["aggressive_sell_flow"]),
                rebound_strength=float(binance["rebound_strength"]),
            )
        )
    return ticks


if __name__ == "__main__":
    args = parse_args()
    capture_path = Path(args.capture_file)
    spec = get_market_spec(settings.pm_market_registry_path, args.market_key)
    if spec is None:
        raise SystemExit(f"market_key not found: {args.market_key}")

    policy = EntryPolicy.from_json(settings.entry_policy_path)
    guard_config = BasisGuardConfig.from_json(settings.basis_guards_path)
    simulator = RoundSimulator(
        market_slug=spec.market_key,
        model=BaselineProbabilityModel(),
        policy=policy,
        guard_config=guard_config,
        paper_engine=PaperExecutionEngine(PaperExecutionConfig.from_json(settings.paper_execution_path)),
        enable_reverse_exit=True,
    )
    report = simulator.run(load_ticks(capture_path))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / "docs" / "reports" / f"captured_paper_report_{args.market_key}_{timestamp}.md"
    write_markdown_report(output_path, render_markdown_report(report, stage_name="Captured Paper Report"))
    print(report.metrics())
    print(output_path)
