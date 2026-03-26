from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

THRESHOLDS_BPS = [650, 1500, 3000, 5000, 10000]

TIERS_ORDER = ["weak", "medium", "strong", "very_strong"]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = max(0, int(len(sorted_values) * pct) - 1)
    return sorted_values[idx]


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


def _would_enter(row: dict, threshold_bps: float) -> bool:
    """Simulate entry under relaxed spread+slippage threshold, keeping all other guards."""
    if row.get("snapshot_source") != "live":
        return False
    if row.get("policy_reason") != "policy_allowed":
        return False
    if float(row.get("pm_spread_bps", 999_999)) > threshold_bps:
        return False
    if float(row.get("expected_slippage_bps", 999_999)) > threshold_bps:
        return False
    # Keep time guard: min_entry_tleft still blocks
    guard_reasons = [str(g) for g in row.get("guard_reasons", [])]
    if "min_entry_tleft" in guard_reasons:
        return False
    # Keep confidence guard: low_confidence still blocks
    paper_reasons = [str(p) for p in row.get("paper_reasons", [])]
    if "low_confidence" in paper_reasons:
        return False
    return True


def analyze_counterfactual(rows: list[dict]) -> str:
    live_rows = [r for r in rows if r.get("snapshot_source") == "live"]
    total = len(live_rows)

    # --- Summary table: one row per threshold ---
    summary_rows: list[list[str]] = []
    threshold_details: dict[int, dict] = {}

    for t in THRESHOLDS_BPS:
        passing = [r for r in live_rows if _would_enter(r, t)]
        count = len(passing)
        rate = count / total if total else 0.0
        delta = count - len([r for r in live_rows if _would_enter(r, THRESHOLDS_BPS[0])])

        slippages = sorted(float(r.get("expected_slippage_bps", 0.0)) for r in passing)
        spreads = sorted(float(r.get("pm_spread_bps", 0.0)) for r in passing)
        mean_slip = fmean(slippages) if slippages else 0.0
        p95_slip = _percentile(slippages, 0.95)
        mean_spread = fmean(spreads) if spreads else 0.0
        p95_spread = _percentile(spreads, 0.95)

        summary_rows.append([
            str(t),
            str(count),
            f"{rate:.2%}",
            f"{delta:+d}" if t != THRESHOLDS_BPS[0] else "baseline",
            f"{mean_spread:.0f}",
            f"{p95_spread:.0f}",
            f"{mean_slip:.0f}",
            f"{p95_slip:.0f}",
        ])

        threshold_details[t] = {
            "passing": passing,
            "count": count,
            "mean_slip": mean_slip,
            "p95_slip": p95_slip,
        }

    # --- Per-threshold bucket breakdown ---
    bucket_sections: list[str] = []
    for t in THRESHOLDS_BPS:
        passing = threshold_details[t]["passing"]
        by_bucket: Counter[str] = Counter()
        by_tier: Counter[str] = Counter()
        for r in passing:
            bk = f"{r.get('time_bucket')}|{r.get('distance_bucket')}"
            by_bucket[bk] += 1
            by_tier[str(r.get("signal_tier", ""))] += 1

        bucket_rows = [
            [bk, str(cnt), f"{cnt / len(passing):.1%}" if passing else "0.0%"]
            for bk, cnt in by_bucket.most_common(10)
        ]
        tier_rows = [
            [tier, str(by_tier.get(tier, 0)),
             f"{by_tier.get(tier, 0) / len(passing):.1%}" if passing else "0.0%"]
            for tier in TIERS_ORDER
        ]
        bucket_sections.extend([
            f"### threshold = {t} bps  ({threshold_details[t]['count']} entries, "
            f"mean_slip={threshold_details[t]['mean_slip']:.0f} bps, "
            f"p95_slip={threshold_details[t]['p95_slip']:.0f} bps)",
            "",
            "**By time×distance bucket:**",
            "",
            _table(["bucket", "count", "share"], bucket_rows),
            "",
            "**By signal tier:**",
            "",
            _table(["tier", "count", "share"], tier_rows),
            "",
        ])

    lines = [
        "# Counterfactual Threshold Relaxation Analysis",
        "",
        f"- total_live_rows: {total}",
        f"- thresholds_tested_bps: {THRESHOLDS_BPS}",
        "- logic: entry passes if policy_allowed AND pm_spread_bps ≤ T AND expected_slippage_bps ≤ T",
        "- guards still active: min_entry_tleft, low_confidence",
        "- guards relaxed: spread_too_wide, slippage_too_high",
        "",
        "## Summary",
        "",
        _table(
            ["max_spread_bps", "entries", "entry_rate", "delta_vs_650",
             "mean_spread_bps", "p95_spread_bps", "mean_slip_bps", "p95_slip_bps"],
            summary_rows,
        ),
        "",
        "## Per-Threshold Breakdown",
        "",
    ] + bucket_sections + [
        "## Decision Framework",
        "",
        "- `mean_slip_bps` = average cost to enter per side at this threshold.",
        "- For a strategy to be profitable, its signal edge must exceed `mean_slip_bps` in expectation.",
        "- At `max_spread_bps=650`: conservative, only best liquidity windows.",
        "- At `max_spread_bps=3000`: broader access but mean slippage rises substantially.",
        "- Threshold should only be relaxed once signal edge is validated against outcome data.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Counterfactual analysis: how many entries at relaxed spread/slippage thresholds."
    )
    parser.add_argument("input_files", nargs="+", help="One or more JSONL files to combine.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    paths = [Path(f) for f in args.input_files]
    rows = load_rows(*paths)
    report = analyze_counterfactual(rows)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / "docs" / "reports" / f"counterfactual_thresholds_{timestamp}.md"
    output_path.write_text(report, encoding="utf-8")
    print(output_path)
