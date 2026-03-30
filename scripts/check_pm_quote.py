"""Quick sanity check for PM CLOB ask-order fix.

Fetches a live quote from Polymarket and verifies:
  - yes_ask and no_ask are not stuck at 0.99
  - yes_ask + no_ask is in a sane range for a binary market [1.00, 1.20]
  - spread_bps is < 500 bps for each side

Usage:
    PYTHONPATH=./src python scripts/check_pm_quote.py
"""

import sys
from datetime import datetime, timezone

from binance_detector.config.market_registry import get_market_spec
from binance_detector.config.settings import settings
from binance_detector.connectors.polymarket.client import PolymarketClient

MARKET_KEY = "btc_updown_5m"

spec = get_market_spec(settings.pm_market_registry_path, MARKET_KEY)
if spec is None:
    print(f"ERROR: market key '{MARKET_KEY}' not found in registry")
    sys.exit(1)

client = PolymarketClient(market_slug=spec.market_slug or spec.market_slug_template or "")
now = datetime.now(timezone.utc)

print(f"Fetching PM quote at {now.isoformat()} ...")
quote = client.get_quote_for_spec_at(spec, now)

yes_spread = quote.spread_bps("YES")
no_spread  = quote.spread_bps("NO")
ask_sum    = quote.yes_ask + quote.no_ask

print()
print(f"  yes_ask        = {quote.yes_ask:.4f}")
print(f"  no_ask         = {quote.no_ask:.4f}")
print(f"  yes_bid        = {quote.yes_bid:.4f}")
print(f"  no_bid         = {quote.no_bid:.4f}")
print(f"  yes_ask+no_ask = {ask_sum:.4f}  (expected 1.00–1.20)")
print(f"  YES spread     = {yes_spread:.1f} bps")
print(f"  NO  spread     = {no_spread:.1f} bps")
print(f"  book_liquidity = {quote.book_liquidity:.0f}")
print(f"  quote_age      = {quote.quote_age_seconds:.1f}s")
print()

failures = []

if quote.yes_ask >= 0.95:
    failures.append(f"FAIL yes_ask={quote.yes_ask:.4f} >= 0.95 — looks like worst ask bug is still present")
if quote.no_ask >= 0.95:
    failures.append(f"FAIL no_ask={quote.no_ask:.4f} >= 0.95 — looks like worst ask bug is still present")
if ask_sum < 1.00:
    failures.append(f"FAIL ask_sum={ask_sum:.4f} < 1.00 — impossible for binary market")
if ask_sum > 1.20:
    failures.append(f"WARN ask_sum={ask_sum:.4f} > 1.20 — very wide market (low liquidity?)")
if yes_spread > 500:
    failures.append(f"WARN YES spread={yes_spread:.0f} bps > 500 — unusually wide")
if no_spread > 500:
    failures.append(f"WARN NO spread={no_spread:.0f} bps > 500 — unusually wide")

if failures:
    for f in failures:
        print(f)
    sys.exit(1)
else:
    print("OK — all sanity checks passed")
    sys.exit(0)
