import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.agents.research_worker_agent import ResearchWorkerAgent
from pm_agent_worker.tools.search_provider import _finalize_scored_results, _score_result


class AliasAwareRetrievalTest(unittest.TestCase):
    def test_alias_match_outscores_irrelevant_result(self) -> None:
        alias_tokens = ["ai glasses", "smart glasses"]

        alias_score = _score_result(
            {
                "url": "https://www.meta.com/smart-glasses/",
                "title": "Meta Smart Glasses Official Overview",
                "snippet": "Official overview of Meta smart glasses features and pricing.",
            },
            "智能眼镜 official pricing",
            preferred_source_types=("web", "pricing"),
            preferred_domains=("meta.com",),
            topic_alias_tokens=alias_tokens,
        )
        irrelevant_score = _score_result(
            {
                "url": "https://figma.cool/fonts/install-guide",
                "title": "Figma 字体安装指南",
                "snippet": "如何安装字体和插件。",
            },
            "智能眼镜 official pricing",
            preferred_source_types=("web", "pricing"),
            preferred_domains=("meta.com",),
            topic_alias_tokens=alias_tokens,
        )

        self.assertGreater(alias_score, irrelevant_score)

    def test_collect_evidence_passes_topic_alias_tokens_to_search_provider(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {
                "id": "task-1",
                "category": "market_trends",
                "market_step": "market-trends",
                "title": "市场趋势",
                "brief": "关注智能眼镜赛道",
                "status": "running",
                "source_count": 0,
                "retry_count": 0,
            }
            request = {
                "topic": "AI智能眼镜",
                "industry_template": "ai_product",
                "max_sources": 4,
                "max_subtasks": 1,
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            }

            class BrowserStub:
                def is_available(self):
                    return False

                def open(self, url):
                    return {"status": "unavailable", "url": url}

            with patch.object(agent, "_build_queries", return_value=["ai glasses official pricing"]), patch.object(
                agent,
                "_build_zero_result_retry_queries",
                return_value=[],
            ), patch.object(
                agent.search_provider,
                "search",
                AsyncMock(return_value=[]),
            ) as search_mock:
                evidence = await agent.collect_evidence(request, task, [], BrowserStub())
            return evidence, search_mock.await_args.kwargs

        evidence, kwargs = asyncio.run(run_case())

        self.assertEqual(evidence, [])
        self.assertIn("topic_alias_tokens", kwargs)
        self.assertIn("ai glasses", kwargs["topic_alias_tokens"])
        self.assertTrue(
            any(token in kwargs["topic_alias_tokens"] for token in ("ai smart glasses", "smart glasses")),
        )

    def test_alias_priority_still_keeps_other_relevant_results_when_alias_match_is_thin(self) -> None:
        results = _finalize_scored_results(
            "智能眼镜 market analysis",
            [
                {
                    "url": "https://example.com/smart-glasses-market",
                    "title": "Smart Glasses Market Analysis",
                    "snippet": "Smart glasses market growth, pricing, and adoption.",
                    "score": 72,
                    "source_type": "article",
                    "alias_required": True,
                    "alias_match_tokens": ["smart glasses"],
                    "alias_mismatch": False,
                    "topic_mismatch": False,
                    "topic_sparse_match": False,
                    "topic_match_score": 6.2,
                    "strong_query_hits": 3,
                },
                {
                    "url": "https://example.org/ar-eyewear-report",
                    "title": "AR Eyewear Industry Report",
                    "snippet": "智能眼镜市场增长、采用率与代表玩家。",
                    "score": 54,
                    "source_type": "article",
                    "alias_required": True,
                    "alias_match_tokens": [],
                    "alias_mismatch": True,
                    "topic_mismatch": False,
                    "topic_sparse_match": False,
                    "topic_match_score": 3.1,
                    "strong_query_hits": 2,
                },
            ],
            max_results=4,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["url"], "https://example.com/smart-glasses-market")
        self.assertIn("https://example.org/ar-eyewear-report", [item["url"] for item in results])


if __name__ == "__main__":
    unittest.main()
