# Roadmap проекта: торговля 5m раундами Polymarket через сигналы Binance

## 0. Цель проекта

Построить систему, которая:
- получает микроструктурные сигналы из Binance,
- переводит их в вероятность исхода **Polymarket BTC Up/Down 5m**,
- принимает решения по входу/выходу,
- сначала доказывает edge в симуляции и paper-режиме,
- затем безопасно переходит к live execution.

Главный принцип:
- **Binance = источник сигнала**
- **Polymarket = место исполнения**
- **Chainlink / правила рынка = источник истины для резолва**

---

## 0.1 Текущий статус по stage-докам

По загруженным stage-документам проект уже продвинулся дальше исходного roadmap и сейчас находится в таком состоянии:

- **Stage 01 Foundation**: базовый фундамент уже реализован — canonical round engine, baseline probability model, simulator, entry policy v1, reverse-exit groundwork, basis guards.
- **Stage 02 Simulation Analytics**: есть markdown-отчёты и таблицы `time × distance`, `tier usefulness`, причины блокировок, late damage detection.
- **Stage 03 Signal Core**: detector layer уже выделен и расширен (`wall pull`, `major drop`, `full remove`, `absorption`, `resilience`), есть per-tick debug CSV.
- **Stage 04 Binance REST Binding**: Binance connector уже переведён на public REST depth/trades/klines, но всё ещё есть demo-fallback, который нужно жёстче контролировать.
- **Stage 05 PM Execution And Ops**: есть публичные PM quotes, paper execution engine, broker hardening scaffold, canary runner, redeem-service separation и observability baseline.

### Что это значит по факту

Roadmap больше не выглядит как чистый plan-from-zero. Сейчас проект находится на переходе от:
- synthetic/offline scaffold,

к:
- real sequential market-data loop,
- живым round summaries,
- проверке signal quality уже на реальных снапшотах,
- и только потом к настоящему live order placement.

### Главные незакрытые риски

- signal quality ещё не доказана на реальных последовательных рыночных данных;
- Binance layer всё ещё может silently fallback'нуться в demo snapshot;
- paper/live execution scaffold есть, но полноценного live placement ещё нет;
- redeem separation есть, но реальный onchain redemption ещё не доведён;
- synthetic analytics полезна для пайплайна, но не для окончательных выводов о real edge.

## 1. Конечный результат

К финалу проекта система должна уметь:
1. синхронно определять 5m раунды Polymarket;
2. фиксировать цену открытия раунда и корректно считать расстояние цены до open;
3. собирать сигналы из стакана Binance в реальном времени;
4. оценивать вероятность закрытия раунда выше/ниже open;
5. сравнивать эту вероятность с ценой рынка Polymarket с учётом fee/slippage/basis;
6. открывать и закрывать позиции по строгим правилам;
7. вести полную аналитику по каждому входу, shadow-opportunity и reversal-exit;
8. безопасно работать в live без аналитической contamination.

---

## 2. Архитектурные блоки

### A. Round engine
Отвечает за:
- определение текущего 5m раунда;
- round_id / start_ts / end_ts;
- фиксацию round open price;
- корректную финализацию исхода.

### B. Market data
Отвечает за:
- Binance depth / trades / mid / microprice / imbalance / velocity;
- Polymarket best bid/ask, book liquidity, fill environment;
- basis check между Binance и settle/reference feed.

### C. Signal engine
Отвечает за:
- вычисление detector signals;
- агрегацию в итоговую вероятность `p_up` / `p_down`;
- силу сигнала: weak / medium / strong / very_strong.

### D. Execution engine
Отвечает за:
- entry policy;
- passive/taker режим;
- preflight checks;
- partial fills / replenish / cancel / reverse-exit.

### E. Analytics
Отвечает за:
- summary по round/entry/exit;
- time × distance × strength анализ;
- usefulness reversal-exit;
- contamination detection.

---

## 3. Roadmap по этапам

## M1. Базовая синхронизация 5m раундов

### Цель
Надёжно понимать, какой сейчас раунд, где его open, сколько осталось времени, и по какому условию он резолвится.

### Задачи
- сделать единый canonical round manager для 5m;
- убрать любые дубли классов / путаницу round_id;
- хранить `round_open_price`, `round_close_ref_price`, `t_left`;
- жёстко разделить:
  - текущую рыночную цену,
  - цену открытия раунда,
  - цену для settle/result.

### Definition of Done
- ни одного расхождения round_id в логах;
- open price фиксируется один раз и не плавает;
- итог раунда считается отдельно от forced close логики;
- по 100+ раундам нет ложных FLAT / wrong winner summary.

---

## M2. Чистый Binance signal core

### Цель
Собрать минимальный, но сильный набор сигналов микроструктуры Binance.

### Задачи
- оставить базовые detectors:
  - velocity,
  - queue imbalance,
  - microprice,
  - wall pull / major drop / full remove,
  - absorption / resilience;
- нормализовать их на 5m режим;
- зафиксировать единый формат per-tick debug columns.

### Definition of Done
- каждый detector пишет свои debug-поля в CSV;
- нет "чёрных ящиков" без объяснимого вклада;
- сигналы стабильны на повторных прогонах с одинаковым входом.

---

## M3. Baseline probability model

### Цель
Перевести сигналы Binance не в "рост/падение вообще", а в вероятность закрытия выше/ниже **round open**.

### Задачи
- ввести state features:
  - `distance_to_open_bps`,
  - `time_left_bucket`,
  - `velocity_short`,
  - `queue_imbalance`,
  - `microprice_delta`,
  - `volatility_recent`;
- построить baseline score:
  - сначала rule-based;
- итог: `p_up_total`, `p_down_total`, `signal_tier`.

### Definition of Done
- модель выдаёт probability score на каждом тике;
- вероятность монотонно и логично реагирует на удаление от open и на скорость движения;
- baseline уже лучше случайного по ключевым бакетам.

---

## M4. Симулятор 5m раундов

### Цель
Доказать полезность стратегии вне live execution noise.

### Задачи
- сделать прогон 100 / 300 / 500 раундов;
- логировать:
  - candidate entries,
  - actual entries,
  - shadow opportunities,
  - missed fills,
  - blocked entries;
- сохранять round summary отдельно от execution side-effects.

### Метрики
- pnl;
- winrate;
- avg edge at entry;
- avg damage on bad late entries;
- contribution by detector;
- quality by time bucket;
- quality by distance bucket.

### Definition of Done
- можно воспроизводимо сравнивать конфиги;
- два одинаковых прогона дают одинаковую или почти одинаковую аналитику;
- summary не загрязняется forced flat / allowance / broker-noise.

---

## M5. Entry policy v1

### Цель
Сделать строгую систему входов, которая режет слабые зоны.

### Задачи
- построить allow/ban policy по:
  - `time_bucket`,
  - `distance_bucket`,
  - `signal_tier`;
- внедрить policy формата:
  - default allowed tiers,
  - by_time,
  - by_distance,
  - by_time_distance;
- запретить статистически плохие зоны;
- ослабить входы в late-phase.

### Definition of Done
- policy описывается конфигом без правки кода;
- на 150–300 раундах видно снижение late damage;
- weak tier режется точечно, а не глобально вслепую.

---

## M6. Reverse-exit usefulness analyzer

### Цель
Понять, reverse-exit реально спасает или просто шумит.

### Задачи
- добавить аналитику по каждому reverse-exit:
  - `saved_loss`,
  - `cut_winner`,
  - `infra_failed`,
  - `counterfactual_hold_to_settle`;
- хранить силу exit-сигнала;
- считать результат по фазам раунда и distance buckets.

### Definition of Done
- можно жёстко ответить, полезен ли reverse-exit;
- есть таблица пользы по tier/time/distance;
- exit contamination отделена от signal quality.

---

## M7. Strength-tier analytics

### Цель
Перевести качество сигнала в управляемые уровни силы.

### Задачи
- стандартизировать tiers:
  - weak,
  - medium,
  - strong,
  - very_strong;
- анализ actual entries и shadow opportunities по tier;
- понять, какие tiers можно разрешать в каких фазах/дистанциях.

### Definition of Done
- для каждого tier есть статистика:
  - winrate,
  - pnl,
  - avg edge,
  - late damage;
- policy строится уже на реальных tier distribution, а не на ощущениях.

---

## M8. Basis / settle alignment layer

### Цель
Защитить стратегию от ошибки: сигнал с Binance есть, но settle/market truth не совпадают.

### Задачи
- ввести `basis_bps` между Binance и settle/reference feed;
- завести guards:
  - max basis,
  - stale settle reference,
  - stale PM quote,
  - illiquid PM book;
- логировать все block reasons отдельно.

### Definition of Done
- каждый blocked entry объясним;
- basis divergence видна в summary;
- стратегия не торгует заведомо плохие условия рассинхрона.

---

## M9. Paper execution на Polymarket

### Цель
Подключить реальные PM market data и paper-order semantics без риска денег.

### Задачи
- читать best bid/ask и ликвидность Polymarket;
- считать entry feasibility;
- моделировать passive vs taker fill;
- логировать blockers:
  - stale_quote,
  - spread_too_wide,
  - illiquid_book,
  - slippage_too_high,
  - min_entry_tleft,
  - cooldown,
  - no_entry_last_seconds.

### Definition of Done
- можно прогонять стратегию на реальных PM quotes в paper mode;
- видно, где стратегия хороша по сигналу, но непригодна по исполнению.

---

## M10. Live broker hardening

### Цель
Сделать live execution безопасным и диагностируемым.

### Задачи
- проверить и зафиксировать:
  - conservative order-status normalization,
  - ask > 0 validation,
  - partial fill logic,
  - replenish logic,
  - pending entry ttl,
  - cancel/resolve unknown order handling;
- исключить ложные fills;
- исключить silent failures.

### Definition of Done
- каждая неудачная сделка имеет точный reason;
- нет ложных filled при пустом status;
- нет скрытых ZeroDivision / allowance ambiguity / phantom entry states.

---

## M11. Live canary

### Цель
Включить минимальный live режим с маленьким риском.

### Задачи
- один рынок;
- минимальный stake;
- один entry на раунд;
- отключить агрессивные reversal flows на старте;
- сохранить максимум логов/summary.

### Definition of Done
- 30–50 live rounds без критических execution багов;
- все сделки объяснимы постфактум;
- pnl вторичен, сначала — корректность и diagnosability.

---

## M12. Redemption / resolved-market servicing

### Цель
Не смешивать торговую логику с обслуживанием выигранных позиций.

### Задачи
- вынести redeem flow в отдельный сервис/скрипт;
- периодически проверять resolved markets;
- забирать выигранные позиции отдельно от основного бота;
- логировать, что было redeemed и когда.

### Definition of Done
- основной бот не зависит от redeem логики;
- кошелёк не "забивается" выигранными unresolved/redeemable позициями;
- нет влияния redeem процесса на торговую логику.

---

## M13. Production observability

### Цель
Сделать систему пригодной для долгой эксплуатации.

### Задачи
- health metrics;
- heartbeat;
- last good quote time;
- last order action time;
- SSE/debug endpoints;
- per-round structured summary;
- аварийные guardrails.

### Definition of Done
- по одному summary можно понять, что произошло в раунде;
- любые зависания/рассинхроны быстро видны;
- можно безопасно гонять длительные серии.

---

## 4. Приоритеты прямо сейчас

### P0 — сделать сначала
1. **M1 Round engine correctness**
2. **M3 baseline probability model вокруг round open**
3. **M4 clean simulator analytics**
4. **M5 entry policy v1**
5. **M6 reverse-exit usefulness analyzer**
6. **M8 basis/settle alignment**

### P1 — после этого
7. **M9 paper execution on real PM quotes**
8. **M10 live broker hardening**
9. **M11 live canary**

### P2 — затем
10. **M12 redeem service**
11. **M13 production observability**

---

## 5. Ближайший практический план

### Шаг 1
Зафиксировать финальный 5m round pipeline:
- round id;
- round open;
- time left;
- settle/result separation.

### Шаг 2
Сделать baseline score только из:
- distance_to_open,
- velocity,
- queue imbalance.

### Шаг 3
Прогнать 100–150 раундов и получить:
- time × distance таблицы,
- tier usefulness,
- late damage zones.

### Шаг 4
На базе этого включить config-driven entry policy.

### Шаг 5
Отдельно проверить reverse-exit не по pnl в целом, а по:
- saved_loss,
- cut_winner,
- infra_failed.

---

## 6. Критерии успеха проекта

Проект можно считать успешным, если одновременно выполняется следующее:
- стратегия статистически лучше baseline;
- edge воспроизводим на нескольких сериях прогонов;
- broker/execution ошибки не маскируют реальное качество сигнала;
- live canary работает без критических execution surprises;
- решение о входе объяснимо по логам и summary;
- есть понятный путь от сигнала Binance до результата на Polymarket.

---

## 7. Главный принцип управления проектом

Сначала доказываем:
1. корректность round engine,
2. качество сигнала,
3. чистоту аналитики,

и только потом масштабируем execution.

Не наоборот.

