import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.workflows.research_workflow import ResearchWorkflowEngine


class WorkflowQualityGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ResearchWorkflowEngine(runtime_config={"llm": {"provider": "disabled"}})

    def test_assess_report_readiness_flags_single_weak_dimension_for_supplement(self) -> None:
        assessment = self.engine._assess_report_readiness(
            tasks=[
                {"market_step": "market-trends"},
                {"market_step": "user-research"},
                {"market_step": "competitor-analysis"},
            ],
            claims=[],
            evidence=[
                {"market_step": "market-trends", "source_domain": "a.com"},
                {"market_step": "market-trends", "source_domain": "b.com"},
                {"market_step": "market-trends", "source_domain": "a.com"},
                {"market_step": "user-research", "source_domain": "c.com"},
                {"market_step": "user-research", "source_domain": "d.com"},
                {"market_step": "user-research", "source_domain": "c.com"},
                {"market_step": "competitor-analysis", "source_domain": "e.com"},
            ],
        )

        self.assertTrue(assessment["needs_supplemental"])
        self.assertEqual([item["market_step"] for item in assessment["weak_dimensions"]], ["competitor-analysis"])

    def test_assess_report_readiness_avoids_full_research_when_most_dimensions_are_weak(self) -> None:
        assessment = self.engine._assess_report_readiness(
            tasks=[
                {"market_step": "market-trends"},
                {"market_step": "user-research"},
                {"market_step": "competitor-analysis"},
            ],
            claims=[],
            evidence=[
                {"market_step": "market-trends", "source_domain": "a.com"},
                {"market_step": "user-research", "source_domain": "b.com"},
                {"market_step": "competitor-analysis", "source_domain": "c.com"},
            ],
        )

        self.assertFalse(assessment["needs_supplemental"])
        self.assertEqual(len(assessment["weak_dimensions"]), 3)

    def test_run_research_executes_supplemental_collection_and_updates_quality_summary(self) -> None:
        request = {
            "job_id": "job-1",
            "topic": "AI眼镜",
            "industry_template": "ai_product",
            "research_mode": "deep",
            "depth_preset": "deep",
            "workflow_command": "deep_general_scan",
            "max_sources": 4,
            "max_subtasks": 1,
            "max_competitors": 4,
            "review_sample_target": 4,
            "time_budget_minutes": 10,
            "geo_scope": ["中国"],
            "output_locale": "zh-CN",
        }
        job = self.engine.build_job_blueprint(dict(request))
        publish = AsyncMock()

        self.engine.planner.build_tasks = Mock(
            return_value=[
                {
                    "id": "task-1",
                    "category": "market_trends",
                    "title": "市场趋势",
                    "brief": "研究 AI 眼镜市场趋势。",
                    "market_step": "market-trends",
                    "status": "queued",
                    "source_count": 0,
                    "retry_count": 0,
                    "latest_error": None,
                }
            ]
        )

        async def fake_collect_evidence(_request, task, _competitor_names, _browser, on_progress=None, cancel_probe=None):
            if str(task.get("id") or "").startswith("job-1-supplement-"):
                return [
                {
                    "id": "e2",
                    "market_step": "market-trends",
                    "source_domain": "b.com",
                    "source_url": "https://b.com/trends",
                    "source_type": "web",
                    "confidence": 0.81,
                    "authority_score": 0.78,
                },
                {
                    "id": "e3",
                    "market_step": "market-trends",
                    "source_domain": "c.com",
                    "source_url": "https://c.com/trends",
                    "source_type": "article",
                    "confidence": 0.79,
                    "authority_score": 0.74,
                },
            ]
            return [
                {
                    "id": "e1",
                    "market_step": "market-trends",
                    "source_domain": "a.com",
                    "source_url": "https://a.com/trends",
                    "source_type": "web",
                    "confidence": 0.76,
                    "authority_score": 0.71,
                }
            ]

        self.engine.research_worker.collect_evidence = AsyncMock(side_effect=fake_collect_evidence)
        self.engine.verifier.build_claims = Mock(
            side_effect=[
                [
                    {
                        "id": "c1",
                        "claim_text": "当前市场窗口存在，但证据仍偏单薄。",
                        "market_step": "market-trends",
                        "status": "directional",
                        "confidence": 0.62,
                        "actionability_score": 0.7,
                        "evidence_ids": ["e1"],
                    }
                ],
                [
                    {
                        "id": "c1",
                        "claim_text": "市场窗口已经获得多域名交叉验证。",
                        "market_step": "market-trends",
                        "status": "confirmed",
                        "confidence": 0.88,
                        "actionability_score": 0.84,
                        "evidence_ids": ["e1", "e2", "e3"],
                    },
                    {
                        "id": "c2",
                        "claim_text": "价格敏感度正在下降。",
                        "market_step": "market-trends",
                        "status": "verified",
                        "confidence": 0.74,
                        "actionability_score": 0.72,
                        "evidence_ids": ["e1", "e2"],
                    },
                    {
                        "id": "c3",
                        "claim_text": "用户需求仍在早期探索阶段。",
                        "market_step": "market-trends",
                        "status": "directional",
                        "confidence": 0.6,
                        "actionability_score": 0.55,
                        "evidence_ids": ["e3"],
                    },
                    {
                        "id": "c4",
                        "claim_text": "某些增长预期仍有争议。",
                        "market_step": "market-trends",
                        "status": "disputed",
                        "confidence": 0.56,
                        "actionability_score": 0.4,
                        "evidence_ids": ["e1"],
                        "counter_evidence_ids": ["e9"],
                    },
                ],
            ]
        )
        self.engine.synthesizer.extract_competitors = Mock(return_value=[])
        self.engine.synthesizer.build_report = Mock(return_value={"markdown": "# 报告", "stage": "draft", "section_count": 1})

        assets = asyncio.run(self.engine.run_research(job, dict(request), publish))

        self.assertEqual(self.engine.research_worker.collect_evidence.await_count, 2)
        self.assertEqual(self.engine.verifier.build_claims.call_count, 2)
        self.assertEqual(len(assets["evidence"]), 3)
        self.assertEqual(job["quality_score_summary"]["formal_claim_count"], 4)
        self.assertEqual(job["quality_score_summary"]["formal_evidence_count"], 3)
        self.assertEqual(job["quality_score_summary"]["formal_domain_count"], 3)
        self.assertEqual(job["quality_score_summary"]["confirmed_claim_count"], 1)
        self.assertEqual(job["quality_score_summary"]["verified_claim_count"], 1)
        self.assertEqual(job["quality_score_summary"]["directional_claim_count"], 1)
        self.assertEqual(job["quality_score_summary"]["disputed_claim_count"], 1)


if __name__ == "__main__":
    unittest.main()
