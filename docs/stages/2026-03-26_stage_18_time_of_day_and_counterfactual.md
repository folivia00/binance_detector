# Stage 18 Time-of-Day And Counterfactual Threshold Analysis

## Scope

Этот этап реализует два аналитических инструмента, определённых в Stage 17 как приоритетные
шаги перед принятием решения по execution thresholds:

1. **Time-of-day spread/liquidity report** — почасовая разбивка PM spread и ликвидности по UTC.
2. **Counterfactual threshold relaxation** — симуляция входов при ослабленных `max_spread_bps`.

Данные: объединённые прогоны VPS (2368 live rows):
- [live_paper_loop_20260325T110301Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260325T110301Z.jsonl) (568 rows)
- [live_paper_loop_20260325T184955Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260325T184955Z.jsonl) (1800 rows)

Отчёты:
- [time_of_day_report_20260326T090429Z.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/reports/time_of_day_report_20260326T090429Z.md)
- [counterfactual_thresholds_20260326T090431Z.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/reports/counterfactual_thresholds_20260326T090431Z.md)

---

## Added

- [scripts/analyze_time_of_day.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/analyze_time_of_day.py)
- [scripts/analyze_counterfactual_thresholds.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/analyze_counterfactual_thresholds.py)

Оба скрипта принимают один или несколько JSONL файлов, пишут markdown в `docs/reports/`.

---

## Findings: Time-of-Day

### Обзор

| Метрика | Значение |
|---------|----------|
| overall_mean_pm_spread_bps | 5 420 |
| overall_**p50**_pm_spread_bps | **3 855** |
| overall_p95_pm_spread_bps | 17 714 |

**Важно:** медиана (3855) заметно ниже среднего (5420). Рынок не равномерно плохой — он имеет
тяжёлый хвост из экстремально широких spread-моментов, которые тянут среднее вверх.

### Лучшие часы по ликвидности

| hour_utc | rows | mean_spread | p50_spread | stw_rate | allowed |
|----------|------|-------------|------------|----------|---------|
| 18:00 | 33 | 3 354 | **518** | **48.5%** | 8 |
| 15:00 | 86 | 4 267 | 3 713 | 72.1% | **15** |
| 03:00 | 152 | 4 898 | 3 294 | 77.6% | 9 |
| 02:00 | 202 | 5 014 | 4 000 | 81.7% | 14 |

**18:00 UTC** — единственный час с `p50 < 1000 bps` и `stw_rate < 50%`. Но выборка мала (33 строки).

**15:00 UTC** — US pre-market session, наибольшее число `allowed_entries` (15) при разумной выборке.

### Худшие часы

| hour_utc | mean_spread | stw_rate |
|----------|-------------|----------|
| 14:00 | 6 256 | 82.4% |
| 01:00 | 6 098 | 90.6% |
| 00:00 | 5 988 | 82.7% |

01:00 UTC — самый плохой (stw_rate 90.6%). Соответствует ночному азиатскому затишью.

### Вывод по time-of-day

Рынок PM BTC 5m **структурно неравномерен** по времени суток. Диапазон 15:00–18:00 UTC
(европейский вечер / US начало сессии) выглядит заметно лучше. Для убедительного вывода
нужно больше данных (текущий coverage: 17 из 24 часов, некоторые с малой выборкой).

---

## Findings: Counterfactual Threshold Relaxation

### Сводная таблица

| max_spread_bps | entries | entry_rate | delta | mean_slip_bps | p95_slip_bps |
|----------------|---------|------------|-------|---------------|--------------|
| **650 (текущий)** | 209 | 8.83% | baseline | **172** | 518 |
| 1 500 | 230 | 9.71% | +21 | 245 | 952 |
| 3 000 | 241 | 10.18% | +32 | 329 | 1 176 |
| 5 000 | 246 | 10.39% | +37 | 395 | 1 758 |
| 10 000 | 249 | 10.52% | +40 | 466 | 2 247 |

### Главное открытие: биmodальность PM spread

Поднятие порога с 650 до 10 000 bps даёт только **+40 входов (+19%)** при росте
mean_slippage в 2.7x (172 → 466 bps).

Это означает: PM spread структурно биmодален.
- Либо спред очень низкий (< 650 bps) — реальная ликвидность есть;
- Либо спред очень высокий (> 5 000 bps) — рынок фактически неликвиден.

Промежуточной зоны (650–5000 bps) с существенным числом тиков почти нет.

### Tier structure при всех порогах

При любом пороге от 650 до 10 000 bps структура тиров одинакова:

| tier | доля |
|------|------|
| weak | 0% |
| medium | 0% |
| strong | 5–8% |
| **very_strong** | **92–94%** |

Whitelist-policy естественно фильтрует к сильным сигналам вне зависимости от spread threshold.

### Вывод по counterfactual

Текущий `max_spread_bps: 650` захватывает **84% всей реальной opportunity** (209/249).
Ослабление до 10 000 даёт ещё 40 входов, но каждый обходится в 2.7x дороже по slippage.
Без данных о фактическом PnL ослабление порога экономически не оправдано.

---

## Decision: Execution Thresholds

По итогам двух анализов:

**Остаёмся на `max_spread_bps: 650` (Вариант A из Stage 17).**

Обоснование:
1. Биmodальность подтверждает, что 650 bps — это не произвольный порог, а граница
   реальной ликвидности PM рынка.
2. Ослабление даёт минимальный прирост (+19%) при существенном росте slippage cost.
3. До получения outcome данных (реальных PnL по исходу раундов) любое ослабление
   было бы необоснованным.

**Дополнительно:**
Следующий прогон запускать в 14:00–18:00 UTC для лучшей выборки в часы с наилучшей ликвидностью.

---

## Next Steps

1. Накопить outcome данные (BTC цена на закрытии раунда vs predicted action) для
   оценки реального signal edge.
2. После получения хотя бы ~200 завершённых раундов с outcomes — сопоставить
   signal_tier / time_bucket с winrate.
3. Только после этого обсуждать live canary.
