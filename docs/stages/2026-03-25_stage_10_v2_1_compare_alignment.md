# Stage 10 V2.1 Compare Alignment

## Scope

Этот этап фиксирует сверку текущей реализации с roadmap-файлом `polymarket_5_m_roadmap_v_2_1_tier_calibration.md`.

Проверка показала:

- config-driven tier thresholds уже вынесены в конфиг;
- live-paper rows уже пишут `raw_score`, `probability_edge`, `calibration_version`;
- compare tooling уже было добавлено;
- но compare report ещё не покрывал весь набор before/after-срезов, который требуется в milestone `M8.1`.

## Gap Found

До этого compare report был слишком узким и показывал только несколько агрегированных метрик:

- `very_strong_share`;
- `allowed_entries`;
- `policy_allowed`;
- `spread_too_wide`;
- `slippage_too_high`.

Этого недостаточно для roadmap v2.1, потому что после calibration нужно сравнивать не только summary-метрики, но и структуру решений:

- distribution tiers до/после;
- allowed entries по `time × distance`;
- policy / guard / paper blockers до/после;
- coverage по `time × distance`;
- execution bottlenecks по проблемным bucket'ам.

## Added

### Expanded live-loop analysis

В [live_loop_reporting.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/analytics/live_loop_reporting.py) добавлены новые срезы:

- `evaluations_by_bucket`;
- `guard_blocked_by_bucket`;
- `paper_blocked_by_bucket`;
- `spread_blocked_by_bucket`;
- `slippage_blocked_by_bucket`.

Это позволяет анализировать не только общий объём блокировок, но и их концентрацию по `time_bucket|distance_bucket`.

### Compare report now matches the milestone

Compare report теперь включает отдельные разделы:

- `Tier Distribution`;
- `Allowed Entry Buckets`;
- `Policy Blockers`;
- `Guard Blockers`;
- `Paper Blockers`;
- `Time x Distance Coverage`;
- `Execution Bottleneck Buckets` для `spread_too_wide` и `slippage_too_high`.

### Test coverage

Добавлен unit test:

- [test_live_loop_reporting.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/tests/unit/test_live_loop_reporting.py)

Тест проверяет, что compare markdown действительно содержит ключевые секции roadmap v2.1.

## Result

После этого этапа milestone `M8.1 Configurable Tier Calibration` закрыт лучше и точнее:

- calibration configurable;
- telemetry по score уже есть;
- before/after comparison теперь пригоден для реального decision-making;
- policy retuning по-прежнему не нужно делать вслепую до повторного long-run.

## Next Step

Следующий рабочий шаг по roadmap остаётся прежним:

1. прогнать длинную live-paper серию с текущим calibration config;
2. выпустить compare report против pre-calibration baseline run;
3. только потом переходить к `entry_policy_v1.json` и `basis_guards_v1.json`.
