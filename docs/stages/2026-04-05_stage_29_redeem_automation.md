# Stage 29 — Redeem Automation via Gnosis Safe

**Date:** 2026-04-05  
**Branch:** dev → main (после успешного 10-раундового теста)  
**Status:** Implemented, tested (real redeem confirmed: 4.96 USDC)

---

## Objective

Автоматизировать выкуп (redeem) выигрышных CTF-токенов после закрытия раундов.  
CTF-токены хранятся на Gnosis Safe (`PM_FUNDER_ADDRESS`), поэтому прямой вызов `redeemPositions` от MetaMask EOA невозможен — транзакцию нужно проводить через `Safe.execTransaction`.

Параллельно основному торговому циклу запускается `RedeemWorker` — фоновый поток, который каждые N минут сканирует логи и редимит выигрышные позиции без вмешательства пользователя.

---

## Key Discovery (R1 Investigation)

Полное исследование: `docs/stages/redeem_proxy_investigation.md`

| Факт | Значение |
|------|----------|
| Тип контракта | Gnosis Safe v1.3.0 (стандартный) |
| Структура | 1-of-1 multisig, единственный owner = MetaMask EOA |
| Factory | `0xaacFeEa03eB1561C4e67d661e40682Bd20E3541b` (Polymarket Safe Proxy Factory) |
| Способ исполнения | `execTransaction` с pre-validated signature (v=1) |
| Новые зависимости | **нет** (только `web3>=6.0`, уже установлен) |

### Pre-validated Signature (главный инсайт)

Gnosis Safe v1.3.0 поддерживает тип подписи `v=1`:
```solidity
if (v == 1) {
    currentOwner = address(uint160(uint256(r)));
    require(msg.sender == currentOwner || approvedHashes[...]);
}
```
Если отправитель транзакции (msg.sender) = owner Safe → подпись считается валидной **без реальной криптоподписи**.

```python
# 65 байт: r(32) + s(32) + v(1)
owner_bytes = to_bytes(hexstr=eoa_address)   # 20 bytes
r = b'\x00' * 12 + owner_bytes               # left-pad to 32
s = b'\x00' * 32
v = b'\x01'
prevalidated_sig = r + s + v                 # exactly 65 bytes
```

---

## Architecture

```
run_live_loop.py (процесс)
│
├── [main thread]  торговый цикл — каждые 5 сек
│       ├── evaluate_once() → сигнал Binance
│       ├── LiveExecutionEngine.execute() → CLOB ордер
│       └── пишет строку в live_loop_YYYYMMDDTHHMMSSZ.jsonl
│
└── [RedeemWorker, daemon=True]  каждые 300 сек
        ├── читает live_loop_*.jsonl → slug-и со status="filled"
        ├── пропускает slug-и из redeem_done.json
        ├── Gamma API: closed? conditionId? clobTokenIds? negRisk?
        ├── Safe.balanceOfBatch → есть ли CTF токены
        ├── payoutDenominator guard (E4: oracle не resolve-ил)
        └── Safe.execTransaction → CTF.redeemPositions([1, 2])
                → USDC возвращается на Safe
                → пишет в redeem_done.json
```

### Цепочка вызовов для одного редима

```
MetaMask EOA (msg.sender = EOA)
    │
    ▼ execTransaction(to=CTF, data=redeemPositions_calldata, signatures=prevalidated_sig)
Safe (0xc58621...)
    │ внутри: msg.sender = Safe
    ▼ redeemPositions(USDC, 0x0, conditionId, [1, 2])
CTF (0x4D97DC...)
    │ сжигает ERC-1155 токены с баланса Safe
    ▼ переводит USDC → Safe
```

---

## New Files

### `src/binance_detector/execution/safe_executor.py`

**`SafeExecutor`** — исполняет произвольный calldata через Gnosis Safe.

| метод | описание |
|-------|----------|
| `is_available()` | проверяет что EOA является owner Safe |
| `verify()` | возвращает диагностику: version, threshold, nonce, owners, MATIC баланс EOA |
| `execute(to, data, value=0)` | отправляет `execTransaction` с pre-validated sig, возвращает tx_hash |
| `execute_and_wait(to, data, timeout=120)` | ждёт receipt, проверяет status=1 |

**Gas параметры:**
- `gas = 250_000` — реальный расход ~120-150k, с запасом
- `maxFeePerGas = baseFeePerGas + 30 gwei` (через `get_block("pending")`)
- `maxPriorityFeePerGas = 30 gwei` (минимум для Polygon)
- `chainId = 137` (Polygon)

**ABI (минимальный, встроен в файл):**
- `execTransaction` — 10 параметров
- `getOwners`, `nonce`, `getThreshold`, `VERSION`

---

### `src/binance_detector/services/redeem_live.py`

**`RedeemResult`** — dataclass результата одного редима:

| поле | тип | описание |
|------|-----|----------|
| `round_id` | str | `btc_updown_5m:20260405T...` |
| `slug` | str | `btc-updown-5m-1775331000` |
| `condition_id` | str | bytes32 hex из Gamma API |
| `yes_balance_shares` | int | raw ERC-1155 units (6 decimals) |
| `no_balance_shares` | int | raw ERC-1155 units |
| `balance_usd` | float | (yes + no) / 1e6 |
| `status` | str | `redeemed` / `dry_run` / `skipped` / `failed` / `not_resolved` / `already_done` |
| `tx_hash` | str | хэш транзакции (если redeemed) |
| `error` | str | текст ошибки (если failed) |

**`LiveRedeemService.scan_and_redeem(dry_run)`** — основная логика:

1. `_collect_filled_slugs()` — читает все `live_loop_*.jsonl`, парсит `round_id` → slug
2. Пропускает slug-и из `redeem_done.json`
3. `_fetch_market_info(slug)` — Gamma API: closed? negRisk? conditionId? clobTokenIds?
4. `_check_balances()` — `balanceOfBatch([safe, safe], [yes_id, no_id])` на CTF/NegRiskAdapter
5. `payoutDenominator` guard — если = 0, oracle не готов → status=`not_resolved`; если вызов упал → proceed (Polymarket CTF не всегда экспортирует getter)
6. `_redeem_via_safe()` — `encode_abi("redeemPositions", [USDC, 0x0, conditionId, [1,2]])` → `safe_executor.execute_and_wait()`
7. Атомарная запись в `redeem_done.json` (через `.tmp` + rename)

**NegRisk маркеты:** `market.negRisk == True` → `redeemPositions` на `NegRiskAdapter` (`0xd91E80...`) вместо CTF. ABI идентичный, только адрес контракта другой.

**indexSets = [1, 2]:** передаётся всегда — CTF игнорирует сторону с нулевым балансом.

---

### `scripts/run_redeem.py`

Standalone скрипт для ручного и scheduled редима.

```bash
# Показать все позиции к редиму (без tx):
python scripts/run_redeem.py --dry-run
python scripts/run_redeem.py --list

# Редимить все найденные в логах:
python scripts/run_redeem.py

# Один конкретный маркет:
python scripts/run_redeem.py --single-slug btc-updown-5m-1775331000

# Сканировать последние N дней (медленно):
python scripts/run_redeem.py --dry-run --days 7

# Повторить уже сделанные (recovery):
python scripts/run_redeem.py --force
```

**Стартовые проверки:**
- MATIC баланс EOA < 0.01 → `ERROR` + инструкция по пополнению (при `dry_run` предупреждение, не выход)
- EOA не является owner Safe → `ERROR`, выход
- Все Polygon RPC недоступны → `ERROR`, выход

**`data/logs/redeem_done.json`** — state-файл:
```json
{
  "btc-updown-5m-1775331000": "0xabc...tx_hash",
  "btc-updown-5m-1775332200": "0xdef...tx_hash"
}
```

---

## Modified Files

### `scripts/run_live_loop.py`

Добавлены аргументы для управления RedeemWorker:

| аргумент | по умолчанию | описание |
|----------|-------------|----------|
| `--no-redeem` | off | отключить RedeemWorker полностью |
| `--redeem-dry-run` | off | воркер работает, но tx не отправляет |
| `--redeem-interval N` | 300 | интервал проверки в секундах |

**RedeemWorker активируется только при `--live`** (в dry-run режиме торговли редим не нужен — нет реальных позиций).

```python
t = threading.Thread(
    target=_redeem_worker,
    args=(service, args.redeem_interval, args.redeem_dry_run),
    daemon=True,        # умирает вместе с main thread
    name="RedeemWorker",
)
t.start()
```

---

## Адреса контрактов (Polygon)

| контракт | адрес |
|----------|-------|
| ConditionalTokens (CTF) | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` |
| NegRiskAdapter | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` |
| USDC.e (collateral) | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` |
| Polymarket Safe Proxy Factory | `0xaacFeEa03eB1561C4e67d661e40682Bd20E3541b` |

---

## VPS Setup

Новых env vars не требуется — `PM_PRIVATE_KEY` и `PM_FUNDER_ADDRESS` уже используются для торговли.

Опционально:
```bash
export POLYGON_RPC_URL=https://1rpc.io/matic  # переопределить RPC (есть fallback-список)
```

**Запуск с redeem:**
```bash
# Запустить прогон с реальными ордерами + автоматическим redeem каждые 5 мин:
nohup python scripts/run_live_loop.py \
    --market-key btc_updown_5m \
    --iterations 1800 \
    --live \
    --redeem-interval 300 \
    > logs/live_loop.log 2>&1 &
```

**Ручной редим накопленных позиций:**
```bash
python scripts/run_redeem.py --dry-run   # проверить что есть
python scripts/run_redeem.py             # редимить
```

---

## Error Scenarios & Handling

| ошибка | симптом | обработка |
|--------|---------|-----------|
| E1 — 0 MATIC на EOA | `insufficient funds for gas` | `run_redeem.py` проверяет баланс на старте и выводит адрес для пополнения |
| E2 — рынок не закрыт | Gamma: `closed=false` | skip, попробует на следующей итерации |
| E3 — oracle не resolve-ил | `redeemPositions` revert | `payoutDenominator=0` → status=`not_resolved`, retry на следующей итерации |
| E4 — `payoutDenominator` не экспортируется | `b''` empty return | proceed (treat as unknown), пусть CTF сам вернёт revert если не готово |
| E5 — RPC rate limiting | `429` или пустой ответ | fallback по списку: `1rpc.io/matic` → `polygon-rpc.com` → `rpc.ankr.com` |
| E6 — нулевой баланс после fill | `YES=0 NO=0` | skip (Polymarket мог auto-settle) |
| E7 — двойной редим | slug уже в `redeem_done.json` | немедленный skip без RPC вызовов |
| E8 — воркер падает | exception в цикле | `log.error` + `sleep(interval)`, **основной цикл не затрагивается** |
| E9 — JSONL повреждён | `json.JSONDecodeError` | `try/except` на каждой строке, пропускает |
| E10 — много pending после простоя | 100+ позиций | обрабатывает батчем, `time.sleep(2)` между tx |

---

## Acceptance Tests

```bash
# T1 — диагностика Safe:
python scripts/run_redeem.py --dry-run
# Ожидаем: safe diagnostics с version=1.3.0, eoa_is_owner=true, eoa_matic_balance>0

# T2 — dry-run сканирование:
python scripts/run_redeem.py --list
# Ожидаем: список позиций с балансами (если есть filled logs)

# T3 — реальный редим:
python scripts/run_redeem.py
# Ожидаем: TX hash, receipt.status=1, USDC на балансе Safe увеличился

# T4 — защита от двойного редима:
python scripts/run_redeem.py  # run 1 → redeemed
python scripts/run_redeem.py  # run 2 → "already in redeem_done.json", 0 tx

# T5 — single-slug:
python scripts/run_redeem.py --single-slug btc-updown-5m-1775331000
# Ожидаем: редим только этого раунда

# T6 — параллельный воркер в прогоне (10 раундов):
python scripts/run_live_loop.py --market-key btc_updown_5m \
    --iterations 720 --interval-seconds 5 \
    --live --redeem-interval 300
# Ожидаем: "[REDEEM] Worker started", торговля идёт, воркер логирует каждые 5 мин
# При закрытии раунда: "[REDEEM] Redeemed btc-updown-5m-EPOCH X.XX USDC tx=0x..."
```

---

## Real Test Results (2026-04-05)

| параметр | значение |
|----------|----------|
| Safe адрес | `0xc58621d2A06cea51256AC588d58d3Bbc617b9b02` |
| EOA адрес | `0xa1595124dE591AfF92190b63F44C000105D62CCE` |
| Safe version | 1.3.0 |
| threshold | 1 |
| Тестовый редим | `btc-updown-5m-1775331000`, NO=4964000 (4.964 USDC) |
| Статус | ✓ redeemed, receipt.status=1 |
| Проблемы при отладке | 1) `payoutDenominator` возвращает `b''` на Polymarket CTF (исправлено: treat as unknown) 2) EOA MATIC = 0 (решение: пополнить ≥0.1 MATIC) |

---

## Safety Design

| механизм | описание |
|----------|----------|
| `daemon=True` поток | воркер умирает вместе с основным процессом, не зависает в фоне |
| `redeem_done.json` | исключает двойной редим при любом количестве перезапусков |
| атомарная запись `.tmp` → rename | нет повреждения state-файла при kill -9 |
| `threading.Lock` | безопасно при будущем параллельном запуске |
| MATIC guard | скрипт проверяет баланс EOA до отправки tx |
| `execute_and_wait` | проверяет `receipt.status == 1`, иначе `SafeExecutorError` |
| `--redeem-dry-run` | можно запустить воркер без реальных tx (для тестирования интеграции) |
| `--no-redeem` | полное отключение воркера без изменения кода |

---

## Next Steps

- После 24h прогона: проверить `data/logs/redeem_done.json` — все filled раунды присутствуют
- Если MATIC на EOA < 0.1 — пополнить
- Stage 30 (опционально): добавить вывод USDC с Safe на EOA автоматически (сейчас USDC остаётся на Safe и используется для следующих ордеров — это корректное поведение)
