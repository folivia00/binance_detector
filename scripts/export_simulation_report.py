from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.analytics.reporting import render_markdown_report, write_markdown_report
from binance_detector.analytics.simulator import RoundSimulator
from binance_detector.config.settings import settings
from binance_detector.execution.paper import PaperExecutionConfig, PaperExecutionEngine
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
        paper_engine=PaperExecutionEngine(PaperExecutionConfig.from_json(settings.paper_execution_path)),
        enable_reverse_exit=True,
    )
    report = simulator.run(build_synthetic_ticks())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / "docs" / "reports" / f"simulation_report_{timestamp}.md"
    content = render_markdown_report(report, stage_name="Simulation Report")
    write_markdown_report(output_path, content)
    print(output_path)
