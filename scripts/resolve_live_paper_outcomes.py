from __future__ import annotations

"""
Stage 19A — Post-hoc outcome resolve pipeline.

Reads one or more live-paper-loop JSONL files, fetches the Binance 5m close
price for each unique round, computes the round winner (UP/DOWN/FLAT), and
writes a resolved_decisions JSONL where every live row carries the outcome.

Output schema (per row, all original fields preserved):
  round_close_price   float   BTC/USDT price at round close
  round_winner        str     "UP" / "DOWN" / "FLAT"
  action_correct      bool    True if action matches winner (only meaningful when winner != FLAT)
  resolve_status      str     "ok" / "fetch_error" / "no_data"
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

BINANCE_BASE = "https://api.binance.com"
FLAT_THRESHOLD_PCT = 0.02   # price move < 0.02% = FLAT
CALL_SLEEP_SECONDS = 0.25   # conservative rate limit between Binance calls


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def load_rows(*paths: Path) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return rows


# ---------------------------------------------------------------------------
# Round ID parsing
# ---------------------------------------------------------------------------

def parse_round_start(round_id: str) -> datetime:
    """'btc_updown_5m:20260325T110000Z' -> UTC datetime at round open."""
    ts_str = round_id.split(":")[-1]          # '20260325T110000Z'
    return datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Binance kline fetch
# ---------------------------------------------------------------------------

def _get_json(url: str, timeout: float = 10.0) -> list | dict:
    with urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_close_price(round_id: str, symbol: str = "BTCUSDT") -> tuple[float | None, str]:
    """
    Returns (close_price, status) where status in {'ok', 'no_data', 'fetch_error'}.
    Fetches the 5m kline whose open_time == round start.
    """
    try:
        start_dt = parse_round_start(round_id)
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = start_ms + 5 * 60 * 1000
        params = urlencode({
            "symbol": symbol,
            "interval": "5m",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 1,
        })
        url = f"{BINANCE_BASE}/api/v3/klines?{params}"
        data = _get_json(url)
        if not data:
            return None, "no_data"
        # kline: [open_time, open, high, low, close, volume, ...]
        return float(data[0][4]), "ok"
    except Exception as exc:
        return None, f"fetch_error:{type(exc).__name__}"


# ---------------------------------------------------------------------------
# Winner computation
# ---------------------------------------------------------------------------

def compute_winner(open_price: float, close_price: float) -> str:
    if open_price <= 0:
        return "FLAT"
    move_pct = (close_price - open_price) / open_price * 100
    if move_pct > FLAT_THRESHOLD_PCT:
        return "UP"
    if move_pct < -FLAT_THRESHOLD_PCT:
        return "DOWN"
    return "FLAT"


# ---------------------------------------------------------------------------
# Core resolve pipeline
# ---------------------------------------------------------------------------

def resolve_rounds(
    live_rows: list[dict],
    symbol: str,
    *,
    verbose: bool = True,
) -> dict[str, dict]:
    """
    Fetches close price for each unique round_id.
    Returns mapping: round_id -> {close_price, winner, status, open_price}.
    """
    # collect unique rounds and their open prices
    rounds: dict[str, float] = {}
    for row in live_rows:
        rid = str(row["round_id"])
        if rid not in rounds:
            rounds[rid] = float(row.get("round_open_price", 0.0))

    resolved: dict[str, dict] = {}
    total = len(rounds)
    for idx, (round_id, open_price) in enumerate(sorted(rounds.items()), 1):
        close_price, status = fetch_close_price(round_id, symbol)
        if close_price is not None and open_price > 0:
            winner = compute_winner(open_price, close_price)
        else:
            winner = "UNKNOWN"
        resolved[round_id] = {
            "open_price": open_price,
            "close_price": close_price,
            "round_winner": winner,
            "resolve_status": status,
        }
        if verbose:
            close_str = f"{close_price:.2f}" if close_price is not None else "N/A"
            print(f"  [{idx}/{total}] {round_id} winner={winner} "
                  f"(open={open_price:.2f}, close={close_str}, {status})")
        if idx < total:
            time.sleep(CALL_SLEEP_SECONDS)

    return resolved


def enrich_rows(live_rows: list[dict], resolved: dict[str, dict]) -> list[dict]:
    """Adds round outcome fields to every live row."""
    enriched: list[dict] = []
    for row in live_rows:
        rid = str(row["round_id"])
        outcome = resolved.get(rid, {"close_price": None, "round_winner": "UNKNOWN", "resolve_status": "missing"})
        close_price = outcome["close_price"]
        winner = outcome["round_winner"]
        action = str(row.get("action", ""))
        action_correct: bool | None = None
        if winner not in ("UNKNOWN", "FLAT"):
            action_correct = (
                (action == "YES" and winner == "UP") or
                (action == "NO" and winner == "DOWN")
            )
        new_row = dict(row)
        new_row["round_close_price"] = close_price
        new_row["round_winner"] = winner
        new_row["action_correct"] = action_correct
        new_row["resolve_status"] = outcome["resolve_status"]
        enriched.append(new_row)
    return enriched


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stage 19A: post-hoc outcome resolve. "
            "Fetches Binance 5m close prices for each round and enriches decision rows with winner."
        )
    )
    parser.add_argument("input_files", nargs="+", help="One or more live-paper-loop JSONL files.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-round progress output.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    paths = [Path(f) for f in args.input_files]

    print(f"Loading rows from {len(paths)} file(s)...")
    all_rows = load_rows(*paths)
    live_rows = [r for r in all_rows if r.get("snapshot_source") == "live"]
    print(f"  total rows: {len(all_rows)}, live rows: {len(live_rows)}")

    unique_rounds = len({str(r["round_id"]) for r in live_rows})
    print(f"  unique rounds to resolve: {unique_rounds}")
    print(f"  estimated time: ~{unique_rounds * CALL_SLEEP_SECONDS:.0f}s\n")

    print("Resolving round outcomes via Binance klines...")
    resolved = resolve_rounds(live_rows, args.symbol, verbose=not args.quiet)

    # stats
    ok = sum(1 for v in resolved.values() if v["resolve_status"] == "ok")
    up = sum(1 for v in resolved.values() if v["round_winner"] == "UP")
    down = sum(1 for v in resolved.values() if v["round_winner"] == "DOWN")
    flat = sum(1 for v in resolved.values() if v["round_winner"] == "FLAT")
    unknown = sum(1 for v in resolved.values() if v["round_winner"] == "UNKNOWN")
    print(f"\nResolve summary: ok={ok}/{unique_rounds}  UP={up}  DOWN={down}  FLAT={flat}  UNKNOWN={unknown}")

    print("\nEnriching decision rows...")
    enriched = enrich_rows(live_rows, resolved)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / "data" / "logs" / f"resolved_decisions_{timestamp}.jsonl"
    output_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in enriched),
        encoding="utf-8",
    )
    print(f"\nOutput: {output_path}")
    print(f"  rows written: {len(enriched)}")
    print(f"  resolvable rounds (ok): {ok}/{unique_rounds}")
