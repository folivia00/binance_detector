# Stage 06 Real Capture Paper Loop

## Scope

Этот этап переводит проект от purely synthetic paper run к реальному последовательному потоку snapshots.

## Added Elements

### Market Registry

- Polymarket market registry config: [pm_market_registry.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/pm_market_registry.json)
- registry loader: [market_registry.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/config/market_registry.py)

Registry теперь умеет задавать:

- fixed `market_slug`;
- dynamic `market_slug_template`;
- explicit `yes_token_id` / `no_token_id`.

### Live Capture

- sequential snapshot capture script: [capture_live_snapshots.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/capture_live_snapshots.py)

Capture пишет в JSONL:

- timestamp;
- market registry context;
- Binance snapshot fields;
- Polymarket quote snapshot fields.

### Paper From Captured Stream

- runner over captured live snapshots: [run_paper_from_capture.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_paper_from_capture.py)

Этот runner:

- читает JSONL;
- переводит записи в `SimulationTick`;
- использует тот же `RoundSimulator`;
- выпускает markdown report по реальной последовательности snapshots.

## Important Notes

- registry уже содержит рабочий `btc_updown_5m` с dynamic slug template `btc-updown-5m-{round_start_epoch}`;
- при появлении точных `yes_token_id` / `no_token_id` их можно просто прописать в registry без переписывания pipeline;
- settle в captured paper run пока approximated как последний Binance market price внутри раунда.

## Why This Matters

Это первый шаг, который действительно соединяет:

- real Binance public snapshots;
- real Polymarket public quotes;
- round engine;
- paper execution;
- analytics.

## Next Step

Следующий важный шаг:

- накопить более длинную серию captured snapshots;
- зафиксировать точные BTC 5m market ids;
- сравнить captured-paper analytics против synthetic baseline;
- только потом думать о real order execution.
