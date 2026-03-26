Да, это точное замечание.
Я бы не называл следующий этап просто “Outcome edge validation”, потому что это звучит как готовый анализ, а по факту сначала нужен отдельный инфраструктурный слой резолва исходов.

Сейчас по roadmap действительно требуется доказать edge на реальных данных, а не только собрать execution/blocker-аналитику.
И Stage 18 как раз упирается в то, что threshold decision уже почти закрыт, а следующий большой вопрос — outcome/PnL, но для этого текущего JSONL недостаточно.

Я бы формулировал это так:

Правильное разбиение следующего этапа
#### Stage 19A — Outcome Resolve Infrastructure

Не “валидация edge”, а именно подготовка данных.

Цель:

научиться для каждого round/event восстановить winner постфактум;
не трогать пока live loop сложной новой логикой;
получить reproducible pipeline: JSONL decisions -> resolved outcomes.

И здесь я согласен: post-hoc resolve — лучший первый вариант.

Почему он лучше:

не лезет в stateful loop;
не добавляет новую точку отказа в live-runner;
можно пересчитать все уже накопленные JSONL задним числом;
проще дебажить отдельно от сигнального пайплайна.
Что должно быть в 19A

### Минимальный pipeline такой:

взять из JSONL:
round_id
round_open_price
timestamp / start_ts / end_ts
signal_tier
time_bucket
distance_bucket
action
should_enter
для каждого round_id определить:
round_close_price
winner = UP / DOWN / FLAT? по вашей принятой логике
сохранить enriched dataset:
resolved_rounds.jsonl или resolved_entries.parquet
с полями:
round_id
open_price
close_price
winner
entry_side
entry_correct
signal_tier
time_bucket
distance_bucket
pm_spread_bps
expected_slippage_bps
Источник outcome

Из двух вариантов я бы тоже выбрал:

сначала отдельный resolve-скрипт по historical Binance candles/trades,
а не немедленное дописывание live loop.

То есть:

Stage 19A: resolve_live_paper_outcomes.py
Stage 19B: уже отчёт outcome_edge_validation.md

Это аккуратнее архитектурно.

Важная тонкость по данным

Твоё минорное замечание на самом деле не минорное, а очень важное:

very_strong 92–94% в allowed entries — это в значительной степени свойство whitelist-policy, а не чистое свойство сигнала. Stage 18 это фактически подтверждает: при любых counterfactual spread thresholds allowed-entries почти целиком состоят из very_strong, потому что policy уже пропускает в основном их.

Отсюда важное следствие:

Нельзя делать вывод “tier X лучше tier Y” только по allowed entries

Потому что:

medium и strong в allowed-flow почти не представлены;
это будет selection bias, созданный policy.

Поэтому outcome-валидацию я бы делил на 2 уровня:

### Уровень 1 — Signal edge on all decision rows

Смотреть outcome по:

всем live rows,
или хотя бы по всем should_enter = true,
независимо от того, пропустила ли их whitelist-policy.

Это даст ответ:

есть ли edge у самого сигнала;
как ведут себя weak / medium / strong / very_strong.
### Уровень 2 — Execution-aware edge on allowed entries

Отдельно смотреть:

только policy_allowed / allowed_entries.

Это даст другой ответ:

что реально остаётся после policy и execution guards.

Оба ответа нужны, но это разные вопросы.

Поэтому я бы переименовал следующий этап

Не в stage_19_outcome_edge_validation.md, а так:

вариант 1
stage_19_outcome_resolve_infrastructure.md

вариант 2
stage_19_resolved_outcomes_pipeline.md

А уже следующий после него:

stage_20_outcome_edge_validation.md

Мой рекомендуемый порядок
19A — post-hoc resolve pipeline
прогнать его на уже накопленных JSONL
собрать merged resolved dataset
20 — outcome report:
winrate by signal_tier
winrate by time_bucket × distance_bucket
отдельно all should_enter
отдельно policy_allowed
отдельно allowed_entries