# Stage 11 V2.1 Post-Calibration Compare

## Scope

Этот этап фиксирует первый нормальный before/after compare после `M8.1 Configurable Tier Calibration`.

Сравнивались:

- baseline long run: [live_paper_loop_20260324T112810Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260324T112810Z.jsonl)
- recalibrated run: [live_paper_loop_20260324T174047Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260324T174047Z.jsonl)

Markdown compare report:

- [live_paper_loop_compare_20260325T043336Z.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/reports/live_paper_loop_compare_20260325T043336Z.md)

## Key Findings

### Tier saturation improved

Главная цель milestone выполнена:

- `very_strong_share`: `68.07% -> 46.56%`
- `strong_share`: `13.66% -> 23.39%`
- `medium_share`: `11.26% -> 16.22%`
- `weak_share`: `7.02% -> 13.83%`

Это означает, что tier distribution стала заметно менее схлопнутой наверх и closer to usable decision tiers.

### Policy became less permissive

- `policy_allowed`: `2046 / 2380 -> 1379 / 1800`
- `policy_allowed_rate`: `85.97% -> 76.61%`
- `allowed_entries`: `171 -> 107`
- `allowed_entry_rate`: `7.18% -> 5.94%`

Это ожидаемо: после пересборки tiers policy получила более селективный поток сигналов.

### Execution remains the main bottleneck

Execution-side ограничения почти не улучшились:

- `spread_too_wide_rate`: `78.91% -> 79.94%`
- `slippage_too_high_rate`: `86.26% -> 87.11%`

То есть calibration улучшила структуру сигналов, но не изменила рыночную пригодность PM execution environment.

### Decision concentration changed, but not radically

Разрешённые входы всё ещё концентрируются в `late|stretched`, но слабее, чем раньше:

- `late|stretched allowed share`: `60.82% -> 47.66%`

При этом вырос вклад других bucket'ов:

- `late|far`: `11.11% -> 17.76%`
- `final|far`: `5.26% -> 9.35%`
- `early|stretched`: `0.00% -> 4.67%`

Это уже лучше для аналитики: решения меньше завязаны на один перегретый bucket.

## Interpretation

По roadmap это хороший результат:

- calibration phase действительно имела смысл;
- насыщение `very_strong` больше не мешает оценивать tiers;
- compare now supports policy retuning on cleaner live-paper data.

Но важный operational вывод остаётся прежним:

- главный limiter стратегии сейчас не policy itself;
- главный limiter — execution feasibility на PM book.

## Next Step

Теперь можно переходить к следующему шагу roadmap уже без слепого retuning:

1. пересмотреть `entry_policy_v1.json` на основе нового before/after compare;
2. отдельно оценить, какие `time × distance × tier` зоны вообще имеют шанс на исполнение;
3. не пытаться "лечить" policy там, где основной blocker остаётся `spread_too_wide` или `slippage_too_high`.
