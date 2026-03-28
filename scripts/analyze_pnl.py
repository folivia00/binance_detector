from __future__ import annotations

"""
Stage 22 — Trade-level PnL validation.

Reads resolved_decisions JSONL (output of resolve_live_paper_outcomes.py) and
computes expected PnL for allowed entries using the actual PM entry price.

PnL model (Polymarket binary token):
  - You buy a token at pm_entry_price (e.g. 0.72 = 72 cents)
  - Token settles at $1.00 if correct, $0.00 if wrong
  - Per dollar staked:
      win  → gross return = 1/pm_entry_price, net = 1/pm_entry_price - 1
      loss → net = -1
  - Expected net PnL per dollar = winrate × (1/p - 1) + (1 - winrate) × (-1)
                                 = winrate/p - 1
  - Breakeven: pm_entry_price = winrate (e.g. 80% winrate → breakeven at p=0.80)

Rows without pm_entry_price (old JSONL pre-Stage 22) are skipped for PnL
but still counted in winrate tables.
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TIERS_ORDER = ["weak", "medium", "strong", "very_strong"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_no data_"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def load_rows(*paths: Path) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return rows


def _pnl(winrate: float, entry_price: float) -> float:
    """Expected net PnL per dollar staked."""
    return winrate / entry_price - 1.0


def _pnl_stats(rows: list[dict]) -> dict:
    """
    Returns dict with winrate, mean_entry_price, implied_payout,
    expected_pnl_pct, has_entry_price (bool).
    """
    decidable = [r for r in rows if r.get("action_correct") is not None]
    correct = [r for r in decidable if r["action_correct"] is True]
    winrate = len(correct) / len(decidable) if decidable else None

    priced = [r for r in rows if float(r.get("pm_entry_price", 0)) > 0]
    if not priced:
        return {
            "total": len(rows), "decidable": len(decidable),
            "winrate": winrate, "has_entry_price": False,
        }

    prices = [float(r["pm_entry_price"]) for r in priced]
    mean_p = fmean(prices)
    median_p = median(prices)
    implied_payout = 1.0 / mean_p if mean_p > 0 else None
    exp_pnl = _pnl(winrate, mean_p) if winrate is not None and mean_p > 0 else None
    breakeven_p = winrate if winrate is not None else None

    return {
        "total": len(rows),
        "decidable": len(decidable),
        "priced": len(priced),
        "winrate": winrate,
        "mean_entry_price": mean_p,
        "median_entry_price": median_p,
        "implied_payout_x": implied_payout,
        "expected_pnl_pct": exp_pnl,
        "breakeven_price": breakeven_p,
        "has_entry_price": True,
    }


def _pnl_row(label: str, stats: dict) -> list[str]:
    wr = stats.get("winrate")
    wr_s = f"{wr:.1%}" if wr is not None else "—"
    if not stats.get("has_entry_price"):
        return [label, str(stats["decidable"]), wr_s, "—", "—", "—", "—"]
    p = stats.get("mean_entry_price", 0)
    pay = stats.get("implied_payout_x")
    pnl = stats.get("expected_pnl_pct")
    be = stats.get("breakeven_price")
    p_s = f"{p:.3f}" if p else "—"
    pay_s = f"{pay:.3f}x" if pay else "—"
    pnl_s = f"{pnl:+.1%}" if pnl is not None else "—"
    be_s = f"{be:.3f}" if be else "—"
    return [label, str(stats["decidable"]), wr_s, p_s, pay_s, pnl_s, be_s]


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def analyze_pnl(rows: list[dict]) -> str:
    resolved = [r for r in rows if r.get("resolve_status") == "ok"]
    allowed = [r for r in resolved if r.get("should_enter") is True]
    policy_allowed = [r for r in resolved if r.get("policy_reason") == "policy_allowed"]

    has_prices = any(float(r.get("pm_entry_price", 0)) > 0 for r in allowed)

    up = sum(1 for r in resolved if r.get("round_winner") == "UP")
    down = sum(1 for r in resolved if r.get("round_winner") == "DOWN")
    flat = sum(1 for r in resolved if r.get("round_winner") == "FLAT")

    header = [
        "# Trade-Level PnL Validation Report",
        "",
        f"- total_resolved_rows: {len(resolved)}",
        f"- policy_allowed_rows: {len(policy_allowed)}",
        f"- allowed_entries (should_enter=True): {len(allowed)}",
        f"- round_distribution: UP={up}  DOWN={down}  FLAT={flat}",
        f"- pm_entry_price available: {'yes' if has_prices else 'no (pre-Stage-22 data — prices are 0)'}",
        "",
        "**PnL formula (per dollar staked):**",
        "  win  → net = 1/pm_entry_price − 1",
        "  loss → net = −1",
        "  expected = winrate/pm_entry_price − 1",
        "  breakeven at pm_entry_price = winrate",
        "",
        "---",
        "",
    ]

    body: list[str] = []

    # --- Overall summary table ---
    all_stats = _pnl_stats(resolved)
    pol_stats = _pnl_stats(policy_allowed)
    ent_stats = _pnl_stats(allowed)

    summary_rows = [
        _pnl_row("all rows", all_stats),
        _pnl_row("policy_allowed", pol_stats),
        _pnl_row("allowed_entries", ent_stats),
    ]
    body += [
        "## Summary",
        "",
        _table(
            ["population", "decidable", "winrate", "mean_entry_price",
             "implied_payout", "expected_pnl", "breakeven_price"],
            summary_rows,
        ),
        "",
    ]

    if not has_prices:
        body += [
            "> **Note:** `pm_entry_price` is 0 for all rows — this JSONL was recorded",
            "> before Stage 22. Run a new live loop and resolve to get PnL numbers.",
            "> Winrate column above is valid; PnL columns require entry price data.",
            "",
        ]
    else:
        # Approximate PnL at different assumed winrate scenarios
        if ent_stats.get("mean_entry_price"):
            p = ent_stats["mean_entry_price"]
            body += [
                "## PnL Sensitivity (allowed_entries)",
                "",
                f"At mean_entry_price = {p:.3f} ({p*100:.1f} cents per token):",
                "",
            ]
            scenario_rows = []
            for wr in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90, 1.00]:
                pnl = _pnl(wr, p)
                scenario_rows.append([f"{wr:.0%}", f"{pnl:+.1%}"])
            body += [
                _table(["winrate_scenario", "expected_pnl_per_dollar"], scenario_rows),
                "",
                f"**Actual observed winrate:** {ent_stats['winrate']:.1%} "
                f"→ expected PnL = {ent_stats['expected_pnl_pct']:+.1%} per dollar",
                "",
            ]

    # --- By tier (allowed_entries) ---
    if allowed:
        by_tier: dict[str, list[dict]] = defaultdict(list)
        for r in allowed:
            by_tier[str(r.get("signal_tier", "unknown"))].append(r)

        tier_rows = []
        for tier in TIERS_ORDER:
            s = _pnl_stats(by_tier.get(tier, []))
            if s["decidable"] == 0:
                continue
            tier_rows.append(_pnl_row(tier, s))

        if tier_rows:
            body += [
                "## By Signal Tier (allowed_entries)",
                "",
                _table(
                    ["tier", "decidable", "winrate", "mean_entry_price",
                     "implied_payout", "expected_pnl", "breakeven_price"],
                    tier_rows,
                ),
                "",
            ]

    # --- By bucket (allowed_entries) ---
    if allowed:
        by_bucket: dict[str, list[dict]] = defaultdict(list)
        for r in allowed:
            bk = f"{r.get('time_bucket', '?')}|{r.get('distance_bucket', '?')}"
            by_bucket[bk].append(r)

        bucket_rows = []
        for bk, bk_rows in sorted(by_bucket.items(), key=lambda x: len(x[1]), reverse=True):
            s = _pnl_stats(bk_rows)
            if s["decidable"] == 0:
                continue
            bucket_rows.append(_pnl_row(bk, s))

        if bucket_rows:
            body += [
                "## By Bucket (allowed_entries)",
                "",
                _table(
                    ["bucket", "decidable", "winrate", "mean_entry_price",
                     "implied_payout", "expected_pnl", "breakeven_price"],
                    bucket_rows,
                ),
                "",
            ]

    return "\n".join(header + body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 22: trade-level PnL validation on resolved decisions JSONL."
    )
    parser.add_argument(
        "input_files", nargs="+",
        help="One or more resolved_decisions JSONL files.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    paths = [Path(f) for f in args.input_files]
    rows = load_rows(*paths)
    report = analyze_pnl(rows)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / "docs" / "reports" / f"pnl_validation_{timestamp}.md"
    output_path.write_text(report, encoding="utf-8")
    print(output_path)
