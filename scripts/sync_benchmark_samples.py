#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
WORKER_SRC = ROOT_DIR / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.benchmark.quality_benchmark import (  # noqa: E402
    DEFAULT_CASES_PATH,
    build_sample_result_catalog,
)


def main() -> int:
    output_path = ROOT_DIR / "benchmarks" / "sample_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bundles = build_sample_result_catalog(DEFAULT_CASES_PATH)
    output_path.write_text(json.dumps(bundles, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(bundles)} sample benchmark bundles to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
