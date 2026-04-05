"""Standalone script: redeem winning Polymarket CTF positions via Gnosis Safe.

Reads live_loop logs to find filled orders, checks CTF balances on the
Safe, and calls redeemPositions through Safe.execTransaction using the
pre-validated signature trick (Path A from redeem_proxy_investigation.md).

Usage
-----
    # Check balances only, no transactions:
    python scripts/run_redeem.py --dry-run

    # List all redeemable positions (alias for --dry-run):
    python scripts/run_redeem.py --list

    # Redeem all winning positions:
    python scripts/run_redeem.py

    # Redeem a specific market by slug:
    python scripts/run_redeem.py --single-slug btc-updown-5m-1775331000

    # Scan all btc-updown-5m markets for last N days (slow):
    python scripts/run_redeem.py --dry-run --days 7

Required env vars:
    PM_PRIVATE_KEY       — MetaMask EOA private key (hex)
    PM_FUNDER_ADDRESS    — Gnosis Safe address (holds CTF tokens)
    POLYGON_RPC_URL      — (optional) override; default: https://1rpc.io/matic
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("redeem")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
POLYGON_RPC_FALLBACKS = [
    "https://1rpc.io/matic",
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
]
STATE_FILE = ROOT / "data" / "logs" / "redeem_done.json"
LOG_DIR = ROOT / "data" / "logs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def connect_polygon(rpc_override: str = ""):
    from web3 import Web3
    candidates = [rpc_override] if rpc_override else []
    candidates += [r for r in POLYGON_RPC_FALLBACKS if r not in candidates]
    for url in candidates:
        try:
            log.info("Trying RPC: %s", url)
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
            block = w3.eth.block_number
            log.info("Connected. Block: %d", block)
            return w3
        except Exception as exc:
            log.warning("RPC %s failed: %s", url, exc)
    return None


def epochs_for_days(days: int) -> list[int]:
    """All btc-updown-5m round epochs for last N days (5-minute slots)."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_epoch = int(start.timestamp() // 300) * 300
    end_epoch = int(now.timestamp() // 300) * 300
    return list(range(start_epoch, end_epoch, 300))


def load_done() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_done(done: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(done, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Redeem winning Polymarket CTF positions via Gnosis Safe")
    p.add_argument("--dry-run", action="store_true",
                   help="Check balances only, send no transactions.")
    p.add_argument("--list", action="store_true",
                   help="Alias for --dry-run: show redeemable positions and exit.")
    p.add_argument("--single-slug", default="",
                   help="Redeem only this specific market (e.g. btc-updown-5m-1775331000).")
    p.add_argument("--days", type=int, default=0,
                   help="Scan all btc-updown-5m markets for last N days (slow).")
    p.add_argument("--rpc", default="",
                   help="Override Polygon RPC URL.")
    p.add_argument("--force", action="store_true",
                   help="Ignore redeem_done.json and attempt re-redeem (for recovery).")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    dry_run = args.dry_run or args.list

    # Validate dependencies
    try:
        from web3 import Web3
    except ImportError:
        log.error("web3 not installed. Run: pip install web3")
        sys.exit(1)

    private_key = os.getenv("PM_PRIVATE_KEY", "")
    funder = os.getenv("PM_FUNDER_ADDRESS", "")
    if not private_key or not funder:
        log.error("PM_PRIVATE_KEY and PM_FUNDER_ADDRESS must be set.")
        sys.exit(1)

    w3 = connect_polygon(args.rpc or os.getenv("POLYGON_RPC_URL", ""))
    if w3 is None:
        log.error("All Polygon RPCs failed. Set POLYGON_RPC_URL.")
        sys.exit(1)

    # Initialize SafeExecutor
    from binance_detector.execution.safe_executor import SafeExecutor, SafeExecutorError
    from binance_detector.services.redeem_live import LiveRedeemService

    executor = SafeExecutor(w3=w3, safe_address=funder, eoa_private_key=private_key)

    # Diagnostics — retry up to 3 times (transient RPC issues can return b'' on eth_call)
    diag: dict = {}
    for attempt in range(3):
        diag = executor.verify()
        if diag.get("eoa_is_owner"):
            break
        owners = diag.get("owners", [])
        if owners and not diag.get("eoa_is_owner"):
            break  # owners loaded OK but EOA genuinely not in list — don't retry
        if attempt < 2:
            log.warning("Safe verify failed (attempt %d/3), retrying in 3s...", attempt + 1)
            time.sleep(3)

    log.info("Safe diagnostics: %s", json.dumps(diag, default=str))

    if not diag.get("eoa_is_owner"):
        owners = diag.get("owners", [])
        if not owners:
            log.error(
                "Safe contract call failed (RPC issue?). "
                "Try again or set POLYGON_RPC_URL to another endpoint."
            )
        else:
            log.error("EOA %s is NOT owner of Safe %s — cannot execute.",
                      executor.eoa_address, funder)
        if not dry_run:
            sys.exit(1)
        log.warning("Continuing in dry-run mode despite verify failure.")

    matic_bal = diag.get("eoa_matic_balance", 0.0)
    if isinstance(matic_bal, str):  # error string from _call
        log.warning("Could not read MATIC balance: %s", matic_bal)
        matic_bal = 0.0
    if matic_bal < 0.01:
        log.error(
            "EOA %s has only %.6f MATIC — insufficient for gas.\n"
            "  Send at least 0.5 MATIC to %s on Polygon to cover transaction fees.",
            executor.eoa_address, matic_bal, executor.eoa_address,
        )
        if not dry_run:
            sys.exit(1)
    elif matic_bal < 0.1:
        log.warning(
            "EOA MATIC balance is low (%.6f MATIC). Consider topping up %s.",
            matic_bal, executor.eoa_address,
        )

    done_state = load_done() if not args.force else {}

    # If --single-slug: override the log scanning
    if args.single_slug:
        _run_single_slug(
            slug=args.single_slug,
            round_id=f"manual:{args.single_slug}",
            w3=w3,
            executor=executor,
            done_state=done_state,
            dry_run=dry_run,
        )
        return

    # Build service for log-based scanning
    service = LiveRedeemService(
        w3=w3,
        safe_executor=executor,
        log_dir=LOG_DIR,
        state_file=STATE_FILE,
    )

    # Override slugs if --days provided (scan wider range)
    if args.days > 0:
        log.info("Scanning all btc-updown-5m markets for last %d days...", args.days)
        _run_days_scan(args.days, service, done_state, dry_run, args.force)
        return

    # Default: log-based scan
    log.info("Scanning live_loop logs for filled orders...")
    results = service.scan_and_redeem(dry_run=dry_run)

    redeemed = [r for r in results if r.status == "redeemed"]
    dry_found = [r for r in results if r.status == "dry_run"]
    failed = [r for r in results if r.status == "failed"]

    if dry_run:
        if dry_found:
            log.info("--- Redeemable positions (%d) ---", len(dry_found))
            for r in dry_found:
                log.info("  %s | YES=%d NO=%d | %.4f USDC",
                         r.slug, r.yes_balance_shares, r.no_balance_shares, r.balance_usd)
        else:
            log.info("No redeemable positions found.")
        log.info("Run without --dry-run to execute redemptions.")
    else:
        log.info("Done. %d redeemed, %d failed.", len(redeemed), len(failed))
        for r in redeemed:
            log.info("  REDEEMED %s %.4f USDC tx=%s", r.slug, r.balance_usd, r.tx_hash)
        for r in failed:
            log.error("  FAILED %s: %s", r.slug, r.error)


def _run_single_slug(
    slug: str,
    round_id: str,
    w3: object,
    executor: object,
    done_state: dict,
    dry_run: bool,
) -> None:
    """Redeem a single market by slug."""
    from binance_detector.services.redeem_live import (
        LiveRedeemService, _MarketInfo, _gamma_get, _parse_clob_token_ids,
        CTF_ADDRESS, USDC_ADDRESS,
    )

    log.info("Single-slug mode: %s", slug)

    if slug in done_state and not dry_run:
        log.warning("%s already in redeem_done.json (tx=%s). Use --force to retry.", slug, done_state[slug])
        return

    # Fetch from Gamma
    try:
        result = _gamma_get("/markets", {"slug": slug})
        if not isinstance(result, list) or not result:
            log.error("Market %s not found in Gamma.", slug)
            return
        market = result[0]
    except Exception as exc:
        log.error("Gamma fetch failed: %s", exc)
        return

    if not market.get("closed"):
        log.warning("%s is not yet closed.", slug)
        return

    condition_id = market.get("conditionId", "")
    clob_ids = _parse_clob_token_ids(market.get("clobTokenIds"))
    if not condition_id or len(clob_ids) < 2:
        log.error("Missing conditionId or clobTokenIds for %s", slug)
        return

    from eth_utils import to_checksum_address
    safe_addr = to_checksum_address(executor.safe_address)

    # Build temp service for balance + redeem logic
    service = LiveRedeemService(
        w3=w3,
        safe_executor=executor,
        log_dir=LOG_DIR,
        state_file=STATE_FILE,
    )

    result_obj = service._process_one(slug, round_id, done_state, dry_run)
    if result_obj is None:
        log.info("Nothing to redeem for %s (zero balance or not found).", slug)
    elif result_obj.status == "dry_run":
        log.info("DRY RUN: %s — YES=%d NO=%d (%.4f USDC)",
                 slug, result_obj.yes_balance_shares, result_obj.no_balance_shares,
                 result_obj.balance_usd)
    elif result_obj.status == "redeemed":
        log.info("REDEEMED: %s — %.4f USDC tx=%s", slug, result_obj.balance_usd, result_obj.tx_hash)
        save_done({**done_state, slug: result_obj.tx_hash})
    else:
        log.warning("Status: %s — %s", result_obj.status, result_obj.error)


def _run_days_scan(
    days: int,
    service: object,
    done_state: dict,
    dry_run: bool,
    force: bool,
) -> None:
    """Scan all btc-updown-5m epochs for last N days."""
    from binance_detector.services.redeem_live import _gamma_get, _parse_clob_token_ids

    epochs = epochs_for_days(days)
    log.info("Checking %d epochs...", len(epochs))

    redeemed_count = 0
    found_count = 0

    for i, epoch in enumerate(epochs, 1):
        slug = f"btc-updown-5m-{epoch}"
        if slug in done_state and not force:
            continue
        if i % 100 == 0:
            log.info("  [%d/%d] scanning...", i, len(epochs))

        result = service._process_one(slug, f"days_scan:{slug}", done_state, dry_run)
        if result is None:
            continue

        if result.status in ("dry_run",):
            found_count += 1
            log.info("  %s — YES=%d NO=%d (%.4f USDC)",
                     slug, result.yes_balance_shares, result.no_balance_shares, result.balance_usd)
        elif result.status == "redeemed":
            redeemed_count += 1
            done_state[slug] = result.tx_hash
            save_done(done_state)
            log.info("  REDEEMED %s %.4f USDC tx=%s", slug, result.balance_usd, result.tx_hash)
            time.sleep(2)  # avoid RPC rate limiting between txs
        elif result.status == "failed":
            log.error("  FAILED %s: %s", slug, result.error)

    if dry_run:
        log.info("Dry-run complete. %d redeemable positions found.", found_count)
    else:
        log.info("Done. %d positions redeemed.", redeemed_count)


if __name__ == "__main__":
    main()
