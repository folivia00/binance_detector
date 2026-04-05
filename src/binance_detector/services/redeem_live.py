"""LiveRedeemService — automatic CTF token redemption via Gnosis Safe.

Reads live_loop_*.jsonl for filled orders, finds the corresponding markets
on Gamma, checks CTF balances, and redeems through the Proxy Safe.

Safe execution path: docs/stages/redeem_proxy_investigation.md (R1)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
# ABI — ConditionalTokens (same for NegRiskAdapter subset)
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
    balance_usd: float        # total redeemable (yes_bal + no_bal) / 1e6
    status: str               # "redeemed" | "dry_run" | "skipped" | "failed" | "not_resolved" | "already_done"
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
    neg_risk: bool            # True → use NegRiskAdapter instead of CTF


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
    """

    def __init__(
        self,
        w3: "Web3",
        safe_executor: "SafeExecutor",
        log_dir: Path,
        state_file: Path,
    ) -> None:
        self.w3 = w3
        self.safe_executor = safe_executor
        self.log_dir = log_dir
        self.state_file = state_file
        self._lock = threading.Lock()  # guards state_file reads/writes

        from eth_utils import to_checksum_address
        self._ctf = w3.eth.contract(
            address=to_checksum_address(CTF_ADDRESS), abi=_CTF_ABI
        )
        self._neg_risk = w3.eth.contract(
            address=to_checksum_address(NEG_RISK_ADAPTER), abi=_CTF_ABI
        )
        self._safe_addr = safe_executor.safe_address

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scan_and_redeem(self, dry_run: bool = True) -> list[RedeemResult]:
        """Find all winning positions and redeem them (or report in dry_run mode).

        Flow per market:
          1. Read logs → filled epochs
          2. Skip already in redeem_done.json
          3. Gamma: fetch market info (closed? negRisk? conditionId? clobTokenIds?)
          4. balanceOfBatch on Safe → skip if both 0
          5. payoutDenominator guard → skip if 0 (oracle not resolved yet)
          6. dry_run? → log only; else execTransaction → redeemPositions [1, 2]
          7. Write to redeem_done.json
        """
        done_state = self._load_done()
        filled_slugs = self._collect_filled_slugs()
        results: list[RedeemResult] = []

        if not filled_slugs:
            log.info("[REDEEM] No filled orders in logs.")
            return results

        log.info("[REDEEM] Found %d filled slugs to check.", len(filled_slugs))

        for slug, round_id in filled_slugs.items():
            if slug in done_state:
                log.debug("[REDEEM] %s — already redeemed, skipping.", slug)
                continue

            result = self._process_one(slug, round_id, done_state, dry_run)
            if result is not None:
                results.append(result)
                if result.status == "redeemed":
                    log.info(
                        "[REDEEM] %s redeemed %.4f USDC tx=%s",
                        slug, result.balance_usd, result.tx_hash,
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
        # 1. Fetch market from Gamma
        market_info = self._fetch_market_info(slug, round_id)
        if market_info is None:
            return None

        # 2. Check balances on Safe
        try:
            yes_bal, no_bal = self._check_balances(market_info)
        except Exception as exc:
            log.warning("[REDEEM] balanceOfBatch error for %s: %s", slug, exc)
            return None

        total_shares = yes_bal + no_bal
        if total_shares == 0:
            log.debug("[REDEEM] %s — zero balance, skipping.", slug)
            return None

        balance_usd = total_shares / 1e6
        log.info("[REDEEM] %s — YES=%d NO=%d (%.4f USDC)", slug, yes_bal, no_bal, balance_usd)

        # 3. E4 guard: check oracle resolved via payoutDenominator.
        # If the call succeeds and returns 0 → oracle hasn't resolved yet, skip.
        # If the call fails (empty bytes, unsupported selector) → unknown, proceed;
        # redeemPositions will revert on-chain if not yet resolved, costing minimal gas.
        try:
            cid_bytes = _condition_id_bytes(market_info.condition_id)
            contract = self._neg_risk if market_info.neg_risk else self._ctf
            payout_denom = contract.functions.payoutDenominator(cid_bytes).call()
            if payout_denom == 0:
                log.info("[REDEEM] %s — oracle not yet resolved (payoutDenominator=0), skipping.", slug)
                return RedeemResult(
                    round_id=round_id, slug=slug,
                    condition_id=market_info.condition_id,
                    yes_balance_shares=yes_bal, no_balance_shares=no_bal,
                    balance_usd=balance_usd, status="not_resolved",
                )
        except Exception as exc:
            # payoutDenominator may not be exposed on this CTF version — proceed;
            # if oracle isn't ready, redeemPositions will revert (caught below).
            log.debug("[REDEEM] payoutDenominator unavailable for %s (%s) — proceeding.", slug, exc)

        # 4. Dry run
        if dry_run:
            log.info("[REDEEM] DRY RUN — would redeem %s (%.4f USDC)", slug, balance_usd)
            return RedeemResult(
                round_id=round_id, slug=slug,
                condition_id=market_info.condition_id,
                yes_balance_shares=yes_bal, no_balance_shares=no_bal,
                balance_usd=balance_usd, status="dry_run",
            )

        # 5. Execute redeemPositions through Safe
        try:
            tx_hash = self._redeem_via_safe(market_info)
            result = RedeemResult(
                round_id=round_id, slug=slug,
                condition_id=market_info.condition_id,
                yes_balance_shares=yes_bal, no_balance_shares=no_bal,
                balance_usd=balance_usd,
                status="redeemed", tx_hash=tx_hash,
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
            slug=slug,
            round_id=round_id,
            condition_id=condition_id,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            neg_risk=bool(market.get("negRisk", False)),
        )

    def _check_balances(self, market_info: _MarketInfo) -> tuple[int, int]:
        """Return (yes_balance, no_balance) on the Safe address."""
        ids = [market_info.yes_token_id, market_info.no_token_id]
        accounts = [self._safe_addr, self._safe_addr]
        contract = self._neg_risk if market_info.neg_risk else self._ctf
        balances = contract.functions.balanceOfBatch(accounts, ids).call()
        return int(balances[0]), int(balances[1])

    def _redeem_via_safe(self, market_info: _MarketInfo) -> str:
        """Build redeemPositions calldata and execute through Safe. Returns tx_hash."""
        from eth_utils import to_checksum_address

        cid_bytes = _condition_id_bytes(market_info.condition_id)
        contract_addr = NEG_RISK_ADAPTER if market_info.neg_risk else CTF_ADDRESS
        contract = self._neg_risk if market_info.neg_risk else self._ctf

        # indexSets=[1,2] redeems both YES and NO in a single tx.
        # CTF silently skips the side with zero balance.
        calldata = contract.encode_abi(
            "redeemPositions",
            args=[
                to_checksum_address(USDC_ADDRESS),  # collateralToken
                b"\x00" * 32,                       # parentCollectionId = bytes32(0)
                cid_bytes,                           # conditionId
                [1, 2],                              # indexSets: YES=1, NO=2
            ],
        )

        receipt = self.safe_executor.execute_and_wait(
            to=contract_addr,
            data=calldata,
        )
        return receipt["transactionHash"].hex() if isinstance(receipt["transactionHash"], bytes) else receipt["transactionHash"]

    # ------------------------------------------------------------------
    # Log scanning
    # ------------------------------------------------------------------

    def _collect_filled_slugs(self) -> dict[str, str]:
        """Return {slug: round_id} for all filled entries in live_loop logs."""
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
    # State persistence  (redeem_done.json)
    # ------------------------------------------------------------------

    def _load_done(self) -> dict:
        """Load {slug: tx_hash} from redeem_done.json."""
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
            # Reload to pick up any changes from parallel runs
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
