# Stage 01 Foundation

## Scope

Первый контрольный этап закрывает основу для приоритетов `P0` из roadmap:

- `M1` canonical round engine;
- `M3` baseline probability model вокруг `round_open`;
- `M4` офлайн-симулятор 5m раундов;
- `M5` config-driven entry policy v1;
- `M6` reverse-exit usefulness groundwork;
- `M8` basis / settle alignment guards.

## Implemented Elements

### Round Engine

- единый round manager: [manager.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/rounds/manager.py)
- round state и result-модели: [rounds.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/domain/rounds.py)
- разделены:
  - текущая market price;
  - `round_open_price`;
  - `round_close_ref_price`

### Market State / Features

- рыночные снимки Binance и PM quotes: [market.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/domain/market.py)
- state-features вокруг round open: [state.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/features/state.py)
- текущие baseline features:
  - `distance_to_open_bps`
  - `time_left_bucket`
  - `velocity_short`
  - `queue_imbalance`
  - `microprice_delta`
  - `volatility_recent`

### Model / Policy / Guards

- baseline probability model: [baseline.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/models/baseline.py)
- policy config: [entry_policy_v1.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/entry_policy_v1.json)
- basis and execution guards: [basis_guards_v1.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/basis_guards_v1.json)

### Simulator / Analytics

- round simulator: [simulator.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/analytics/simulator.py)
- reverse-exit records: [reverse_exit.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/analytics/reverse_exit.py)
- synthetic run script: [run_simulation.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_simulation.py)

## Current Limitations

- Binance connector пока отдаёт demo snapshot, а не реальные book/trade streams.
- Polymarket connector пока не подключён к реальным quotes/order semantics.
- симуляция идёт на synthetic ticks, поэтому текущий `pnl` нужен для диагностики пайплайна, а не для выводов о реальном edge.
- reverse-exit аналитика уже логируется, но пока строится на synthetic regime shift.

## Verification

- unit tests:
  - round open фиксируется один раз на раунд
  - round id меняется ровно на 5m boundary
  - probability score растёт при усилении distance/velocity
- smoke commands:
  - `python scripts/run_live_bot.py`
  - `python scripts/run_simulation.py`

## Next Step

Следующий этап: построить markdown-отчёты и таблицы `time × distance`, `tier usefulness`, `late damage zones`, чтобы policy v1 принималась уже на основе агрегированной аналитики, а не вручную.
