"""One-time setup: derive Polymarket CLOB API credentials from your wallet private key.

Run this once on the VPS (or locally). It will print export commands for the
three env vars needed by run_live_loop.py.

Usage
-----
    export PM_PRIVATE_KEY=0x<your_polygon_private_key>
    python scripts/setup_pm_api_key.py

Output example:
    export PM_API_KEY="abc123..."
    export PM_API_SECRET="def456..."
    export PM_API_PASSPHRASE="xyz789..."

Add these to ~/.bashrc or a .env file on the VPS.
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
    # L1-only client (no API creds needed yet)
    clob = build_clob_client(check=False)
    print(f"Wallet address: {clob.get_address()}")
    print("Deriving / creating API credentials...")

    creds = clob.create_or_derive_api_creds()

    print("\nCredentials derived successfully. Add to your environment:\n")
    print(f'export PM_API_KEY="{creds.api_key}"')
    print(f'export PM_API_SECRET="{creds.api_secret}"')
    print(f'export PM_API_PASSPHRASE="{creds.api_passphrase}"')
    print("\nThen re-run: python scripts/run_live_loop.py --market-key btc_updown_5m --live")


if __name__ == "__main__":
    main()
