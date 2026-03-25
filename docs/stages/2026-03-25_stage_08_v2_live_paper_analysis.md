# Stage 08 V2 Live Paper Analysis

## Scope

Этот этап переводит длинный `live_paper_loop` прогон из сырых JSONL строк в нормальную round-level аналитическую отчётность.

## Added Elements

- live loop analyzer: [analyze_live_paper_loop.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/analyze_live_paper_loop.py)
- reporting module: [live_loop_reporting.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/analytics/live_loop_reporting.py)

## What The Report Captures

- total evaluations;
- observed / completed round count;
- effective cadence;
- live vs demo snapshot ratio;
- fallback reasons;
- tier saturation;
- policy / guard / paper blockers;
- allowed entry buckets;
- preliminary findings по execution bottlenecks.

## Critical Fix Included

Во время этого этапа был найден и исправлен важный риск:

- demo fallback больше не должен участвовать как нормальный signal tick в stateful live runner;
- такие тики теперь помечаются как `demo_fallback_skip`, чтобы не загрязнять round analytics.

## Why This Matters

Теперь проект можно вести по `roadmap v2` уже на базе реальных длинных live-paper серий, а не по ощущениям от сырых логов.

## Next Step

Следующий шаг:

- выпускать markdown report после каждого большого live-paper прогона;
- на основе этих отчётов калибровать tier thresholds и execution guards;
- затем повторять серию и сравнивать distribution между прогонами.
