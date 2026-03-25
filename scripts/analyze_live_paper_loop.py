from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_detector.analytics.live_loop_reporting import (
    analyze_live_loop,
    render_live_loop_comparison,
    render_live_loop_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze live paper loop JSONL and emit markdown report.")
    parser.add_argument("input_file")
    parser.add_argument("--compare-to", default="")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    input_path = Path(args.input_file)
    analysis = analyze_live_loop(input_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.compare_to:
        compare_path = Path(args.compare_to)
        compare_analysis = analyze_live_loop(compare_path)
        output_path = ROOT / "docs" / "reports" / f"live_paper_loop_compare_{timestamp}.md"
        output_path.write_text(
            render_live_loop_comparison(compare_path, compare_analysis, input_path, analysis),
            encoding="utf-8",
        )
    else:
        output_path = ROOT / "docs" / "reports" / f"live_paper_loop_report_{timestamp}.md"
        output_path.write_text(render_live_loop_report(input_path, analysis), encoding="utf-8")
    print(output_path)
