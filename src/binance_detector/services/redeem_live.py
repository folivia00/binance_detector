"""LiveRedeemService — automatic CTF token redemption via Gnosis Safe.

Reads live_loop_*.jsonl for filled orders, finds the corresponding markets
on Gamma, checks CTF balances, and redeems through the Proxy Safe.

Safe execution path: docs/stages/redeem_proxy_investigation.md (R1)

Stage 30 improvements:
- Pending TX tracking (redeem_pending.json) — handles receipt timeout
- Date filter in _collect_filled_slugs (lookback_days)
- Empty balance in-memory cache (avoids repeated RPC for settled markets)
- Fixed log: filter done FIRST, then report new_to_check count
- balanceOfBatch retry (3 attempts, 2s delay)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from web3 import Web3
    from binance_detector.execution.safe_executor import SafeExecutor

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Polygon contract addresses
# ---------------------------------------------------------------------------
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
GAMMA_BASE = "https://gamma-api.polymarket.com"

# ---------------------------------------------------------------------------
# ABI
# ---------------------------------------------------------------------------
_CTF_ABI = [
    {
        "name": "balanceOfBatch",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "accounts", "type": "address[]"},
            {"name": "ids",      "type": "uint256[]"},
        ],
        "outputs": [{"name": "", "type": "uint256[]"}],
    },
    {
        "name": "redeemPositions",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "collateralToken",     "type": "address"},
            {"name": "parentCollectionId",  "type": "bytes32"},
            {"name": "conditionId",         "type": "bytes32"},
            {"name": "indexSets",           "type": "uint256[]"},
        ],
        "outputs": [],
    },
    {
        # payoutDenominator(conditionId) → 0 if oracle hasn't resolved yet.
        # Note: Polymarket's CTF may not expose this getter — treat call errors as "unknown".
        "name": "payoutDenominator",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "conditionId", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class RedeemResult:
    round_id: str
    slug: str
    condition_id: str
    yes_balance_shares: int   # raw ERC-1155 units (6 decimals)
    no_balance_shares: int
    balance_usd: float        # total redeemable (yes + no) / 1e6
    status: str               # "redeemed" | "dry_run" | "skipped" | "failed"
                              # | "not_resolved" | "already_done" | "pending"
    tx_hash: str = ""
    error: str = ""

    def as_log_dict(self) -> dict:
        return {
            **asdict(self),
            "ts": datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class _MarketInfo:
    slug: str
    round_id: str
    condition_id: str
    yes_token_id: int
    no_token_id: int
    neg_risk: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gamma_get(path: str, params: dict | None = None) -> object:
    url = GAMMA_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; polymarket-redeem/1.0)",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _condition_id_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str.removeprefix("0x")).rjust(32, b"\x00")


def _parse_clob_token_ids(raw: object) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def _parse_round_date(round_id: str) -> datetime | None:
    """Extract UTC date from round_id like 'btc_updown_5m:20260405T094000Z'."""
    import re
    m = re.search(r":(\d{8})T", round_id)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class LiveRedeemService:
    """Scan filled orders from logs and redeem winning CTF positions via Safe.

    Args:
        w3: Connected Web3 instance (Polygon).
        safe_executor: Configured SafeExecutor (wraps PM_FUNDER_ADDRESS).
        log_dir: Directory containing live_loop_*.jsonl files.
        state_file: Path to redeem_done.json (tracks already redeemed slugs).
        lookback_days: Only consider filled rounds from last N days (default: 2).
    """

    def __init__(
        self,
        w3: "Web3",
        safe_executor: "SafeExecutor",
        log_dir: Path,
        state_file: Path,
        lookback_days: int = 2,
    ) -> None:
        self.w3 = w3
        self.safe_executor = safe_executor
        self.log_dir = log_dir
        self.state_file = state_file
        self.lookback_days = lookback_days
        self._pending_file = state_file.parent / "redeem_pending.json"
        self._lock = threading.Lock()

        from eth_utils import to_checksum_address
        self._ctf = w3.eth.contract(
            address=to_checksum_address(CTF_ADDRESS), abi=_CTF_ABI
        )
        self._neg_risk = w3.eth.contract(
            address=to_checksum_address(NEG_RISK_ADAPTER), abi=_CTF_ABI
        )
        self._safe_addr = safe_executor.safe_address

        # In-memory cache of slugs confirmed to have zero balance.
        # Avoids repeated balanceOfBatch calls for auto-settled markets.
        # Not persisted — reset on service restart (intentional).
        self._zero_balance_cache: set[str] = set()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scan_and_redeem(self, dry_run: bool = True) -> list[RedeemResult]:
        """Find all winning positions and redeem them (or report in dry_run mode).

        Returns list of RedeemResult for positions that had non-zero balance.
        """
        results: list[RedeemResult] = []

        # Step 0: resolve any pending TXs from previous iterations
        self._resolve_pending(results)

        done_state = self._load_done()
        all_slugs = self._collect_filled_slugs()

        # Filter out already-done slugs BEFORE logging
        new_slugs = {
            slug: rid for slug, rid in all_slugs.items()
            if slug not in done_state and slug not in self._load_pending()
        }

        total = len(all_slugs)
        done_count = total - len(new_slugs)
        if new_slugs:
            log.info(
                "[REDEEM] scan: filled_in_logs=%d, already_done=%d, new_to_check=%d",
                total, done_count, len(new_slugs),
            )
        else:
            log.debug(
                "[REDEEM] scan: filled_in_logs=%d, already_done=%d, new_to_check=0",
                total, done_count,
            )
            return results

        for slug, round_id in new_slugs.items():
            result = self._process_one(slug, round_id, done_state, dry_run)
            if result is not None:
                results.append(result)
                if result.status == "redeemed":
                    log.info(
                        "[REDEEM] %s redeemed %.4f USDC tx=%s",
                        slug, result.balance_usd, result.tx_hash,
                    )
                elif result.status == "pending":
                    log.warning(
                        "[REDEEM] %s TX pending (will check next iteration) tx=%s",
                        slug, result.tx_hash,
                    )

        return results

    # ------------------------------------------------------------------
    # Per-market processing
    # ------------------------------------------------------------------

    def _process_one(
        self,
        slug: str,
        round_id: str,
        done_state: dict,
        dry_run: bool,
    ) -> RedeemResult | None:
        if slug in self._zero_balance_cache:
            log.debug("[REDEEM] %s — zero balance cache hit, skipping.", slug)
            return None

        market_info = self._fetch_market_info(slug, round_id)
        if market_info is None:
            return None

        try:
            yes_bal, no_bal = self._check_balances_with_retry(market_info)
        except Exception as exc:
            log.warning("[REDEEM] balanceOfBatch failed for %s: %s", slug, exc)
            return None

        total_shares = yes_bal + no_bal
        if total_shares == 0:
            log.debug("[REDEEM] %s — zero balance, caching.", slug)
            self._zero_balance_cache.add(slug)
            return None

        balance_usd = total_shares / 1e6
        log.info("[REDEEM] %s — YES=%d NO=%d (%.4f USDC)", slug, yes_bal, no_bal, balance_usd)

        # E4 guard: payoutDenominator — if 0 oracle not resolved; if call fails proceed
        try:
            cid_bytes = _condition_id_bytes(market_info.condition_id)
            contract = self._neg_risk if market_info.neg_risk else self._ctf
            payout_denom = contract.functions.payoutDenominator(cid_bytes).call()
            if payout_denom == 0:
                log.info("[REDEEM] %s — oracle not yet resolved, skipping.", slug)
                return RedeemResult(
                    round_id=round_id, slug=slug,
                    condition_id=market_info.condition_id,
                    yes_balance_shares=yes_bal, no_balance_shares=no_bal,
                    balance_usd=balance_usd, status="not_resolved",
                )
        except Exception as exc:
            log.debug("[REDEEM] payoutDenominator unavailable for %s (%s) — proceeding.", slug, exc)

        if dry_run:
            log.info("[REDEEM] DRY RUN — would redeem %s (%.4f USDC)", slug, balance_usd)
            return RedeemResult(
                round_id=round_id, slug=slug,
                condition_id=market_info.condition_id,
                yes_balance_shares=yes_bal, no_balance_shares=no_bal,
                balance_usd=balance_usd, status="dry_run",
            )

        try:
            receipt = self._redeem_via_safe(market_info)
            tx_hash = _extract_tx_hash(receipt)

            if receipt.get("status") == "pending":
                # TX sent but not yet mined — save to pending state
                self._save_pending(slug, tx_hash, round_id, market_info.condition_id,
                                   yes_bal, no_bal, balance_usd)
                return RedeemResult(
                    round_id=round_id, slug=slug,
                    condition_id=market_info.condition_id,
                    yes_balance_shares=yes_bal, no_balance_shares=no_bal,
                    balance_usd=balance_usd, status="pending", tx_hash=tx_hash,
                )

            # Confirmed
            result = RedeemResult(
                round_id=round_id, slug=slug,
                condition_id=market_info.condition_id,
                yes_balance_shares=yes_bal, no_balance_shares=no_bal,
                balance_usd=balance_usd, status="redeemed", tx_hash=tx_hash,
            )
            self._mark_done(done_state, slug, tx_hash)
            return result
        except Exception as exc:
            log.error("[REDEEM] TX failed for %s: %s", slug, exc)
            return RedeemResult(
                round_id=round_id, slug=slug,
                condition_id=market_info.condition_id,
                yes_balance_shares=yes_bal, no_balance_shares=no_bal,
                balance_usd=balance_usd, status="failed", error=str(exc),
            )

    # ------------------------------------------------------------------
    # Pending TX resolution
    # ------------------------------------------------------------------

    def _resolve_pending(self, results: list[RedeemResult]) -> None:
        """Check all pending TXs and move confirmed ones to done state."""
        pending = self._load_pending()
        if not pending:
            return

        done_state = self._load_done()
        log.info("[REDEEM] Checking %d pending TX(s)...", len(pending))
        to_remove: list[str] = []

        for slug, entry in pending.items():
            tx_hash = entry.get("tx_hash", "")
            if not tx_hash:
                to_remove.append(slug)
                continue
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            except Exception as exc:
                log.debug("[REDEEM] pending receipt check failed for %s: %s", slug, exc)
                continue

            if receipt is None:
                log.debug("[REDEEM] %s still pending (tx=%s)", slug, tx_hash)
                continue

            if receipt["status"] == 1:
                log.info("[REDEEM] pending TX confirmed: %s %.4f USDC tx=%s",
                         slug, entry.get("balance_usd", 0), tx_hash)
                self._mark_done(done_state, slug, tx_hash)
                results.append(RedeemResult(
                    round_id=entry.get("round_id", ""),
                    slug=slug,
                    condition_id=entry.get("condition_id", ""),
                    yes_balance_shares=entry.get("yes_balance_shares", 0),
                    no_balance_shares=entry.get("no_balance_shares", 0),
                    balance_usd=entry.get("balance_usd", 0.0),
                    status="redeemed",
                    tx_hash=tx_hash,
                ))
                to_remove.append(slug)
            else:
                log.error("[REDEEM] pending TX reverted: %s (tx=%s)", slug, tx_hash)
                to_remove.append(slug)  # Remove from pending — will be retried fresh next scan

        if to_remove:
            self._remove_from_pending(to_remove)

    # ------------------------------------------------------------------
    # Gamma / on-chain helpers
    # ------------------------------------------------------------------

    def _fetch_market_info(self, slug: str, round_id: str) -> _MarketInfo | None:
        try:
            result = _gamma_get("/markets", {"slug": slug})
        except Exception as exc:
            log.debug("[REDEEM] Gamma fetch failed for %s: %s", slug, exc)
            return None

        if not isinstance(result, list) or not result:
            log.debug("[REDEEM] %s — not found in Gamma.", slug)
            return None

        market = result[0]
        if not market.get("closed"):
            log.debug("[REDEEM] %s — market still open.", slug)
            return None

        condition_id = market.get("conditionId", "")
        clob_ids = _parse_clob_token_ids(market.get("clobTokenIds"))
        if not condition_id or len(clob_ids) < 2:
            log.debug("[REDEEM] %s — missing conditionId or clobTokenIds.", slug)
            return None

        try:
            yes_token_id = int(clob_ids[0])
            no_token_id = int(clob_ids[1])
        except (ValueError, TypeError) as exc:
            log.debug("[REDEEM] %s — clobTokenIds parse error: %s", slug, exc)
            return None

        return _MarketInfo(
            slug=slug, round_id=round_id,
            condition_id=condition_id,
            yes_token_id=yes_token_id, no_token_id=no_token_id,
            neg_risk=bool(market.get("negRisk", False)),
        )

    def _check_balances_with_retry(
        self, market_info: _MarketInfo, attempts: int = 3, delay: float = 2.0
    ) -> tuple[int, int]:
        """balanceOfBatch with retry on RPC error."""
        ids = [market_info.yes_token_id, market_info.no_token_id]
        accounts = [self._safe_addr, self._safe_addr]
        contract = self._neg_risk if market_info.neg_risk else self._ctf
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                balances = contract.functions.balanceOfBatch(accounts, ids).call()
                return int(balances[0]), int(balances[1])
            except Exception as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    log.debug("[REDEEM] balanceOfBatch attempt %d failed for %s: %s — retrying",
                              attempt + 1, market_info.slug, exc)
                    time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def _redeem_via_safe(self, market_info: _MarketInfo) -> dict:
        """Build redeemPositions calldata and execute through Safe. Returns receipt dict."""
        from eth_utils import to_checksum_address

        cid_bytes = _condition_id_bytes(market_info.condition_id)
        contract_addr = NEG_RISK_ADAPTER if market_info.neg_risk else CTF_ADDRESS
        contract = self._neg_risk if market_info.neg_risk else self._ctf

        calldata = contract.encode_abi(
            "redeemPositions",
            args=[
                to_checksum_address(USDC_ADDRESS),
                b"\x00" * 32,
                cid_bytes,
                [1, 2],
            ],
        )
        return self.safe_executor.execute_and_wait(to=contract_addr, data=calldata)

    # ------------------------------------------------------------------
    # Log scanning
    # ------------------------------------------------------------------

    def _collect_filled_slugs(self) -> dict[str, str]:
        """Return {slug: round_id} for filled entries within lookback_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
        slugs: dict[str, str] = {}
        if not self.log_dir.exists():
            return slugs

        for log_file in sorted(self.log_dir.glob("live_loop_*.jsonl")):
            try:
                with open(log_file, encoding="utf-8") as f:
                    for line in f:
                        try:
                            row = json.loads(line)
                        except Exception:
                            continue
                        ex = row.get("execution", {})
                        if ex.get("status") != "filled":
                            continue
                        round_id = row.get("round_id", "")
                        if ":" not in round_id:
                            continue

                        # Date filter: skip rounds older than lookback_days.
                        # If unparseable → include (safe default, better a redundant check).
                        round_date = _parse_round_date(round_id)
                        if round_date is not None and round_date < cutoff:
                            continue

                        ts_str = round_id.split(":")[1]
                        try:
                            dt = datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ").replace(
                                tzinfo=timezone.utc
                            )
                        except ValueError:
                            continue
                        epoch = int(dt.timestamp())
                        slug = f"btc-updown-5m-{epoch}"
                        slugs[slug] = round_id
            except Exception:
                pass
        return slugs

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_done(self) -> dict:
        with self._lock:
            if not self.state_file.exists():
                return {}
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {}

    def _mark_done(self, done_state: dict, slug: str, tx_hash: str) -> None:
        """Atomically update redeem_done.json."""
        with self._lock:
            if self.state_file.exists():
                try:
                    done_state = json.loads(self.state_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            done_state[slug] = tx_hash
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(done_state, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)

    def _load_pending(self) -> dict:
        with self._lock:
            if not self._pending_file.exists():
                return {}
            try:
                return json.loads(self._pending_file.read_text(encoding="utf-8"))
            except Exception:
                return {}

    def _save_pending(
        self, slug: str, tx_hash: str, round_id: str, condition_id: str,
        yes_bal: int, no_bal: int, balance_usd: float,
    ) -> None:
        with self._lock:
            pending = {}
            if self._pending_file.exists():
                try:
                    pending = json.loads(self._pending_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            pending[slug] = {
                "tx_hash": tx_hash,
                "round_id": round_id,
                "condition_id": condition_id,
                "yes_balance_shares": yes_bal,
                "no_balance_shares": no_bal,
                "balance_usd": balance_usd,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
            self._pending_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._pending_file.with_suffix(".pending_tmp")
            tmp.write_text(json.dumps(pending, indent=2), encoding="utf-8")
            tmp.replace(self._pending_file)

    def _remove_from_pending(self, slugs: list[str]) -> None:
        with self._lock:
            if not self._pending_file.exists():
                return
            try:
                pending = json.loads(self._pending_file.read_text(encoding="utf-8"))
            except Exception:
                return
            for slug in slugs:
                pending.pop(slug, None)
            tmp = self._pending_file.with_suffix(".pending_tmp")
            tmp.write_text(json.dumps(pending, indent=2), encoding="utf-8")
            tmp.replace(self._pending_file)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _extract_tx_hash(receipt: dict) -> str:
    raw = receipt.get("transactionHash", "")
    if isinstance(raw, bytes):
        return "0x" + raw.hex()
    return str(raw)
