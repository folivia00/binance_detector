from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


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


def analyze_time_of_day(rows: list[dict]) -> str:
    # live rows only
    live_rows = [r for r in rows if r.get("snapshot_source") == "live"]

    by_hour: dict[int, list[dict]] = defaultdict(list)
    for row in live_rows:
        ts = datetime.fromisoformat(str(row["ts"]))
        by_hour[ts.hour].append(row)

    # overall stats for context
    all_spreads = sorted(float(r.get("pm_spread_bps", 0.0)) for r in live_rows)
    overall_mean = fmean(all_spreads) if all_spreads else 0.0
    overall_p50 = _percentile(all_spreads, 0.50)
    overall_p95 = _percentile(all_spreads, 0.95)

    hour_rows: list[list[str]] = []
    for hour in sorted(by_hour):
        hrs = by_hour[hour]
        spreads = sorted(float(r.get("pm_spread_bps", 0.0)) for r in hrs)
        liquidities = [float(r.get("pm_book_liquidity", 0.0)) for r in hrs]
        spread_too_wide = sum(1 for r in hrs if "spread_too_wide" in r.get("guard_reasons", []))
        allowed = sum(1 for r in hrs if r.get("should_enter"))
        policy_allowed = sum(1 for r in hrs if r.get("policy_reason") == "policy_allowed")

        mean_spread = fmean(spreads) if spreads else 0.0
        p50_spread = _percentile(spreads, 0.50)
        p95_spread = _percentile(spreads, 0.95)
        mean_liq = fmean(liquidities) if liquidities else 0.0
        stw_rate = spread_too_wide / len(hrs) if hrs else 0.0

        hour_rows.append([
            f"{hour:02d}:00",
            str(len(hrs)),
            str(policy_allowed),
            f"{mean_spread:.0f}",
            f"{p50_spread:.0f}",
            f"{p95_spread:.0f}",
            f"{mean_liq:.0f}",
            f"{stw_rate:.1%}",
            str(allowed),
        ])

    # best windows: hours with lowest mean spread among those with >= 20 rows
    eligible = [(h, by_hour[h]) for h in by_hour if len(by_hour[h]) >= 20]
    best_hours = sorted(
        eligible,
        key=lambda x: fmean(float(r.get("pm_spread_bps", 0.0)) for r in x[1]),
    )[:5]

    best_rows: list[list[str]] = []
    for hour, hrs in best_hours:
        spreads = [float(r.get("pm_spread_bps", 0.0)) for r in hrs]
        allowed = sum(1 for r in hrs if r.get("should_enter"))
        best_rows.append([
            f"{hour:02d}:00",
            str(len(hrs)),
            f"{fmean(spreads):.0f}",
            f"{_percentile(sorted(spreads), 0.50):.0f}",
            str(allowed),
        ])

    lines = [
        "# Time-of-Day Spread and Liquidity Report",
        "",
        f"- total_live_rows: {len(live_rows)}",
        f"- hours_covered: {len(by_hour)}",
        f"- overall_mean_pm_spread_bps: {overall_mean:.0f}",
        f"- overall_p50_pm_spread_bps: {overall_p50:.0f}",
        f"- overall_p95_pm_spread_bps: {overall_p95:.0f}",
        "",
        "## Hourly Breakdown (UTC)",
        "",
        "Columns: `stw_rate` = spread_too_wide / all rows in that hour.",
        "",
        _table(
            ["hour_utc", "rows", "policy_allowed", "mean_spread_bps",
             "p50_spread_bps", "p95_spread_bps", "mean_liquidity", "stw_rate", "allowed_entries"],
            hour_rows,
        ),
        "",
        "## Best Liquidity Windows (lowest mean spread, min 20 rows)",
        "",
        _table(
            ["hour_utc", "rows", "mean_spread_bps", "p50_spread_bps", "allowed_entries"],
            best_rows,
        ),
        "",
        "## Interpretation Notes",
        "",
        "- Hours with `mean_spread_bps` < 2000 and `stw_rate` < 50% are candidates for a time-of-day filter in entry policy.",
        "- Hours where `allowed_entries` > 0 despite low `policy_allowed` indicate execution-side liquidity windows.",
        "- Cross-reference with BTC volatility schedule (US market open 13:30–16:00 UTC, Asia 00:00–04:00 UTC).",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Time-of-day spread and liquidity analysis from live paper loop JSONL.")
    parser.add_argument("input_files", nargs="+", help="One or more JSONL files to combine.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    paths = [Path(f) for f in args.input_files]
    rows = load_rows(*paths)
    report = analyze_time_of_day(rows)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = ROOT / "docs" / "reports" / f"time_of_day_report_{timestamp}.md"
    output_path.write_text(report, encoding="utf-8")
    print(output_path)
