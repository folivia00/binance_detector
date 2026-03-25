# Stage 16 VPS Fetch Parallelism

## Scope

Этот этап устраняет главное узкое место, обнаруженное при первом длинном VPS-прогоне:

- ожидаемый cadence: **5 секунд/тик**;
- фактический cadence на VPS: **~45 секунд/тик**;
- причина: 6 последовательных HTTP-запросов с высоким RTT.

## Root Cause

Каждый вызов `evaluate_once()` делал 6 последовательных REST-запросов:

| Шаг | Запрос | Типичный RTT на VPS |
|-----|--------|-------------------|
| Binance 1 | `/api/v3/depth` | ~7s |
| Binance 2 | `/api/v3/trades` | ~7s |
| Binance 3 | `/api/v3/klines` | ~7s |
| PM 1 | `gamma-api /markets/slug/{slug}` | ~7s |
| PM 2 | `clob /book?token_id=yes` | ~7s |
| PM 3 | `clob /book?token_id=no` | ~7s |

**Итого: ~42s + sleep(5) = ~47s/тик**

Проблема не в timeouts (live_ratio был 100%) — запросы успевали, но суммарно давали 45s.

## Changes

### 1. Binance: параллельный fetch 3 запросов

Файл: [client.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/connectors/binance/client.py)

Вместо последовательного `depth → trades → klines` используется `ThreadPoolExecutor(max_workers=3)`:

```
depth  ──┐
trades ──┼─── parallel → _build_live_snapshot()
klines ──┘
```

Экономия: ~14s (2 запроса из 3 идут параллельно).

### 2. PolymarketClient: кэш token IDs + параллельный book fetch

Файл: [client.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/connectors/polymarket/client.py)

**Token ID cache:**

- `_token_cache: dict[str, tuple[str, str]]` — кэш по `resolved_slug`.
- Slug меняется раз в 5 минут (привязан к round epoch).
- На большинстве тиков slug lookup пропускается → экономия ~7s/тик.
- При смене раунда — одна единственная cache miss, потом снова hit.

**Параллельный book fetch:**

```
yes_book ──┐
           ├─── parallel → _build_quote()
no_book  ──┘
```

Экономия: ~7s (2 book-запроса идут параллельно вместо последовательно).

### 3. live.py: параллельный Binance || PM на верхнем уровне

Файл: [live.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/pipelines/live.py)

```
Binance fetch (3 parallel) ──┐
                              ├─── ThreadPoolExecutor(max_workers=2)
PM fetch (cache + 2 parallel)┘
```

`now_ts` передаётся в `get_quote_for_spec_at` до старта обоих futures.
Это корректно: `floor_to_5m(now_ts)` и `floor_to_5m(snapshot.ts)` будут
одинаковым round boundary в пределах одного тика.

## Expected Cadence Improvement

| Слой | До | После |
|------|-----|-------|
| Binance 3 calls | ~21s | ~7s (parallel) |
| PM slug lookup | ~7s | ~0s (cache hit) |
| PM 2 books | ~14s | ~7s (parallel) |
| Binance \|\| PM | ~35s | ~7s (outer parallel) |
| sleep(5) | +5s | +5s |
| **Итого** | **~47s** | **~12s** |

Целевой cadence 5–10 секунд достигается при RTT ~5-7s до API-серверов.

## Implementation Notes

- Все изменения — stdlib only (`concurrent.futures.ThreadPoolExecutor`).
- Нет новых зависимостей.
- Retry-логика в `BinanceClient._get_json` работает корректно внутри потоков.
- Shared mutable state в `BinanceClient` (`_previous_bid_depth_top` и др.)
  обновляется только в `_build_live_snapshot`, который вызывается
  **после** завершения всех futures. Race condition отсутствует.
- `_token_cache` в `PolymarketClient` — single-threaded (обновляется в потоке PM-future). Race condition отсутствует.

## Validation

Unit tests green — `PYTHONPATH=./src python -m unittest discover -s ./tests/unit -v`

## Next Step

1. Задеплоить на VPS и запустить новый длинный прогон;
2. Проверить `effective_cadence_seconds` в отчёте: цель < 15s;
3. Запустить compare-отчёт против `live_paper_loop_20260325T110301Z.jsonl`;
4. Если cadence в норме — принимать решения по `basis_guards_v1.json`
   на основе `mean_pm_spread_bps` из enriched telemetry.
