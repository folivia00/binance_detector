"""Factory for authenticated Polymarket ClobClient.

Reads credentials from environment variables:
    PM_PRIVATE_KEY       — Polygon wallet private key (hex, with or without 0x)
    PM_API_KEY           — Polymarket CLOB API key (derive once via setup_pm_api_key.py)
    PM_API_SECRET        — CLOB API secret
    PM_API_PASSPHRASE    — CLOB API passphrase

Usage
-----
    from binance_detector.connectors.polymarket.auth import build_clob_client
    clob = build_clob_client()          # raises if env vars missing
    clob = build_clob_client(check=False)  # returns client even without L2 creds (L1 only)
"""
from __future__ import annotations

import os

CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137


def build_clob_client(*, check: bool = True) -> object:
    """Return a configured ClobClient.

    Parameters
    ----------
    check : bool
        If True (default), raise ValueError if L2 credentials (API key / secret /
        passphrase) are missing. Set to False for L1-only operations (e.g. deriving
        API keys during setup).
    """
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
    except ImportError as exc:
        raise ImportError("py-clob-client not installed. Run: pip install py-clob-client") from exc

    private_key = os.getenv("PM_PRIVATE_KEY", "")
    if not private_key:
        raise ValueError(
            "PM_PRIVATE_KEY environment variable is not set. "
            "Export your Polygon wallet private key: export PM_PRIVATE_KEY=0x..."
        )

    api_key = os.getenv("PM_API_KEY", "")
    api_secret = os.getenv("PM_API_SECRET", "")
    api_passphrase = os.getenv("PM_API_PASSPHRASE", "")

    if check and not (api_key and api_secret and api_passphrase):
        raise ValueError(
            "PM_API_KEY / PM_API_SECRET / PM_API_PASSPHRASE not set. "
            "Run scripts/setup_pm_api_key.py once to derive them from PM_PRIVATE_KEY."
        )

    creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase) if api_key else None

    return ClobClient(
        host=CLOB_HOST,
        chain_id=POLYGON_CHAIN_ID,
        key=private_key,
        creds=creds,
        signature_type=0,  # EOA
    )
