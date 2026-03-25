from __future__ import annotations

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import time
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.observability.state import ObservabilityState


STATE_PATH = ROOT / "data" / "logs" / "observability_state.json"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        state = ObservabilityState.read(STATE_PATH)
        if self.path == "/health":
            payload = {
                "ok": True,
                "heartbeat_at": state.heartbeat_at,
                "last_error": state.last_error,
                "last_snapshot_source": state.last_snapshot_source,
                "last_fallback_reason": state.last_fallback_reason,
            }
        elif self.path == "/heartbeat":
            payload = {"heartbeat_at": state.heartbeat_at}
        elif self.path == "/summary/latest":
            payload = state.last_summary
        elif self.path == "/debug/state":
            payload = asdict(state)
        elif self.path == "/debug/events":
            payload = {
                "guardrail_events": state.guardrail_events,
                "recent_round_summaries": state.recent_round_summaries,
            }
        elif self.path == "/sse/state":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                for _ in range(5):
                    fresh_state = ObservabilityState.read(STATE_PATH)
                    payload = json.dumps(asdict(fresh_state), ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        else:
            self.send_response(404)
            self.end_headers()
            return

        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8765), Handler)
    print("observability server listening on http://127.0.0.1:8765")
    server.serve_forever()
