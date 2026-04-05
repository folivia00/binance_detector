"""Factory for authenticated Polymarket ClobClient.

Requires environment variables:
    PM_PRIVATE_KEY       — Polygon wallet private key (hex)
    PM_FUNDER_ADDRESS    — Wallet address holding USDC
    PM_SIGNATURE_TYPE    — 2  (funder/proxy mode)
    PM_API_KEY           — API key (derive once via setup_pm_api_key.py)
    PM_API_SECRET        — API secret
    PM_API_PASSPHRASE    — API passphrase

L1 (signing orders) uses the private key.
L2 (posting orders) uses API credentials derived from the private key.

Run scripts/setup_pm_api_key.py once to derive PM_API_KEY / SECRET / PASSPHRASE.
"""
from __future__ import annotations

import os

CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137


def build_clob_client() -> object:
    """Return a fully configured ClobClient ready for order placement (L1 + L2)."""
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
    except ImportError as exc:
        raise ImportError("py-clob-client not installed. Run: pip install py-clob-client") from exc

    private_key = os.getenv("PM_PRIVATE_KEY", "")
    if not private_key:
        raise ValueError("PM_PRIVATE_KEY not set.\n  export PM_PRIVATE_KEY=0x<key>")

    funder = os.getenv("PM_FUNDER_ADDRESS", "")
    if not funder:
        raise ValueError("PM_FUNDER_ADDRESS not set.\n  export PM_FUNDER_ADDRESS=0x<address>")

    sig_type = int(os.getenv("PM_SIGNATURE_TYPE", "2"))

    api_key = os.getenv("PM_API_KEY", "")
    api_secret = os.getenv("PM_API_SECRET", "")
    api_passphrase = os.getenv("PM_API_PASSPHRASE", "")

    if not (api_key and api_secret and api_passphrase):
        raise ValueError(
            "PM_API_KEY / PM_API_SECRET / PM_API_PASSPHRASE not set.\n"
            "  Run: python scripts/setup_pm_api_key.py"
        )

    creds = ApiCreds(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase,
    )

    return ClobClient(
        host=CLOB_HOST,
        chain_id=POLYGON_CHAIN_ID,
        key=private_key,
        funder=funder,
        signature_type=sig_type,
        creds=creds,
    )
