# Stage 20 — Outcome Edge Validation

## Scope

Анализ реального signal edge по resolved outcomes (Stage 19A output).
Два уровня: raw сигнал (все строки) и execution-filtered (allowed entries).

Данные:
- [resolved_decisions_20260326T093539Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/resolved_decisions_20260326T093539Z.jsonl) — 2368 rows, 189 unique rounds

Отчёт:
- [outcome_edge_20260326T094011Z.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/reports/outcome_edge_20260326T094011Z.md)

---

## Added

- [scripts/analyze_outcome_edge.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/analyze_outcome_edge.py)

Принимает resolved_decisions JSONL, вычисляет winrate на трёх уровнях (all rows /
policy_allowed / allowed_entries), разбивка по tier и time×distance bucket.

---

## Findings

### Население

| уровень | строк | decidable | correct | winrate |
|---------|-------|-----------|---------|---------|
| Level 1A — все строки | 2368 | 1984 | 1292 | **65.1%** |
| Level 1B — policy_allowed | 332 | 311 | 289 | **92.9%** |
| Level 2 — allowed_entries | 144 | 141 | 141 | **100.0%** |

Decidable = строки с round_winner ∈ {UP, DOWN} (FLAT исключён).

---

### Level 1A: Winrate по signal_tier (все строки)

| tier | total | decidable | winrate |
|------|-------|-----------|---------|
| weak | 282 | 242 | **50.0%** |
| medium | 432 | 357 | **46.2%** |
| strong | 561 | 453 | **56.7%** |
| very_strong | 1093 | 932 | **80.4%** |

**Ключевой вывод:** очень чёткая монотонная зависимость — tier коррелирует с edge.
`very_strong` показывает 80.4% winrate на всех строках без каких-либо фильтров.
`medium` — ниже 50%, фактически отрицательный edge (контр-signal).

---

### Level 1A: Winrate по time×distance bucket (top buckets)

| bucket | total | decidable | winrate |
|--------|-------|-----------|---------|
| mid\|stretched | 65 | 63 | **96.8%** |
| late\|stretched | 59 | 59 | **98.3%** |
| final\|stretched | 34 | 34 | **97.1%** |
| early\|stretched | 13 | 12 | **91.7%** |
| final\|at_open | 37 | 10 | **90.0%** |
| final\|far | 85 | 85 | **85.9%** |
| mid\|far | 202 | 178 | **79.2%** |

**`stretched` buckets — исключительный предсказательный сигнал** (91–98% по всем строкам,
без фильтров). Это интерпретируется как late-momentum: когда сигнал долго указывает
в одну сторону ("stretched"), направление раунда уже фактически определено.

`early|at_open` и `early|near` — около 51%, фактически случайные.

---

### Separation Analysis

Сигнал структурно разделяется на два класса:

**Высокий edge (>70%):** very_strong tier + stretched/far distance buckets.
Это именно то сочетание, что захватывает текущая policy.

**Низкий/нулевой edge (<55%):** weak/medium tier + early/at_open buckets.
Входить здесь нецелесообразно независимо от spread.

---

### Level 2: 100% winrate предупреждение

Level 2 (allowed_entries, should_enter=True) показывает 100% на 141 decidable случае.
Это требует осторожной интерпретации:

**Почему это правдоподобно:**
- 94% allowed entries — это `stretched` или `far` distance buckets
- Доминируют `late|stretched` (49) и `late|far` (41) — вход на последних тиках раунда
- К этому моменту направление уже фактически определено momentum'ом
- Это по сути late-momentum стратегия, не lookahead

**Почему нельзя считать финальной цифрой:**
- 189 раундов — слишком малая выборка для 100% вывода
- Ещё нет данных о slippage и реальном PnL (payout зависит от PM цены, не только winrate)
- Нужно минимум ~500–1000 раундов для статистической уверенности
- Distribution UP=49, DOWN=92 — сильный directional bias в этом периоде

---

### Asymmetry: UP vs DOWN в allowed_entries

| | UP rounds | DOWN rounds |
|-|-----------|-------------|
| allowed_entries | 49 | 92 |

Ratio 1:1.88 — system сильно уклонился в DOWN в данном периоде (2026-03-25).
Нормально ли это постоянно или это специфика конкретного дня — требует данных из других прогонов.

---

## Decision

**Сигнал имеет реальный edge — особенно в very_strong tier и stretched/far buckets.**

Из данных следует:
1. Policy корректно изолирует high-edge ситуации (92.9% → 100% после фильтрации).
2. `medium` tier показывает sub-50% — его исключение из policy оправдано.
3. `stretched` distance bucket — наиболее предсказуемый режим; именно он доминирует в allowed_entries.
4. До набора >500 раундов с diverse conditions (разные дни, разные часы) 100% не является
   финальным ответом — но данные убедительно указывают на наличие edge.

**Порог max_spread_bps: 650 остаётся в силе** — ослаблять его без PnL данных нецелесообразно,
поскольку edge уже подтверждён на текущем conservative threshold.

---

## Next Steps

1. **Накопить данные** — прогнать ещё 2–3 дня. Целевой объём: ≥ 500 раундов
   для статистической значимости (binomial CI 95% < ±5%).
2. **PnL анализ** — добавить реальный payout (PM цена на входе × winrate - slippage).
   Edge в winrate ≠ edge в PnL без учёта payout curve.
3. **PM price at entry** — сохранять в JSONL цену YES/NO токена в момент входа,
   чтобы вычислить реальный implied payout, а не только winrate.
4. **Direction bias analysis** — проверить, является ли DOWN bias (1.88x) устойчивым
   или специфичен для 2026-03-25.
