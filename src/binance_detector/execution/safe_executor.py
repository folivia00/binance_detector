"""SafeExecutor — executes calldata through a Gnosis Safe v1.3.0 proxy.

Uses pre-validated signature (v=1): when msg.sender == owner the Safe
treats the transaction as already approved, no EIP-712 signing required.

References:
- docs/stages/redeem_proxy_investigation.md  (full R1 investigation)
- GnosisSafe.sol checkSignatures: v==1 → require(msg.sender == owner)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from eth_utils import to_checksum_address

if TYPE_CHECKING:
    from web3 import Web3

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ABI — Gnosis Safe (minimal subset needed)
# ---------------------------------------------------------------------------

_SAFE_ABI = [
    {
        "name": "execTransaction",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "to",              "type": "address"},
            {"name": "value",           "type": "uint256"},
            {"name": "data",            "type": "bytes"},
            {"name": "operation",       "type": "uint8"},
            {"name": "safeTxGas",       "type": "uint256"},
            {"name": "baseGas",         "type": "uint256"},
            {"name": "gasPrice",        "type": "uint256"},
            {"name": "gasToken",        "type": "address"},
            {"name": "refundReceiver",  "type": "address"},
            {"name": "signatures",      "type": "bytes"},
        ],
        "outputs": [{"name": "success", "type": "bool"}],
    },
    {
        "name": "getOwners",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address[]"}],
    },
    {
        "name": "nonce",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getThreshold",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "VERSION",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    },
]

_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Gas limit for execTransaction(redeemPositions).
# Actual usage on Polygon is ~120-150k; 250k gives a safe margin without overpaying.
_DEFAULT_GAS = 250_000
_MIN_PRIORITY_FEE_GWEI = 30
# base_fee multiplier: 2× gives room for a 2× spike in base fee between estimation and inclusion.
# base_fee + 30gwei is too tight — if base_fee spikes the TX gets stuck in mempool.
_BASE_FEE_MULTIPLIER = 2
# Receipt timeout: one full round (300s). TX on Polygon can be slow during congestion.
_DEFAULT_WAIT_TIMEOUT = 300


class SafeExecutorError(Exception):
    pass


class SafeExecutor:
    """Executes arbitrary calldata through a Gnosis Safe using the
    pre-validated signature trick (v=1, msg.sender == owner).

    Args:
        w3: Connected Web3 instance (Polygon).
        safe_address: PM_FUNDER_ADDRESS (the Safe contract).
        eoa_private_key: Private key of the MetaMask EOA (Safe owner).
    """

    def __init__(self, w3: "Web3", safe_address: str, eoa_private_key: str) -> None:
        from eth_account import Account

        self.w3 = w3
        self.safe_address = to_checksum_address(safe_address)
        self._account = Account.from_key(eoa_private_key)
        self.eoa_address = self._account.address
        self._safe = w3.eth.contract(address=self.safe_address, abi=_SAFE_ABI)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if the EOA is an owner of the Safe and Safe is reachable."""
        try:
            code = self.w3.eth.get_code(self.safe_address)
            if not code or code == b"":
                log.warning("SafeExecutor: no bytecode at %s", self.safe_address)
                return False
            owners = self._safe.functions.getOwners().call()
            return any(to_checksum_address(o) == self.eoa_address for o in owners)
        except Exception as exc:
            log.warning("SafeExecutor.is_available failed: %s", exc)
            return False

    def verify(self) -> dict:
        """Return diagnostic info about the Safe (for logging/debugging).

        Each call is independent — a failing RPC for one field does not block others.
        eoa_is_owner is derived from getOwners() only (the critical check).
        """
        def _call(fn):
            try:
                return fn()
            except Exception as exc:
                return f"error: {exc}"

        owners_raw = _call(lambda: self._safe.functions.getOwners().call())
        owners: list[str] = []
        eoa_is_owner = False
        if isinstance(owners_raw, list):
            owners = [to_checksum_address(o) for o in owners_raw]
            eoa_is_owner = self.eoa_address in owners

        return {
            "safe_address": self.safe_address,
            "eoa_address": self.eoa_address,
            "eoa_matic_balance": round(
                _call(lambda: self.w3.eth.get_balance(self.eoa_address) / 1e18) or 0.0, 6
            ),
            "version": _call(lambda: self._safe.functions.VERSION().call()),
            "threshold": _call(lambda: self._safe.functions.getThreshold().call()),
            "nonce": _call(lambda: self._safe.functions.nonce().call()),
            "owners": owners,
            "eoa_is_owner": eoa_is_owner,
        }

    def execute(
        self,
        to: str,
        data: bytes,
        value: int = 0,
        gas: int = _DEFAULT_GAS,
    ) -> str:
        """Execute `data` calldata at `to` through the Safe.

        Returns tx_hash (hex string). Raises SafeExecutorError on failure.

        Uses operation=0 (CALL), safeTxGas=0, baseGas=0, gasPrice=0,
        gasToken=0x0, refundReceiver=0x0 — no GSN refund mechanism.
        """
        to = to_checksum_address(to)
        sig = self._prevalidated_signature(self.eoa_address)

        # maxFeePerGas = base_fee * 2 + priority.
        # Multiplying base_fee by 2 gives enough room for a 2× spike between
        # estimation and inclusion. base_fee + 30gwei alone is too tight on Polygon.
        try:
            pending = self.w3.eth.get_block("pending")
            base_fee = pending.get("baseFeePerGas", self.w3.eth.gas_price)
        except Exception:
            base_fee = self.w3.eth.gas_price
        max_priority = self.w3.to_wei(_MIN_PRIORITY_FEE_GWEI, "gwei")
        max_fee = base_fee * _BASE_FEE_MULTIPLIER + max_priority
        # Use "pending" to include any mempool TXs in nonce count.
        # This prevents "replacement transaction underpriced" when a previous TX
        # is still in mempool — new TXs queue after it instead of conflicting.
        eoa_nonce = self.w3.eth.get_transaction_count(self.eoa_address, "pending")

        try:
            tx = self._safe.functions.execTransaction(
                to,             # to
                value,          # value
                data,           # data
                0,              # operation = CALL
                0,              # safeTxGas
                0,              # baseGas
                0,              # gasPrice (no refund)
                _ZERO_ADDRESS,  # gasToken
                _ZERO_ADDRESS,  # refundReceiver
                sig,            # signatures (pre-validated)
            ).build_transaction({
                "from": self.eoa_address,
                "nonce": eoa_nonce,
                "gas": gas,
                "maxFeePerGas": max_fee,
                "maxPriorityFeePerGas": max_priority,
                "chainId": 137,  # Polygon
            })
        except Exception as exc:
            raise SafeExecutorError(f"build_transaction failed: {exc}") from exc

        # Retry loop: on "replacement transaction underpriced" bump gas by 30% and retry.
        # This replaces any stuck pending TX at the same nonce (Polygon requires ≥10% bump).
        for attempt in range(3):
            try:
                signed = self._account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                return "0x" + tx_hash.hex()
            except Exception as exc:
                if "replacement transaction underpriced" in str(exc) and attempt < 2:
                    log.warning(
                        "SafeExecutor: replacement underpriced (attempt %d) — bumping gas +30%%",
                        attempt + 1,
                    )
                    max_fee = int(max_fee * 1.3)
                    max_priority = int(max_priority * 1.3)
                    tx["maxFeePerGas"] = max_fee
                    tx["maxPriorityFeePerGas"] = max_priority
                    continue
                raise SafeExecutorError(f"send_raw_transaction failed: {exc}") from exc

    def execute_and_wait(
        self,
        to: str,
        data: bytes,
        value: int = 0,
        gas: int = _DEFAULT_GAS,
        timeout: int = _DEFAULT_WAIT_TIMEOUT,
    ) -> dict:
        """Execute and wait for receipt. Returns receipt dict.

        Receipt dict always contains:
          - "transactionHash": hex string
          - "status": 1 (confirmed) or "pending" (timed out, TX in mempool)

        Raises SafeExecutorError only if TX reverts (status=0).
        On timeout (TX in mempool but not yet mined) returns {"status": "pending", ...}
        so the caller can persist the tx_hash and check it later.
        """
        tx_hash = self.execute(to=to, data=data, value=value, gas=gas)
        log.info("SafeExecutor: TX sent %s", tx_hash)
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        except Exception as exc:
            # TimeExhausted or RPC error — TX may still be in mempool.
            # Return pending state so caller can track and retry.
            log.warning(
                "SafeExecutor: receipt timeout for %s (%s) — TX may still be pending",
                tx_hash, exc,
            )
            return {"status": "pending", "transactionHash": tx_hash}

        if receipt["status"] != 1:
            raise SafeExecutorError(
                f"TX reverted: {tx_hash} (status={receipt['status']})"
            )
        log.info("SafeExecutor: TX confirmed %s (gas_used=%d)", tx_hash, receipt["gasUsed"])
        return dict(receipt)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prevalidated_signature(owner_address: str) -> bytes:
        """Build 65-byte pre-validated signature (v=1).

        Format: r(32) + s(32) + v(1)
          r = 0x00...00 + owner_address (left-padded to 32 bytes)
          s = 0x00...00 (32 zero bytes)
          v = 0x01

        GnosisSafe.sol logic:
            if (v == 1) {
                currentOwner = address(uint160(uint256(r)));
                require(msg.sender == currentOwner || approvedHashes[...]);
            }
        Since we send the tx from the EOA (msg.sender == owner), the check passes.
        """
        from eth_utils import to_bytes
        owner_bytes = to_bytes(hexstr=owner_address)  # 20 bytes
        r = b"\x00" * 12 + owner_bytes                # pad left to 32
        s = b"\x00" * 32
        v = b"\x01"
        sig = r + s + v
        assert len(sig) == 65, f"Expected 65 bytes, got {len(sig)}"
        return sig
