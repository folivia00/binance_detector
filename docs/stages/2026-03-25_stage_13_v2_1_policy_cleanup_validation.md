# Stage 13 V2.1 Policy Cleanup Validation

## Scope

Этот этап фиксирует первый длинный live-paper прогон после перехода на active whitelist-policy:

- [entry_policy_v2.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/entry_policy_v2.json)

Сравнение шло против предыдущего post-calibration baseline run:

- before: [live_paper_loop_20260324T174047Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260324T174047Z.jsonl)
- after: [live_paper_loop_20260325T045104Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260325T045104Z.jsonl)

Compare report:

- [live_paper_loop_compare_20260325T094318Z.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/reports/live_paper_loop_compare_20260325T094318Z.md)

## What Changed

### Policy noise dropped sharply

Главный результат policy cleanup:

- `policy_allowed`: `1379 -> 229`
- `policy_allowed_rate`: `76.61% -> 12.72%`

То есть whitelist-policy действительно перестала пускать в работу почти все заведомо шумные bucket'ы.

### Allowed entries fell only moderately

- `allowed_entries`: `107 -> 88`
- `allowed_entry_rate`: `5.94% -> 4.89%`

Это означает, что policy noise был срезан гораздо сильнее, чем объём реально проходящих входов.

### Execution bottlenecks remain dominant

Даже после policy cleanup PM execution всё ещё режет большинство решений:

- `spread_too_wide`: `1439 -> 1383`
- `slippage_too_high`: `1568 -> 1557`

Иными словами, policy cleanup улучшил селективность, но не решил главную рыночную проблему исполнения.

### Allowed buckets became cleaner

После cleanup разрешённые входы концентрируются почти только в ожидаемых whitelist buckets:

- `late|stretched`: `41`
- `mid|stretched`: `21`
- `late|far`: `20`
- `final|far`: `4`
- `final|near`: `2`

`early|stretched` в этом прогоне не дал ни одного actual entry, хотя в policy всё ещё разрешён.

## Data Quality Note

Это важное замечание по самому прогону:

- `live_ratio`: `99.94% -> 97.44%`
- non-live rows: `46`

Основная причина:

- `URLError: <urlopen error timed out>` — `44` случаев

Это не должно загрязнять analytics, потому что demo fallback rows уже пропускаются как `demo_fallback_skip`, но это ухудшает integrity длинного live-paper run и должно учитываться при дальнейших выводах.

## Interpretation

По roadmap policy cleanup можно считать успешным:

- селективность policy выросла сильно;
- allowed entries просели умеренно;
- решение о входе стало чище и ближе к реально исполнимым bucket'ам.

Но следующий bottleneck теперь виден ещё яснее:

- не `tier calibration`;
- не permissive policy;
- а PM execution environment и устойчивость live market-data loop.

## Next Step

Следующий практический шаг:

1. не трогать tiers повторно без необходимости;
2. прицельно смотреть `basis_guards_v1.json` и execution-side filters;
3. отдельно решить, нужен ли сетевой hardening Binance fetch loop из-за серии timeout fallback'ов.
