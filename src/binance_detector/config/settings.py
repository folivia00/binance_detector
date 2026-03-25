from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "data"


@dataclass(slots=True)
class Settings:
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    polymarket_api_key: str = os.getenv("POLYMARKET_API_KEY", "")
    polymarket_api_secret: str = os.getenv("POLYMARKET_API_SECRET", "")
    polymarket_funder: str = os.getenv("POLYMARKET_FUNDER", "")
    model_path: Path = Path(os.getenv("MODEL_PATH", str(DATA_DIR / "models" / "latest.pkl")))
    entry_policy_path: Path = BASE_DIR / "configs" / "entry_policy_v2.json"
    basis_guards_path: Path = BASE_DIR / "configs" / "basis_guards_v1.json"
    paper_execution_path: Path = BASE_DIR / "configs" / "paper_execution_v1.json"
    pm_market_registry_path: Path = BASE_DIR / "configs" / "pm_market_registry.json"
    tier_calibration_path: Path = BASE_DIR / "configs" / "tier_calibration_v1.json"
    round_seconds: int = 300
    symbol: str = "BTCUSDT"


settings = Settings()
