from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.observability.state import ObservabilityState
from binance_detector.pipelines.live import LivePaperRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stateful live paper loop with structured summaries.")
    parser.add_argument("--market-key", default="btc_updown_5m")
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    runner = LivePaperRunner(symbol="BTCUSDT", market_key=args.market_key)
    state_path = ROOT / "data" / "logs" / "observability_state.json"
    loop_log_path = ROOT / "data" / "logs" / f"live_paper_loop_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    last_round_id = ""
    current_round_rows: list[dict[str, object]] = []

    with loop_log_path.open("w", encoding="utf-8") as handle:
        for index in range(args.iterations):
            obs = ObservabilityState.read(state_path)
            obs.touch_heartbeat()
            signal = runner.evaluate_once()
            if signal is None:
                obs.write(state_path)
                time.sleep(args.interval_seconds)
                continue

            obs.touch_quote()
            obs.set_snapshot_status(source=signal.snapshot_source, fallback_reason=signal.fallback_reason)
            if signal.snapshot_source != "live":
                obs.add_guardrail_event(f"binance_fallback:{signal.fallback_reason}")
            if signal.should_enter:
                obs.touch_order_action()

            row = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "round_id": signal.round_id,
                "action": signal.action,
                "confidence": signal.confidence,
                "probability_edge": signal.probability_edge,
                "raw_score": signal.raw_score,
                "signal_tier": signal.signal_tier,
                "calibration_version": signal.calibration_version,
                "time_bucket": signal.time_bucket,
                "distance_bucket": signal.distance_bucket,
                "snapshot_source": signal.snapshot_source,
                "fallback_reason": signal.fallback_reason,
                "policy_reason": signal.policy_reason,
                "guard_reasons": list(signal.guard_reasons),
                "paper_reasons": list(signal.paper_reasons),
                "should_enter": signal.should_enter,
                "market_price": signal.market_price,
                "round_open_price": signal.round_open_price,
                "basis_bps": signal.basis_bps,
                "pm_quote_age_seconds": signal.pm_quote_age_seconds,
                "pm_book_liquidity": signal.pm_book_liquidity,
                "pm_spread_bps": signal.pm_spread_bps,
                "expected_slippage_bps": signal.expected_slippage_bps,
            }
            handle.write(json.dumps(row) + "\n")
            current_round_rows.append(row)

            if last_round_id and signal.round_id != last_round_id:
                previous_rows = [item for item in current_round_rows if item["round_id"] == last_round_id]
                if previous_rows:
                    summary = {
                        "mode": "live_paper_loop",
                        "round_id": last_round_id,
                        "ticks_seen": len(previous_rows),
                        "last_action": previous_rows[-1]["action"],
                        "last_confidence": previous_rows[-1]["confidence"],
                        "entries_allowed": sum(1 for item in previous_rows if item["should_enter"]),
                        "snapshot_sources": sorted({str(item["snapshot_source"]) for item in previous_rows}),
                        "last_market_price": previous_rows[-1]["market_price"],
                        "round_open_price": previous_rows[0]["round_open_price"],
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    obs.add_round_summary(summary)

            last_round_id = signal.round_id
            obs.last_round_id = signal.round_id
            obs.write(state_path)
            print(json.dumps(row, ensure_ascii=False))
            if index + 1 < args.iterations:
                time.sleep(args.interval_seconds)

    print(loop_log_path)
