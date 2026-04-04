"""Verify Polymarket CLOB connection and wallet status.

With signature_type=2 (funder mode) no API key derivation is needed.
This script just confirms the wallet is reachable and shows balances.

Usage
-----
    export PM_PRIVATE_KEY=0x<key>
    export PM_FUNDER_ADDRESS=0x<address>
    export PM_SIGNATURE_TYPE=2
    python scripts/setup_pm_api_key.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.connectors.polymarket.auth import build_clob_client


def main() -> None:
    print("Connecting to Polymarket CLOB...")
    clob = build_clob_client()

    address = clob.get_address()
    print(f"  Wallet address : {address}")

    try:
        ok = clob.get_ok()
        print(f"  CLOB status    : {ok}")
    except Exception as e:
        print(f"  CLOB status    : ERROR — {e}")

    try:
        balance = clob.get_balance_allowance(params={"asset_type": "COLLATERAL"})
        print(f"  USDC balance   : {balance}")
    except Exception as e:
        print(f"  USDC balance   : ERROR — {e}")

    print("\nConnection OK. You can now run:")
    print("  python scripts/run_live_loop.py --market-key btc_updown_5m --live")


if __name__ == "__main__":
    main()
