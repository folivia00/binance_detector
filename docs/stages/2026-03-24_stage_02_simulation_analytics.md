# Stage 02 Simulation Analytics

## Scope

Этот этап продолжает roadmap после foundation-слоя и закрывает ближайший практический шаг:

- собрать таблицы `time × distance`;
- посмотреть `tier usefulness`;
- выделить плохие зоны для следующего витка `entry policy`.

## Added Elements

- markdown reporting helpers: [reporting.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/analytics/reporting.py)
- экспорт отчёта симуляции: [export_simulation_report.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/export_simulation_report.py)
- каталог документации и stage-документов: [docs/README.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/README.md)

## What The Report Shows

Отчёт теперь строит:

- общие метрики по симуляции;
- таблицу `time × distance`;
- breakdown по `candidate_entry`, `actual_entry`, `blocked_entry`, `reverse_exit`;
- usefulness по `medium / strong / very_strong`;
- причины блокировки;
- late damage zones, если они реально есть в данных.

## Current Findings On Synthetic Run

- входы почти полностью концентрируются в `early|at_open`;
- `mid|at_open` встречается редко и на текущей synthetic выборке выглядит лучше, но выборка слишком маленькая;
- все tiers пока отрицательные по `pnl`, несмотря на рост `avg_edge`;
- reverse-exit уже даёт положительный `saved_loss`, значит слой аналитики работает и его можно дальше калибровать;
- late damage zones не выявлены, потому что текущая policy почти не допускает поздние входы.

## Why This Matters

Теперь policy можно менять не вслепую, а по таблицам и markdown-отчётам. Это важный контрольный этап перед усилением `M2` Binance signal core и перед более жёсткой настройкой `M5`.

## Next Step

Следующий рабочий этап:

- усилить synthetic/offline signal core так, чтобы были не только `at_open` входы;
- затем на новых бакетах пересобрать policy-конфиг;
- после этого переходить к реальным Binance market-data bindings.
