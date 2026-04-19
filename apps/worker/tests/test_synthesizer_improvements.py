import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


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

    def test_polish_generated_markdown_strips_reasoning_and_placeholder_content(self) -> None:
        raw_markdown = (
            "<think>内部推理，不应进入最终报告</think>\n"
            "# AI眼镜市场研究报告\n\n"
            "## 核心结论摘要\n"
            "【3-5条硬结论 + PM含义】\n"
            "该结论基于公开线索 [S1] 与 [知乎选型指南]。\n\n"
            "## 建议动作\n"
            "开始撰写正文：\n"
            "- 先验证需求。\n"
        )
        fallback_markdown = (
            "# AI眼镜市场研究报告\n\n"
            "## 核心结论摘要\n- fallback\n\n"
            "## 决策快照\n- fallback\n\n"
            "## 研究范围与方法\n- fallback\n\n"
            "## 竞争格局\n- fallback\n\n"
            "## 证据冲突与使用边界\n- fallback\n\n"
            "## 建议动作\n- fallback\n\n"
            "## 待验证问题\n- fallback\n\n"
            "## 关键证据摘录\n- fallback\n"
        )

        polished = self.agent._polish_generated_markdown(
            markdown=raw_markdown,
            request=self.request,
            stage="draft",
            fallback_markdown=fallback_markdown,
            allowed_citation_labels={"[S1]"},
        )

        self.assertNotIn("<think>", polished)
        self.assertNotIn("3-5条硬结论", polished)
        self.assertNotIn("[知乎选型指南]", polished)
        self.assertIn("[S1]", polished)

    def test_build_report_with_llm_output_removes_reasoning_leakage(self) -> None:
        llm_client = Mock()
        llm_client.is_enabled.return_value = True
        llm_client.complete.return_value = (
            "<think>不要输出</think>\n"
            "# AI眼镜市场研究报告\n\n"
            "## 核心结论摘要\n"
            "【3-5条硬结论 + PM含义】\n"
            "围绕核心用户任务形成方向判断 [S1]。\n\n"
            "## 决策快照\n"
            "- 当前成熟度中等。\n\n"
            "## 建议动作\n"
            "- 先补齐用户访谈。\n"
        )
        agent = SynthesizerAgent(llm_client=llm_client)

        report = agent.build_report(
            self.request,
            claims=[
                {
                    "id": "c1",
                    "claim_text": "核心用户更关注佩戴舒适度与交互自然度。",
                    "market_step": "user-research",
                    "status": "directional",
                    "confidence": 0.66,
                    "actionability_score": 0.78,
                    "caveats": ["仍需补充用户访谈样本。"],
                }
            ],
            evidence=[
                {
                    "id": "e1",
                    "market_step": "user-research",
                    "title": "用户任务观察",
                    "summary": "用户优先关注佩戴舒适度和交互负担。",
                    "source_url": "https://example.com/user-study",
                    "source_type": "article",
                    "confidence": 0.82,
                    "authority_score": 0.72,
                    "citation_label": "[S1]",
                }
            ],
            competitor_names=["Ray-Ban Meta"],
        )

        self.assertNotIn("<think>", report["markdown"])
        self.assertNotIn("3-5条硬结论", report["markdown"])
        self.assertNotIn("【", report["executive_memo_markdown"])


if __name__ == "__main__":
    unittest.main()
