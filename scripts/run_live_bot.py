from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.pipelines.live import run_live_round
from binance_detector.storage.paths import ensure_data_dirs


if __name__ == "__main__":
    ensure_data_dirs()
    signal = run_live_round(symbol="BTCUSDT", market_slug="bitcoin-up-or-down-5m")
    print(signal)
