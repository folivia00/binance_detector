from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.config.market_registry import get_market_spec
from binance_detector.config.settings import settings
from binance_detector.connectors.binance.client import BinanceClient
from binance_detector.connectors.polymarket.client import PolymarketClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture sequential Binance/Polymarket snapshots into JSONL.")
    parser.add_argument("--market-key", default="btc_updown_5m")
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--output", default="")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    spec = get_market_spec(settings.pm_market_registry_path, args.market_key)
    if spec is None:
        raise SystemExit(f"market_key not found: {args.market_key}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else ROOT / "data" / "raw" / "live" / f"capture_{args.market_key}_{timestamp}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    binance = BinanceClient(symbol=settings.symbol)
    polymarket = PolymarketClient(market_slug=spec.market_slug or spec.market_key)

    with output_path.open("w", encoding="utf-8") as handle:
        for index in range(args.samples):
            snapshot = binance.fetch_signal_snapshot()
            resolved_slug = polymarket.resolve_market_slug_for_spec(spec, snapshot.ts)
            quote = polymarket.get_quote_for_spec_at(spec, snapshot.ts)
            record = {
                "ts": snapshot.ts.isoformat(),
                "market_key": spec.market_key,
                "resolved_market_slug": resolved_slug,
                "market_lookup_query": spec.lookup_query,
                "yes_token_id": spec.yes_token_id,
                "no_token_id": spec.no_token_id,
                "binance": {
                    "market_price": snapshot.market_price,
                    "best_bid": snapshot.best_bid,
                    "best_ask": snapshot.best_ask,
                    "microprice": snapshot.microprice,
                    "queue_imbalance": snapshot.queue_imbalance,
                    "velocity_short": snapshot.velocity_short,
                    "microprice_delta": snapshot.microprice_delta,
                    "volatility_recent": snapshot.volatility_recent,
                    "bid_depth_top": snapshot.bid_depth_top,
                    "ask_depth_top": snapshot.ask_depth_top,
                    "bid_wall_change": snapshot.bid_wall_change,
                    "ask_wall_change": snapshot.ask_wall_change,
                    "bid_full_remove": snapshot.bid_full_remove,
                    "ask_full_remove": snapshot.ask_full_remove,
                    "aggressive_buy_flow": snapshot.aggressive_buy_flow,
                    "aggressive_sell_flow": snapshot.aggressive_sell_flow,
                    "rebound_strength": snapshot.rebound_strength,
                    "snapshot_source": snapshot.snapshot_source,
                    "fallback_reason": snapshot.fallback_reason
                },
                "polymarket": {
                    "yes_bid": quote.yes_bid,
                    "yes_ask": quote.yes_ask,
                    "no_bid": quote.no_bid,
                    "no_ask": quote.no_ask,
                    "book_liquidity": quote.book_liquidity,
                    "quote_age_seconds": quote.quote_age_seconds
                }
            }
            handle.write(json.dumps(record) + "\n")
            print(f"captured {index + 1}/{args.samples} ts={record['ts']}")
            if index + 1 < args.samples:
                time.sleep(args.interval_seconds)

    print(output_path)
