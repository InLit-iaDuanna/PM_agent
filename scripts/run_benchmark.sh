#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./common.sh
source "$ROOT_DIR/scripts/common.sh"

PYTHON_BIN="${PM_AGENT_PYTHON:-$(_find_any_python)}"
if [[ -z "$PYTHON_BIN" ]]; then
  _print_error "python3 or python is required to run the benchmark."
  exit 1
fi

BENCHMARK_TOPICS_FILE="${BENCHMARK_TOPICS_FILE:-$ROOT_DIR/packages/research-core/data/golden_research_benchmarks.json}"
BENCHMARK_RESULTS_PATH="${BENCHMARK_RESULTS_PATH:-$ROOT_DIR/benchmarks/sample_results.json}"
BENCHMARK_JSON_OUT="${BENCHMARK_JSON_OUT:-$ROOT_DIR/tmp/benchmark-quality-report.json}"
BENCHMARK_REQUIRE_ALL_CASES="${BENCHMARK_REQUIRE_ALL_CASES:-0}"
BENCHMARK_MINIMUM_SCORED_CASES="${BENCHMARK_MINIMUM_SCORED_CASES:-1}"

ARGS=(
  "$ROOT_DIR/scripts/run_quality_benchmark.py"
  "--cases" "$BENCHMARK_TOPICS_FILE"
  "--results" "$BENCHMARK_RESULTS_PATH"
  "--json-out" "$BENCHMARK_JSON_OUT"
  "--minimum-scored-cases" "$BENCHMARK_MINIMUM_SCORED_CASES"
)

if [[ "$BENCHMARK_REQUIRE_ALL_CASES" == "1" ]]; then
  ARGS+=("--require-all-cases")
fi

exec "$PYTHON_BIN" "${ARGS[@]}"
