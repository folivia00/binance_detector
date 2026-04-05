# Stage 30 — Redeem Worker Optimization

**Date:** 2026-04-05  
**Branch:** dev → main  
**Status:** Implemented, syntax verified

---

## Motivation

Stage 29 ввёл RedeemWorker, но в первом реальном тесте (10 раундов) обнаружились две проблемы:

### Проблема 1 — TX stuck in mempool (критическая)

```
INFO  [REDEEM] btc-updown-5m-1775382000 — YES=10960400 NO=0 (10.9604 USDC)
INFO  SafeExecutor: TX sent 0xf5714b68e777a0b2aae0b81108aca705894766f50da...
ERROR [REDEEM] TX failed: Transaction ... is not in the chain after 120 seconds
```

**Диагноз:** TX был отправлен (`blockNumber: None` — в мемпуле), но `wait_for_transaction_receipt(timeout=120)` упал. Причина медленного майнинга: `maxFeePerGas = base_fee + 30gwei` — слишком мало запаса при спайке base fee. Если base fee вырастает даже на 5%, TX замерзает.

**Последствия без фикса:** TX не попадает в `redeem_done.json` → следующая итерация воркера посылает новый TX → потенциальный двойной редим (хотя CTF это игнорирует при нулевом балансе, лишний газ тратится).

### Проблема 2 — balanceOfBatch transient RPC error

```
WARNING [REDEEM] balanceOfBatch error for btc-updown-5m-1775330400:
  Could not transact with/call contract function, is contract deployed correctly and chain synced?
```

Единичная RPC ошибка, не связанная с контрактом. Ни retry, ни кэш отсутствовали.

### Проблема 3 — Misleading log (из v2 плана)

```
INFO [REDEEM] Found 4 filled slugs to check.  ← все 4 уже в done, 0 RPC вызовов
```

Лог печатался до фильтрации `redeem_done.json`, создавая ложное ощущение активности.

---

## Changes

### `safe_executor.py` — Gas & timeout fixes

**Fix 1: `maxFeePerGas = base_fee × 2 + priority`**

```python
# было:
max_fee = base_fee + max_priority           # слишком мало при спайке

# стало:
max_fee = base_fee * _BASE_FEE_MULTIPLIER + max_priority  # 2× буфер
```

При base_fee=76 gwei: было `106 gwei`, стало `182 gwei`. TX включается даже если base fee вырастает в 2 раза.

**Fix 2: Timeout 120s → 300s + pending state**

```python
# было: поднимал исключение при timeout
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
# → Exception "not in chain after 120s" → статус failed, tx_hash теряется

# стало: при timeout возвращает pending state
try:
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
except Exception:
    return {"status": "pending", "transactionHash": tx_hash}
```

Вызывающий код сохраняет `tx_hash` в `redeem_pending.json` и проверяет receipt на следующей итерации.

---

### `redeem_live.py` — 5 улучшений

#### 1. Pending TX tracking (`redeem_pending.json`)

Новый state-файл `data/logs/redeem_pending.json`:
```json
{
  "btc-updown-5m-1775382000": {
    "tx_hash": "0xf5714b...",
    "round_id": "btc_updown_5m:20260405T095000Z",
    "balance_usd": 10.9604,
    "sent_at": "2026-04-05T17:52:36Z"
  }
}
```

Каждый вызов `scan_and_redeem` начинается с `_resolve_pending()`:
- Проверяет receipt каждого pending TX через RPC
- `receipt.status == 1` → переносит в `redeem_done.json`, удаляет из pending
- `receipt.status == 0` (revert) → удаляет из pending (будет переотправлен при следующем скане со свежим балансом)
- `receipt is None` (всё ещё в мемпуле) → оставляет в pending, пробует снова позже

#### 2. Date filter в `_collect_filled_slugs`

```python
# Только filled rounds за последние N дней (default: 2)
cutoff = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
round_date = _parse_round_date(round_id)  # парсит "btc_updown_5m:20260405T..." → 2026-04-05
if round_date is not None and round_date < cutoff:
    continue
# Fallback: если round_id нечитаемый → включать в скан (безопасный default)
```

Почему `lookback_days=2` по умолчанию (не 0 и не 1):
- Раунды закрывающиеся ~полночь UTC попадают в "вчерашние"
- Oracle resolve может задержаться до 5 минут после закрытия
- 2 дня = надёжный буфер без перебора всей истории

#### 3. In-memory cache нулевых балансов

```python
self._zero_balance_cache: set[str] = set()

# После balanceOfBatch → YES=0 AND NO=0 → добавить в кэш
if total_shares == 0:
    self._zero_balance_cache.add(slug)
    return None  # следующие сканы: немедленный skip без RPC

# Кэш НЕ персистируется — сбрасывается при рестарте
# Если Polymarket auto-settled → после рестарта проверим и снова закэшируем
```

#### 4. Фикс лога (фильтрация ПЕРЕД логированием)

```python
# было:
log.info("[REDEEM] Found %d filled slugs to check.", len(all_slugs))
# потом фильтрация...

# стало:
new_slugs = {s: r for s, r in all_slugs.items() if s not in done_state ...}
if new_slugs:
    log.info("[REDEEM] scan: filled_in_logs=%d, already_done=%d, new_to_check=%d",
             total, done_count, len(new_slugs))
else:
    log.debug(...)  # тихо если нечего делать
```

#### 5. Retry для `balanceOfBatch` (3 попытки × 2s delay)

```python
def _check_balances_with_retry(self, market_info, attempts=3, delay=2.0):
    for attempt in range(attempts):
        try:
            balances = contract.functions.balanceOfBatch(accounts, ids).call()
            return int(balances[0]), int(balances[1])
        except Exception as exc:
            if attempt < attempts - 1:
                time.sleep(delay)
    raise last_exc
```

---

### `run_live_loop.py` — Adaptive interval state machine

**Новые CLI аргументы:**

| аргумент | default | описание |
|----------|---------|----------|
| `--redeem-interval N` | 300 | active interval (сек) |
| `--redeem-idle-interval N` | 900 | idle interval когда нет новых filled (сек) |
| `--redeem-idle-threshold N` | 3 | пустых сканов для перехода в IDLE |
| `--redeem-lookback-days N` | 2 | сколько дней назад смотреть в логах |

**State machine:**

```
ACTIVE (interval=300s)
  │
  │ new_to_check > 0 → stay ACTIVE, reset empty_scans=0
  │
  │ new_to_check = 0 → empty_scans++
  │   if empty_scans >= 3:
  └──────────────────────────────► IDLE (interval=900s)
                                      │
                                      │ new_to_check > 0 → ACTIVE
                                      │ new_to_check = 0 → stay IDLE
```

**Логи переходов:**
```
[REDEEM] state: ACTIVE → IDLE (3 empty scans, next in 900s)
[REDEEM] state: IDLE → ACTIVE (new candidate found)
```

---

## State Files Summary

| файл | назначение | формат |
|------|-----------|--------|
| `data/logs/redeem_done.json` | отредимленные slugs | `{slug: tx_hash}` |
| `data/logs/redeem_pending.json` | TX отправлены, receipt ожидается | `{slug: {tx_hash, round_id, ...}}` |

Оба файла пишутся атомарно через `.tmp` + `rename`.

---

## Команда для следующего теста

```bash
python scripts/run_live_loop.py \
  --market-key btc_updown_5m \
  --iterations 720 \
  --interval-seconds 5 \
  --live \
  --redeem-interval 300 \
  --redeem-lookback-days 2
```

**Ожидаемые логи при суточном прогоне:**
```
RedeemWorker started (active=300s, idle=900s, lookback=2d, dry_run=False)

# Пока нет новых filled:
[REDEEM] scan: filled_in_logs=5, already_done=5, new_to_check=0   ← DEBUG, не INFO

# После 3 пустых сканов:
[REDEEM] state: ACTIVE → IDLE (3 empty scans, next in 900s)

# Когда round закрылся и баланс > 0:
[REDEEM] state: IDLE → ACTIVE (new candidate found)
[REDEEM] scan: filled_in_logs=6, already_done=5, new_to_check=1
[REDEEM] btc-updown-5m-EPOCH — YES=10960400 NO=0 (10.9604 USDC)
SafeExecutor: TX sent 0x...
SafeExecutor: TX confirmed 0x... (gas_used=143210)
[REDEEM] btc-updown-5m-EPOCH redeemed 10.9604 USDC tx=0x...

# Если TX завис в мемпуле (случается при congestion):
SafeExecutor: receipt timeout for 0x... — TX may still be pending
[REDEEM] btc-updown-5m-EPOCH TX pending (will check next iteration) tx=0x...
# На следующем скане:
[REDEEM] Checking 1 pending TX(s)...
[REDEEM] pending TX confirmed: btc-updown-5m-EPOCH 10.9604 USDC tx=0x...
```

---

## Error Root Causes (из теста)

| ошибка | причина | фикс |
|--------|---------|------|
| TX не майнится 120s | `maxFeePerGas = base_fee + 30gwei` — нет запаса | `base_fee * 2 + 30gwei` |
| TX "not in chain" → статус failed | `wait_for_transaction_receipt` кидал исключение | Catch timeout → return `{status: pending}` |
| tx_hash терялся при timeout | Не сохранялся до получения receipt | Сохранение в `redeem_pending.json` сразу при отправке |
| balanceOfBatch RPC error | Transient node issue | 3 retry × 2s |
| "Found 4 filled slugs" (всё done) | Лог до фильтрации | Фильтр done FIRST, лог DEBUG если new=0 |
