# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Обзор проекта

Бот для торговли на Polymarket — предсказывает направление BTC за 5-минутные раунды, используя сигналы микроструктуры стакана Binance. Работает в режиме бумажной торговли (симуляция) или в живом режиме. Вся конфигурация стратегии — JSON-файлы; изменение стратегии не требует правки кода.

## Команды

**Установка:**
```bash
pip install -r requirements.txt   # устанавливает пакет в editable-режиме через -e .
```

**Запуск тестов:**
```bash
PYTHONPATH=./src python -m unittest discover -s ./tests/unit -v

# Один файл:
PYTHONPATH=./src python -m unittest tests.unit.test_baseline_model -v

# Один тест:
PYTHONPATH=./src python -m unittest tests.unit.test_baseline_model.TestBaselineModel.test_prediction -v
```

**Синтетическая симуляция (120 раундов, живые данные не нужны):**
```bash
python scripts/run_simulation.py
```

**Live paper loop (реальные данные Binance + Polymarket):**
```bash
python scripts/run_live_paper_loop.py --market-key btc_updown_5m --iterations 1800 --interval-seconds 5
```

**Захват реальных снапшотов для воспроизведения:**
```bash
python scripts/capture_live_snapshots.py --market-key btc_updown_5m --samples 24 --interval-seconds 5
python scripts/run_paper_from_capture.py data/raw/live/capture_btc_updown_5m_*.jsonl --market-key btc_updown_5m
```

**Анализ и отчёты:**
```bash
python scripts/analyze_live_paper_loop.py data/logs/live_paper_loop_*.jsonl
python scripts/analyze_time_of_day.py
python scripts/analyze_counterfactual_thresholds.py
python scripts/analyze_outcome_edge.py
python scripts/export_simulation_report.py
python scripts/export_tick_debug_csv.py
```

**Сервер наблюдаемости (локальный HTTP-мониторинг):**
```bash
python scripts/run_observability_server.py
# Эндпоинты: /health, /heartbeat, /summary/latest, /debug/state, /debug/events, /sse/state
```

## Архитектура

### Поток данных (за один тик)

```
BinanceClient → BinanceSignalSnapshot
PolymarketClient → PolymarketQuote
          ↓
CanonicalRoundManager → MarketRound (привязка к 5м-границе)
          ↓
compute_detector_state() → DetectorState (8 детекторов микроструктуры)
          ↓
build_round_features() → RoundFeatures (бакеты дистанции и времени)
          ↓
BaselineProbabilityModel → RoundPrediction (p_up, p_down, signal_tier)
          ↓
EntryPolicy → разрешить/заблокировать (whitelist комбинаций tier×bucket)
          ↓
evaluate_entry_guards() → проверка basis, свежести, ликвидности, спреда, времени
          ↓
PaperExecutionEngine → PaperExecutionDecision (slippage, cooldown, confidence)
```

### Ключевые модули

| Модуль | Роль |
|--------|------|
| `signals/detectors.py` | 8 детекторов: velocity, queue_imbalance, microprice, wall_pull, major_drop, full_remove, absorption, resilience. Возвращает `DetectorState` с агрегатом `detector_bias` |
| `features/state.py` | Бакетизирует дистанцию (`at_open|near|far|stretched`) и время (`early|mid|late|final`), собирает `RoundFeatures` |
| `models/baseline.py` | Сигмоид-формула из признаков Binance + детекторов + временного множителя. Классифицирует эдж по тирам через `tier_calibration_v1.json` |
| `strategy/entry_policy.py` | JSON-whitelist: каждое правило маппит `(time_bucket, distance_bucket)` → разрешённые тиры |
| `strategy/guards.py` | Жёсткие ограничения: basis_bps, свежесть котировок, ликвидность, спред, минимальное оставшееся время |
| `execution/paper.py` | Симуляция исполнения: slippage, cooldown, порог уверенности |
| `rounds/manager.py` | Округляет timestamp до 5м-границы, отслеживает open_price раунда, резолвит исходы |
| `pipelines/live.py` | `LivePaperRunner` — главный цикл оркестрации для живой бумажной торговли |
| `analytics/simulator.py` | `RoundSimulator` — синтетическая симуляция на сгенерированных данных |
| `connectors/binance/client.py` | REST: глубина стакана, недавние сделки, 1м-свечи |
| `connectors/polymarket/client.py` | Gamma + CLOB API; ищет маркеты по slug-шаблону `btc-updown-5m-{epoch}` |

### Конфигурационные файлы (`configs/`)

- `entry_policy_v2.json` — Активная политика входа: whitelist `(time_bucket, distance_bucket)` → разрешённые тиры. `allowed_tiers: []` = входы запрещены для этой комбинации.
- `basis_guards_v1.json` — Пороги гардов: `max_basis_bps: 15`, `min_book_liquidity: 150`, `max_spread_bps: 650`, `min_entry_t_left_seconds: 20`, `no_entry_last_seconds: 10`
- `paper_execution_v1.json` — Исполнение: `cooldown_seconds: 30`, `max_slippage_bps: 150`, `min_entry_confidence: 0.55`
- `tier_calibration_v1.json` — Пороги эджа: medium ≥8%, strong ≥18%, very_strong ≥30%
- `pm_market_registry.json` — Ключ маркета `btc_updown_5m` с динамическим slug-шаблоном

### Доменные типы (`domain/`)

- `BinanceSignalSnapshot` — mid_price, velocity, queue_imbalance, microprice_delta, volatility, стакан
- `PolymarketQuote` — yes_ask, no_ask, yes_bid, no_bid, timestamp
- `MarketRound` — round_start_epoch, open_price, time_left_seconds
- `RoundPrediction` — p_up_total, p_down_total, signal_tier (weak|medium|strong|very_strong)
- `TradingSignal` — составной сигнал для решения об входе

### Директории данных

- `data/raw/live/` — Захваченные живые снапшоты (JSONL)
- `data/logs/` — JSONL-логи live loop, состояние observability, кандидаты на redeem
- `docs/stages/` — Документация по этапам разработки (писать сюда после завершения этапа)
- `docs/reports/` — Сгенерированные аналитические отчёты

## Заметки по разработке

- **Python 3.11+**; пакет устанавливается в editable-режиме; для скриптов нужен `PYTHONPATH=./src`
- **Стратегия веток**: `dev` — разработка + документация этапов; `main` — чистый код для VPS
- **Документация этапов**: после завершения этапа писать в `docs/stages/stage_XX_*.md`
- **Деплой на VPS**: вручную через SSH + git clone (см. `docs/VPS_QUICKSTART.md`)
- **Настройка стратегии**: только через JSON в `configs/`, без правки кода. `allowed_tiers: []` = вход в этот bucket полностью запрещён.
- **Текущий маркет**: `btc_updown_5m` — slug ищется динамически через Gamma API по шаблону `btc-updown-5m-{round_start_epoch}`
