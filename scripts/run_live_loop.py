"""Live trading loop — places real orders on Polymarket CLOB.

By default runs in DRY RUN mode (no real orders placed).
Set dry_run=false in configs/live_execution_v1.json to enable live trading.

Usage
-----
    # Dry run (safe, no orders):
    python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800

    # Live trading:
    python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live

    # Live trading + redeem worker (default: enabled when --live):
    python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live
    python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live --redeem-interval 120
    python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live --no-redeem
    python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live --redeem-dry-run

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
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
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
    # RedeemWorker options (active only when --live, ignored in dry-run mode)
    parser.add_argument("--no-redeem", action="store_true",
                        help="Disable background RedeemWorker (default: enabled with --live).")
    parser.add_argument("--redeem-dry-run", action="store_true",
                        help="RedeemWorker checks balances but sends no transactions.")
    parser.add_argument("--redeem-interval", type=int, default=300,
                        help="Active scan interval in seconds (default: 300).")
    parser.add_argument("--redeem-idle-interval", type=int, default=900,
                        help="Idle scan interval when no new slugs found (default: 900).")
    parser.add_argument("--redeem-idle-threshold", type=int, default=3,
                        help="Empty scans before switching to idle mode (default: 3).")
    parser.add_argument("--redeem-lookback-days", type=int, default=2,
                        help="How many days back to scan filled orders (default: 2).")
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


POLYGON_RPC_FALLBACKS = [
    "https://1rpc.io/matic",
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
]


def _connect_polygon() -> object | None:
    """Connect to Polygon RPC, trying fallbacks. Returns Web3 or None."""
    try:
        from web3 import Web3
    except ImportError:
        log.warning("[REDEEM] web3 not installed — RedeemWorker disabled.")
        return None

    rpc_override = os.getenv("POLYGON_RPC_URL", "")
    candidates = [rpc_override] if rpc_override else []
    candidates += [r for r in POLYGON_RPC_FALLBACKS if r not in candidates]

    for url in candidates:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
            w3.eth.block_number  # connectivity check
            log.info("[REDEEM] Connected to Polygon RPC: %s", url)
            return w3
        except Exception:
            pass
    log.warning("[REDEEM] All Polygon RPCs failed — RedeemWorker disabled.")
    return None


def _build_redeem_service(log_dir: Path, state_file: Path, lookback_days: int = 2) -> object | None:
    """Build SafeExecutor + LiveRedeemService. Returns service or None on error."""
    private_key = os.getenv("PM_PRIVATE_KEY", "")
    funder = os.getenv("PM_FUNDER_ADDRESS", "")
    if not private_key or not funder:
        log.warning("[REDEEM] PM_PRIVATE_KEY / PM_FUNDER_ADDRESS not set — RedeemWorker disabled.")
        return None

    w3 = _connect_polygon()
    if w3 is None:
        return None

    try:
        from binance_detector.execution.safe_executor import SafeExecutor
        from binance_detector.services.redeem_live import LiveRedeemService

        executor = SafeExecutor(w3=w3, safe_address=funder, eoa_private_key=private_key)
        if not executor.is_available():
            log.warning("[REDEEM] SafeExecutor: EOA is not owner of Safe %s — disabled.", funder)
            return None

        service = LiveRedeemService(
            w3=w3,
            safe_executor=executor,
            log_dir=log_dir,
            state_file=state_file,
            lookback_days=lookback_days,
        )
        return service
    except Exception as exc:
        log.warning("[REDEEM] Could not initialize RedeemService: %s", exc)
        return None


def _redeem_worker(
    service: object,
    active_interval: int,
    dry_run: bool,
    idle_interval: int = 900,
    idle_threshold: int = 3,
) -> None:
    """Background daemon thread with adaptive interval.

    State machine:
      ACTIVE (active_interval): scan found new candidates → stay ACTIVE
      ACTIVE → IDLE: empty_scans >= idle_threshold (consecutive empty scans)
      IDLE (idle_interval): new candidate found → back to ACTIVE immediately
    """
    log.info(
        "[REDEEM] Worker started (active=%ds, idle=%ds, idle_after=%d empty scans, dry_run=%s)",
        active_interval, idle_interval, idle_threshold, dry_run,
    )
    state = "ACTIVE"
    empty_scans = 0

    while True:
        interval = active_interval if state == "ACTIVE" else idle_interval
        try:
            results = service.scan_and_redeem(dry_run=dry_run)
            actionable = [r for r in results if r.status in ("redeemed", "dry_run", "pending")]

            if actionable:
                empty_scans = 0
                if state == "IDLE":
                    log.info("[REDEEM] state: IDLE → ACTIVE (new candidate found)")
                    state = "ACTIVE"
                for r in actionable:
                    if r.status == "redeemed":
                        log.info("[REDEEM] Redeemed %s %.4f USDC tx=%s",
                                 r.slug, r.balance_usd, r.tx_hash)
                    elif r.status == "dry_run":
                        log.info("[REDEEM] DRY_RUN %s would redeem %.4f USDC",
                                 r.slug, r.balance_usd)
            else:
                empty_scans += 1
                if state == "ACTIVE" and empty_scans >= idle_threshold:
                    log.info(
                        "[REDEEM] state: ACTIVE → IDLE (%d empty scans, next in %ds)",
                        empty_scans, idle_interval,
                    )
                    state = "IDLE"
                    empty_scans = 0

        except Exception as exc:
            log.error("[REDEEM] Worker error: %s", exc, exc_info=True)

        time.sleep(interval)


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

    # Start RedeemWorker only in live (non-dry-run) mode and if not disabled
    if not live_cfg.dry_run and not args.no_redeem:
        state_file = ROOT / "data" / "logs" / "redeem_done.json"
        redeem_service = _build_redeem_service(
            log_dir=ROOT / "data" / "logs",
            state_file=state_file,
            lookback_days=args.redeem_lookback_days,
        )
        if redeem_service is not None:
            t = threading.Thread(
                target=_redeem_worker,
                args=(redeem_service, args.redeem_interval, args.redeem_dry_run),
                kwargs={
                    "idle_interval": args.redeem_idle_interval,
                    "idle_threshold": args.redeem_idle_threshold,
                },
                daemon=True,
                name="RedeemWorker",
            )
            t.start()
            log.info(
                "RedeemWorker started (active=%ds, idle=%ds, lookback=%dd, dry_run=%s)",
                args.redeem_interval, args.redeem_idle_interval,
                args.redeem_lookback_days, args.redeem_dry_run,
            )
        else:
            log.warning("RedeemWorker could not start — check env vars and RPC.")
    else:
        if live_cfg.dry_run:
            log.info("RedeemWorker disabled (trading dry_run mode).")
        else:
            log.info("RedeemWorker disabled (--no-redeem flag).")

    last_entry_ts: datetime | None = None
    last_entered_round: str | None = None
    last_round_id: str = ""

    with log_path.open("a", encoding="utf-8") as fh:
        for i in range(args.iterations):
            now = datetime.now(timezone.utc)
            if i > 0 and i % 12 == 0:
                log.info("tick=%d round=%s", i, last_round_id or "?")
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
                        # compute actual time left from round_id (format: "key:20260404T083500Z")
                        try:
                            round_start_str = signal.round_id.split(":")[1]
                            round_start = datetime.strptime(round_start_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                            time_left_seconds = max(0, int((round_start + timedelta(seconds=300) - now).total_seconds()))
                        except Exception:
                            time_left_seconds = 60  # fallback
                        entry_result = live_engine.execute(
                            side=signal.action,
                            confidence=signal.confidence,
                            token_id=token_id,
                            quote=runner.polymarket.get_quote_for_spec_at(market_spec, now),
                            time_left_seconds=time_left_seconds,
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
                last_round_id = signal.round_id

            except KeyboardInterrupt:
                log.info("Interrupted by user.")
                break
            except Exception as exc:
                log.error("evaluate_once failed: %s", exc, exc_info=True)

            time.sleep(args.interval_seconds)

    log.info("Done. Log: %s", log_path)


if __name__ == "__main__":
    main()
