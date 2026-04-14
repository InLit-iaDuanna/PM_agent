import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.benchmark.quality_benchmark import (  # noqa: E402
    DEFAULT_CASES_PATH,
    DEFAULT_RESULTS_PATH,
    evaluate_case,
    load_benchmark_cases,
    load_benchmark_results,
    run_benchmark,
)


class QualityBenchmarkTest(unittest.TestCase):
    def test_golden_case_catalog_has_30_topics(self) -> None:
        cases = load_benchmark_cases(DEFAULT_CASES_PATH)

        self.assertEqual(len(cases), 30)
        self.assertEqual(cases[0]["id"], "cn-ai-glasses-market-trends")

    def test_sample_benchmark_report_passes_for_available_cases(self) -> None:
        report = run_benchmark(DEFAULT_CASES_PATH, DEFAULT_RESULTS_PATH, require_all_cases=True, minimum_scored_cases=30)

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["scored_case_count"], 30)
        self.assertEqual(report["summary"]["missing_case_count"], 0)
        self.assertEqual(report["summary"]["passed_case_count"], 30)

    def test_evaluate_case_detects_off_topic_regression(self) -> None:
        cases = {item["id"]: item for item in load_benchmark_cases(DEFAULT_CASES_PATH)}
        results = load_benchmark_results(DEFAULT_RESULTS_PATH)
        bundle = deepcopy(results["cn-ai-glasses-market-trends"])
        bundle["assets"]["evidence"][0]["title"] = "Download fonts for design mockups"
        bundle["assets"]["evidence"][0]["summary"] = "A generic font install guide."
        bundle["assets"]["evidence"][0]["source_url"] = "https://figma.cool/fonts/install-guide"
        bundle["assets"]["evidence"][0]["source_domain"] = "figma.cool"

        result = evaluate_case(cases["cn-ai-glasses-market-trends"], bundle)

        self.assertFalse(result["scores"]["precision"]["passed"])
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
