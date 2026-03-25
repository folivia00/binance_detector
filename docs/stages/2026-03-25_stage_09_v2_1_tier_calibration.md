# Stage 09 V2.1 Tier Calibration

## Scope

Этот этап соответствует `M8.1 Configurable Tier Calibration` как дополнению к roadmap v2.

## Added Elements

### Configurable Tier Thresholds

- tier calibration config: [tier_calibration_v1.json](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/configs/tier_calibration_v1.json)
- loader: [tier_calibration.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/config/tier_calibration.py)

Baseline model теперь берёт thresholds из конфига, а не хардкодит их в коде.

### Raw Score Telemetry

Теперь в live-paper rows попадают:

- `raw_score`
- `probability_edge`
- `calibration_version`

Это позволяет понять, проблема в самой форме score или только в tier thresholds.

### Before / After Comparison

- analyzer теперь умеет строить не только single-run report, но и compare report между двумя live-paper сериями:
  [analyze_live_paper_loop.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/analyze_live_paper_loop.py)

## Goal Of This Milestone

- снизить saturation `very_strong`;
- сделать tier distribution более ступенчатой;
- не трогать scoring logic вслепую;
- сравнивать calibration before/after до policy retuning.

## Next Step

Следующий шаг по roadmap:

- прогнать новую длинную live-paper серию с current calibration config;
- выпустить compare report против baseline run;
- только потом переходить к policy retuning.
