import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.agents.synthesizer_agent import SynthesizerAgent
from pm_agent_worker.workflows.research_workflow import ResearchWorkflowEngine


class CompetitorAnalysisQualityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = SynthesizerAgent()
        self.request = {
            "topic": "AI眼镜",
            "industry_template": "ai_product",
            "research_mode": "deep",
            "depth_preset": "deep",
            "geo_scope": ["中国", "美国"],
            "max_competitors": 6,
        }
        self.evidence = [
            {
                "id": "e1",
                "title": "Ray-Ban Meta 官方产品页",
                "summary": "Ray-Ban Meta 主打拍摄、语音助手和日常佩戴场景，强调更像普通眼镜的佩戴体验。",
                "extracted_fact": "Ray-Ban Meta 用更日常的眼镜形态承接拍摄与 AI 助手场景。",
                "market_step": "competitor-analysis",
                "competitor_name": "Ray-Ban Meta",
                "citation_label": "[S1]",
                "confidence": 0.84,
                "authority_score": 0.9,
                "freshness_score": 0.82,
                "source_type": "web",
                "source_url": "https://www.meta.com/smart-glasses/",
            },
            {
                "id": "e2",
                "title": "Ray-Ban Meta pricing",
                "summary": "Ray-Ban Meta 官方售价 299 美元，定价集中在消费级智能眼镜区间。",
                "extracted_fact": "官方价格页给出了 299 美元起售的公开定价线索。",
                "market_step": "business-and-channels",
                "competitor_name": "Ray-Ban Meta",
                "citation_label": "[S2]",
                "confidence": 0.81,
                "authority_score": 0.88,
                "freshness_score": 0.8,
                "source_type": "pricing",
                "source_url": "https://www.meta.com/smart-glasses/pricing",
            },
            {
                "id": "e3",
                "title": "XREAL 产品介绍",
                "summary": "XREAL 面向观影和空间显示场景，强调大屏沉浸体验与轻量硬件搭配。",
                "extracted_fact": "XREAL 的核心定位更接近显示与娱乐体验，而非日常拍摄。",
                "market_step": "competitor-analysis",
                "competitor_name": "XREAL",
                "citation_label": "[S3]",
                "confidence": 0.77,
                "authority_score": 0.76,
                "freshness_score": 0.74,
                "source_type": "web",
                "source_url": "https://www.xreal.com/",
            },
            {
                "id": "e4",
                "title": "XREAL 用户讨论",
                "summary": "用户常把 XREAL 视作 AI 眼镜的替代方案，主要比较显示效果、重量与续航。",
                "extracted_fact": "XREAL 更多被当作替代方案而非完全同位竞品。",
                "market_step": "reviews-and-sentiment",
                "competitor_name": "XREAL",
                "citation_label": "[S4]",
                "confidence": 0.72,
                "authority_score": 0.66,
                "freshness_score": 0.7,
                "source_type": "review",
                "source_url": "https://example.com/xreal-review",
            },
        ]

    def test_extract_competitors_builds_richer_profiles(self) -> None:
        competitors = self.agent.extract_competitors(self.request, self.evidence)

        competitor_lookup = {item["name"]: item for item in competitors}
        self.assertIn("Ray-Ban Meta", competitor_lookup)
        self.assertIn("XREAL", competitor_lookup)
        ray_ban_meta = competitor_lookup["Ray-Ban Meta"]
        xreal = competitor_lookup["XREAL"]
        self.assertEqual(ray_ban_meta["category"], "direct")
        self.assertIn("299", ray_ban_meta["pricing"])
        self.assertIn("拍摄", ray_ban_meta["positioning"])
        self.assertGreaterEqual(ray_ban_meta["evidence_count"], 2)
        self.assertTrue(ray_ban_meta["key_sources"])
        self.assertEqual(xreal["category"], "indirect")
        self.assertTrue(xreal["differentiation"])
        self.assertIn("观影", xreal["positioning"])

    def test_extract_competitors_backfills_text_only_evidence(self) -> None:
        text_only_evidence = [
            {
                "id": "legacy-1",
                "title": "Ray-Ban Meta 官方产品页",
                "summary": "Ray-Ban Meta 主打拍照、语音助手和日常佩戴体验。",
                "extracted_fact": "Ray-Ban Meta 已经形成以日常拍摄和 AI 助手为核心的产品路线。",
                "quote": "Ray-Ban Meta focuses on capture and AI assistance.",
                "market_step": "market-trends",
                "competitor_name": None,
                "confidence": 0.83,
                "authority_score": 0.92,
                "freshness_score": 0.8,
                "source_type": "web",
                "source_url": "https://www.meta.com/ai-glasses",
            },
            {
                "id": "legacy-2",
                "title": "Rokid AI Glasses - Redefining Reality",
                "summary": "Rokid 的 AI 眼镜强调翻译、拍摄与更轻量的佩戴方式。",
                "extracted_fact": "Rokid 正在以轻量 AI 眼镜切入消费级市场。",
                "quote": "Rokid introduces a lighter AI glasses line.",
                "market_step": "user-research",
                "competitor_name": None,
                "confidence": 0.78,
                "authority_score": 0.85,
                "freshness_score": 0.77,
                "source_type": "web",
                "source_url": "https://global.rokid.com/",
            },
            {
                "id": "legacy-3",
                "title": "小米AI眼镜",
                "summary": "小米AI眼镜售价 1999 元起，强调拍照、翻译和耳机一体化体验。",
                "extracted_fact": "小米把 AI 眼镜作为下一代个人智能设备切入。",
                "quote": "小米AI眼镜售价 1999 元起。",
                "market_step": "user-research",
                "competitor_name": None,
                "confidence": 0.76,
                "authority_score": 0.82,
                "freshness_score": 0.79,
                "source_type": "pricing",
                "source_url": "https://www.mi.com/prod/xiaomi-ai-glasses",
            },
        ]

        annotated = self.agent.backfill_evidence_competitors(self.request, text_only_evidence)
        competitors = self.agent.extract_competitors(self.request, text_only_evidence)
        competitor_names = [item["name"] for item in competitors]

        self.assertEqual(annotated[0]["competitor_name"], "Ray-Ban Meta")
        self.assertEqual(annotated[1]["competitor_name"], "Rokid")
        self.assertEqual(annotated[2]["competitor_name"], "小米")
        self.assertIn("Ray-Ban Meta", competitor_names)
        self.assertIn("Rokid", competitor_names)
        self.assertIn("小米", competitor_names)

    def test_build_report_renders_structured_competitor_sections(self) -> None:
        report = self.agent.build_report(
            self.request,
            claims=[
                {
                    "id": "c1",
                    "claim_text": "AI 眼镜赛道里，Ray-Ban Meta 与 XREAL 分别代表日常穿戴型与显示体验型路线。",
                    "market_step": "competitor-analysis",
                    "confidence": 0.82,
                    "status": "verified",
                    "actionability_score": 0.85,
                    "caveats": ["仍需补充中国市场定价与渠道口径。"],
                }
            ],
            evidence=self.evidence,
            competitor_names=["Ray-Ban Meta", "XREAL"],
        )

        self.assertIn("| 竞品 | 角色 | 当前定位 | 定价线索 | 核心差异 | 证据足迹 |", report["markdown"])
        self.assertIn("| 竞品 | 当前定位 | 最值得盯的差异 | 仍需补的证据 |", report["markdown"])
        self.assertIn("### Ray-Ban Meta", report["markdown"])
        self.assertIn("关键来源", report["markdown"])
        self.assertIn("299 美元", report["markdown"])

    def test_progress_snapshot_does_not_fabricate_competitor_placeholder(self) -> None:
        engine = ResearchWorkflowEngine(runtime_config={"llm": {"provider": "disabled"}})
        snapshot = engine._build_progress_snapshot(
            job={
                "tasks": [],
                "completed_task_count": 0,
                "source_count": 0,
                "claims_count": 0,
            },
            assets={
                "evidence": [],
                "competitors": [],
                "report": {},
            },
            competitor_names=[],
        )

        self.assertEqual(snapshot["competitor_coverage"], [])


if __name__ == "__main__":
    unittest.main()
