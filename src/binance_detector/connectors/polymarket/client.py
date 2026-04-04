from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from binance_detector.config.market_registry import PolymarketMarketSpec
from binance_detector.domain.market import PolymarketQuote
from binance_detector.domain.rounds import MarketRound
from binance_detector.utils.time import floor_to_5m


@dataclass(slots=True)
class PolymarketClient:
    """Public Gamma/CLOB client for market discovery and book snapshots."""

    market_slug: str
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    timeout_seconds: float = 6.0
    user_agent: str = "Mozilla/5.0"
    _token_cache: dict[str, tuple[str, str]] = field(default_factory=dict, init=False)

    def get_active_round(self) -> MarketRound | None:
        now = datetime.now(timezone.utc)
        starts_at = floor_to_5m(now)
        return MarketRound(
            round_id=f"{self.market_slug}:{starts_at.strftime('%Y%m%dT%H%M%SZ')}",
            market_slug=self.market_slug,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=5),
            round_open_price=0.0,
            last_market_price=0.0,
        )

    def discover_markets(self, query: str | None = None, limit: int = 100) -> list[dict]:
        payload = self._get_json(
            base_url=self.gamma_base_url,
            path="/markets",
            params={"active": "true", "closed": "false", "limit": limit},
        )
        if not isinstance(payload, list):
            return []
        if not query:
            return payload
        needle = query.lower()
        return [
            market
            for market in payload
            if needle in str(market.get("question", "")).lower()
            or needle in str(market.get("slug", "")).lower()
        ]

    def get_market_metadata(self, query: str | None = None) -> dict | None:
        matches = self.discover_markets(query=query or self.market_slug, limit=250)
        if not matches:
            return None
        exact = next((item for item in matches if item.get("slug") == self.market_slug), None)
        return exact or matches[0]

    def get_market_by_slug(self, slug: str) -> dict | None:
        payload = self._get_json(
            base_url=self.gamma_base_url,
            path=f"/markets/slug/{slug}",
            params={},
        )
        return payload if isinstance(payload, dict) else None

    def get_quote(
        self,
        query: str | None = None,
        yes_token_id: str | None = None,
        no_token_id: str | None = None,
    ) -> PolymarketQuote:
        try:
            resolved_yes_token, resolved_no_token = self.resolve_token_ids(
                query=query,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
            )
            if not resolved_yes_token or not resolved_no_token:
                return self._demo_quote()
            yes_book = self.get_order_book(resolved_yes_token)
            no_book = self.get_order_book(resolved_no_token)
            return self._build_quote(yes_book=yes_book, no_book=no_book)
        except Exception:
            return self._demo_quote()

    def get_quote_for_spec(self, spec: PolymarketMarketSpec) -> PolymarketQuote:
        return self.get_quote_for_spec_at(spec, datetime.now(timezone.utc))

    def get_quote_for_spec_at(self, spec: PolymarketMarketSpec, ts: datetime) -> PolymarketQuote:
        resolved_slug = self.resolve_market_slug_for_spec(spec, ts)
        if resolved_slug:
            if resolved_slug not in self._token_cache:
                market = self.get_market_by_slug(resolved_slug)
                token_ids = json.loads(market.get("clobTokenIds", "[]")) if market else []
                if len(token_ids) >= 2:
                    self._token_cache[resolved_slug] = (str(token_ids[0]), str(token_ids[1]))
                    if len(self._token_cache) > 3:
                        del self._token_cache[next(iter(self._token_cache))]
            cached = self._token_cache.get(resolved_slug)
            if cached:
                yes_token_id, no_token_id = cached
                try:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        f_yes = executor.submit(self.get_order_book, yes_token_id)
                        f_no = executor.submit(self.get_order_book, no_token_id)
                        yes_book = f_yes.result()
                        no_book = f_no.result()
                    return self._build_quote(yes_book=yes_book, no_book=no_book)
                except Exception:
                    return self._demo_quote()
        return self.get_quote(
            query=spec.lookup_query,
            yes_token_id=spec.yes_token_id or None,
            no_token_id=spec.no_token_id or None,
        )

    def resolve_market_slug_for_spec(self, spec: PolymarketMarketSpec, ts: datetime) -> str:
        if spec.market_slug:
            return spec.market_slug
        if spec.market_slug_template:
            round_start = floor_to_5m(ts.astimezone(timezone.utc))
            round_start_epoch = int(round_start.timestamp())
            return spec.market_slug_template.format(round_start_epoch=round_start_epoch)
        return ""

    def get_token_ids_for_spec(self, spec: PolymarketMarketSpec, ts: datetime) -> tuple[str, str]:
        """Return (yes_token_id, no_token_id) for the current round, or ('', '') if unavailable."""
        resolved_slug = self.resolve_market_slug_for_spec(spec, ts)
        if not resolved_slug:
            return "", ""
        cached = self._token_cache.get(resolved_slug)
        if cached:
            return cached
        try:
            market = self.get_market_by_slug(resolved_slug)
            token_ids = json.loads(market.get("clobTokenIds", "[]")) if market else []
            if len(token_ids) >= 2:
                pair: tuple[str, str] = (str(token_ids[0]), str(token_ids[1]))
                self._token_cache[resolved_slug] = pair
                return pair
        except Exception:
            pass
        return "", ""

    def resolve_token_ids(
        self,
        *,
        query: str | None = None,
        yes_token_id: str | None = None,
        no_token_id: str | None = None,
    ) -> tuple[str, str]:
        if yes_token_id and no_token_id:
            return yes_token_id, no_token_id
        market = self.get_market_metadata(query=query)
        if not market:
            return "", ""
        token_ids = json.loads(market.get("clobTokenIds", "[]"))
        if len(token_ids) < 2:
            return "", ""
        return str(token_ids[0]), str(token_ids[1])

    def get_order_book(self, token_id: str) -> dict:
        return self._get_json(
            base_url=self.clob_base_url,
            path="/book",
            params={"token_id": token_id},
        )

    def _build_quote(self, *, yes_book: dict, no_book: dict) -> PolymarketQuote:
        yes_bids = yes_book.get("bids", [])
        yes_asks = yes_book.get("asks", [])
        no_bids = no_book.get("bids", [])
        no_asks = no_book.get("asks", [])
        yes_bid = float(yes_bids[-1]["price"]) if yes_bids else 0.0
        yes_ask = float(yes_asks[-1]["price"]) if yes_asks else 1.0  # asks sorted DESCENDING → [-1] = best (cheapest) ask
        no_bid = float(no_bids[-1]["price"]) if no_bids else 0.0
        no_ask = float(no_asks[-1]["price"]) if no_asks else 1.0    # asks sorted DESCENDING → [-1] = best (cheapest) ask
        book_liquidity = sum(float(level["size"]) for level in yes_bids[-5:] + yes_asks[-5:] + no_bids[-5:] + no_asks[-5:])
        timestamp_ms = max(int(yes_book.get("timestamp", "0")), int(no_book.get("timestamp", "0")))
        quote_age_seconds = 0.0
        if timestamp_ms > 0:
            ts = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            quote_age_seconds = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        return PolymarketQuote(
            ts=datetime.now(timezone.utc),
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            book_liquidity=book_liquidity,
            quote_age_seconds=quote_age_seconds,
        )

    def _demo_quote(self) -> PolymarketQuote:
        now = datetime.now(timezone.utc)
        return PolymarketQuote(
            ts=now,
            yes_bid=0.495,
            yes_ask=0.505,
            no_bid=0.495,
            no_ask=0.505,
            book_liquidity=250.0,
            quote_age_seconds=0.3,
        )

    def _get_json(self, *, base_url: str, path: str, params: dict[str, object]) -> dict | list:
        url = f"{base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
