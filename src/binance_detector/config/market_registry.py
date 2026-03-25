from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(slots=True)
class PolymarketMarketSpec:
    market_key: str
    description: str
    market_slug: str = ""
    market_slug_template: str = ""
    search_query: str = ""
    yes_token_id: str = ""
    no_token_id: str = ""
    enabled: bool = True

    @property
    def has_token_ids(self) -> bool:
        return bool(self.yes_token_id and self.no_token_id)

    @property
    def lookup_query(self) -> str:
        return self.market_slug or self.market_slug_template or self.search_query or self.market_key


def load_market_registry(path: Path) -> list[PolymarketMarketSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [PolymarketMarketSpec(**item) for item in payload.get("markets", [])]


def get_market_spec(path: Path, market_key: str) -> PolymarketMarketSpec | None:
    for spec in load_market_registry(path):
        if spec.market_key == market_key and spec.enabled:
            return spec
    return None
