import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.agents.synthesizer_agent import SynthesizerAgent


class SynthesizerImprovementsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = SynthesizerAgent()
        self.request = {
            "topic": "AI眼镜",
            "industry_template": "ai_product",
            "research_mode": "deep",
            "depth_preset": "deep",
            "geo_scope": ["中国"],
            "output_locale": "zh-CN",
        }

    def test_section_sufficiency_is_true_with_enough_evidence_and_domains(self) -> None:
        sufficiency = self.agent._section_evidence_sufficiency(
            "竞争格局",
            [
                {"market_step": "competitor-analysis", "source_url": "https://meta.com/1"},
                {"market_step": "competitor-analysis", "source_url": "https://xreal.com/1"},
                {"market_step": "competitor-analysis", "source_url": "https://meta.com/2"},
            ],
        )

        self.assertTrue(sufficiency["sufficient"])
        self.assertEqual(sufficiency["evidence_count"], 3)
        self.assertEqual(sufficiency["unique_domains"], 2)

    def test_section_sufficiency_is_false_when_evidence_count_is_low(self) -> None:
        sufficiency = self.agent._section_evidence_sufficiency(
            "竞争格局",
            [
                {"market_step": "competitor-analysis", "source_url": "https://meta.com/1"},
                {"market_step": "competitor-analysis", "source_url": "https://xreal.com/1"},
            ],
        )

        self.assertFalse(sufficiency["sufficient"])
        self.assertEqual(sufficiency["evidence_count"], 2)

    def test_section_sufficiency_is_false_when_only_one_domain_exists(self) -> None:
        sufficiency = self.agent._section_evidence_sufficiency(
            "竞争格局",
            [
                {"market_step": "competitor-analysis", "source_url": "https://meta.com/1"},
                {"market_step": "competitor-analysis", "source_url": "https://meta.com/2"},
                {"market_step": "competitor-analysis", "source_url": "https://meta.com/3"},
            ],
        )

        self.assertFalse(sufficiency["sufficient"])
        self.assertEqual(sufficiency["unique_domains"], 1)

    def test_unmapped_section_is_always_sufficient(self) -> None:
        sufficiency = self.agent._section_evidence_sufficiency("核心结论摘要", [])

        self.assertTrue(sufficiency["sufficient"])

    def test_irrelevant_evidence_is_not_counted_for_section(self) -> None:
        sufficiency = self.agent._section_evidence_sufficiency(
            "竞争格局",
            [
                {"market_step": "user-research", "source_url": "https://example.com/user"},
                {"market_step": "market-trends", "source_url": "https://example.com/trend"},
            ],
        )

        self.assertEqual(sufficiency["evidence_count"], 0)
        self.assertFalse(sufficiency["sufficient"])

    def test_supporting_evidence_prefers_domain_diversity(self) -> None:
        claim = {"market_step": "competitor-analysis", "evidence_ids": ["e1", "e2", "e3"]}
        evidence = [
            {"id": "e1", "market_step": "competitor-analysis", "source_url": "https://meta.com/1", "confidence": 0.92},
            {"id": "e2", "market_step": "competitor-analysis", "source_url": "https://meta.com/2", "confidence": 0.9},
            {"id": "e3", "market_step": "competitor-analysis", "source_url": "https://xreal.com/1", "confidence": 0.86},
        ]

        selected = self.agent._supporting_evidence_for_claim(claim, evidence, limit=2)

        self.assertEqual([item["id"] for item in selected], ["e1", "e3"])

    def test_supporting_evidence_falls_back_when_only_one_domain_exists(self) -> None:
        claim = {"market_step": "competitor-analysis", "evidence_ids": []}
        evidence = [
            {"id": "e1", "market_step": "competitor-analysis", "source_url": "https://meta.com/1", "confidence": 0.92},
            {"id": "e2", "market_step": "competitor-analysis", "source_url": "https://meta.com/2", "confidence": 0.9},
            {"id": "e3", "market_step": "competitor-analysis", "source_url": "https://meta.com/3", "confidence": 0.86},
        ]

        selected = self.agent._supporting_evidence_for_claim(claim, evidence, limit=2)

        self.assertEqual([item["id"] for item in selected], ["e1", "e2"])

    def test_fallback_report_lists_insufficient_sections_in_open_questions(self) -> None:
        report = self.agent.build_report(
            self.request,
            claims=[
                {
                    "id": "c1",
                    "claim_text": "Ray-Ban Meta 在当前样本里更接近日常穿戴型路线。",
                    "market_step": "competitor-analysis",
                    "status": "directional",
                    "confidence": 0.64,
                    "actionability_score": 0.78,
                    "caveats": ["仍需补充中国市场渠道和价格交叉验证。"],
                }
            ],
            evidence=[
                {
                    "id": "e1",
                    "market_step": "competitor-analysis",
                    "title": "Ray-Ban Meta",
                    "summary": "Meta 官方产品页强调拍摄、语音助手和日常佩戴。",
                    "source_url": "https://meta.com/smart-glasses",
                    "source_type": "web",
                    "confidence": 0.84,
                    "authority_score": 0.9,
                    "citation_label": "[S1]",
                },
                {
                    "id": "e2",
                    "market_step": "recommendations",
                    "title": "PM action note",
                    "summary": "建议先做用户场景验证，再决定差异化路线。",
                    "source_url": "https://example.com/pm-note",
                    "source_type": "article",
                    "confidence": 0.7,
                    "authority_score": 0.6,
                    "citation_label": "[S2]",
                },
            ],
            competitor_names=["Ray-Ban Meta"],
        )

        self.assertIn("以下章节当前仍不足以展开完整论证", report["markdown"])
        self.assertIn("市场结构与趋势", report["markdown"])
        self.assertIn("补证门槛", report["markdown"])


if __name__ == "__main__":
    unittest.main()
