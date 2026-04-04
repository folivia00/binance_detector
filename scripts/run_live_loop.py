"""Live trading loop — places real orders on Polymarket CLOB.

By default runs in DRY RUN mode (no real orders placed).
Set dry_run=false in configs/live_execution_v1.json to enable live trading.

Usage
-----
    # Dry run (safe, no orders):
    python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800

    # Live trading:
    python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live

Required env vars for live trading (add to ~/.bashrc on VPS):
    PM_PRIVATE_KEY       — Polygon wallet private key (hex)
    PM_FUNDER_ADDRESS    — Wallet address holding USDC
    PM_SIGNATURE_TYPE    — 2  (funder/proxy mode, no API keys needed)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.config.market_registry import get_market_spec
from binance_detector.config.settings import settings
from binance_detector.connectors.polymarket.auth import build_clob_client
from binance_detector.execution.live import LiveExecutionConfig, LiveExecutionEngine
from binance_detector.pipelines.live import LivePaperRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("live_loop")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live trading loop for Polymarket BTC 5m markets")
    parser.add_argument("--market-key", default="btc_updown_5m")
    parser.add_argument("--iterations", type=int, default=1800)
    parser.add_argument("--interval-seconds", type=int, default=5)
    parser.add_argument("--live", action="store_true",
                        help="Enable live trading (requires PM credentials). Default: dry run.")
    return parser.parse_args()


def _log_path() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "data" / "logs" / f"live_loop_{ts}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _serialise(obj: object) -> object:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialise(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (tuple, list)):
        return [_serialise(i) for i in obj]
    return obj


def main() -> None:
    args = parse_args()

    live_cfg = LiveExecutionConfig.from_json(settings.live_execution_path)

    # --live flag forces dry_run=False; otherwise respect config value
    if args.live and live_cfg.dry_run:
        live_cfg = dataclasses.replace(live_cfg, dry_run=False)

    # Build ClobClient only if needed
    clob_client = None
    if not live_cfg.dry_run:
        log.info("Live mode: loading Polymarket CLOB credentials...")
        clob_client = build_clob_client()
        log.info("CLOB client ready. address=%s", clob_client.get_address())
    else:
        log.info("DRY RUN mode — no real orders will be placed.")

    live_engine = LiveExecutionEngine(config=live_cfg, clob_client=clob_client)

    # Signal runner (same as paper loop, just for signal generation)
    runner = LivePaperRunner(market_key=args.market_key)
    market_spec = runner.current_market_spec()

    log_path = _log_path()
    log.info("Logging to %s", log_path)
    log.info("stake_usd=%.2f dry_run=%s iterations=%d", live_cfg.stake_usd, live_cfg.dry_run, args.iterations)

    last_entry_ts: datetime | None = None
    last_entered_round: str | None = None

    with log_path.open("a", encoding="utf-8") as fh:
        for i in range(args.iterations):
            now = datetime.now(timezone.utc)
            try:
                signal = runner.evaluate_once()
                if signal is None:
                    time.sleep(args.interval_seconds)
                    continue

                entry_result = None
                if signal.should_enter and signal.round_id != last_entered_round:
                    # get token id for the predicted side
                    yes_token_id, no_token_id = runner.polymarket.get_token_ids_for_spec(
                        market_spec, now
                    )
                    token_id = yes_token_id if signal.action == "YES" else no_token_id

                    if token_id:
                        entry_result = live_engine.execute(
                            side=signal.action,
                            confidence=signal.confidence,
                            token_id=token_id,
                            quote=runner.polymarket.get_quote_for_spec_at(market_spec, now),
                            time_left_seconds=0,  # signal already passed time guard
                            last_entry_ts=last_entry_ts,
                            now=now,
                        )
                        if entry_result.status in ("filled", "dry_run"):
                            last_entry_ts = now
                            last_entered_round = signal.round_id
                            log.info(
                                "ENTRY round=%s side=%s price=%.3f status=%s order_id=%s",
                                signal.round_id,
                                signal.action,
                                entry_result.filled_price,
                                entry_result.status,
                                entry_result.order_id,
                            )
                    else:
                        log.warning("token_id unavailable for round=%s", signal.round_id)

                row: dict = {
                    "ts": now.isoformat(),
                    "round_id": signal.round_id,
                    "action": signal.action,
                    "signal_tier": signal.signal_tier,
                    "time_bucket": signal.time_bucket,
                    "distance_bucket": signal.distance_bucket,
                    "should_enter": signal.should_enter,
                    "pm_entry_price": signal.pm_entry_price if hasattr(signal, "pm_entry_price") else None,
                    "confidence": signal.confidence,
                    "snapshot_source": signal.snapshot_source,
                }
                if entry_result is not None:
                    row["execution"] = {
                        "status": entry_result.status,
                        "dry_run": entry_result.dry_run,
                        "side": entry_result.side,
                        "stake_usd": entry_result.stake_usd,
                        "filled_price": entry_result.filled_price,
                        "order_id": entry_result.order_id,
                        "block_reasons": list(entry_result.block_reasons),
                        "error": entry_result.error,
                    }

                fh.write(json.dumps(row) + "\n")
                fh.flush()

            except KeyboardInterrupt:
                log.info("Interrupted by user.")
                break
            except Exception as exc:
                log.error("evaluate_once failed: %s", exc, exc_info=True)

            time.sleep(args.interval_seconds)

    log.info("Done. Log: %s", log_path)


if __name__ == "__main__":
    main()
