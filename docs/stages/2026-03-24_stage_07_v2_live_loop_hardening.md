# Stage 07 V2 Live Loop Hardening

## Scope

Этот этап уже относится к `roadmap v2` и закрывает не каркас, а оставшиеся operational risks:

- silent Binance demo fallback;
- одноразовый live evaluation без stateful round loop;
- слабая observability для последовательного live/paper режима.

## Added Elements

### Explicit Snapshot Source

- `BinanceSignalSnapshot` теперь несёт:
  - `snapshot_source`
  - `fallback_reason`

- Binance client теперь:
  - явно маркирует `live` vs `demo`;
  - хранит `last_snapshot_source`;
  - хранит `last_fallback_reason`;
  - умеет запрещать demo fallback через `allow_demo_fallback=False`.

### Stateful Live Runner

- live pipeline переведён на stateful runner: [live.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/pipelines/live.py)

Это важно потому, что round manager теперь живёт между тиками, а не пересоздаётся на каждый вызов.

### Structured Live Decisions

- `TradingSignal` теперь несёт:
  - `round_id`
  - `signal_tier`
  - `time_bucket`
  - `distance_bucket`
  - `snapshot_source`
  - `fallback_reason`
  - `policy_reason`
  - `guard_reasons`
  - `paper_reasons`
  - `should_enter`

### Live Paper Loop

- добавлен длительный stateful loop: [run_live_paper_loop.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_live_paper_loop.py)

Он:

- последовательно опрашивает рынок;
- пишет JSONL по каждому live evaluation;
- строит per-round structured summaries;
- обновляет observability state по ходу работы.

### Observability Upgrade

- observability state расширен:
  - `last_snapshot_source`
  - `last_fallback_reason`
  - `guardrail_events`
  - `recent_round_summaries`

- observability server теперь поддерживает:
  - `/debug/events`
  - `/sse/state`

## Added Tests

- dynamic slug resolution for BTC 5m
- explicit Binance demo fallback marking

См. [test_market_registry_and_fallback.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/tests/unit/test_market_registry_and_fallback.py)

## Why This Matters

Это снимает главный v2-риск: теперь проект не может тихо притворяться live, если фактически ушёл в demo source. Плюс появился реальный stateful loop, на котором уже можно собирать длительные series и live round summaries.

## Next Step

Следующий полезный шаг по v2:

- прогнать более длинную живую серию через `run_live_paper_loop.py`;
- накопить `recent_round_summaries`;
- на их основе калибровать policy/guards уже по реальным round-level данным.
