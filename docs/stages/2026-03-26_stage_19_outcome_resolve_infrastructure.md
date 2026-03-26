# Stage 19A — Outcome Resolve Infrastructure

## Scope

Построение post-hoc pipeline для восстановления исходов раундов (UP/DOWN/FLAT) по историческим
данным Binance, без изменения live loop.

Данные: те же объединённые VPS прогоны (2368 live rows), что использовались в Stage 18:
- [live_paper_loop_20260325T110301Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260325T110301Z.jsonl) (568 rows)
- [live_paper_loop_20260325T184955Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260325T184955Z.jsonl) (1800 rows)

Выход:
- [resolved_decisions_20260326T093539Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/resolved_decisions_20260326T093539Z.jsonl) (2368 rows)

---

## Added

- [scripts/resolve_live_paper_outcomes.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/resolve_live_paper_outcomes.py)

Принимает один или несколько JSONL файлов, для каждого уникального `round_id` вытаскивает
Binance 5m kline, вычисляет winner и добавляет поля к каждой строке.

---

## Pipeline Design

### Почему post-hoc, а не live

- Не трогает stateful live loop — никакой новой точки отказа.
- Можно пересчитать все уже накопленные JSONL задним числом.
- Отлаживается изолированно от сигнального пайплайна.

### Алгоритм

1. Из JSONL: `round_id`, `round_open_price`, `action`.
2. Для каждого уникального `round_id` — `parse_round_start()` парсит timestamp из ID
   (`btc_updown_5m:20260325T110000Z` → UTC datetime).
3. Запрос `GET /api/v3/klines?symbol=BTCUSDT&interval=5m&startTime=...&limit=1` —
   возвращает close price 5-минутной свечи раунда.
4. `compute_winner(open_price, close_price)`:
   - `move_pct > 0.02%` → UP
   - `move_pct < -0.02%` → DOWN
   - иначе → FLAT
5. `enrich_rows()` добавляет к каждой строке:
   - `round_close_price`
   - `round_winner` (UP/DOWN/FLAT/UNKNOWN)
   - `action_correct` (bool, None если FLAT/UNKNOWN)
   - `resolve_status` (ok/no_data/fetch_error)

### Выходная схема (все оригинальные поля сохраняются)

| поле | тип | описание |
|------|-----|----------|
| `round_close_price` | float | BTC/USDT цена на закрытии раунда |
| `round_winner` | str | UP / DOWN / FLAT |
| `action_correct` | bool\|None | True если action совпадает с winner (None для FLAT) |
| `resolve_status` | str | ok / fetch_error / no_data |

---

## Run Results

```
Loading rows from 2 file(s)...
  total rows: 2368, live rows: 2368
  unique rounds to resolve: 189
  estimated time: ~47s

Resolving round outcomes via Binance klines...
  [1/189] ... [189/189] ...

Resolve summary: ok=189/189  UP=76  DOWN=83  FLAT=30  UNKNOWN=0

Enriching decision rows...
Output: data/logs/resolved_decisions_20260326T093539Z.jsonl
  rows written: 2368
  resolvable rounds (ok): 189/189
```

### Ключевые цифры

| метрика | значение |
|---------|----------|
| total live rows | 2368 |
| unique rounds | 189 |
| resolved ok | 189 / 189 (100%) |
| UP | 76 (40.2%) |
| DOWN | 83 (43.9%) |
| FLAT | 30 (15.9%) |
| UNKNOWN | 0 |

Все 189 раундов разрешены успешно. Биnaрное соотношение UP/DOWN (76/83) близко к 50/50,
что соответствует ожиданиям для случайного рынка. 15.9% раундов закрылись FLAT (<0.02% движения).

---

## Two-Level Validation Design (для Stage 20)

По замечанию из Stage 19 Lardio: нельзя делать вывод "tier X лучше tier Y" только по
`allowed_entries` — это selection bias от whitelist-policy (94% very_strong по определению).

Поэтому в Stage 20 (`analyze_outcome_edge.py`) будут два независимых уровня:

### Уровень 1 — Signal edge on all decision rows
- Все live rows (или все `should_enter = true`)
- Показывает: есть ли edge у самого сигнала независимо от policy
- Winrate по: signal_tier, time_bucket × distance_bucket

### Уровень 2 — Execution-aware edge on allowed entries
- Только `policy_allowed` / `allowed_entries`
- Показывает: что реально остаётся после policy и execution guards
- Те же разбивки

Оба ответа нужны, но это разные вопросы.

---

## Next Steps

**Stage 20** — `scripts/analyze_outcome_edge.py`:
- winrate by `signal_tier`
- winrate by `time_bucket × distance_bucket`
- отдельно: all should_enter / policy_allowed / allowed_entries
- input: `data/logs/resolved_decisions_20260326T093539Z.jsonl`
