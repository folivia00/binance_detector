from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.analytics.simulator import RoundSimulator
from binance_detector.config.settings import settings
from binance_detector.models.baseline import BaselineProbabilityModel
from binance_detector.strategy.entry_policy import EntryPolicy
from binance_detector.strategy.guards import BasisGuardConfig
from run_simulation import build_synthetic_ticks


if __name__ == "__main__":
    policy = EntryPolicy.from_json(settings.entry_policy_path)
    guard_config = BasisGuardConfig.from_json(settings.basis_guards_path)
    simulator = RoundSimulator(
        market_slug="bitcoin-up-or-down-5m",
        model=BaselineProbabilityModel(),
        policy=policy,
        guard_config=guard_config,
        enable_reverse_exit=True,
    )
    report = simulator.run(build_synthetic_ticks())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / "data" / "logs" / f"tick_debug_{timestamp}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(report.tick_debug_rows[0].keys()) if report.tick_debug_rows else []
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report.tick_debug_rows)
    print(output_path)
