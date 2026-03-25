# Stage 12 V2.1 Policy Retuning

## Scope

Этот этап переводит live-paper policy из permissive baseline в более жёсткий whitelist после post-calibration compare.

Основание для retuning:

- [live_paper_loop_compare_20260325T043336Z.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/reports/live_paper_loop_compare_20260325T043336Z.md)
- [2026-03-25_stage_11_v2_1_post_calibration_compare.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/stages/2026-03-25_stage_11_v2_1_post_calibration_compare.md)

## Why The Policy Needed To Change

После calibration tier distribution стала чище, но active policy всё ещё оставалась слишком широкой по отношению к реальным execution conditions.

По recalibrated long-run:

- `policy_allowed_rate` оставался `76.61%`;
- при этом `allowed_entry_rate` был только `5.94%`;
- большинство ранних `near` / `at_open` bucket'ов давали `0` реально исполнимых входов;
- основной execution bottleneck по-прежнему шёл через `spread_too_wide` и `slippage_too_high`.

Это означало, что policy пропускает слишком много зон, которые на практике почти всегда режутся дальше execution layer.

## New Policy Shape

Добавлен новый config:

- [entry_policy_v2.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/entry_policy_v2.json)

Именно он теперь используется по умолчанию через:

- [settings.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/config/settings.py)

Новая policy не строится от широкого default allow. Вместо этого она whitelists только bucket'ы, которые в post-calibration run показали хотя бы ограниченную реальную исполнимость:

- `early|stretched -> very_strong`
- `mid|stretched -> strong, very_strong`
- `late|far -> strong, very_strong`
- `late|stretched -> very_strong`
- `final|near -> very_strong`
- `final|far -> very_strong`

Все остальные bucket'ы по умолчанию заблокированы.

## Expected Effect

На базе уже собранной recalibrated серии такая форма policy должна:

- резко уменьшить `policy_allowed` noise;
- отсечь buckets, которые consistently не дают исполнимых входов;
- почти не потерять реально прошедшие `should_enter` решения из рабочих зон.

Практический смысл этого шага:

- policy теперь ближе к реальному PM execution environment;
- сравнение signal quality и execution bottlenecks станет чище;
- следующий live-paper прогон будет полезнее для basis/guards tuning.

## Validation

Добавлен unit test:

- [test_entry_policy.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/tests/unit/test_entry_policy.py)

Тест проверяет, что active `entry_policy_v2.json` действительно даёт whitelist semantics по ключевым bucket'ам.

## Next Step

Следующий шаг по roadmap:

1. повторить длинный `run_live_paper_loop.py` уже с active `entry_policy_v2.json`;
2. снова выпустить markdown compare report;
3. проверить, насколько снизился `policy_allowed_rate` и как изменились execution bottlenecks после policy cleanup.
