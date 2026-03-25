from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.connectors.polymarket.client import PolymarketClient
from binance_detector.services.redeem import RedeemService


if __name__ == "__main__":
    service = RedeemService(PolymarketClient(market_slug="bitcoin"))
    candidates = service.scan_resolved_markets(query="bitcoin")
    output_path = ROOT / "data" / "logs" / "redeem_candidates.json"
    service.write_candidates(output_path, candidates)
    print(output_path)
    print(f"candidates={len(candidates)}")
