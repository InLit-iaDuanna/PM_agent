import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.agents.research_worker_agent import ResearchWorkerAgent


class SearchStrategyImprovementsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = ResearchWorkerAgent()
        self.task = {
            "id": "task-1",
            "category": "competitor_analysis",
            "market_step": "competitor-analysis",
        }

    def test_research_is_insufficient_when_domain_ratio_is_too_low(self) -> None:
        snapshot = {
            "required_query_tags": [],
            "covered_query_tags": [],
            "missing_skill_targets": {},
            "step_domain_counts": {"competitor-analysis": 3},
            "primary_source_evidence": 3,
            "high_confidence_evidence": 4,
            "unique_domains": 3,
            "evidence_count": 10,
        }

        self.assertFalse(self.agent._research_is_sufficient(self.task, snapshot, target_sources=4))

    def test_research_is_insufficient_when_high_confidence_ratio_is_too_low(self) -> None:
        snapshot = {
            "required_query_tags": [],
            "covered_query_tags": [],
            "missing_skill_targets": {},
            "step_domain_counts": {"competitor-analysis": 4},
            "primary_source_evidence": 3,
            "high_confidence_evidence": 2,
            "unique_domains": 4,
            "evidence_count": 10,
        }

        self.assertFalse(self.agent._research_is_sufficient(self.task, snapshot, target_sources=4))

    def test_research_is_sufficient_with_good_diversity_and_signal_mix(self) -> None:
        snapshot = {
            "required_query_tags": ["official", "analysis"],
            "covered_query_tags": ["official", "analysis"],
            "missing_skill_targets": {},
            "step_domain_counts": {"competitor-analysis": 3},
            "primary_source_evidence": 3,
            "high_confidence_evidence": 3,
            "unique_domains": 3,
            "evidence_count": 6,
        }

        self.assertTrue(self.agent._research_is_sufficient(self.task, snapshot, target_sources=4))

    def test_research_is_insufficient_with_zero_evidence(self) -> None:
        snapshot = {
            "required_query_tags": [],
            "covered_query_tags": [],
            "missing_skill_targets": {},
            "step_domain_counts": {},
            "primary_source_evidence": 0,
            "high_confidence_evidence": 0,
            "unique_domains": 0,
            "evidence_count": 0,
        }

        self.assertFalse(self.agent._research_is_sufficient(self.task, snapshot, target_sources=3))

    def test_extract_wave_findings_filters_by_wave_index(self) -> None:
        findings = self.agent._extract_wave_findings(
            [
                {
                    "competitor_name": "Ray-Ban Meta",
                    "source_domain": "meta.com",
                    "extracted_fact": "Ray-Ban Meta focuses on capture and assistant features.",
                    "confidence": 0.8,
                    "retrieval_trace": {"wave_index": 1},
                },
                {
                    "competitor_name": "XREAL",
                    "source_domain": "xreal.com",
                    "extracted_fact": "XREAL focuses on display experiences.",
                    "confidence": 0.81,
                    "retrieval_trace": {"wave_index": 2},
                },
            ],
            wave_index=0,
        )

        self.assertEqual(findings["competitor_names"], ["Ray-Ban Meta"])
        self.assertEqual(findings["covered_domains"], ["meta.com"])
        self.assertEqual(findings["unique_domains"], 1)

    def test_extract_wave_findings_ignores_missing_trace(self) -> None:
        findings = self.agent._extract_wave_findings(
            [
                {
                    "competitor_name": "Ray-Ban Meta",
                    "source_domain": "meta.com",
                    "extracted_fact": "Ray-Ban Meta focuses on capture and assistant features.",
                    "confidence": 0.8,
                }
            ],
            wave_index=0,
        )

        self.assertEqual(findings["evidence_count"], 0)
        self.assertEqual(findings["competitor_names"], [])

    def test_rewrite_validation_queries_uses_discovered_entities_and_review_domains(self) -> None:
        request = {"topic": "AI眼镜", "output_locale": "zh-CN"}
        rewritten = self.agent._rewrite_validation_queries(
            request=request,
            task=self.task,
            original_queries=["AI眼镜 官方 对比"],
            anchor_findings={
                "competitor_names": ["Ray-Ban Meta"],
                "covered_domains": ["meta.com"],
                "key_claims_to_verify": ["Battery life is still a tradeoff"],
                "unique_domains": 1,
            },
            competitor_names=["XREAL"],
        )

        combined = " || ".join(rewritten).lower()
        self.assertIn("ray-ban meta", combined)
        self.assertIn("xreal", combined)
        self.assertTrue(any(query.startswith("site:") for query in rewritten))

    def test_build_search_waves_does_not_exceed_query_budget(self) -> None:
        task = {
            **self.task,
            "query_budget": 8,
        }
        queries = [f"query {index}" for index in range(30)]

        waves = self.agent._build_search_waves(task, queries)

        self.assertLessEqual(sum(len(wave["queries"]) for wave in waves), 8)


if __name__ == "__main__":
    unittest.main()
