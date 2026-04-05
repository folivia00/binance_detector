"""Derive Polymarket CLOB API credentials and verify connection.

Run once to get PM_API_KEY / PM_API_SECRET / PM_API_PASSPHRASE from your wallet.
These are needed for posting orders (L2 auth), even with signature_type=2.

Usage
-----
    export PM_PRIVATE_KEY=0x<key>
    export PM_FUNDER_ADDRESS=0x<address>
    export PM_SIGNATURE_TYPE=2
    python scripts/setup_pm_api_key.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, AssetType, BalanceAllowanceParams

CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137


def main() -> None:
    private_key = os.getenv("PM_PRIVATE_KEY", "")
    funder = os.getenv("PM_FUNDER_ADDRESS", "")
    sig_type = int(os.getenv("PM_SIGNATURE_TYPE", "2"))

    if not private_key or not funder:
        print("ERROR: set PM_PRIVATE_KEY and PM_FUNDER_ADDRESS first.")
        sys.exit(1)

    # L1 client — derive API credentials
    client_l1 = ClobClient(
        host=CLOB_HOST,
        chain_id=POLYGON_CHAIN_ID,
        key=private_key,
        funder=funder,
        signature_type=sig_type,
    )

    print(f"Wallet address : {client_l1.get_address()}")
    print("Deriving API credentials (L2)...")

    creds = client_l1.create_or_derive_api_creds()
    print("\nSuccess! Add to your ~/.bashrc (or current session):\n")
    print(f'export PM_API_KEY="{creds.api_key}"')
    print(f'export PM_API_SECRET="{creds.api_secret}"')
    print(f'export PM_API_PASSPHRASE="{creds.api_passphrase}"')

    # Verify L2 works — set creds on existing client (keeps signature_type=2 state)
    print("\nVerifying L2 connection...")
    client_l1.set_api_creds(creds)
    try:
        balance = client_l1.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        print(f"  USDC balance : {balance}")
    except Exception as e:
        print(f"  USDC balance : ERROR — {e}")

    print("\nNow set the three PM_API_* vars above, then run:")
    print("  python scripts/run_live_loop.py --market-key btc_updown_5m --live")


if __name__ == "__main__":
    main()
