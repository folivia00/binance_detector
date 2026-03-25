from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[3]
RAW_BINANCE_DIR = BASE_DIR / "data" / "raw" / "binance"
RAW_POLYMARKET_DIR = BASE_DIR / "data" / "raw" / "polymarket"
FEATURES_DIR = BASE_DIR / "data" / "interim" / "features"
MODELS_DIR = BASE_DIR / "data" / "models"
LOGS_DIR = BASE_DIR / "data" / "logs"


def ensure_data_dirs() -> None:
    for path in (
        RAW_BINANCE_DIR,
        RAW_POLYMARKET_DIR,
        FEATURES_DIR,
        MODELS_DIR,
        LOGS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)

