# Binance Detector

Каркас проекта под бота, который использует данные Binance для прогноза исхода 5-минутных раундов Polymarket по цене Bitcoin.

## Что внутри

```text
binance_detector/
├─ configs/
│  ├─ basis_guards_v1.json
│  ├─ entry_policy_v1.json
│  ├─ entry_policy_v2.json
│  └─ paper_execution_v1.json
├─ data/
│  ├─ raw/
│  │  ├─ binance/
│  │  └─ polymarket/
│  ├─ interim/
│  │  └─ features/
│  ├─ models/
│  └─ logs/
├─ docs/
│  ├─ reports/
│  └─ stages/
├─ scripts/
│  ├─ backfill_binance.py
│  ├─ capture_live_snapshots.py
│  ├─ export_simulation_report.py
│  ├─ export_tick_debug_csv.py
│  ├─ run_live_bot.py
│  ├─ run_live_canary.py
│  ├─ run_observability_server.py
│  ├─ run_paper_from_capture.py
│  ├─ run_redeem_service.py
│  ├─ run_simulation.py
│  └─ train_model.py
├─ src/binance_detector/
│  ├─ analytics/
│  ├─ config/
│  ├─ connectors/
│  ├─ domain/
│  ├─ execution/
│  ├─ features/
│  ├─ models/
│  ├─ observability/
│  ├─ pipelines/
│  ├─ rounds/
│  ├─ services/
│  ├─ signals/
│  ├─ storage/
│  ├─ strategy/
│  └─ utils/
└─ tests/
   ├─ integration/
   └─ unit/
```

## Поток данных

1. `connectors/binance` получает market data Binance.
2. `connectors/polymarket` получает market metadata и order book Polymarket.
3. `rounds` фиксирует canonical 5m round, `round_open_price` и `t_left`.
4. `signals` считает detectors микроструктуры.
5. `features` собирает state around open.
6. `models` переводит это в `p_up_total` / `p_down_total`.
7. `strategy` применяет policy и guards.
8. `execution` моделирует paper execution.
9. `analytics` строит round summary, tier usefulness и debug trace.

## Роли модулей

- `config`: настройки окружения, тайминги раунда, пути к данным.
- `domain`: типы данных для раундов, котировок, сигналов и предсказаний.
- `connectors`: доступ к Binance и Polymarket.
- `signals`: detector layer микроструктуры.
- `features`: state features вокруг round open.
- `models`: baseline probability model.
- `strategy`: allow/ban policy и basis/quote guards.
- `execution`: paper execution и broker state machine.
- `analytics`: симулятор, markdown summary, reverse-exit usefulness.
- `observability`: heartbeat, state, debug endpoints.
- `services`: вспомогательные сервисы, например redeem scan.

## Paper Прогон 5m Раундов

Ниже описан основной paper flow для 5-минутных раундов.

### Что считается paper-прогоном в текущем проекте

Сейчас paper-прогон не отправляет реальные ордера в Polymarket. Он делает следующее:

1. строит последовательность 5-минутных раундов;
2. на каждом тике считает сигналы Binance-подобной микроструктуры;
3. переводит их в вероятность закрытия выше/ниже `round_open`;
4. применяет `entry policy`, `basis guards` и paper execution rules;
5. строит аналитику по входам, блокировкам, reverse-exit и bucket tables.

Текущий основной paper pipeline использует synthetic 5m stream, но опирается на тот же round/signal/model/execution слой, который используется и в live smoke-flow.

Для следующего уровня paper-анализа уже есть и реальный capture flow:

1. записать последовательные live snapshots Binance + Polymarket в JSONL;
2. прогнать их тем же paper engine;
3. получить markdown-report уже по реальному последовательному потоку.

### Подготовка

Из корня проекта:

```powershell
$env:PYTHONPATH="src"
```

Если нужны только unit-тесты перед прогоном:

```powershell
python -m unittest discover -s tests\unit -v
```

### Быстрый paper smoke-test

Эта команда делает один paper-прогон по synthetic 5m rounds и печатает общие метрики:

```powershell
python scripts\run_simulation.py
```

Что выдаётся в консоль:

- число round summaries;
- суммарный `pnl`;
- `winrate`;
- `avg_edge_at_entry`;
- число `reverse_exit`.

### Полный paper-прогон с артефактами

1. Запустить симулятор:

```powershell
python scripts\run_simulation.py
```

2. Сгенерировать markdown-отчёт:

```powershell
python scripts\export_simulation_report.py
```

3. Сгенерировать per-tick debug CSV:

```powershell
python scripts\export_tick_debug_csv.py
```

После этого будут созданы:

- `docs/reports/simulation_report_<timestamp>.md`
- `data/logs/tick_debug_<timestamp>.csv`

### Paper-прогон по реальному capture-файлу

Этот режим уже не synthetic. Он записывает последовательные реальные snapshots и затем прогоняет их через тот же paper engine.

1. Записать snapshots в JSONL:

```powershell
python scripts\capture_live_snapshots.py --market-key btc_updown_5m --samples 24 --interval-seconds 5
```

2. Прогнать paper engine по записанному файлу:

```powershell
python scripts\run_paper_from_capture.py data\raw\live\capture_btc_updown_5m_<timestamp>.jsonl --market-key btc_updown_5m
```

Что получится:

- `data/raw/live/capture_<market_key>_<timestamp>.jsonl`
- `docs/reports/captured_paper_report_<market_key>_<timestamp>.md`

### Что такое `btc_updown_5m`

Сейчас в registry уже заведен рабочий `market_key`:

- `btc_updown_5m`

Он использует динамический slug template для 5-минутных BTC markets Polymarket. Конфиг лежит в:

- [pm_market_registry.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/pm_market_registry.json)

Если появится необходимость жёстко пинить `yes_token_id` / `no_token_id`, это можно сделать прямо в registry без переписывания pipeline.

### Что смотреть в markdown-отчёте

Markdown-отчёт нужен для оценки качества paper strategy по 5-минутным раундам.

Основные секции:

- `Simulation Summary`
  показывает общую прибыльность и базовые метрики серии прогонов.
- `Time x Distance`
  показывает, как стратегия ведёт себя в бакетах `time_bucket | distance_bucket`.
- `Event Breakdown`
  показывает число `candidate_entry`, `actual_entry`, `blocked_entry`, `reverse_exit`.
- `Tier Usefulness`
  показывает полезность `medium`, `strong`, `very_strong`.
- `Block Reasons`
  показывает, что чаще всего режет входы.
- `Late Damage Zones`
  показывает поздние бакеты с плохим damage, если они есть.

### Что смотреть в debug CSV

CSV нужен для покадрового разбора сигнала внутри 5m round.

Там есть:

- `round_id`
- `market_price`
- `round_open_price`
- `distance_to_open_bps`
- `time_left_bucket`
- `distance_bucket`
- базовые state features
- detector columns:
  - `detector_velocity`
  - `detector_queue_imbalance`
  - `detector_microprice`
  - `detector_wall_pull`
  - `detector_major_drop`
  - `detector_full_remove`
  - `detector_absorption`
  - `detector_resilience`
  - `detector_bias`
- `p_up_total`
- `p_down_total`
- `signal_tier`

Этот CSV нужен, чтобы понимать, почему модель на конкретном тике дала `YES` или `NO`.

### Конфиги, которые влияют на paper-прогон

- [entry_policy_v2.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/entry_policy_v2.json)
  активная policy по умолчанию. Это whitelist-policy после post-calibration retuning.
- [entry_policy_v1.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/entry_policy_v1.json)
  baseline policy до post-calibration retuning; сохранена для сравнения.
- [basis_guards_v1.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/basis_guards_v1.json)
  управляет guards по `basis`, quote freshness, spread, liquidity и `t_left`.
- [paper_execution_v1.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/paper_execution_v1.json)
  управляет paper execution filters: `max_slippage_bps`, `min_entry_confidence`, `cooldown_seconds`, `no_entry_last_seconds`.

Если меняешь эти конфиги, прогон надо повторить и заново сравнить markdown-report и debug CSV.

### Практический цикл paper-анализа

Базовый рабочий цикл такой:

1. прогнать `python scripts\run_simulation.py`
2. выгрузить `python scripts\export_simulation_report.py`
3. выгрузить `python scripts\export_tick_debug_csv.py`
4. посмотреть `Time x Distance`, `Tier Usefulness` и `Block Reasons`
5. скорректировать `entry_policy_v2.json` или `basis_guards_v1.json`
6. повторить прогон и сравнить новую серию с предыдущей

### Ограничения текущего paper-режима

- 5m round engine уже canonical, но основной paper run пока synthetic, а не на исторических реальных BTC 5m rounds Polymarket.
- Реальные Binance public snapshots подключены для live smoke-flow, но paper loop пока не пишет длинную живую серию.
- Polymarket public order books подключены, но реальные ордера не отправляются.
- Поэтому текущий paper-прогон нужен для калибровки логики, policy и аналитики, а не для вывода о готовности к live trade.

## Live Smoke И Canary

Быстрый live smoke:

```powershell
python scripts\run_live_bot.py
```

Минимальный canary:

```powershell
python scripts\run_live_canary.py
```

Локальный observability server:

```powershell
python scripts\run_observability_server.py
```

Доступные endpoints:

- `http://127.0.0.1:8765/health`
- `http://127.0.0.1:8765/heartbeat`
- `http://127.0.0.1:8765/summary/latest`
- `http://127.0.0.1:8765/debug/state`

## Redeem Service

Сканирование resolved markets вынесено отдельно:

```powershell
python scripts\run_redeem_service.py
```

Результат будет записан в `data/logs/redeem_candidates.json`.

## Документация По Этапам

Текущий статус по roadmap фиксируется в `docs/stages/`.

Ключевые stage-файлы:

- [2026-03-24_stage_01_foundation.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/stages/2026-03-24_stage_01_foundation.md)
- [2026-03-24_stage_02_simulation_analytics.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/stages/2026-03-24_stage_02_simulation_analytics.md)
- [2026-03-24_stage_03_signal_core.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/stages/2026-03-24_stage_03_signal_core.md)
- [2026-03-24_stage_04_binance_rest_binding.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/stages/2026-03-24_stage_04_binance_rest_binding.md)
- [2026-03-24_stage_05_pm_execution_ops.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/stages/2026-03-24_stage_05_pm_execution_ops.md)
- [2026-03-24_stage_06_real_capture_paper_loop.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/stages/2026-03-24_stage_06_real_capture_paper_loop.md)

## Следующий Практический Шаг

Следующий сильный шаг после текущего README-flow:

1. перевести paper loop с synthetic series на длинную реальную последовательность Binance snapshots;
2. жёстко привязать paper execution к конкретным BTC 5m market identifiers Polymarket;
3. только после этого переходить к настоящему live execution.
