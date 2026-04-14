import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.agents.research_worker_agent import ResearchWorkerAgent
from pm_agent_worker.agents.verifier_agent import VerifierAgent


class ResearchQualityMetadataTest(unittest.TestCase):
    def test_build_evidence_record_populates_normalized_metadata(self) -> None:
        agent = ResearchWorkerAgent()

        record = agent._build_evidence_record(
            request={"topic": "AI 眼镜", "industry_template": "ai_product"},
            task={"id": "task-1", "market_step": "user-research", "title": "用户需求"},
            result={"title": "Official help center"},
            analysis={
                "quote": "Users want to trace claims back to source material.",
                "summary": "帮助中心内容显示产品强调可追溯性。",
                "extracted_fact": "可追溯性是核心价值点。",
                "confidence": 0.82,
                "tags": ["page-content", "official"],
                "competitor_name": "Ray-Ban Meta",
            },
            evidence_index=1,
            source_url="https://docs.example.com/help/traceability",
            source_type="documentation",
            published_at="2026-04-02T00:00:00+00:00",
            authority_score=0.9,
            retrieval_trace={
                "query": "ai glasses official pricing",
                "query_id": "task-1-query-1",
                "wave_key": "anchor",
                "wave_index": "1",
                "provider": "Bing",
                "rank": "2",
                "score": "33.666",
                "topic_match_score": "2.345",
                "alias_match_tokens": ["ai glasses", "", "ai glasses"],
                "query_tags": ["official", "Pricing", "official"],
            },
        )

        self.assertEqual(record["normalized_fact"], "可追溯性是核心价值点。")
        self.assertEqual(record["raw_support"], "Users want to trace claims back to source material.")
        self.assertEqual(record["extraction_method"], "page_content")
        self.assertEqual(record["freshness_bucket"], "last_30_days")
        self.assertIn("topic:ai-眼镜", record["entity_ids"])
        self.assertIn("competitor:ray-ban-meta", record["entity_ids"])
        self.assertEqual(record["reliability_scores"]["authority"], 0.9)
        self.assertEqual(record["reliability_scores"]["freshness"], 0.82)
        self.assertEqual(record["reliability_scores"]["relevance"], 0.82)
        self.assertEqual(record["query_plan_id"], "task-1-query-1")
        self.assertEqual(record["retrieval_trace"]["provider"], "bing")
        self.assertEqual(record["retrieval_trace"]["rank"], 2)
        self.assertEqual(record["retrieval_trace"]["score"], 33.67)
        self.assertEqual(record["retrieval_trace"]["topic_match_score"], 2.35)
        self.assertEqual(record["retrieval_trace"]["alias_match_tokens"], ["ai glasses"])
        self.assertEqual(record["retrieval_trace"]["query_tags"], ["official", "pricing"])

    def test_verifier_build_claims_populates_support_matrix_and_verification_state(self) -> None:
        agent = VerifierAgent()

        claims = agent.build_claims(
            {"job_id": "job-1", "topic": "AI PM", "research_mode": "standard"},
            [
                {
                    "id": "e1",
                    "market_step": "recommendations",
                    "confidence": 0.84,
                    "authority_score": 0.88,
                    "source_tier": "t1",
                    "competitor_name": None,
                    "quote": "",
                    "summary": "官方资料建议先跑转化验证。",
                    "extracted_fact": "先验证转化路径。",
                },
                {
                    "id": "e2",
                    "market_step": "recommendations",
                    "confidence": 0.79,
                    "authority_score": 0.74,
                    "source_tier": "t2",
                    "competitor_name": None,
                    "quote": "",
                    "summary": "第三方分析建议先验证付费意愿。",
                    "extracted_fact": "先验证付费意愿。",
                },
            ],
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], "verified")
        self.assertEqual(claims[0]["verification_state"], "supported")
        self.assertEqual(claims[0]["supporting_evidence_ids"], ["e1", "e2"])
        self.assertEqual(claims[0]["contradicting_evidence_ids"], [])
        self.assertEqual(claims[0]["decision_impact"], "high")
        self.assertIn("平均置信度", claims[0]["confidence_reason"])


if __name__ == "__main__":
    unittest.main()
