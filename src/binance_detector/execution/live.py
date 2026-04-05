"""Live execution engine — places real orders on Polymarket CLOB.

dry_run=True (default): runs all pre-flight checks, logs decisions, does NOT place orders.
dry_run=False: places FOK market orders via py-clob-client.

One trade per round is enforced via cooldown_seconds (≥ round duration).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from binance_detector.domain.market import PolymarketQuote


@dataclass(slots=True)
class LiveExecutionConfig:
    stake_usd: float = 5.0
    cooldown_seconds: int = 30
    min_entry_confidence: float = 0.55
    no_entry_last_seconds: int = 10
    dry_run: bool = True

    @classmethod
    def from_json(cls, path: Path) -> "LiveExecutionConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(**payload)


@dataclass(slots=True)
class LiveExecutionResult:
    allowed: bool
    dry_run: bool
    side: str                   # "YES" | "NO"
    token_id: str               # PM CLOB token ID used
    stake_usd: float
    order_id: str | None        # None if blocked or dry_run
    filled_price: float         # 0.0 if not filled
    filled_size_usd: float      # 0.0 if not filled
    status: str                 # "filled" | "dry_run" | "blocked" | "error"
    block_reasons: tuple[str, ...]
    error: str | None


class LiveExecutionEngine:
    """Places real FOK market orders on the Polymarket CLOB.

    Parameters
    ----------
    config : LiveExecutionConfig
    clob_client : ClobClient | None
        Pass a py_clob_client.client.ClobClient instance for live trading.
        Must be None if dry_run=True (no client needed).
    """

    def __init__(self, config: LiveExecutionConfig, clob_client: object | None = None) -> None:
        self.config = config
        self._clob = clob_client

    def execute(
        self,
        *,
        side: str,
        confidence: float,
        token_id: str,
        quote: PolymarketQuote,
        time_left_seconds: int,
        last_entry_ts: datetime | None = None,
        now: datetime | None = None,
    ) -> LiveExecutionResult:
        current_time = now or datetime.now()
        block_reasons: list[str] = []

        # --- pre-flight checks (same logic as PaperExecutionEngine) ---
        if confidence < self.config.min_entry_confidence:
            block_reasons.append("low_confidence")
        if time_left_seconds <= self.config.no_entry_last_seconds:
            block_reasons.append("no_entry_last_seconds")
        if last_entry_ts is not None:
            elapsed = (current_time - last_entry_ts).total_seconds()
            if elapsed < self.config.cooldown_seconds:
                block_reasons.append("cooldown")

        ask_price = quote.ask_price(side)
        if ask_price <= 0 or ask_price >= 1.0:
            block_reasons.append("invalid_ask_price")

        if block_reasons:
            return LiveExecutionResult(
                allowed=False,
                dry_run=self.config.dry_run,
                side=side,
                token_id=token_id,
                stake_usd=self.config.stake_usd,
                order_id=None,
                filled_price=0.0,
                filled_size_usd=0.0,
                status="blocked",
                block_reasons=tuple(block_reasons),
                error=None,
            )

        # --- dry run: skip actual order ---
        if self.config.dry_run:
            return LiveExecutionResult(
                allowed=True,
                dry_run=True,
                side=side,
                token_id=token_id,
                stake_usd=self.config.stake_usd,
                order_id=None,
                filled_price=ask_price,
                filled_size_usd=self.config.stake_usd,
                status="dry_run",
                block_reasons=(),
                error=None,
            )

        # --- live order placement ---
        if self._clob is None:
            return LiveExecutionResult(
                allowed=False,
                dry_run=False,
                side=side,
                token_id=token_id,
                stake_usd=self.config.stake_usd,
                order_id=None,
                filled_price=0.0,
                filled_size_usd=0.0,
                status="error",
                block_reasons=("no_clob_client",),
                error="ClobClient not provided but dry_run=False",
            )

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
            from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

            # Round price to tick (0.01)
            rounded_price = float(
                Decimal(str(ask_price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
            # Compute size (shares) so that price × size has ≤ 2 decimal places.
            # PM checks maker_amount = price × size and requires ≤ 2 decimals.
            # Strategy: size = round_down(stake / price, 2) then round up by 0.01 steps
            # until price × size has ≤ 2 decimal places (or keep as-is if it does).
            p = Decimal(str(rounded_price))
            s_target = Decimal(str(self.config.stake_usd)) / p
            # Start from floor to 2 decimal places, find step that makes p*s 2-decimal
            # Round down so we never exceed stake_usd; find nearest valid size
            # where price × size has exactly ≤ 2 decimal places (PM constraint)
            size_dec = s_target.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            for _ in range(200):
                maker = (p * size_dec).quantize(Decimal("0.000001"))
                if maker == maker.quantize(Decimal("0.01")):
                    break
                size_dec -= Decimal("0.01")

            size = float(size_dec)

            order_args = OrderArgs(
                token_id=token_id,
                price=rounded_price,
                size=size,
                side="BUY",
            )
            signed_order = self._clob.create_order(
                order_args,
                PartialCreateOrderOptions(tick_size="0.01"),
            )
            # GTC limit at ask price fills immediately if liquidity available;
            # avoids FOK precision constraints on maker/taker amounts
            resp = self._clob.post_order(signed_order, OrderType.GTC)

            order_id = resp.get("orderID") or resp.get("id") or ""
            status = resp.get("status", "unknown")
            # GTC: "matched"/"success" = filled immediately
            # "live" = placed on book but not filled — cancel immediately
            if status == "live" and order_id:
                try:
                    self._clob.cancel({"orderID": order_id})
                except Exception:
                    pass
                return LiveExecutionResult(
                    allowed=True,
                    dry_run=False,
                    side=side,
                    token_id=token_id,
                    stake_usd=self.config.stake_usd,
                    order_id=order_id,
                    filled_price=0.0,
                    filled_size_usd=0.0,
                    status="cancelled",
                    block_reasons=(),
                    error="GTC order not filled (no liquidity at ask)",
                )
            if status in ("matched", "success"):
                return LiveExecutionResult(
                    allowed=True,
                    dry_run=False,
                    side=side,
                    token_id=token_id,
                    stake_usd=self.config.stake_usd,
                    order_id=order_id,
                    filled_price=ask_price,
                    filled_size_usd=self.config.stake_usd,
                    status="filled",
                    block_reasons=(),
                    error=None,
                )
            else:
                return LiveExecutionResult(
                    allowed=True,
                    dry_run=False,
                    side=side,
                    token_id=token_id,
                    stake_usd=self.config.stake_usd,
                    order_id=order_id,
                    filled_price=0.0,
                    filled_size_usd=0.0,
                    status="cancelled",
                    block_reasons=(),
                    error=f"PM status={status}",
                )
        except Exception as exc:
            return LiveExecutionResult(
                allowed=False,
                dry_run=False,
                side=side,
                token_id=token_id,
                stake_usd=self.config.stake_usd,
                order_id=None,
                filled_price=0.0,
                filled_size_usd=0.0,
                status="error",
                block_reasons=("order_failed",),
                error=str(exc),
            )
