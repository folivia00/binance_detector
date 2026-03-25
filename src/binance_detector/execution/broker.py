from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


NormalizedOrderStatus = Literal[
    "pending",
    "open",
    "partially_filled",
    "filled",
    "canceled",
    "rejected",
    "unknown",
]


@dataclass(slots=True)
class OrderState:
    order_id: str
    side: str
    requested_size: float
    status: NormalizedOrderStatus
    created_at: datetime
    updated_at: datetime
    filled_size: float = 0.0
    avg_price: float = 0.0
    failure_reason: str = ""


def normalize_order_status(
    raw_status: str | None,
    *,
    filled_size: float,
    requested_size: float,
    canceled: bool = False,
) -> NormalizedOrderStatus:
    if canceled:
        return "canceled"
    normalized = (raw_status or "").strip().lower()
    if not normalized:
        if filled_size >= requested_size > 0:
            return "filled"
        if filled_size > 0:
            return "partially_filled"
        return "unknown"
    if normalized in {"open", "live", "placed"}:
        return "open"
    if normalized in {"pending", "new"}:
        return "pending"
    if normalized in {"filled", "matched"}:
        return "filled"
    if normalized in {"cancelled", "canceled"}:
        return "canceled"
    if normalized in {"rejected", "failed"}:
        return "rejected"
    if filled_size >= requested_size > 0:
        return "filled"
    if filled_size > 0:
        return "partially_filled"
    return "unknown"


class BrokerStateMachine:
    def __init__(self, pending_ttl_seconds: int = 20, replenish_min_fill_ratio: float = 0.6) -> None:
        self.pending_ttl_seconds = pending_ttl_seconds
        self.replenish_min_fill_ratio = replenish_min_fill_ratio

    def apply_update(
        self,
        order: OrderState,
        *,
        raw_status: str | None,
        filled_size: float,
        avg_price: float,
        updated_at: datetime,
        canceled: bool = False,
    ) -> OrderState:
        order.status = normalize_order_status(
            raw_status,
            filled_size=filled_size,
            requested_size=order.requested_size,
            canceled=canceled,
        )
        order.filled_size = filled_size
        order.avg_price = avg_price
        order.updated_at = updated_at
        if order.status == "unknown":
            order.failure_reason = "unknown_order_status"
        return order

    def pending_expired(self, order: OrderState, now: datetime) -> bool:
        if order.status not in {"pending", "open", "partially_filled"}:
            return False
        return (now - order.created_at).total_seconds() > self.pending_ttl_seconds

    def should_replenish(self, order: OrderState) -> bool:
        if order.status not in {"open", "partially_filled"}:
            return False
        if order.requested_size <= 0:
            return False
        fill_ratio = order.filled_size / order.requested_size
        return 0 < fill_ratio < self.replenish_min_fill_ratio
