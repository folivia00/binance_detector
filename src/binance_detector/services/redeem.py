from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from binance_detector.connectors.polymarket.client import PolymarketClient


@dataclass(slots=True)
class RedeemCandidate:
    market_id: str
    slug: str
    question: str
    closed: bool
    accepting_orders: bool


class RedeemService:
    """Separate resolved-market scanner.

    Real wallet redemption is intentionally not mixed into the trading loop.
    """

    def __init__(self, client: PolymarketClient) -> None:
        self.client = client

    def scan_resolved_markets(self, query: str | None = None) -> list[RedeemCandidate]:
        markets = self.client._get_json(
            base_url=self.client.gamma_base_url,
            path="/markets",
            params={"closed": "true", "limit": 100},
        )
        if not isinstance(markets, list):
            return []
        candidates: list[RedeemCandidate] = []
        needle = (query or "").lower()
        for market in markets:
            if needle and needle not in str(market.get("question", "")).lower() and needle not in str(market.get("slug", "")).lower():
                continue
            candidates.append(
                RedeemCandidate(
                    market_id=str(market.get("id", "")),
                    slug=str(market.get("slug", "")),
                    question=str(market.get("question", "")),
                    closed=bool(market.get("closed", False)),
                    accepting_orders=bool(market.get("acceptingOrders", False)),
                )
            )
        return candidates

    def write_candidates(self, path: Path, candidates: list[RedeemCandidate]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([asdict(candidate) for candidate in candidates], indent=2),
            encoding="utf-8",
        )
