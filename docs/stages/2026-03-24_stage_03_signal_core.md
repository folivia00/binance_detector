# Stage 03 Signal Core

## Scope

Этот этап двигает roadmap в сторону `M2` и делает signal core более явным и объяснимым.

## Added Elements

- detector package: [signals/detectors.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/signals/detectors.py)
- расширенный snapshot-слой с raw microstructure fields: [market.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/domain/market.py)
- round features теперь несут detector scores: [rounds.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/domain/rounds.py)
- baseline model теперь учитывает:
  - wall pull
  - major drop
  - full remove
  - absorption
  - resilience
  - aggregate detector bias

## Debug Trace

Per-tick debug columns теперь можно выгружать в CSV через:

- [export_tick_debug_csv.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/export_tick_debug_csv.py)

CSV хранит:

- round/time context;
- price relative to open;
- base state features;
- detector columns;
- `p_up_total`, `p_down_total`, `signal_tier`.

## Current Status

- signal core пока работает на synthetic/raw placeholders, а не на реальных Binance depth/trade streams;
- зато структура detectors уже отделена от модели и готова к замене synthetic feed на real feed без переписывания аналитики;
- live/demo pipeline и simulator используют один и тот же detector layer.

## Next Step

Следующий шаг по roadmap: на новых detector signals снова прогнать analytics и посмотреть, появились ли дополнительные `time × distance` зоны, после чего уже поджимать policy по фактическим плохим сегментам.
