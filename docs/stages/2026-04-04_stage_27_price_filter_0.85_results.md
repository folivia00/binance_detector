# Stage 27 — Price Filter 0.85 Results & Optimal Threshold Confirmed

**Date:** 2026-04-04
**Duration:** 14.1 hours
**Rounds:** 170 total, 103 with entry (61%)
**Config:** max_entry_price=0.85 (lowered from 0.92 in Stage 26)

---

## Objective

Test whether a tighter price filter (0.85 vs 0.92) improves PnL by ensuring better entry prices at the cost of fewer trades.

---

## Results

### Level 2 — Allowed Entries (should_enter=True)

| metric | value |
|--------|-------|
| entry ticks | 287 |
| decidable | 209 |
| winrate | **73.7%** |
| mean_entry_price | 0.694 |
| PnL/dollar | **+6.2%** |

### By bucket

| bucket | decidable | winrate |
|--------|-----------|---------|
| mid\|near | 186 | 74.7% |
| final\|near | 13 | 76.9% |
| late\|far | 10 | 50.0% |

---

## Comparison with Stage 26 (0.92)

| metric | Stage 26 (0.92) | Stage 27 (0.85) | delta |
|--------|----------------|----------------|-------|
| rounds/day | ~236 | ~176 | −60 |
| winrate | **80.5%** | 73.7% | −6.8% |
| mean price | 0.755 | 0.694 | −0.061 |
| PnL/dollar | **+6.6%** | +6.2% | −0.4% |
| $5/trade/day | **+$78** | +$54 | −$24 |

---

## Analysis

Tightening the price filter from 0.92 → 0.85 hurt performance on all metrics:

1. **Winrate dropped** from 80.5% → 73.7%. The trades excluded in the 0.85–0.92 range were disproportionately winning trades — the market was correctly pricing confident signals.

2. **Fewer trades** (176/day vs 236/day) with lower PnL means significantly less daily income.

3. **late|far degraded** to 50% winrate (break-even) — that bucket needs at least moderate price uncertainty (0.85–0.92) to be profitable.

4. **PnL nearly identical** (+6.2% vs +6.6%) despite a 6% lower mean entry price — confirming that lower price alone doesn't guarantee better returns if winrate drops proportionally.

---

## Conclusion

**max_entry_price=0.92 is the optimal threshold.**

The sweet spot is confirmed: prices below 0.92 indicate the market hasn't fully priced in the direction. Prices below 0.85 tend to reflect rounds with genuinely low signal confidence, not just market uncertainty — hence the winrate drop.

**Action taken:** Reverted `max_entry_price` to 0.92 in `basis_guards_v1.json`.

---

## Daily PnL Projection (at 0.92, Stage 26 metrics)

| stake | per trade | per day (~236 trades) |
|-------|-----------|-----------------------|
| $5 | +$0.33 | **+$78** |
| $10 | +$0.66 | **+$156** |
| $25 | +$1.65 | **+$390** |
| $50 | +$3.30 | **+$779** |

---

## Next Steps

- **Stage 28:** Live Execution Engine — replace PaperExecutionEngine with real CLOB orders on Polymarket
- **Stage 29:** First real trades at minimal stakes ($5/trade)
- Strategy parameters are now frozen: policy=entry_policy_v2.json, max_entry_price=0.92, mid|near as primary bucket

---

## Price Filter Progression Summary

| stage | max_entry_price | winrate | PnL | trades/day |
|-------|----------------|---------|-----|------------|
| 24 | none | ~60% | +0.9% | ~288 |
| 26 | 0.92 | **80.5%** | **+6.6%** | 236 |
| 27 | 0.85 | 73.7% | +6.2% | 176 |
| **optimal** | **0.92** | **80.5%** | **+6.6%** | **236** |
