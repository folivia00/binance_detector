# Stage 14 Execution Telemetry And Retry Hardening

## Scope

Этот этап закрывает следующий практический разрыв после policy cleanup:

- раньше live-paper loop показывал только `block reasons`;
- но для execution/basis retuning не хватало самих чисел `spread`, `slippage`, `quote_age`, `basis`;
- long runs также страдали от Binance timeout fallback'ов без retry.

## Added

### Paper execution config became explicit

Добавлен config:

- [paper_execution_v1.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/paper_execution_v1.json)

И путь к нему в:

- [settings.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/config/settings.py)

Теперь active paper execution thresholds грузятся из конфига, а не только из hardcoded defaults.

Это применяется в:

- [live.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/pipelines/live.py)
- [run_simulation.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_simulation.py)
- [export_simulation_report.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/export_simulation_report.py)
- [run_paper_from_capture.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_paper_from_capture.py)

### Live-paper rows now carry execution telemetry

В [signals.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/domain/signals.py) и [live.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/pipelines/live.py) добавлены поля:

- `basis_bps`
- `pm_quote_age_seconds`
- `pm_book_liquidity`
- `pm_spread_bps`
- `expected_slippage_bps`

Они уже пишутся в JSONL через:

- [run_live_paper_loop.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_live_paper_loop.py)

### Reporting now shows the actual execution environment

В [live_loop_reporting.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/analytics/live_loop_reporting.py) добавлены:

- `mean_basis_bps`
- `p95_abs_basis_bps`
- `mean_pm_spread_bps`
- `p95_pm_spread_bps`
- `mean_expected_slippage_bps`
- `p95_expected_slippage_bps`
- `mean_pm_quote_age_seconds`
- `p95_pm_quote_age_seconds`

Теперь следующий long-run report пригоден не только для подсчёта blockers, но и для калибровки самих execution thresholds.

### Binance fetch loop became less fragile

В [client.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/connectors/binance/client.py) добавлен консервативный retry/backoff на REST fetch:

- `max_retries = 2`
- `retry_backoff_seconds = 0.4`

Это должно уменьшить число demo fallback rows в длинных live-paper сериях без перехода к агрессивной retry logic.

## Validation

Проверка прошла:

- unit tests green;
- короткий smoke-loop выпустил JSONL с новыми telemetry fields:
  [live_paper_loop_20260325T095231Z.jsonl](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/data/logs/live_paper_loop_20260325T095231Z.jsonl)
- analyzer выпустил markdown-report с execution telemetry:
  [live_paper_loop_report_20260325T095256Z.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/reports/live_paper_loop_report_20260325T095256Z.md)

## Key Observation

Даже короткий smoke-loop уже показал, что execution environment может быть экстремально плохим:

- `mean_pm_spread_bps` > `13000`
- `mean_expected_slippage_bps` > `13000`

Это ещё не основание немедленно менять thresholds, но уже подтверждает, что следующий этап retuning должен опираться на telemetry, а не только на reason counts.

## Next Step

Следующий шаг по roadmap:

1. прогнать новую длинную live-paper серию с enriched telemetry;
2. выпустить compare report;
3. принимать решение по `basis_guards_v1.json` и `paper_execution_v1.json` уже по фактическим `spread/slippage/quote_age` распределениям.
