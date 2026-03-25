from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from collections import Counter

from binance_detector.analytics.reverse_exit import ReverseExitRecord
from binance_detector.analytics.simulator import RoundSummary, SimulationReport


@dataclass(slots=True)
class BucketStats:
    bucket_key: str
    entries: int
    wins: int
    pnl: float
    avg_edge: float
    avg_late_damage: float
    reverse_saved_loss: float
    reverse_cut_winner: float

    @property
    def winrate(self) -> float:
        return self.wins / self.entries if self.entries else 0.0


def _safe_mean(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _bucket_stats(
    bucket_key: str,
    summaries: list[RoundSummary],
    reverse_records: list[ReverseExitRecord],
) -> BucketStats:
    wins = sum(1 for summary in summaries if summary.pnl > 0)
    late_damage_values = [
        abs(summary.pnl)
        for summary in summaries
        if summary.pnl < 0 and summary.time_bucket in {"late", "final"}
    ]
    return BucketStats(
        bucket_key=bucket_key,
        entries=len(summaries),
        wins=wins,
        pnl=sum(summary.pnl for summary in summaries),
        avg_edge=_safe_mean([summary.avg_edge_at_entry for summary in summaries]),
        avg_late_damage=_safe_mean(late_damage_values),
        reverse_saved_loss=sum(item.saved_loss for item in reverse_records),
        reverse_cut_winner=sum(item.cut_winner for item in reverse_records),
    )


def summarize_by_time_distance(report: SimulationReport) -> list[BucketStats]:
    groups: dict[str, list[RoundSummary]] = {}
    reverse_groups: dict[str, list[ReverseExitRecord]] = {}
    for summary in report.round_summaries:
        if summary.entry_side is None or summary.time_bucket is None or summary.distance_bucket is None:
            continue
        key = f"{summary.time_bucket}|{summary.distance_bucket}"
        groups.setdefault(key, []).append(summary)
    for record in report.reverse_exit_records:
        key = f"{record.time_left_bucket}|{record.distance_bucket}"
        reverse_groups.setdefault(key, []).append(record)
    return sorted(
        (
            _bucket_stats(key, summaries, reverse_groups.get(key, []))
            for key, summaries in groups.items()
        ),
        key=lambda item: (item.bucket_key, -item.entries),
    )


def summarize_by_tier(report: SimulationReport) -> list[BucketStats]:
    groups: dict[str, list[RoundSummary]] = {}
    reverse_groups: dict[str, list[ReverseExitRecord]] = {}
    for summary in report.round_summaries:
        if summary.entry_side is None or summary.signal_tier is None:
            continue
        groups.setdefault(summary.signal_tier, []).append(summary)
    for record in report.reverse_exit_records:
        reverse_groups.setdefault(record.signal_tier, []).append(record)
    order = {"weak": 0, "medium": 1, "strong": 2, "very_strong": 3}
    return sorted(
        (
            _bucket_stats(key, summaries, reverse_groups.get(key, []))
            for key, summaries in groups.items()
        ),
        key=lambda item: order.get(item.bucket_key, 99),
    )


def identify_late_damage_zones(report: SimulationReport, min_entries: int = 3) -> list[BucketStats]:
    candidates = [
        bucket
        for bucket in summarize_by_time_distance(report)
        if bucket.entries >= min_entries
        and bucket.bucket_key.split("|", 1)[0] in {"late", "final"}
        and bucket.avg_late_damage > 0
    ]
    return sorted(candidates, key=lambda item: (-item.avg_late_damage, -item.entries))


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_no data_"
    separator = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_markdown_report(report: SimulationReport, stage_name: str) -> str:
    metrics = report.metrics()
    event_counts = Counter(event.event_type for event in report.events)
    block_reason_counts = Counter(
        event.reason for event in report.events if event.event_type == "blocked_entry"
    )
    time_distance_rows = [
        [
            bucket.bucket_key,
            str(bucket.entries),
            f"{bucket.winrate:.2%}",
            f"{bucket.pnl:.4f}",
            f"{bucket.avg_edge:.4f}",
            f"{bucket.avg_late_damage:.4f}",
        ]
        for bucket in summarize_by_time_distance(report)
    ]
    tier_rows = [
        [
            bucket.bucket_key,
            str(bucket.entries),
            f"{bucket.winrate:.2%}",
            f"{bucket.pnl:.4f}",
            f"{bucket.avg_edge:.4f}",
            f"{bucket.reverse_saved_loss:.4f}",
            f"{bucket.reverse_cut_winner:.4f}",
        ]
        for bucket in summarize_by_tier(report)
    ]
    late_damage_rows = [
        [
            bucket.bucket_key,
            str(bucket.entries),
            f"{bucket.avg_late_damage:.4f}",
            f"{bucket.pnl:.4f}",
        ]
        for bucket in identify_late_damage_zones(report)
    ]
    event_rows = [
        [event_type, str(count)]
        for event_type, count in sorted(event_counts.items(), key=lambda item: item[0])
    ]
    block_rows = [
        [reason, str(count)]
        for reason, count in block_reason_counts.most_common()
    ]
    blocked_entries = sum(summary.blocked_entries for summary in report.round_summaries)
    shadow_opportunities = sum(summary.shadow_opportunities for summary in report.round_summaries)

    sections = [
        f"# {stage_name}",
        "",
        "## Simulation Summary",
        "",
        f"- rounds: {int(metrics['rounds'])}",
        f"- pnl: {metrics['pnl']:.4f}",
        f"- winrate: {metrics['winrate']:.2%}",
        f"- avg_edge_at_entry: {metrics['avg_edge_at_entry']:.4f}",
        f"- avg_late_damage: {metrics['avg_late_damage']:.4f}",
        f"- blocked_entries_total: {blocked_entries}",
        f"- shadow_opportunities_total: {shadow_opportunities}",
        f"- reverse_exit_records: {len(report.reverse_exit_records)}",
        "",
        "## Time x Distance",
        "",
        _format_table(
            ["bucket", "entries", "winrate", "pnl", "avg_edge", "avg_late_damage"],
            time_distance_rows,
        ),
        "",
        "## Event Breakdown",
        "",
        _format_table(["event_type", "count"], event_rows),
        "",
        "## Tier Usefulness",
        "",
        _format_table(
            ["tier", "entries", "winrate", "pnl", "avg_edge", "saved_loss", "cut_winner"],
            tier_rows,
        ),
        "",
        "## Block Reasons",
        "",
        _format_table(["reason", "count"], block_rows),
        "",
        "## Late Damage Zones",
        "",
        _format_table(
            ["bucket", "entries", "avg_late_damage", "pnl"],
            late_damage_rows,
        ),
        "",
    ]
    return "\n".join(sections)


def write_markdown_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
