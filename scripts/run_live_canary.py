from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.observability.state import ObservabilityState
from binance_detector.pipelines.live import LivePaperRunner


if __name__ == "__main__":
    signal = LivePaperRunner(symbol="BTCUSDT", market_key="btc_updown_5m").evaluate_once()
    state_path = ROOT / "data" / "logs" / "observability_state.json"
    canary_path = ROOT / "data" / "logs" / "canary_last_summary.json"
    obs = ObservabilityState.read(state_path)
    obs.touch_heartbeat()
    if signal is not None:
        obs.touch_quote()
        obs.set_snapshot_status(source=signal.snapshot_source, fallback_reason=signal.fallback_reason)
        if signal.snapshot_source != "live":
            obs.add_guardrail_event(f"binance_fallback:{signal.fallback_reason}")
        if signal.should_enter:
            obs.touch_order_action()
        summary = {
            "mode": "canary",
            "round_id": signal.round_id,
            "signal": signal.action,
            "confidence": signal.confidence,
            "reason": signal.reason,
            "signal_tier": signal.signal_tier,
            "time_bucket": signal.time_bucket,
            "distance_bucket": signal.distance_bucket,
            "should_enter": signal.should_enter,
            "snapshot_source": signal.snapshot_source,
            "guard_reasons": list(signal.guard_reasons),
            "paper_reasons": list(signal.paper_reasons),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        obs.add_round_summary(summary)
    obs.write(state_path)
    canary_path.parent.mkdir(parents=True, exist_ok=True)
    canary_path.write_text(json.dumps(obs.last_summary, indent=2), encoding="utf-8")
    print(json.dumps(obs.last_summary, indent=2))
