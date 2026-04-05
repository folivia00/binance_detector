Сначала подтвержу понимание: 4 slug-а уже в redeem_done.json, лог "Found 4 filled slugs to check" вводит в заблуждение — он печатается до фильтрации done. Реально 0 RPC вызовов, просто путаница в сообщении. Это первое что нужно починить.
Фильтр по round_id/ts из JSONL (вариант C) — правильный выбор. Имя файла даёт только дату старта прогона, а один прогон может длиться сутки и содержать позиции двух дней. round_id: "btc_updown_5m:20260405T094000Z" — у вас там встроена дата раунда прямо в ID, её и парсить.
Адаптивный интервал (5 мин → 15 мин → обратно) — хорошая схема, реализуется простым счётчиком пустых циклов.
План работы (Stage 30 — Redeem Worker Optimization)
Scope
Улучшения только в RedeemWorker и LiveRedeemService.scan_and_redeem. Основной торговый цикл, SafeExecutor, run_redeem.py (standalone) и redeem_done.json формат не трогаем. Это гарантирует что если что-то сломается в воркере — торговля продолжает работать как раньше.
Задачи (в порядке выполнения)
#### 1. Исправить мисleading лог 

Сейчас: [REDEEM] Found 4 filled slugs to check → после этого фильтрация по redeem_done.json
Станет: сначала отфильтровать, потом залогировать реальное число
Добавить три счётчика в один summary-лог:

  [REDEEM] scan: filled_in_logs=12, already_done=10, new_to_check=2

Если new_to_check=0 → лог уровня DEBUG (не INFO) чтобы не спамить

#### 2. Добавить фильтр по дате в _collect_filled_slugs

Парсить дату из round_id (формат btc_updown_5m:20260405T094000Z → 2026-04-05)
Аргумент --redeem-lookback-days N в run_live_loop.py, по умолчанию N=1 (сегодня + вчера)
Почему 1 день как default, не 0 (только сегодня):

раунды закрывающиеся около полуночи UTC могут попасть в "вчерашние" если закрылись в 23:55 UTC
oracle resolve может задержаться до 5 минут → раунд из вчера но редим сегодня


Для standalone run_redeem.py оставить --days 7 как сейчас (ручная рекавери-задача)
Парсер даты: регулярка r'^[^:]+:(\d{8})T' → groupдата → datetime.strptime(..., "%Y%m%d")
Fallback: если round_id в непонятном формате → включать в скан (safe default, лучше лишняя проверка чем пропущенный редим)

### 3. Добавить in-memory кэш "empty balance" slugs

Новое поле в RedeemWorker: self._empty_balance_cache: set[str] = set()
Если yes_balance=0 AND no_balance=0 после Gamma-проверки (market.closed=true) → добавить в кэш
При следующих сканах эти slug-и пропускаются без RPC вызовов
НЕ персистится в файл — кэш обнуляется при рестарте (это нормально)
Логика: если Polymarket auto-settle — баланс навсегда 0, после рестарта проверим ещё раз и снова закэшируем
Не путать с redeem_done.json — там реально отредимленные, здесь "нечего редимить"

#### 4. Адаптивный интервал сканирования 
Логика state machine:
ACTIVE (interval=300s):
    scan → found new candidates (new_to_check > 0)
    → остаётся ACTIVE

ACTIVE → IDLE:
    scan → new_to_check = 0
    → счётчик empty_scans += 1
    → если empty_scans >= 3 (15 минут подряд пусто) → переход в IDLE

IDLE (interval=900s):
    scan → new_to_check > 0
    → сразу переход в ACTIVE, сбрасываем счётчик
Три параметра (в RedeemWorker.__init__):

active_interval = 300 (5 мин при активной торговле)
idle_interval = 900 (15 мин когда filled нет)
idle_threshold = 3 (сколько пустых сканов подряд = IDLE)

Логи перехода состояний:
[REDEEM] state: ACTIVE → IDLE (3 empty scans, next in 15m)
[REDEEM] state: IDLE → ACTIVE (new candidate found)
#### 5. Новые CLI аргументы в run_live_loop.py
аргументdefaultописание--redeem-lookback-days N1сканировать filled за последние N дней--redeem-idle-interval N900интервал когда нет новых filled (сек)--redeem-idle-threshold N3пустых сканов для перехода в IDLE
Существующий --redeem-interval становится "active interval" (алиас, не ломаем backward compat).
#### 6. Новые unit-тесты 
Создать tests/unit/test_redeem_worker_cache.py:

test_date_filter_parses_round_id — правильный парсинг даты
test_date_filter_skips_old_rounds — фильтрация по N дней
test_date_filter_keeps_unparseable_round_id — fallback (include)
test_empty_balance_cache_hit — второй скан не делает RPC
test_state_transitions — 3 пустых скана → IDLE, новый filled → ACTIVE


