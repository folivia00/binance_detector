# Stage 21 — 500-Round Revalidation + Branch Setup

## Scope

Цели этапа:
1. Набрать ≥500 независимых раундов для подтверждения результатов Stage 20.
2. Разделить git-ветки: `dev` (разработка) и `main` (VPS/production).
3. Верифицировать что числа Stage 20 не случайны — воспроизвести на втором независимом прогоне.

---

## Branch Setup

Создана стратегия двух веток:

| ветка | роль | что хранит |
|-------|------|------------|
| `dev` | разработка | весь код + docs/stages/ + Lardio-заметки + analysis scripts |
| `main` | VPS | только src/, scripts/, config/ — docs/stages/ в .gitignore |

`docs/reports/*.md` — gitignored на обоих ветках (генерируется, не коммитится).
`data/logs/*.jsonl` — gitignored на обоих ветках (передаётся через scp).

Roadmap перемещён из корня в [docs/roadmap/](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/roadmap/).

---

## VPS Run

**Команда запуска:**
```bash
mkdir -p logs && nohup python scripts/run_live_paper_loop.py --iterations 9500 \
  > logs/run_500rounds.log 2>&1 &
```

**Прогон:** Mar 26 10:13 UTC → Mar 27 10:55 UTC (~24.7 часа)

**Причина остановки:** `urllib.error.URLError: Temporary failure in name resolution`
— VPS потерял DNS. Внешняя сетевая ошибка, не баг кода.

**Файл:** `data/logs/live_paper_loop_20260326T101327Z.jsonl`

| метрика | значение |
|---------|----------|
| rows | 4 989 |
| unique rounds | 297 |
| временной диапазон | 2026-03-26 10:13 → 2026-03-27 10:55 UTC |
| BTC диапазон цен | ~66 600 – 69 800 USDT |

---

## Outcome Resolution

```
Resolve summary: ok=297/297  UP=123  DOWN=125  FLAT=49  UNKNOWN=0
```

297/297 раундов resolved успешно через Binance `/api/v3/klines`.
UP/DOWN баланс 123/125 — близко к 50/50, соответствует ожиданиям.

Выходной файл: `data/logs/resolved_decisions_20260328T090615Z.jsonl` (4989 строк)

---

## Edge Validation Results

### Сравнение Stage 20 vs Stage 21

| метрика | Stage 20 (189 раундов) | Stage 21 (297 раундов) | дельта |
|---------|----------------------|----------------------|--------|
| Level 1A winrate | 65.1% | **65.7%** | +0.6% |
| weak tier | 50.0% | 48.8% | −1.2% |
| medium tier | 46.2% | 48.5% | +2.3% |
| strong tier | 56.7% | 56.1% | −0.6% |
| very_strong tier | 80.4% | **80.1%** | −0.3% |
| Level 1B (policy_allowed) | 92.9% | **91.7%** | −1.2% |
| Level 2 (allowed_entries) | 100% / 141 | **100% / 323** | +182 случая |
| mean_slippage_bps | 94 | **94** | 0 |

### Суммарно по обоим прогонам (486 раундов)

| уровень | correct / decidable | winrate |
|---------|---------------------|---------|
| Level 1A | 4030 / 6150 | **65.5%** |
| Level 2 | 464 / 464 | **100.0%** |

### По тирам — Level 1A (оба прогона совместно)

| tier | winrate Stage 20 | winrate Stage 21 | вывод |
|------|-----------------|-----------------|-------|
| weak | 50.0% | 48.8% | случайный |
| medium | 46.2% | 48.5% | sub-50%, исключение из policy оправдано |
| strong | 56.7% | 56.1% | умеренный edge |
| very_strong | 80.4% | 80.1% | **стабильный сильный edge** |

### По bucket — Level 1A, stretched buckets

| bucket | Stage 20 | Stage 21 |
|--------|----------|----------|
| late\|stretched | 98.3% | **100.0%** (149/149) |
| final\|stretched | 97.1% | **100.0%** (96/96) |
| mid\|stretched | 96.8% | 93.8% (135/144) |
| early\|stretched | 91.7% | 91.5% (54/59) |

---

## Key Findings

**Результаты Stage 20 воспроизводятся почти идеально.**

1. **65.5% raw signal winrate** стабильно на 486 раундах — это не шум.
2. **very_strong tier = 80.1–80.4%** — монотонная зависимость tier→edge подтверждена.
3. **stretched + far buckets** — исключительно предсказуемые, 91–100%.
4. **Level 2: 100% на 464 allowed_entries** — на 323 новых случаях результат не изменился.
5. **medium tier** стабильно sub-50% на обоих прогонах — его исключение из policy доказано.

---

## Known Issues

**DNS crash на VPS** — скрипт не перехватывает `URLError` и падает при временном DNS сбое.
Потеряно ~200 потенциальных раундов (~10% прогона).

Два пути решения:
- **A) Retry wrapper** — перехватить `URLError`/`ConnectionError` в `fetch_signal_snapshot` и `get_quote_for_spec_at`, подождать 30с и повторить. Рекомендуется.
- **B) Systemd restart** — настроить на VPS `Restart=on-failure` в unit-файле.

---

## Next Steps

Согласно вердикту Stage 19–20 (Lardio), следующий обязательный рубеж:

**Stage 22 — trade-level PnL validation:**
- Сохранять `pm_price_at_entry` (цену YES/NO токена в момент входа) в JSONL
- Рассчитать implied payout: `1 / pm_price_at_entry`
- Итоговый PnL: `winrate × payout − (1 − winrate) × 1 − slippage_cost`
- Цель: доказать, что edge в winrate конвертируется в положительный PnL
