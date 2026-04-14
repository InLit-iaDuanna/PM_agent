#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
WORKER_SRC = ROOT_DIR / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.benchmark.quality_benchmark import (  # noqa: E402
    DEFAULT_CASES_PATH,
    DEFAULT_JSON_REPORT_PATH,
    DEFAULT_RESULTS_PATH,
    render_markdown_report,
    run_benchmark,
    save_json_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic research quality benchmark.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="Path to the golden benchmark cases JSON file.")
    parser.add_argument("--results", default=str(DEFAULT_RESULTS_PATH), help="Path to benchmark result JSON file or directory.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_REPORT_PATH), help="Where to write the JSON summary report.")
    parser.add_argument("--require-all-cases", action="store_true", help="Fail when any golden topic does not have a result bundle.")
    parser.add_argument("--minimum-scored-cases", type=int, default=1, help="Minimum number of scored cases required for a passing run.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    report = run_benchmark(
        cases_path=args.cases,
        results_path=args.results,
        require_all_cases=args.require_all_cases,
        minimum_scored_cases=args.minimum_scored_cases,
    )
    print(render_markdown_report(report))
    output_path = save_json_report(report, args.json_out)
    print(f"\nJSON report written to {output_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
