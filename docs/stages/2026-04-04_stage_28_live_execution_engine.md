# Stage 28 — Live Execution Engine (Polymarket CLOB Orders)

**Date:** 2026-04-04
**Branch:** dev → main (cherry-pick)
**Status:** Implemented, tested in dry_run mode

---

## Objective

Replace the `PaperExecutionEngine` (simulation only) with a `LiveExecutionEngine` capable of placing real FOK market orders on the Polymarket CLOB. All strategy parameters remain frozen from Stage 26–27.

---

## Architecture

```
run_live_loop.py
    └── LivePaperRunner.evaluate_once()       ← signal generation (unchanged)
          └── LiveExecutionEngine.execute()   ← NEW: real order placement
                ├── dry_run=True → log only, no real orders
                └── dry_run=False → ClobClient.create_market_order + post_order
```

---

## New Files

### `src/binance_detector/execution/live.py`

**`LiveExecutionConfig`** — loaded from `configs/live_execution_v1.json`:

| field | default | description |
|-------|---------|-------------|
| `stake_usd` | 5.0 | USDC per trade |
| `cooldown_seconds` | 30 | min seconds between trades |
| `min_entry_confidence` | 0.55 | minimum model confidence |
| `no_entry_last_seconds` | 10 | don't enter in last N seconds of round |
| `dry_run` | **true** | safety flag — must be set false explicitly for real orders |

**`LiveExecutionResult`** — returned by `execute()`:

| field | description |
|-------|-------------|
| `allowed` | whether pre-flight checks passed |
| `dry_run` | whether this was a simulated trade |
| `status` | `"filled"` / `"dry_run"` / `"blocked"` / `"cancelled"` / `"error"` |
| `order_id` | PM CLOB order ID (None if blocked or dry_run) |
| `filled_price` | actual fill price (ask price for dry_run) |
| `filled_size_usd` | USDC actually staked |
| `block_reasons` | tuple of block reason strings |
| `error` | exception message if status=error |

**Pre-flight checks** (same as PaperExecutionEngine):
- `confidence < min_entry_confidence` → blocked
- `time_left_seconds <= no_entry_last_seconds` → blocked
- `cooldown not elapsed` → blocked
- `ask_price <= 0 or >= 1.0` → blocked (invalid quote)

**Order placement** (when `dry_run=False`):
- Uses `MarketOrderArgs(token_id, amount=stake_usd, side=BUY)` with FOK order type
- BUY the YES token if `action="YES"`, BUY the NO token if `action="NO"`
- `status="filled"` on PM response `"matched"`, `"cancelled"` otherwise

---

### `src/binance_detector/connectors/polymarket/auth.py`

`build_clob_client()` — builds `ClobClient` from environment variables.

**Auth mode: `signature_type=2` (funder/proxy)**
- No separate API key/secret/passphrase needed
- Private key signs orders directly
- Funder address = wallet holding USDC collateral

Environment variables required:
```bash
export PM_PRIVATE_KEY=0x<polygon_wallet_private_key>
export PM_FUNDER_ADDRESS=0x<wallet_address>
export PM_SIGNATURE_TYPE=2
```

---

### `configs/live_execution_v1.json`

```json
{
  "stake_usd": 5.0,
  "cooldown_seconds": 30,
  "min_entry_confidence": 0.55,
  "no_entry_last_seconds": 10,
  "dry_run": true
}
```

`dry_run: true` is the default. To enable live trading, set to `false` **on the VPS only** — never commit with `false`.

---

### `scripts/run_live_loop.py`

Main entry point for live trading.

```bash
# Dry run (safe, no orders):
python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800

# Live trading:
python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live
```

`--live` flag forces `dry_run=False` at runtime (overrides config).

**Log format** (`data/logs/live_loop_<timestamp>.jsonl`):
```json
{
  "ts": "2026-04-04T...",
  "round_id": "btc_updown_5m:20260404T120000Z",
  "action": "YES",
  "signal_tier": "very_strong",
  "time_bucket": "mid",
  "distance_bucket": "near",
  "should_enter": true,
  "pm_entry_price": 0.68,
  "confidence": 0.73,
  "snapshot_source": "live",
  "execution": {
    "status": "filled",
    "dry_run": false,
    "side": "YES",
    "stake_usd": 5.0,
    "filled_price": 0.68,
    "order_id": "0x...",
    "block_reasons": [],
    "error": null
  }
}
```

---

### `scripts/setup_pm_api_key.py`

Connection verification script. Run once on VPS to confirm wallet is reachable:

```bash
python scripts/setup_pm_api_key.py
# Output:
#   Wallet address : 0x...
#   CLOB status    : OK
#   USDC balance   : {...}
```

---

### `src/binance_detector/connectors/polymarket/client.py` (updated)

Added `get_token_ids_for_spec(spec, ts) → (yes_token_id, no_token_id)`:
- Returns cached token IDs for the current round
- Used by `run_live_loop.py` to select which token to buy

---

## VPS Setup for Live Trading

```bash
# 1. Add to ~/.bashrc
export PM_PRIVATE_KEY=0x<private_key>
export PM_FUNDER_ADDRESS=0x<wallet_address>
export PM_SIGNATURE_TYPE=2
source ~/.bashrc

# 2. Verify connection
python scripts/setup_pm_api_key.py

# 3. Run dry run first (30 min = 6 rounds)
python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 360

# 4. Enable live trading in config
# Edit configs/live_execution_v1.json: "dry_run": false
# OR use --live flag

# 5. Start live loop
nohup python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live \
  > logs/live_loop.log 2>&1 &
```

---

## Safety Design

| mechanism | description |
|-----------|-------------|
| `dry_run=true` default | real orders never placed accidentally |
| `--live` explicit flag | must be deliberately passed |
| one trade per round | `last_entered_round` prevents re-entry in same round |
| cooldown guard | 30s min between trades (prevents rapid-fire on signal bursts) |
| confidence guard | `min_entry_confidence=0.55` blocks weak signals |
| time guard | no entry in last 10s of round |
| FOK order type | Fill-or-Kill — no resting open orders left on book |

---

## Frozen Strategy Parameters (from Stage 26–27)

| parameter | value |
|-----------|-------|
| `max_entry_price` | 0.92 |
| active buckets | mid\|near (primary), late\|far, final\|near |
| allowed tiers | very_strong (+ strong in some buckets) |
| stake_usd | 5.0 (Stage 29 starting point) |
| expected winrate | ~80.5% |
| expected PnL/dollar | +6.6% |
| expected trades/day | ~236 |
| expected profit/day at $5 | ~+$78 |

---

## Next Steps

- **Stage 29:** First real trades — run with `--live`, verify fills, monitor for 24h
- Monitor `execution.status` in JSONL log: `filled` / `cancelled` / `error`
- If fill rate < 80%: raise `stake_usd` slightly (more liquidity at ask)
- After 7 days of live data: compare actual winrate vs paper winrate
