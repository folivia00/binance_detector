# Live Execution Error Log

Журнал ошибок в live-режиме торговли (run_live_loop.py --live).
Каждая запись: дата, симптом, причина, исправление.

---

## #1 — 2026-04-04 | BUY не импортируется из py_clob_client

**Файл:** `src/binance_detector/execution/live.py`

**Симптом:**
```
status=error
error=cannot import name 'BUY' from 'py_clob_client.clob_types'
```

**Причина:**
В `live.py` использовалось `from py_clob_client.clob_types import MarketOrderArgs, BUY`.
Константа `BUY` не экспортируется из этой версии библиотеки (0.34.6).

**Исправление:**
```python
# было:
side=BUY
# стало:
side="BUY"
```

---

## #2 — 2026-04-04 | Цена нарушает минимальный tick size (0.01)

**Файл:** `src/binance_detector/execution/live.py`

**Симптом:**
```
status=error
error=PolyApiException[status_code=400,
  error_message={'error': 'order 0x... is invalid.
  Price (0.8400114241553685) breaks minimum tick size rule: 0.01'}]
```

**Причина:**
`create_market_order` без явной цены берёт её из стакана через `calculate_market_price()` — возвращает float с многими знаками. PM требует кратность 0.01.

Попытка округлить `rounded_price` перед передачей в `MarketOrderArgs` не помогла — builder внутри всё равно пересчитывал цену.

**Исправление:**
Переход с `MarketOrderArgs` + `create_market_order` на `OrderArgs` + `create_order(FOK)`:
```python
from decimal import Decimal, ROUND_HALF_UP
rounded_price = float(Decimal(str(ask_price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
order_args = OrderArgs(token_id=token_id, price=rounded_price, size=size, side="BUY")
signed_order = self._clob.create_order(order_args, PartialCreateOrderOptions(tick_size="0.01"))
resp = self._clob.post_order(signed_order, OrderType.FOK)
```

---

## #3 — 2026-04-04 | Неверная точность amounts (maker/taker)

**Файл:** `src/binance_detector/execution/live.py`

**Симптом:**
```
status=error
error=PolyApiException[status_code=400,
  error_message={'error': 'invalid amounts, the market buy orders
  maker amount supports a max accuracy of 2 decimals,
  taker amount a max of 4 decimals'}]
```

**Причина:**
`size` (taker amount = количество shares) округлялся до 2 знаков (`Decimal("0.01")`).
PM требует:
- maker amount (USDC) — максимум 2 знака
- taker amount (shares) — максимум 4 знака

**Исправление:**
```python
# было:
size = float(Decimal(...).quantize(Decimal("0.01"), ...))
# стало:
size = float(Decimal(...).quantize(Decimal("0.0001"), ...))
```

---

## #4 — 2026-04-04 | PM цена из maker/taker не кратна tick size (глубокий баг SDK)

**Файл:** `src/binance_detector/execution/live.py`

**Симптом:**
```
error=PolyApiException[status_code=400,
  error_message={'error': 'order 0x... is invalid.
  Price (0.9100009100009) breaks minimum tick size rule: 0.01'}]
```

**Причина:**
PM проверяет цену не из нашего запроса, а вычисляет её из signed order как `maker_amount / taker_amount` в integer units (×10^6). При maker=5000000, taker=5494500: `5000000/5494500 = 0.9100009...` — не кратно 0.01.

SDK корректно округляет taker до 4 знаков (5.4945), но PM требует чтобы `price × size` было точно кратно 0.01. Для цены 0.91: 5.0/0.91 = 5.4945054... — рациональная дробь с бесконечным периодом, точное представление невозможно в формате `maker_int/taker_int`.

**Исправление:**
1. Перейти с FOK на **GTC limit** ордер (размещается на стакане, заполняется мгновенно при наличии liquidity). Добавлена автоотмена если статус `"live"` (нет заполнения).
2. Вычислять `size` (shares) так, чтобы `price × size` имело ≤ 2 знаков после запятой:
   - Итерировать вниз от `floor(stake/price, 0.01)` пока условие не выполнено
   - Всегда расходуем ≤ stake_usd (никогда не превышаем)

```python
# Найти size (shares) где price × size имеет ≤ 2 decimal places
p = Decimal(str(rounded_price))
size_dec = (Decimal(str(stake_usd)) / p).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
for _ in range(200):
    maker = (p * size_dec).quantize(Decimal("0.000001"))
    if maker == maker.quantize(Decimal("0.01")):
        break
    size_dec -= Decimal("0.01")
```

**Реальные суммы при stake_usd=5.0:**

| цена | size (shares) | потрачено USDC |
|------|---------------|----------------|
| 0.91 | 5.00 | $4.55 |
| 0.88 | 5.50 | $4.84 |
| 0.84 | 5.75 | $4.83 |
| 0.69 | 7.00 | $4.83 |

---

_(продолжение следует по мере появления ошибок)_
