"""Factory for authenticated Polymarket ClobClient.

Supports signature_type=2 (funder/proxy mode) — no separate API keys required.
Orders are signed directly with the wallet private key.

Required environment variables:
    PM_PRIVATE_KEY       — Polygon wallet private key (hex, with or without 0x)
    PM_FUNDER_ADDRESS    — Wallet address that holds USDC (0x...)
    PM_SIGNATURE_TYPE    — Signing mode: 0=EOA, 2=proxy/funder (default: 2)

Usage
-----
    from binance_detector.connectors.polymarket.auth import build_clob_client
    clob = build_clob_client()

VPS setup (add to ~/.bashrc):
    export PM_PRIVATE_KEY=0x<your_private_key>
    export PM_FUNDER_ADDRESS=0x<your_wallet_address>
    export PM_SIGNATURE_TYPE=2

SECURITY: Never commit .env files or hardcode credentials in source code.
"""
from __future__ import annotations

import os

CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137


def build_clob_client() -> object:
    """Return a fully configured ClobClient ready for order placement.

    With signature_type=2 and funder address, no API key/secret/passphrase
    is needed — the wallet key handles both L1 signing and L2 auth.
    """
    try:
        from py_clob_client.client import ClobClient
    except ImportError as exc:
        raise ImportError("py-clob-client not installed. Run: pip install py-clob-client") from exc

    private_key = os.getenv("PM_PRIVATE_KEY", "")
    if not private_key:
        raise ValueError(
            "PM_PRIVATE_KEY not set.\n"
            "  export PM_PRIVATE_KEY=0x<your_polygon_private_key>"
        )

    funder = os.getenv("PM_FUNDER_ADDRESS", "")
    if not funder:
        raise ValueError(
            "PM_FUNDER_ADDRESS not set.\n"
            "  export PM_FUNDER_ADDRESS=0x<your_wallet_address>"
        )

    sig_type = int(os.getenv("PM_SIGNATURE_TYPE", "2"))

    return ClobClient(
        host=CLOB_HOST,
        chain_id=POLYGON_CHAIN_ID,
        key=private_key,
        funder=funder,
        signature_type=sig_type,
    )
