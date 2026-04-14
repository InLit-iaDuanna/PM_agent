import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository
from pm_agent_api.services.research_job_service import ResearchJobService


class QualityGateRulesTest(unittest.TestCase):
    def _create_job(self, repository: InMemoryStateRepository, job_id: str) -> None:
        repository.create_job(
            {
                "id": job_id,
                "topic": "AI PM",
                "industry_template": "ai_product",
                "research_mode": "standard",
                "depth_preset": "light",
                "status": "completed",
                "overall_progress": 100,
                "current_phase": "finalizing",
                "eta_seconds": 0,
                "source_count": 0,
                "competitor_count": 0,
                "completed_task_count": 1,
                "running_task_count": 0,
                "failed_task_count": 0,
                "claims_count": 1,
                "report_version_id": f"{job_id}-report-v1",
                "active_report_version_id": f"{job_id}-report-v1",
                "stable_report_version_id": None,
                "phase_progress": [],
                "tasks": [],
            }
        )

    def test_finalize_blocks_t4_or_requires_external_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                self._create_job(repository, "job-quality-1")
                repository.set_assets(
                    "job-quality-1",
                    {
                        "claims": [
                            {
                                "id": "claim-delta-1",
                                "claim_text": "先验证新增付费路径。",
                                "market_step": "recommendations",
                                "confidence": 0.62,
                                "status": "verified",
                                "verification_state": "supported",
                                "priority": "high",
                                "actionability_score": 0.82,
                                "evidence_ids": ["e1"],
                                "supporting_evidence_ids": ["e1"],
                                "caveats": ["仍需外部证据"],
                            }
                        ],
                        "evidence": [
                            {
                                "id": "e1",
                                "task_id": "task-1",
                                "market_step": "recommendations",
                                "confidence": 0.61,
                                "authority_score": 0.42,
                                "freshness_score": 0.58,
                                "source_url": "internal://delta-context/delta-1",
                                "source_domain": "delta-context",
                                "source_type": "internal",
                                "source_tier": "t4",
                                "final_eligibility": "requires_external_evidence",
                                "title": "Delta fallback note",
                                "summary": "仅有内部上下文线索。",
                                "quote": "仅有内部上下文线索。",
                                "captured_at": "2026-04-11T00:00:00+00:00",
                                "extracted_fact": "需要继续补充外部验证。",
                                "injection_risk": 0.0,
                                "tags": ["delta-context-fallback", "context-only"],
                                "competitor_name": None,
                            }
                        ],
                        "report": {
                            "markdown": "## Executive Summary\n- Pending finalize",
                            "generated_at": "2026-04-11T00:00:00+00:00",
                            "updated_at": "2026-04-11T00:00:00+00:00",
                            "stage": "feedback_pending",
                            "feedback_count": 1,
                            "feedback_notes": [],
                        },
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )

                service = ResearchJobService(repository)
                assets = service.finalize_report("job-quality-1")

                self.assertFalse(assets["report"]["quality_gate"]["passed"])
                self.assertTrue(any("claim-delta-1" in reason for reason in assets["report"]["quality_gate"]["reasons"]))
                self.assertEqual(assets["report"]["quality_gate"]["metrics"]["formal_evidence_count"], 0)

    def test_finalize_requires_explicit_claim_support_not_shared_market_step(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                self._create_job(repository, "job-quality-2")
                repository.set_assets(
                    "job-quality-2",
                    {
                        "claims": [
                            {
                                "id": "claim-open-1",
                                "claim_text": "先验证高付费用户路径。",
                                "market_step": "recommendations",
                                "confidence": 0.73,
                                "status": "verified",
                                "verification_state": "supported",
                                "priority": "high",
                                "actionability_score": 0.84,
                                "evidence_ids": [],
                                "supporting_evidence_ids": [],
                                "caveats": [],
                            }
                        ],
                        "evidence": [
                            {
                                "id": "e1",
                                "task_id": "task-1",
                                "market_step": "recommendations",
                                "confidence": 0.81,
                                "authority_score": 0.82,
                                "freshness_score": 0.76,
                                "source_url": "https://example.com/research",
                                "source_domain": "example.com",
                                "source_type": "article",
                                "source_tier": "t2",
                                "title": "Research summary",
                                "summary": "验证高付费路径更稳妥。",
                                "quote": "validate the higher-value path first",
                                "captured_at": "2026-04-11T00:00:00+00:00",
                                "extracted_fact": "先验证高付费路径。",
                                "injection_risk": 0.0,
                                "tags": ["recommendations"],
                                "competitor_name": None,
                            },
                            {
                                "id": "e2",
                                "task_id": "task-1",
                                "market_step": "recommendations",
                                "confidence": 0.79,
                                "authority_score": 0.78,
                                "freshness_score": 0.74,
                                "source_url": "https://signals.example.org/interviews",
                                "source_domain": "signals.example.org",
                                "source_type": "article",
                                "source_tier": "t2",
                                "title": "Interview summary",
                                "summary": "用户重视更明确的价值证明。",
                                "quote": "users need clearer proof of value",
                                "captured_at": "2026-04-11T00:00:00+00:00",
                                "extracted_fact": "需要更明确的价值证明。",
                                "injection_risk": 0.0,
                                "tags": ["recommendations"],
                                "competitor_name": None,
                            },
                        ],
                        "report": {
                            "markdown": "## Executive Summary\n- Draft report",
                            "generated_at": "2026-04-11T00:00:00+00:00",
                            "updated_at": "2026-04-11T00:00:00+00:00",
                            "stage": "feedback_pending",
                            "feedback_count": 0,
                            "feedback_notes": [],
                        },
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )

                service = ResearchJobService(repository)
                assets = service.finalize_report("job-quality-2")

                self.assertFalse(assets["report"]["quality_gate"]["passed"])
                self.assertEqual(assets["report"]["quality_gate"]["metrics"]["formal_evidence_count"], 2)
                self.assertEqual(assets["report"]["quality_gate"]["metrics"]["formal_domain_count"], 2)
                self.assertEqual(assets["report"]["quality_gate"]["metrics"]["formal_claim_count"], 0)
                self.assertTrue(any("claim-open-1" in reason for reason in assets["report"]["quality_gate"]["reasons"]))

    def test_get_assets_backfills_competitors_from_text_only_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                self._create_job(repository, "job-quality-3")
                repository.update_job(
                    "job-quality-3",
                    {
                        **repository.get_job("job-quality-3"),
                        "topic": "AI眼镜",
                        "source_count": 3,
                    },
                )
                repository.set_assets(
                    "job-quality-3",
                    {
                        "claims": [],
                        "evidence": [
                            {
                                "id": "legacy-e1",
                                "task_id": "task-1",
                                "market_step": "market-trends",
                                "confidence": 0.82,
                                "authority_score": 0.91,
                                "freshness_score": 0.78,
                                "source_url": "https://www.meta.com/ai-glasses",
                                "source_domain": "meta.com",
                                "source_type": "web",
                                "source_tier": "t1",
                                "title": "Ray-Ban Meta 官方产品页",
                                "summary": "Ray-Ban Meta 主打拍照与语音助手。",
                                "quote": "Ray-Ban Meta focuses on capture and AI assistance.",
                                "captured_at": "2026-04-11T00:00:00+00:00",
                                "extracted_fact": "Ray-Ban Meta 已形成日常佩戴型 AI 眼镜路线。",
                                "injection_risk": 0.0,
                                "tags": ["official"],
                                "competitor_name": None,
                            },
                            {
                                "id": "legacy-e2",
                                "task_id": "task-1",
                                "market_step": "user-research",
                                "confidence": 0.79,
                                "authority_score": 0.85,
                                "freshness_score": 0.76,
                                "source_url": "https://global.rokid.com/",
                                "source_domain": "rokid.com",
                                "source_type": "web",
                                "source_tier": "t1",
                                "title": "Rokid AI Glasses - Redefining Reality",
                                "summary": "Rokid 主打轻量化、翻译与拍摄功能。",
                                "quote": "Rokid introduces a lighter AI glasses line.",
                                "captured_at": "2026-04-11T00:00:00+00:00",
                                "extracted_fact": "Rokid 正在用轻量 AI 眼镜切入市场。",
                                "injection_risk": 0.0,
                                "tags": ["official"],
                                "competitor_name": None,
                            },
                            {
                                "id": "legacy-e3",
                                "task_id": "task-1",
                                "market_step": "pricing",
                                "confidence": 0.76,
                                "authority_score": 0.83,
                                "freshness_score": 0.77,
                                "source_url": "https://www.mi.com/prod/xiaomi-ai-glasses",
                                "source_domain": "mi.com",
                                "source_type": "pricing",
                                "source_tier": "t1",
                                "title": "小米AI眼镜",
                                "summary": "小米AI眼镜售价 1999 元起。",
                                "quote": "小米AI眼镜售价 1999 元起。",
                                "captured_at": "2026-04-11T00:00:00+00:00",
                                "extracted_fact": "小米把 AI 眼镜作为下一代个人智能设备切入。",
                                "injection_risk": 0.0,
                                "tags": ["pricing"],
                                "competitor_name": None,
                            },
                        ],
                        "report": {
                            "markdown": "## Executive Summary\n- Draft report",
                            "generated_at": "2026-04-11T00:00:00+00:00",
                            "updated_at": "2026-04-11T00:00:00+00:00",
                            "stage": "draft",
                            "feedback_count": 0,
                            "feedback_notes": [],
                        },
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )

                service = ResearchJobService(repository)
                assets = service.get_assets("job-quality-3")
                competitor_names = [item["name"] for item in assets["competitors"]]

                self.assertIn("Ray-Ban Meta", competitor_names)
                self.assertIn("Rokid", competitor_names)
                self.assertIn("小米", competitor_names)
                self.assertEqual(assets["evidence"][0]["competitor_name"], "Ray-Ban Meta")
                self.assertEqual(assets["evidence"][1]["competitor_name"], "Rokid")
                self.assertEqual(assets["evidence"][2]["competitor_name"], "小米")

                persisted_assets = repository.get_assets("job-quality-3")
                persisted_job = repository.get_job("job-quality-3")
                self.assertTrue(persisted_assets["competitors"])
                self.assertEqual(persisted_assets["evidence"][0]["competitor_name"], "Ray-Ban Meta")
                self.assertGreaterEqual(int(persisted_job["competitor_count"]), 3)


if __name__ == "__main__":
    unittest.main()
