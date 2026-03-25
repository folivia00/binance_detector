from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
import json


@dataclass(slots=True)
class LiveLoopAnalysis:
    total_rows: int
    observed_rounds: int
    completed_rounds: int
    start_ts: datetime
    end_ts: datetime
    live_rows: int
    demo_rows: int
    effective_cadence_seconds: float
    allowed_entries: int
    fallback_reasons: Counter
    signal_tiers: Counter
    policy_reasons: Counter
    guard_reasons: Counter
    paper_reasons: Counter
    time_buckets: Counter
    distance_buckets: Counter
    evaluations_by_bucket: Counter
    allowed_by_bucket: Counter
    guard_blocked_by_bucket: Counter
    paper_blocked_by_bucket: Counter
    spread_blocked_by_bucket: Counter
    slippage_blocked_by_bucket: Counter
    allowed_by_tier: dict[str, int]
    mean_confidence: float
    p95_confidence: float
    mean_probability_edge: float
    p95_probability_edge: float
    mean_raw_score: float
    p95_raw_score: float
    mean_basis_bps: float
    p95_abs_basis_bps: float
    mean_pm_spread_bps: float
    p95_pm_spread_bps: float
    mean_expected_slippage_bps: float
    p95_expected_slippage_bps: float
    mean_pm_quote_age_seconds: float
    p95_pm_quote_age_seconds: float
    calibration_versions: Counter


def load_live_loop_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def analyze_live_loop(path: Path) -> LiveLoopAnalysis:
    rows = load_live_loop_rows(path)
    if not rows:
        raise ValueError(f"empty live loop file: {path}")

    times = [datetime.fromisoformat(str(row["ts"])) for row in rows]
    live_rows = sum(1 for row in rows if row["snapshot_source"] == "live")
    demo_rows = sum(1 for row in rows if row["snapshot_source"] != "live")
    signal_tiers = Counter(str(row["signal_tier"]) for row in rows)
    calibration_versions = Counter(str(row.get("calibration_version", "")) for row in rows if str(row.get("calibration_version", "")))
    policy_reasons = Counter(str(row["policy_reason"]) for row in rows)
    guard_reasons: Counter[str] = Counter()
    paper_reasons: Counter[str] = Counter()
    fallback_reasons = Counter(str(row["fallback_reason"]) for row in rows if str(row["fallback_reason"]))
    time_buckets = Counter(str(row["time_bucket"]) for row in rows if str(row["time_bucket"]))
    distance_buckets = Counter(str(row["distance_bucket"]) for row in rows if str(row["distance_bucket"]))
    evaluations_by_bucket: Counter[str] = Counter()
    allowed_by_bucket: Counter[str] = Counter()
    guard_blocked_by_bucket: Counter[str] = Counter()
    paper_blocked_by_bucket: Counter[str] = Counter()
    spread_blocked_by_bucket: Counter[str] = Counter()
    slippage_blocked_by_bucket: Counter[str] = Counter()
    allowed_by_tier: defaultdict[str, int] = defaultdict(int)

    for row in rows:
        bucket_key = f"{row.get('time_bucket')}|{row.get('distance_bucket')}"
        evaluations_by_bucket[bucket_key] += 1
        row_guard_reasons = [str(item) for item in row.get("guard_reasons", [])]
        row_paper_reasons = [str(item) for item in row.get("paper_reasons", [])]
        guard_reasons.update(row_guard_reasons)
        paper_reasons.update(row_paper_reasons)
        if row_guard_reasons:
            guard_blocked_by_bucket[bucket_key] += 1
        if row_paper_reasons:
            paper_blocked_by_bucket[bucket_key] += 1
        if "spread_too_wide" in row_guard_reasons:
            spread_blocked_by_bucket[bucket_key] += 1
        if "slippage_too_high" in row_paper_reasons:
            slippage_blocked_by_bucket[bucket_key] += 1
        if row.get("should_enter"):
            allowed_by_bucket[bucket_key] += 1
            allowed_by_tier[str(row["signal_tier"])] += 1

    unique_rounds = list(dict.fromkeys(str(row["round_id"]) for row in rows))
    completed_rounds = max(0, len(unique_rounds) - 2) if len(unique_rounds) >= 2 else 0
    total_duration_seconds = max((times[-1] - times[0]).total_seconds(), 0.0)
    effective_cadence_seconds = total_duration_seconds / max(len(rows) - 1, 1)
    confidences = [float(row["confidence"]) for row in rows]
    sorted_confidences = sorted(confidences)
    p95_index = max(0, int(len(sorted_confidences) * 0.95) - 1)
    edges = [float(row.get("probability_edge", abs(float(row["confidence"]) - 0.5))) for row in rows]
    sorted_edges = sorted(edges)
    raw_scores = [float(row.get("raw_score", 0.0)) for row in rows]
    sorted_raw_scores = sorted(raw_scores)
    basis_values = [float(row.get("basis_bps", 0.0)) for row in rows]
    sorted_abs_basis = sorted(abs(value) for value in basis_values)
    spreads = [float(row.get("pm_spread_bps", 0.0)) for row in rows]
    sorted_spreads = sorted(spreads)
    slippages = [float(row.get("expected_slippage_bps", 0.0)) for row in rows]
    sorted_slippages = sorted(slippages)
    quote_ages = [float(row.get("pm_quote_age_seconds", 0.0)) for row in rows]
    sorted_quote_ages = sorted(quote_ages)

    return LiveLoopAnalysis(
        total_rows=len(rows),
        observed_rounds=len(unique_rounds),
        completed_rounds=completed_rounds,
        start_ts=times[0],
        end_ts=times[-1],
        live_rows=live_rows,
        demo_rows=demo_rows,
        effective_cadence_seconds=effective_cadence_seconds,
        allowed_entries=sum(1 for row in rows if row.get("should_enter")),
        fallback_reasons=fallback_reasons,
        signal_tiers=signal_tiers,
        policy_reasons=policy_reasons,
        guard_reasons=guard_reasons,
        paper_reasons=paper_reasons,
        time_buckets=time_buckets,
        distance_buckets=distance_buckets,
        evaluations_by_bucket=evaluations_by_bucket,
        allowed_by_bucket=allowed_by_bucket,
        guard_blocked_by_bucket=guard_blocked_by_bucket,
        paper_blocked_by_bucket=paper_blocked_by_bucket,
        spread_blocked_by_bucket=spread_blocked_by_bucket,
        slippage_blocked_by_bucket=slippage_blocked_by_bucket,
        allowed_by_tier=dict(allowed_by_tier),
        mean_confidence=fmean(confidences),
        p95_confidence=sorted_confidences[p95_index],
        mean_probability_edge=fmean(edges),
        p95_probability_edge=sorted_edges[p95_index],
        mean_raw_score=fmean(raw_scores),
        p95_raw_score=sorted_raw_scores[p95_index],
        mean_basis_bps=fmean(basis_values),
        p95_abs_basis_bps=sorted_abs_basis[p95_index],
        mean_pm_spread_bps=fmean(spreads),
        p95_pm_spread_bps=sorted_spreads[p95_index],
        mean_expected_slippage_bps=fmean(slippages),
        p95_expected_slippage_bps=sorted_slippages[p95_index],
        mean_pm_quote_age_seconds=fmean(quote_ages),
        p95_pm_quote_age_seconds=sorted_quote_ages[p95_index],
        calibration_versions=calibration_versions,
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_no data_"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _top_union_keys(before: Counter, after: Counter, limit: int = 10) -> list[str]:
    keys = set(before) | set(after)
    return sorted(keys, key=lambda key: (before.get(key, 0) + after.get(key, 0), before.get(key, 0), after.get(key, 0), key), reverse=True)[:limit]


def _counter_compare_rows(before: Counter, after: Counter, *, limit: int = 10) -> list[list[str]]:
    rows: list[list[str]] = []
    for key in _top_union_keys(before, after, limit=limit):
        rows.append([key, str(before.get(key, 0)), str(after.get(key, 0))])
    return rows


def _bucket_compare_rows(before: Counter, after: Counter, *, before_total: int, after_total: int, limit: int = 10) -> list[list[str]]:
    rows: list[list[str]] = []
    for key in _top_union_keys(before, after, limit=limit):
        before_count = before.get(key, 0)
        after_count = after.get(key, 0)
        before_share = before_count / before_total if before_total else 0.0
        after_share = after_count / after_total if after_total else 0.0
        rows.append([key, str(before_count), f"{before_share:.2%}", str(after_count), f"{after_share:.2%}"])
    return rows


def render_live_loop_report(path: Path, analysis: LiveLoopAnalysis) -> str:
    duration = analysis.end_ts - analysis.start_ts
    tier_rows = [
        [
            tier,
            str(count),
            str(analysis.allowed_by_tier.get(tier, 0)),
            f"{count / analysis.total_rows:.2%}",
        ]
        for tier, count in analysis.signal_tiers.most_common()
    ]
    guard_rows = [[reason, str(count)] for reason, count in analysis.guard_reasons.most_common(10)]
    paper_rows = [[reason, str(count)] for reason, count in analysis.paper_reasons.most_common(10)]
    policy_rows = [[reason, str(count)] for reason, count in analysis.policy_reasons.most_common(10)]
    coverage_rows = [[bucket, str(count)] for bucket, count in analysis.evaluations_by_bucket.most_common(10)]
    allowed_rows = [[bucket, str(count)] for bucket, count in analysis.allowed_by_bucket.most_common(10)]
    guard_bucket_rows = [[bucket, str(count)] for bucket, count in analysis.guard_blocked_by_bucket.most_common(10)]
    paper_bucket_rows = [[bucket, str(count)] for bucket, count in analysis.paper_blocked_by_bucket.most_common(10)]
    fallback_rows = [[reason, str(count)] for reason, count in analysis.fallback_reasons.most_common()]

    sections = [
        "# Live Paper Loop Report",
        "",
        f"- source_file: `{path.name}`",
        f"- total_evaluations: {analysis.total_rows}",
        f"- observed_round_ids: {analysis.observed_rounds}",
        f"- estimated_completed_rounds: {analysis.completed_rounds}",
        f"- start_ts: {analysis.start_ts.isoformat()}",
        f"- end_ts: {analysis.end_ts.isoformat()}",
        f"- duration: {duration}",
        f"- live_snapshots: {analysis.live_rows}",
        f"- demo_snapshots: {analysis.demo_rows}",
        f"- effective_cadence_seconds: {analysis.effective_cadence_seconds:.2f}",
        f"- allowed_entries: {analysis.allowed_entries}",
        f"- mean_confidence: {analysis.mean_confidence:.4f}",
        f"- p95_confidence: {analysis.p95_confidence:.4f}",
        f"- mean_probability_edge: {analysis.mean_probability_edge:.4f}",
        f"- p95_probability_edge: {analysis.p95_probability_edge:.4f}",
        f"- mean_raw_score: {analysis.mean_raw_score:.4f}",
        f"- p95_raw_score: {analysis.p95_raw_score:.4f}",
        f"- mean_basis_bps: {analysis.mean_basis_bps:.4f}",
        f"- p95_abs_basis_bps: {analysis.p95_abs_basis_bps:.4f}",
        f"- mean_pm_spread_bps: {analysis.mean_pm_spread_bps:.2f}",
        f"- p95_pm_spread_bps: {analysis.p95_pm_spread_bps:.2f}",
        f"- mean_expected_slippage_bps: {analysis.mean_expected_slippage_bps:.2f}",
        f"- p95_expected_slippage_bps: {analysis.p95_expected_slippage_bps:.2f}",
        f"- mean_pm_quote_age_seconds: {analysis.mean_pm_quote_age_seconds:.2f}",
        f"- p95_pm_quote_age_seconds: {analysis.p95_pm_quote_age_seconds:.2f}",
        "",
        "## Data Quality",
        "",
        f"- live_ratio: {analysis.live_rows / analysis.total_rows:.2%}",
        f"- demo_ratio: {analysis.demo_rows / analysis.total_rows:.2%}",
        "",
        _table(["fallback_reason", "count"], fallback_rows),
        "",
        "## Calibration Versions",
        "",
        _table(["version", "count"], [[version, str(count)] for version, count in analysis.calibration_versions.items()]),
        "",
        "## Tier Saturation",
        "",
        _table(["tier", "rows", "allowed_entries", "share"], tier_rows),
        "",
        "## Time x Distance Coverage",
        "",
        _table(["time|distance", "evaluations"], coverage_rows),
        "",
        "## Policy Reasons",
        "",
        _table(["policy_reason", "count"], policy_rows),
        "",
        "## Guard Blockers",
        "",
        _table(["guard_reason", "count"], guard_rows),
        "",
        "## Paper Blockers",
        "",
        _table(["paper_reason", "count"], paper_rows),
        "",
        "## Allowed Entry Buckets",
        "",
        _table(["time|distance", "allowed_count"], allowed_rows),
        "",
        "## Blocked Bucket Concentration",
        "",
        "### Guard-blocked buckets",
        "",
        _table(["time|distance", "blocked_count"], guard_bucket_rows),
        "",
        "### Paper-blocked buckets",
        "",
        _table(["time|distance", "blocked_count"], paper_bucket_rows),
        "",
        "## Preliminary Findings",
        "",
        f"- main_execution_bottleneck: `{analysis.guard_reasons.most_common(1)[0][0] if analysis.guard_reasons else 'none'}` / `{analysis.paper_reasons.most_common(1)[0][0] if analysis.paper_reasons else 'none'}`",
        f"- policy_is_usually_permissive: {analysis.policy_reasons.get('policy_allowed', 0)} / {analysis.total_rows}",
        f"- very_strong_share: {analysis.signal_tiers.get('very_strong', 0) / analysis.total_rows:.2%}",
        "- note: if `very_strong_share` remains unusually high on repeated live-paper runs, tier calibration should be tightened.",
        "- note: demo fallback rows should be treated as data-quality exceptions, not as tradable signal rows.",
        "",
    ]
    return "\n".join(sections)


def render_live_loop_comparison(
    before_path: Path,
    before: LiveLoopAnalysis,
    after_path: Path,
    after: LiveLoopAnalysis,
) -> str:
    def pct(value: float) -> str:
        return f"{value:.2%}"

    rows = [
        ["total_evaluations", str(before.total_rows), str(after.total_rows)],
        ["completed_rounds", str(before.completed_rounds), str(after.completed_rounds)],
        ["live_ratio", pct(before.live_rows / before.total_rows), pct(after.live_rows / after.total_rows)],
        ["allowed_entries", str(before.allowed_entries), str(after.allowed_entries)],
        ["very_strong_share", pct(before.signal_tiers.get("very_strong", 0) / before.total_rows), pct(after.signal_tiers.get("very_strong", 0) / after.total_rows)],
        ["mean_confidence", f"{before.mean_confidence:.4f}", f"{after.mean_confidence:.4f}"],
        ["mean_raw_score", f"{before.mean_raw_score:.4f}", f"{after.mean_raw_score:.4f}"],
        ["mean_basis_bps", f"{before.mean_basis_bps:.4f}", f"{after.mean_basis_bps:.4f}"],
        ["p95_abs_basis_bps", f"{before.p95_abs_basis_bps:.4f}", f"{after.p95_abs_basis_bps:.4f}"],
        ["mean_pm_spread_bps", f"{before.mean_pm_spread_bps:.2f}", f"{after.mean_pm_spread_bps:.2f}"],
        ["p95_pm_spread_bps", f"{before.p95_pm_spread_bps:.2f}", f"{after.p95_pm_spread_bps:.2f}"],
        ["mean_expected_slippage_bps", f"{before.mean_expected_slippage_bps:.2f}", f"{after.mean_expected_slippage_bps:.2f}"],
        ["p95_expected_slippage_bps", f"{before.p95_expected_slippage_bps:.2f}", f"{after.p95_expected_slippage_bps:.2f}"],
        ["mean_pm_quote_age_seconds", f"{before.mean_pm_quote_age_seconds:.2f}", f"{after.mean_pm_quote_age_seconds:.2f}"],
        ["p95_pm_quote_age_seconds", f"{before.p95_pm_quote_age_seconds:.2f}", f"{after.p95_pm_quote_age_seconds:.2f}"],
        ["policy_allowed", str(before.policy_reasons.get("policy_allowed", 0)), str(after.policy_reasons.get("policy_allowed", 0))],
        ["spread_too_wide", str(before.guard_reasons.get("spread_too_wide", 0)), str(after.guard_reasons.get("spread_too_wide", 0))],
        ["slippage_too_high", str(before.paper_reasons.get("slippage_too_high", 0)), str(after.paper_reasons.get("slippage_too_high", 0))],
    ]
    tier_rows = [
        [
            tier,
            str(before.signal_tiers.get(tier, 0)),
            pct(before.signal_tiers.get(tier, 0) / before.total_rows),
            str(after.signal_tiers.get(tier, 0)),
            pct(after.signal_tiers.get(tier, 0) / after.total_rows),
        ]
        for tier in ["weak", "medium", "strong", "very_strong"]
    ]
    return "\n".join(
        [
            "# Live Paper Loop Comparison",
            "",
            f"- before_file: `{before_path.name}`",
            f"- after_file: `{after_path.name}`",
            "",
            _table(["metric", "before", "after"], rows),
            "",
            "## Tier Distribution",
            "",
            _table(["tier", "before_rows", "before_share", "after_rows", "after_share"], tier_rows),
            "",
            "## Allowed Entry Buckets",
            "",
            _table(
                ["time|distance", "before_count", "before_share", "after_count", "after_share"],
                _bucket_compare_rows(
                    before.allowed_by_bucket,
                    after.allowed_by_bucket,
                    before_total=before.allowed_entries,
                    after_total=after.allowed_entries,
                ),
            ),
            "",
            "## Policy Blockers",
            "",
            _table(["policy_reason", "before", "after"], _counter_compare_rows(before.policy_reasons, after.policy_reasons)),
            "",
            "## Guard Blockers",
            "",
            _table(["guard_reason", "before", "after"], _counter_compare_rows(before.guard_reasons, after.guard_reasons)),
            "",
            "## Paper Blockers",
            "",
            _table(["paper_reason", "before", "after"], _counter_compare_rows(before.paper_reasons, after.paper_reasons)),
            "",
            "## Time x Distance Coverage",
            "",
            _table(
                ["time|distance", "before_rows", "before_share", "after_rows", "after_share"],
                _bucket_compare_rows(
                    before.evaluations_by_bucket,
                    after.evaluations_by_bucket,
                    before_total=before.total_rows,
                    after_total=after.total_rows,
                ),
            ),
            "",
            "## Execution Bottleneck Buckets",
            "",
            "### spread_too_wide",
            "",
            _table(
                ["time|distance", "before_count", "before_share", "after_count", "after_share"],
                _bucket_compare_rows(
                    before.spread_blocked_by_bucket,
                    after.spread_blocked_by_bucket,
                    before_total=max(before.guard_reasons.get("spread_too_wide", 0), 1),
                    after_total=max(after.guard_reasons.get("spread_too_wide", 0), 1),
                ),
            ),
            "",
            "### slippage_too_high",
            "",
            _table(
                ["time|distance", "before_count", "before_share", "after_count", "after_share"],
                _bucket_compare_rows(
                    before.slippage_blocked_by_bucket,
                    after.slippage_blocked_by_bucket,
                    before_total=max(before.paper_reasons.get("slippage_too_high", 0), 1),
                    after_total=max(after.paper_reasons.get("slippage_too_high", 0), 1),
                ),
            ),
            "",
            "## Notes",
            "",
            "- compare tier saturation before retuning policy.",
            "- if very_strong share falls while live ratio stays stable, calibration is moving in the right direction.",
            "- if blockers stay dominated by spread/slippage after calibration, the bottleneck remains execution-side, not policy-side.",
            "",
        ]
    )
