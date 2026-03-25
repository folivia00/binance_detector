from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from binance_detector.analytics.live_loop_reporting import (
    analyze_live_loop,
    render_live_loop_comparison,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


class LiveLoopReportingTests(unittest.TestCase):
    def test_comparison_report_includes_tier_and_bucket_sections(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            before_path = tmp_path / "before.jsonl"
            after_path = tmp_path / "after.jsonl"
            _write_jsonl(
                before_path,
                [
                    {
                        "ts": "2026-03-24T11:00:00+00:00",
                        "snapshot_source": "live",
                        "round_id": "r1",
                        "confidence": 0.92,
                        "signal_tier": "very_strong",
                        "policy_reason": "policy_allowed",
                        "guard_reasons": ["spread_too_wide"],
                        "paper_reasons": ["slippage_too_high"],
                        "fallback_reason": "",
                        "time_bucket": "late",
                        "distance_bucket": "stretched",
                        "should_enter": False,
                        "raw_score": 0.4,
                        "probability_edge": 0.42,
                        "calibration_version": "v0",
                    },
                    {
                        "ts": "2026-03-24T11:00:10+00:00",
                        "snapshot_source": "live",
                        "round_id": "r2",
                        "confidence": 0.68,
                        "signal_tier": "strong",
                        "policy_reason": "blocked_by_policy",
                        "guard_reasons": [],
                        "paper_reasons": [],
                        "fallback_reason": "",
                        "time_bucket": "mid",
                        "distance_bucket": "far",
                        "should_enter": True,
                        "raw_score": 0.2,
                        "probability_edge": 0.18,
                        "calibration_version": "v0",
                    },
                ],
            )
            _write_jsonl(
                after_path,
                [
                    {
                        "ts": "2026-03-24T12:00:00+00:00",
                        "snapshot_source": "live",
                        "round_id": "r3",
                        "confidence": 0.71,
                        "signal_tier": "strong",
                        "policy_reason": "policy_allowed",
                        "guard_reasons": ["spread_too_wide"],
                        "paper_reasons": [],
                        "fallback_reason": "",
                        "time_bucket": "mid",
                        "distance_bucket": "far",
                        "should_enter": True,
                        "raw_score": 0.21,
                        "probability_edge": 0.21,
                        "calibration_version": "v1",
                    },
                    {
                        "ts": "2026-03-24T12:00:10+00:00",
                        "snapshot_source": "live",
                        "round_id": "r4",
                        "confidence": 0.59,
                        "signal_tier": "medium",
                        "policy_reason": "policy_allowed",
                        "guard_reasons": [],
                        "paper_reasons": ["slippage_too_high"],
                        "fallback_reason": "",
                        "time_bucket": "early",
                        "distance_bucket": "at_open",
                        "should_enter": False,
                        "raw_score": 0.09,
                        "probability_edge": 0.09,
                        "calibration_version": "v1",
                    },
                ],
            )

            before = analyze_live_loop(before_path)
            after = analyze_live_loop(after_path)
            report = render_live_loop_comparison(before_path, before, after_path, after)

        self.assertIn("## Tier Distribution", report)
        self.assertIn("## Allowed Entry Buckets", report)
        self.assertIn("## Policy Blockers", report)
        self.assertIn("## Guard Blockers", report)
        self.assertIn("## Paper Blockers", report)
        self.assertIn("## Time x Distance Coverage", report)
        self.assertIn("## Execution Bottleneck Buckets", report)
        self.assertIn("late|stretched", report)
        self.assertIn("slippage_too_high", report)


if __name__ == "__main__":
    unittest.main()
