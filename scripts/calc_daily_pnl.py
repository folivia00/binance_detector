"""Calculate per-round trade count and PnL from live paper loop log."""
import json
import sys
from collections import defaultdict

log_path = sys.argv[1] if len(sys.argv) > 1 else "data/logs/live_paper_loop_20260402T150038Z.jsonl"

rounds = defaultdict(list)
total_rows = 0

with open(log_path) as f:
    for line in f:
        row = json.loads(line)
        total_rows += 1
        if row.get("should_enter") is True:
            epoch = row.get("round_start_epoch") or row.get("round_epoch")
            if epoch:
                rounds[epoch].append(row)

# Per-round: take first entry tick only (1 trade per round)
wins = 0
losses = 0
undecided = 0
prices = []

for epoch, ticks in rounds.items():
    tick = ticks[0]  # first entry in this round
    outcome = tick.get("outcome")
    price = tick.get("pm_entry_price") or tick.get("entry_price")
    if price:
        prices.append(float(price))
    if outcome == "win":
        wins += 1
    elif outcome == "loss":
        losses += 1
    else:
        undecided += 1

decided = wins + losses
total_rounds_with_entry = len(rounds)
winrate = wins / decided if decided > 0 else 0
mean_price = sum(prices) / len(prices) if prices else 0

# PnL per dollar: win → 1/price - 1, loss → -1
pnl_per_dollar = winrate / mean_price - 1 if mean_price > 0 else 0

# Hours in log
# Stage 26 was ~14 hours, 169 rounds total
log_hours = 14.0
rounds_per_hour = total_rounds_with_entry / log_hours
rounds_per_day = rounds_per_hour * 24

print(f"=== Stage 26 — Per-Round Analysis ===")
print(f"Total ticks in log:        {total_rows}")
print(f"Rounds with entry:         {total_rounds_with_entry}")
print(f"  wins:                    {wins}")
print(f"  losses:                  {losses}")
print(f"  undecided (no outcome):  {undecided}")
print(f"Decided rounds:            {decided}")
print(f"Winrate (per round):       {winrate:.1%}")
print(f"Mean entry price:          {mean_price:.3f}")
print(f"PnL per dollar:            {pnl_per_dollar:+.1%}")
print()
print(f"=== Extrapolation to 24h ===")
print(f"Log duration:              ~{log_hours:.0f} hours")
print(f"Rounds with entry / hour:  {rounds_per_hour:.1f}")
print(f"Rounds with entry / day:   {rounds_per_day:.0f}")
print()
print(f"=== Daily Profit at stake sizes ===")
for stake in [5, 10, 25, 50, 100]:
    profit_per_trade = stake * pnl_per_dollar
    daily_profit = profit_per_trade * rounds_per_day
    print(f"  ${stake:>4}/trade → ${profit_per_trade:+.2f}/trade → ${daily_profit:+.1f}/day")
