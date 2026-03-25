from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path


@dataclass(slots=True)
class ObservabilityState:
    heartbeat_at: str = ""
    last_good_quote_at: str = ""
    last_order_action_at: str = ""
    last_live_binance_at: str = ""
    last_round_id: str = ""
    last_summary: dict[str, object] = field(default_factory=dict)
    last_error: str = ""
    last_snapshot_source: str = ""
    last_fallback_reason: str = ""
    guardrail_events: list[str] = field(default_factory=list)
    recent_round_summaries: list[dict[str, object]] = field(default_factory=list)

    def touch_heartbeat(self) -> None:
        self.heartbeat_at = datetime.now(timezone.utc).isoformat()

    def touch_quote(self) -> None:
        self.last_good_quote_at = datetime.now(timezone.utc).isoformat()

    def touch_order_action(self) -> None:
        self.last_order_action_at = datetime.now(timezone.utc).isoformat()

    def touch_live_binance(self) -> None:
        self.last_live_binance_at = datetime.now(timezone.utc).isoformat()

    def set_snapshot_status(self, *, source: str, fallback_reason: str) -> None:
        self.last_snapshot_source = source
        self.last_fallback_reason = fallback_reason
        if source == "live":
            self.touch_live_binance()

    def add_guardrail_event(self, event: str) -> None:
        if not event:
            return
        self.guardrail_events.append(event)
        self.guardrail_events = self.guardrail_events[-20:]

    def add_round_summary(self, summary: dict[str, object]) -> None:
        self.last_summary = summary
        self.recent_round_summaries.append(summary)
        self.recent_round_summaries = self.recent_round_summaries[-20:]

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "ObservabilityState":
        if not path.exists():
            return cls()
        return cls(**json.loads(path.read_text(encoding="utf-8")))
