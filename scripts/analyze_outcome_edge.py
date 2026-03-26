from __future__ import annotations

"""
Stage 20 — Outcome edge validation.

Reads a resolved_decisions JSONL (output of resolve_live_paper_outcomes.py) and
computes signal winrate at two levels:

  Level 1 — Signal edge on all live rows (no execution filter applied).
             Shows whether the raw signal has predictive value independent of policy.
  Level 2 — Execution-aware edge on allowed entries (should_enter == True).
             Shows what remains after policy + execution guards.

Both levels are broken down by:
  - signal_tier
  - time_bucket × distance_bucket

An intermediate cut on policy_allowed rows is also included.

Winrate definition:
  winrate = correct / decidable
  decidable = rows where round_winner in {UP, DOWN}  (FLAT excluded)
  correct   = rows where action_correct == True
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
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


def _winrate_stats(rows: list[dict]) -> tuple[int, int, float | None]:
    """Returns (total, decidable, winrate_pct). decidable = non-FLAT rounds."""
    total = len(rows)
    decidable = sum(1 for r in rows if r.get("action_correct") is not None)
    correct = sum(1 for r in rows if r.get("action_correct") is True)
    winrate = correct / decidable * 100 if decidable else None
    return total, decidable, winrate


def _winrate_cell(rows: list[dict]) -> str:
    total, decidable, wr = _winrate_stats(rows)
    if wr is None:
        return f"{total} rows / no decidable"
    return f"{wr:.1f}% ({decidable} decidable, {total} total)"


def load_rows(*paths: Path) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return rows


# ---------------------------------------------------------------------------
# Breakdown tables
# ---------------------------------------------------------------------------

def _tier_table(rows: list[dict]) -> str:
    by_tier: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tier[str(r.get("signal_tier", "unknown"))].append(r)

    table_rows = []
    for tier in TIERS_ORDER:
        tier_rows = by_tier.get(tier, [])
        if not tier_rows:
            table_rows.append([tier, "0", "—", "—", "—"])
            continue
        total, decidable, wr = _winrate_stats(tier_rows)
        correct = sum(1 for r in tier_rows if r.get("action_correct") is True)
        wr_str = f"{wr:.1f}%" if wr is not None else "—"
        table_rows.append([tier, str(total), str(decidable), str(correct), wr_str])

    return _table(["tier", "total", "decidable", "correct", "winrate"], table_rows)


def _bucket_table(rows: list[dict]) -> str:
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        bk = f"{r.get('time_bucket', '?')}|{r.get('distance_bucket', '?')}"
        by_bucket[bk].append(r)

    # Sort by count descending
    sorted_buckets = sorted(by_bucket.items(), key=lambda x: len(x[1]), reverse=True)

    table_rows = []
    for bk, bk_rows in sorted_buckets:
        total, decidable, wr = _winrate_stats(bk_rows)
        correct = sum(1 for r in bk_rows if r.get("action_correct") is True)
        wr_str = f"{wr:.1f}%" if wr is not None else "—"
        table_rows.append([bk, str(total), str(decidable), str(correct), wr_str])

    return _table(["bucket", "total", "decidable", "correct", "winrate"], table_rows)


def _section(title: str, rows: list[dict], note: str = "") -> list[str]:
    total, decidable, wr = _winrate_stats(rows)
    correct = sum(1 for r in rows if r.get("action_correct") is True)
    up = sum(1 for r in rows if r.get("round_winner") == "UP")
    down = sum(1 for r in rows if r.get("round_winner") == "DOWN")
    flat = sum(1 for r in rows if r.get("round_winner") == "FLAT")
    wr_str = f"{wr:.1f}%" if wr is not None else "n/a"

    lines = [
        f"## {title}",
        "",
    ]
    if note:
        lines += [f"_{note}_", ""]
    lines += [
        f"- rows: {total}",
        f"- round outcomes: UP={up}  DOWN={down}  FLAT={flat}",
        f"- decidable (non-FLAT): {decidable}",
        f"- correct: {correct}",
        f"- **overall winrate: {wr_str}**",
        "",
        "### By signal tier",
        "",
        _tier_table(rows),
        "",
        "### By time×distance bucket",
        "",
        _bucket_table(rows),
        "",
    ]
    return lines


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def analyze_outcome_edge(rows: list[dict]) -> str:
    # Resolved rows only (resolve_status == "ok")
    resolved = [r for r in rows if r.get("resolve_status") == "ok"]

    # Population definitions
    all_rows = resolved
    policy_allowed = [r for r in resolved if r.get("policy_reason") == "policy_allowed"]
    allowed_entries = [r for r in resolved if r.get("should_enter") is True]

    unique_rounds = len({str(r["round_id"]) for r in resolved})
    up = sum(1 for r in resolved if r.get("round_winner") == "UP")
    down = sum(1 for r in resolved if r.get("round_winner") == "DOWN")
    flat = sum(1 for r in resolved if r.get("round_winner") == "FLAT")

    header = [
        "# Outcome Edge Validation Report",
        "",
        f"- total_resolved_rows: {len(resolved)}",
        f"- unique_rounds: {unique_rounds}",
        f"- round_distribution: UP={up}  DOWN={down}  FLAT={flat}",
        f"- policy_allowed_rows: {len(policy_allowed)}",
        f"- allowed_entries (should_enter=True): {len(allowed_entries)}",
        "",
        "**Winrate definition:** correct / decidable,",
        "where decidable = rows with round_winner in {UP, DOWN} (FLAT excluded).",
        "",
        "---",
        "",
    ]

    body: list[str] = []

    body += _section(
        "Level 1A — All Resolved Rows (raw signal, no execution filter)",
        all_rows,
        "Baseline signal quality. Includes rows blocked by policy and execution guards.",
    )

    body += _section(
        "Level 1B — Policy-Allowed Rows",
        policy_allowed,
        "Rows where tier+time policy passed. May still be blocked by spread/slippage guards.",
    )

    body += _section(
        "Level 2 — Allowed Entries (should_enter = True)",
        allowed_entries,
        "Rows where all filters passed: policy + spread + slippage + confidence guards.",
    )

    # Cross-section: Level 2 by tier with slippage cost context
    if allowed_entries:
        slippages = [float(r.get("expected_slippage_bps", 0)) for r in allowed_entries]
        mean_slip = fmean(slippages)
        _, decidable, wr = _winrate_stats(allowed_entries)
        wr_str = f"{wr:.1f}%" if wr is not None else "n/a"
        body += [
            "## Edge vs Cost Summary (Level 2)",
            "",
            f"- mean_slippage_bps: {mean_slip:.0f}",
            f"- overall_winrate: {wr_str}",
            "",
            "For a strategy to be profitable:",
            "  edge = (winrate - 0.5) × avg_payout must exceed mean_slippage cost.",
            "",
            "At 50% winrate the strategy breaks even on signal.",
            "Signal edge (winrate > 50%) is required before slippage cost is worth paying.",
            "",
        ]

    return "\n".join(header + body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 20: outcome edge validation on resolved decisions JSONL."
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
    report = analyze_outcome_edge(rows)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / "docs" / "reports" / f"outcome_edge_{timestamp}.md"
    output_path.write_text(report, encoding="utf-8")
    print(output_path)
    print(f"  resolved rows: {sum(1 for r in rows if r.get('resolve_status') == 'ok')}")
