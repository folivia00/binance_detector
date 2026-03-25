# Stage 04 Binance REST Binding

## Scope

Этот этап переводит Binance connector из заглушки в рабочий public REST источник данных.

## Added Elements

- live REST client: [client.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/connectors/binance/client.py)

Client теперь использует public Spot endpoints для:

- order book depth;
- recent trades;
- recent klines.

## What It Produces

Из этих данных собирается `BinanceSignalSnapshot` с:

- best bid / ask;
- mid и microprice;
- queue imbalance;
- short velocity;
- recent volatility;
- top depth aggregates;
- wall changes и full remove heuristics;
- aggressive buy/sell flow;
- rebound strength.

## Important Note

Если сеть или Binance API временно недоступны, connector откатывается в demo snapshot, чтобы pipeline не ломался. Это удобно для разработки, но при переходе к paper/live режимам fallback нужно будет сделать явно логируемым и жёстче контролируемым.

## Next Step

Следующий шаг — начать использовать реальные последовательные snapshots Binance в цикле и смотреть, как detectors ведут себя на живом потоке, а не только на synthetic run.
