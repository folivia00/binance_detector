# Stage 17 VPS Cadence Validation And Compare

## Scope

Этот этап фиксирует результаты первого полного VPS-прогона после Stage 16 (VPS Fetch Parallelism),
проводит сравнение с предыдущим медленным прогоном и закрывает вопрос задержки на VPS.

---

## Прогоны

| Файл | Итераций | Длительность | Cadence | live_ratio |
|------|----------|-------------|---------|------------|
| `live_paper_loop_20260325T110301Z.jsonl` (до фикса) | 568 | ~7 ч | **~45 s/tick** | 100% |
| `live_paper_loop_20260325T184955Z.jsonl` (после фикса) | 1800 | 8.91 ч | **17.8 s/tick** | 100% |

Compare report:
- [live_paper_loop_compare_20260326T083708Z.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/reports/live_paper_loop_compare_20260326T083708Z.md)

---

## Cadence: закрыт

| Метрика | До (Stage 16) | После |
|---------|--------------|-------|
| s/tick | 45.0 | **17.8** |
| Улучшение | — | **2.52×** |
| live_ratio | 100% | **100%** |
| pm_quote_age (mean) | 0.21 s | **0.04 s** |

Параллельный fetch (Binance 3 запроса || PM 2 запроса + token cache) дал ожидаемое
ускорение. PM quote age сократился в 5 раз — котировки теперь практически свежие.

---

## Compare: ключевые числа

| Метрика | Before | After | Динамика |
|---------|--------|-------|----------|
| `total_evaluations` | 568 | 1800 | полный прогон ✅ |
| `completed_rounds` | 79 | **106** | |
| `live_ratio` | 100% | **100%** | стабильно |
| `very_strong_share` | 48.42% | **45.44%** | ↓ медленное снижение |
| `mean_pm_spread_bps` | 5 389 | **5 429** | ≈ стабильно |
| `p95_pm_spread_bps` | 19 208 | **17 358** | ↓ хвост улучшился |
| `mean_expected_slippage_bps` | 4 544 | **5 052** | ≈ стабильно |
| `allowed_entries` | 57 (10.0%) | **87 (4.8%)** | пропорция ↓ |
| `spread_too_wide` rate | 73.1% | **81.9%** | чуть хуже |
| `policy_allowed` rate | 18.5% | **12.6%** | whitelist работает |

---

## Что подтверждено

### Execution bottleneck — рыночный, не кодовый

По двум полным прогонам:

- `mean_pm_spread_bps` стабильно ~5 400 bps (~54% от цены токена)
- `max_spread_bps: 650` в `basis_guards_v1.json` режет **~82% тиков**
- 87 allowed entries за 1800 итераций = **4.8% entry rate**

Это структурная характеристика PM BTC 5m рынка, а не следствие ошибок в коде или калибровке.

### Tier calibration стабилизировалась

`very_strong_share`: 67.88% (Stage 08) → 46.56% → 40.00% → 48.42% → **45.44%**

Значение стабилизировалось в диапазоне 40–48%. Дальнейшая агрессивная
калибровка tier thresholds без данных о реальном PnL нецелесообразна.

### Policy whitelist работает корректно

`policy_allowed_rate`: 76.61% → 12.72% → 12.6% — стабильно после Stage 12.
Whitelist верно отсекает неисполнимые bucket'ы.

---

## Статус roadmap

| Блок | Статус |
|------|--------|
| Tier calibration | ✅ завершён |
| Policy cleanup (whitelist) | ✅ завершён |
| Execution telemetry (Stage 14) | ✅ завершён |
| VPS cadence fix (Stage 16) | ✅ завершён |
| VPS validation compare (Stage 17) | ✅ **этот этап** |
| Execution thresholds decision | 🟡 **следующий шаг** |

---

## Открытые вопросы и предложения

### 1. Execution threshold decision (приоритет: высокий)

По данным двух стабильных прогонов нужно принять решение по `basis_guards_v1.json`
и `paper_execution_v1.json`. Два варианта:

**Вариант A — оставить `max_spread_bps: 650`:**
- Entry rate остаётся ~4–5%
- Входы только в окна реальной ликвидности
- Консервативно, но честно — не платим огромный spread

**Вариант B — поднять `max_spread_bps` до ~3 000–5 000:**
- Entry rate вырастет до ~20–30%
- Но при среднем spread 5 400 bps исполнение будет дорогим
- Имеет смысл только если модель имеет edge > spread cost

Рекомендация: не трогать guard thresholds до получения реальных PnL данных.
Entry rate 4–5% при 17.8s cadence = ~87 potential entries за 9 часов — это рабочее число.

### 2. very_strong_share 45% (приоритет: низкий)

Снижается медленно (67% → 45%). Без реального PnL неясно,
является ли это проблемой. Tier threshold можно поднять
(`very_strong_min_edge: 0.30 → 0.40`) если нужна более жёсткая фильтрация.

### 3. Переход к реальному исполнению (приоритет: по решению)

Scaffold существует (`execution/paper.py`, `execution/broker.py`).
Следующий практический шаг по P1 roadmap:
- Реальное размещение ордеров через Polymarket API
- Broker hardening
- Redemption service

Блокер: нужны реальный кошелёк и ключи.

### 4. Time-of-day анализ spread (приоритет: средний)

`p95_pm_spread_bps = 17 000–19 000` указывает на экстремальные моменты.
Если добавить в отчёт разбивку по часу UTC, можно выявить окна
с системно лучшей ликвидностью и добавить time-of-day фильтр в entry policy.
