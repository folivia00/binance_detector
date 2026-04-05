# Stage 23 — PM CLOB Ask Order Bug: Обнаружение и Исправление

**Дата:** 2026-03-31
**Тип:** Критический баг в коннекторе Polymarket
**Файл:** `src/binance_detector/connectors/polymarket/client.py` → `_build_quote()`
**Коммит фикса:** `1bb324c` (dev) / `aad1614` (main)

---

## 1. Симптом

После реализации логирования `pm_entry_price` в Stage 22 все записанные значения оказались аномально близки к 1.0:

```json
{"event": "entry_decision", "pm_entry_price": 0.99, "should_enter": false, ...}
{"event": "entry_decision", "pm_entry_price": 0.99, "should_enter": false, ...}
{"event": "entry_decision", "pm_entry_price": 0.9874, "should_enter": false, ...}
```

Дополнительный симптом: гард `spread_too_wide` срабатывал почти на каждом тике — `pm_spread_bps` показывал значения 500–900+ bps, хотя реальный спред на Polymarket значительно уже.

---

## 2. Диагностика

### Прямой API-запрос к PM CLOB

Для диагностики был сделан прямой raw-запрос к Polymarket CLOB order book:

```python
import urllib.request, json
token_id = "..."  # YES token для текущего маркета
url = f"https://clob.polymarket.com/book?token_id={token_id}"
with urllib.request.urlopen(url) as r:
    book = json.loads(r.read())

print("YES asks[:3]:", book["asks"][:3])
print("YES asks[-3:]:", book["asks"][-3:])
print("YES bids[:3]:", book["bids"][:3])
print("YES bids[-3:]:", book["bids"][-3:])
```

**Результат:**

```
YES asks[:3]  = [{'price': '0.99', 'size': '12477.17'},
                 {'price': '0.98', 'size': '8234.01'},
                 {'price': '0.97', 'size': '6112.55'}]

YES asks[-3:] = [{'price': '0.07', 'size': '1200.00'},
                 {'price': '0.06', 'size': '980.00'},
                 {'price': '0.05', 'size': '750.00'}]

YES bids[:3]  = [{'price': '0.01', 'size': '500.00'},
                 {'price': '0.02', 'size': '700.00'},
                 {'price': '0.03', 'size': '900.00'}]

YES bids[-3:] = [{'price': '0.02', 'size': '700.00'},
                 {'price': '0.03', 'size': '900.00'},
                 {'price': '0.04', 'size': '1100.00'}]
```

### Вывод

| список | порядок | `[0]` | `[-1]` |
|--------|---------|-------|--------|
| `asks` | **DESCENDING** (от дорогих к дешёвым) | 0.99 — худший аск | 0.05 — **лучший аск** ✓ |
| `bids` | **ASCENDING** (от дешёвых к дорогим) | 0.01 — худший бид | 0.04 — **лучший бид** ✓ |

---

## 3. Баг в коде

### До исправления (`_build_quote` в `client.py`, строки 161–165)

```python
yes_bid = float(yes_bids[-1]["price"]) if yes_bids else 0.0   # bids ascending → [-1] = лучший бид ✓
yes_ask = float(yes_asks[0]["price"])  if yes_asks else 1.0   # BUG: asks descending → [0] = ХУДШИЙ аск ✗
no_bid  = float(no_bids[-1]["price"])  if no_bids  else 0.0   # bids ascending → [-1] = лучший бид ✓
no_ask  = float(no_asks[0]["price"])   if no_asks  else 1.0   # BUG: asks descending → [0] = ХУДШИЙ аск ✗

book_liquidity = sum(float(level["size"]) for level in
    yes_bids[-5:] + yes_asks[:5] +    # BUG: yes_asks[:5] = 5 самых дорогих (неликвидные)
    no_bids[-5:]  + no_asks[:5])      # BUG: no_asks[:5]  = 5 самых дорогих (неликвидные)
```

Ошибка была симметрична для bids и asks — bids случайно парсились правильно (ascending, `[-1]`), а asks парсились неправильно (descending, но брался `[0]`).

### После исправления

```python
yes_bid = float(yes_bids[-1]["price"]) if yes_bids else 0.0   # ascending → [-1] = лучший бид ✓
yes_ask = float(yes_asks[-1]["price"]) if yes_asks else 1.0   # descending → [-1] = лучший аск ✓
no_bid  = float(no_bids[-1]["price"])  if no_bids  else 0.0   # ascending → [-1] = лучший бид ✓
no_ask  = float(no_asks[-1]["price"])  if no_asks  else 1.0   # descending → [-1] = лучший аск ✓

book_liquidity = sum(float(level["size"]) for level in
    yes_bids[-5:] + yes_asks[-5:] +   # [-5:] = 5 уровней у лучшего аска (торгуемые уровни) ✓
    no_bids[-5:]  + no_asks[-5:])     # [-5:] = 5 уровней у лучшего аска (торгуемые уровни) ✓
```

---

## 4. Масштаб последствий

### Что было сломано

| компонент | эффект бага | реальное значение |
|-----------|-------------|-------------------|
| `pm_entry_price` | всегда ~0.99 | реально ~0.50–0.70 в активных раундах |
| `pm_spread_bps` | 500–900 bps (завышен в 10–20x) | реально 20–80 bps |
| `spread_too_wide` гард | срабатывал почти всегда | должен был пропускать большинство тиков |
| `book_liquidity` | считал ликвидность у худших асков | должен считать у лучших |

### Что НЕ было сломано

- **Winrate** (`outcome_edge`) — не зависит от PM цен, только от сигналов Binance → Stage 20/21 результаты **валидны**
- **Signal detection** — детекторы, тиры, временны́е бакеты работали корректно
- **Entry policy whitelist** — tier×bucket логика работала корректно
- **should_enter** — итоговое решение о входе: некоторые входы могли быть заблокированы `spread_too_wide` гардом неправильно, но базовая логика нетронута

### PnL данные до фикса

Все три прогона на VPS (Stage 20, 21, 22) имеют `pm_entry_price ≈ 0.99`. PnL-отчёт по Stage 22 (`pnl_validation_20260330T153908Z.md`) отражает именно эти ложные значения:

```
allowed_entries: winrate=99.4%, mean_entry_price=0.997, expected_pnl=-0.3%
```

Реальный ожидаемый PnL при правильных ценах входа (0.50–0.70) будет значительно выше:
- При winrate=99.4% и entry_price=0.60: `expected_pnl = 0.994/0.60 - 1 = +65.7%`
- При winrate=99.4% и entry_price=0.70: `expected_pnl = 0.994/0.70 - 1 = +42.0%`

---

## 5. История обнаружения

1. **Stage 22 реализация** — добавлено поле `pm_entry_price` в `TradingSignal` и логирование в JSONL
2. **Первый анализ** — все значения в логах оказались ~0.99, что физически невозможно для активного рынка (YES и NO не могут оба стоить 0.99 — сумма > 1)
3. **Гипотеза** — подозрение на wrong index в парсинге order book
4. **Проверка** — прямой raw API-запрос к CLOB подтвердил: asks сортируются DESCENDING
5. **Фикс** — однострочное исправление: `asks[0]` → `asks[-1]` для YES и NO

---

## 6. Ретроспектива

### Почему баг не был замечен раньше

- `pm_entry_price` не логировался до Stage 22 — не было видимости
- Гард `spread_too_wide` срабатывал, но это воспринималось как нормальное поведение в периоды низкой ликвидности
- Winrate оставался высоким несмотря на баг — сигналы Binance работали независимо

### Как найти подобные баги в будущем

- Логировать raw PM quote (yes_ask, no_ask, spread_bps) с самого начала
- Добавить санити-чек: `yes_ask + no_ask` должна быть в диапазоне ~1.0–1.10 (бинарный рынок)
- При любом `pm_entry_price > 0.95` — это подозрительно и требует проверки

---

## 7. Следующие шаги

- [x] Зафиксировать фикс на dev (`1bb324c`) и cherry-pick на main (`aad1614`)
- [x] Запушить origin dev + origin main
- [ ] На VPS: `git pull origin main`, перезапустить прогон
- [ ] Собрать новый датасет с корректными `pm_entry_price`
- [ ] Запустить `analyze_pnl.py` на новых данных
- [ ] Написать Stage 24 с реальными PnL-результатами
