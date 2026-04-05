# Roadmap: Автоматизация Redeem выигрышных позиций Polymarket

**Дата создания:** 2026-04-05  
**Статус:** R1–R5 реализованы, ожидает приёмочных тестов (T1–T6)  
**Контекст:** Polymarket создаёт для каждого пользователя персональный Proxy Safe (вариант Gnosis Safe). CTF токены после fill хранятся на адресе Safe (`PM_FUNDER_ADDRESS`). Прямой вызов `redeemPositions` от MetaMask EOA не работает — транзакцию нужно исполнять через Safe.

---

## Архитектура решения

```
live_loop (main thread)
    │
    ├── каждый тик: торговля + логирование в JSONL
    │
    └── RedeemWorker (background thread, каждые N минут)
            │
            ├── читает live_loop_*.jsonl → filled entries
            ├── проверяет: раунд закрыт? (closed=True в Gamma)
            ├── проверяет: баланс CTF токена > 0?
            ├── если да → исполняет через Safe → redeemPositions
            └── записывает результат в data/logs/redeem_*.jsonl
```

---

## Этапы реализации

---

### Этап R1 — Исследование: тип прокси и ABI

**Цель:** Точно определить какой тип контракта развёрнут на `PM_FUNDER_ADDRESS` и какой метод использует для исполнения транзакций.

**Задачи:**

1. Запросить bytecode: `w3.eth.get_code(PM_FUNDER_ADDRESS)` — убедиться что это контракт, не EOA.

2. Проверить стандартные Gnosis Safe селекторы:
   - `getOwners()` → `0xa0e67e2b`
   - `getThreshold()` → `0xe75235b8`
   - `VERSION()` → `0xffa1ad74`
   - Если отвечает → стандартный Safe → использовать `safe-eth-py`

3. Если не стандартный Safe — проверить Polymarket-кастомный прокси:
   - Найти ABI на Polygonscan: `https://polygonscan.com/address/{PM_FUNDER_ADDRESS}#code`
   - Или: декодировать function selectors из bytecode
   - Искать методы: `exec`, `execute`, `forward`, `proxyTransfer`, `proxyCall`

4. Записать в `docs/stages/redeem_proxy_investigation.md`:
   - Тип контракта и версия
   - Адрес implementation (для proxy pattern)
   - Точный метод для исполнения транзакций
   - Пример calldata

**Критерий завершения R1:**  
Есть рабочий Python-код, который успешно вызывает ЛЮБУЮ on-chain функцию (например `getOwners()` или `VERSION()`) через Safe/Proxy от имени MetaMask ключа.

---

### Этап R2 — Модуль SafeExecutor

**Файл:** `src/binance_detector/execution/safe_executor.py`

**Интерфейс:**
```python
class SafeExecutor:
    def execute(self, to: str, data: bytes) -> str:
        """Исполняет произвольный calldata через Safe. Возвращает tx_hash."""

    def is_available(self) -> bool:
        """Проверяет что Safe подключён и MetaMask ключ является owner."""
```

**Два пути реализации (выбирается по результату R1):**

**Путь A — Стандартный Gnosis Safe:**
```python
# pip install safe-eth-py
from gnosis.eth import EthereumClient
from gnosis.safe import Safe

client = EthereumClient(rpc_url)
safe = Safe(safe_address, client)
safe_tx = safe.build_multisig_tx(to=ctf_addr, value=0, data=calldata)
safe_tx.sign(private_key)
safe_tx.execute(tx_sender_private_key=private_key)
```

**Путь B — Polymarket Custom Proxy:**
```python
proxy = w3.eth.contract(address=safe_addr, abi=PROXY_ABI)
tx = proxy.functions.exec(ctf_addr, 0, calldata).build_transaction({...})
signed = w3.eth.account.sign_transaction(tx, private_key)
w3.eth.send_raw_transaction(signed.raw_transaction)
```

**Критерий завершения R2:**  
`SafeExecutor.execute(CTF_ADDRESS, some_view_calldata)` проходит без ошибок (не обязательно redeemPositions — достаточно любого calldata).

---

### Этап R3 — RedeemService (основная логика)

**Файл:** `src/binance_detector/services/redeem_live.py`

**Логика:**
```python
class LiveRedeemService:
    def scan_and_redeem(self, dry_run: bool = True) -> list[RedeemResult]:
        """
        1. Читает live_loop_*.jsonl → собирает filled orders
        2. Для каждого: проверяет closed + CTF баланс
        3. Если баланс > 0 → редимит через SafeExecutor
        4. Возвращает список результатов
        """
```

**RedeemResult:**
```python
@dataclass
class RedeemResult:
    round_id: str
    slug: str
    side: str           # YES / NO
    balance_shares: int # raw CTF units
    balance_usd: float  # balance / 1e6
    status: str         # "redeemed" | "skipped" | "failed" | "dry_run"
    tx_hash: str
    error: str
```

**Логика пропуска (не тратить gas зря):**
- `balance == 0` → skip
- `already_redeemed` → skip (проверяем по `data/logs/redeem_done.json`)
- `market.closed == False` → skip (раунд ещё идёт)
- `time_since_close < 60s` → skip (подождать oracle)

**Критерий завершения R3:**  
`scan_and_redeem(dry_run=True)` правильно находит все filled rounds из логов, корректно показывает балансы, не падает на пустых логах.

---

### Этап R4 — Интеграция в live loop (параллельный фоновый поток)

**Файл:** `scripts/run_live_loop.py`

**Механика:**
```python
import threading

def redeem_worker(interval_seconds: int = 300, dry_run: bool = False):
    """Фоновый поток: каждые interval_seconds проверяет и редимит."""
    service = LiveRedeemService(...)
    while True:
        try:
            results = service.scan_and_redeem(dry_run=dry_run)
            for r in results:
                if r.status == "redeemed":
                    log.info("[REDEEM] %s/%s %.4f USDC tx=%s", r.slug, r.side, r.balance_usd, r.tx_hash)
        except Exception as e:
            log.error("[REDEEM] worker error: %s", e)
        time.sleep(interval_seconds)

# Запуск в main():
if not args.no_redeem:
    t = threading.Thread(target=redeem_worker, args=(300, args.dry_run), daemon=True)
    t.start()
    log.info("RedeemWorker started (interval=300s, dry_run=%s)", args.dry_run)
```

**Аргументы для `run_live_loop.py`:**
```
--no-redeem      отключить фоновый redeem (по умолчанию включён)
--redeem-dry-run redeem работает но не отправляет tx (для тестирования)
--redeem-interval N  интервал проверки в секундах (default: 300)
```

**Файл состояния редима:**  
`data/logs/redeem_done.json` — словарь `{slug: {side: tx_hash}}` — чтобы не редимить дважды.

**Критерий завершения R4:**  
`run_live_loop.py` запускается, видно лог `RedeemWorker started`, через 5 минут появляется первый отчёт воркера (пусть `No new positions to redeem`). Фоновый поток не блокирует основной цикл.

---

### Этап R5 — Обновление `run_redeem.py` (standalone)

Обновить скрипт с учётом SafeExecutor:
- заменить прямую tx на `SafeExecutor.execute()`
- добавить `--single-slug btc-updown-5m-XXXXX` для ручного редима конкретного раунда
- добавить `--list` — только показать что есть к редиму без отправки

**Критерий завершения R5:**  
```bash
python scripts/run_redeem.py --dry-run         # работает
python scripts/run_redeem.py                   # реально редимит через Safe
python scripts/run_redeem.py --single-slug btc-updown-5m-1775331000  # один раунд
```

---

## Критерии готовности всей фичи (Definition of Done)

| # | Критерий | Как проверить |
|---|----------|---------------|
| 1 | SafeExecutor успешно исполняет calldata через Proxy Safe | Отправить тестовую tx, увидеть receipt.status=1 |
| 2 | `balanceOf` корректно читает CTF баланс с адреса Safe | Видим balance > 0 для filled round |
| 3 | `redeemPositions` через Safe успешно проходит on-chain | TX в Polygonscan, USDC пришёл на кошелёк |
| 4 | `run_redeem.py --dry-run` завершается за < 30 секунд | Лог показывает все pending rounds |
| 5 | `run_redeem.py` без флагов реально редимит → USDC на балансе | Проверить баланс до и после |
| 6 | RedeemWorker запущен параллельно с live loop | Лог воркера появляется каждые 5 минут |
| 7 | Двойной редим невозможен | Повторный запуск → `already_redeemed`, 0 новых tx |
| 8 | При падении воркера основной loop не останавливается | Убить интернет на 1 мин → loop продолжает тикать |
| 9 | Лог `data/logs/redeem_*.jsonl` пишется корректно | Видны все поля: round_id, tx_hash, amount, status |
| 10 | Интеграция в VPS: запускается с `run_live_loop.py` без доп. команд | Деплой на VPS, один запуск = всё работает |

---

## Возможные ошибки и их обработка

### E1 — Прокси не Gnosis Safe (кастомный Polymarket контракт)
**Симптом:** `getOwners()` возвращает revert  
**Обработка:** Переключиться на Путь B — проверить ABI на Polygonscan, найти метод `exec`/`execute`/`forward`

### E2 — Safe nonce конфликт
**Симптом:** `Transaction with nonce X already exists`  
**Обработка:** Читать актуальный nonce с chain перед каждой tx (`safe.retrieve_nonce()` или `eth.get_transaction_count`). Никогда не кешировать nonce.

### E3 — Gas слишком высокий / underpriced
**Симптом:** TX не майнится или `replacement transaction underpriced`  
**Обработка:** Использовать `w3.eth.gas_price * 1.5`, установить max_fee_per_gas. На Polygon ставить минимум 50 gwei.

### E4 — Рынок закрыт в Gamma но oracle ещё не resolve
**Симптом:** `redeemPositions` reverts — `payoutNumerators not set`  
**Обработка:** Ждать 2-5 минут после закрытия раунда перед попыткой редима. Если revert → retry через 60 секунд, максимум 5 попыток.

### E5 — RPC rate limiting
**Симптом:** `429 Too Many Requests` или пустой ответ  
**Обработка:** Fallback через несколько RPC (уже реализован). Добавить `time.sleep(0.5)` между вызовами в воркере.

### E6 — CTF баланс показывает 0 хотя fill был
**Причины:**  
a) clobTokenIds парсится как строка (уже исправлено)  
b) Токены пришли на EOA (0xa1595124...) а не на Safe — если signature_type сменился  
c) Polymarket уже автоматически зачислил USDC (некоторые рынки используют automatic settlement)  
**Обработка:** Проверять баланс на ОБОИХ адресах (Safe + EOA). Логировать какой адрес держит токены.

### E7 — JSONL лог повреждён (неполная строка)
**Симптом:** `json.JSONDecodeError`  
**Обработка:** `try/except` вокруг каждой строки (уже реализовано в `find_filled_epochs_from_logs`).

### E8 — Фоновый поток зависает
**Симптом:** Воркер не пишет лог > 10 минут  
**Обработка:** Оборачивать вызов `scan_and_redeem` в `timeout` через `concurrent.futures`. Если timeout — перезапустить.

### E9 — Двойной редим (race condition)
**Симптом:** Два воркера пытаются редимить одновременно  
**Обработка:** Lock файл или `threading.Lock()`. Запись в `redeem_done.json` должна быть атомарной.

### E10 — Большое количество pending rounds после простоя VPS
**Симптом:** После перезапуска 100+ rounds к редиму  
**Обработка:** Обрабатывать по 10 за итерацию с паузой между, чтобы не перегружать RPC.

---

## Тесты приёмки

```bash
# T1 — unit: корректный парсинг логов
PYTHONPATH=./src python -m unittest tests.unit.test_redeem_service -v

# T2 — интеграционный: dry_run сканирование (нужны реальные env vars)
python scripts/run_redeem.py --dry-run

# T3 — проверка дублирования
python scripts/run_redeem.py --dry-run  # run 1
python scripts/run_redeem.py --dry-run  # run 2 → те же rounds, не дублируются

# T4 — параллельный запуск
python scripts/run_live_loop.py --market-key btc_updown_5m \
    --iterations 10 --interval-seconds 5 \
    --redeem-interval 30 --redeem-dry-run
# Ожидаем: в логах появляется "[REDEEM] worker..." каждые 30 сек

# T5 — реальный редим (осторожно, отправляет tx!)
python scripts/run_redeem.py --single-slug btc-updown-5m-1775331000
# Ожидаем: TX hash, receipt.status=1, USDC на кошельке увеличился

# T6 — устойчивость к RPC падению
# Отключить сеть на 60 сек во время прогона T4
# Ожидаем: main loop продолжает тикать, воркер логирует ошибку и retry
```

---

## Порядок выполнения

```
R1 (1-2 часа)  → исследовать тип прокси
R2 (2-3 часа)  → SafeExecutor (зависит от результата R1)
R3 (1-2 часа)  → LiveRedeemService
R4 (1 час)     → интеграция в run_live_loop.py
R5 (30 мин)    → обновление run_redeem.py
Тесты (1 час)  → T1-T6
```

**Общая оценка:** 6-9 часов (основная неизвестность — R1, тип прокси).

---

## Зависимости

| Пакет | Зачем | Установка |
|-------|-------|-----------|
| `web3>=6.0` | RPC вызовы, подпись tx | уже установлен |
| `safe-eth-py` | Если стандартный Gnosis Safe (Путь A) | `pip install safe-eth-py` |
| без доп. пакетов | Если кастомный прокси (Путь B) | — |

---

## Файлы которые будут созданы/изменены

| Файл | Действие |
|------|----------|
| `src/binance_detector/execution/safe_executor.py` | СОЗДАТЬ |
| `src/binance_detector/services/redeem_live.py` | СОЗДАТЬ |
| `scripts/run_redeem.py` | ОБНОВИТЬ (заменить прямую tx на SafeExecutor) |
| `scripts/run_live_loop.py` | ОБНОВИТЬ (добавить RedeemWorker thread) |
| `data/logs/redeem_done.json` | СОЗДАЁТСЯ авто (state файл) |
| `tests/unit/test_redeem_service.py` | СОЗДАТЬ |
| `docs/stages/redeem_proxy_investigation.md` | СОЗДАТЬ (результаты R1) |
| `pyproject.toml` | ОБНОВИТЬ (добавить safe-eth-py если нужно) |
