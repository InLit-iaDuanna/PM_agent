import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx


ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.agents.research_worker_agent import ResearchWorkerAgent


class CompetitorRetrievalResilienceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = ResearchWorkerAgent()
        self.request = {
            "topic": "AI眼镜",
            "industry_template": "ai_product",
            "geo_scope": ["中国"],
            "output_locale": "zh-CN",
            "max_sources": 4,
            "max_subtasks": 1,
            "runtime_config": {"debug_policy": {"auto_open_mode": "debug_only"}},
        }
        self.task = {
            "id": "task-1",
            "category": "competitor_landscape",
            "market_step": "competitor-analysis",
            "title": "AI眼镜竞品格局",
            "brief": "调研 AI 眼镜竞品与替代品。",
            "status": "running",
            "source_count": 0,
            "retry_count": 0,
        }

    def test_fallback_queries_include_known_competitor_anchor(self) -> None:
        queries = self.agent._build_fallback_queries(self.request, self.task, competitor_names=["Ray-Ban Meta", "XREAL"])

        combined = " || ".join(queries).lower()
        self.assertIn("ray-ban meta", combined)
        self.assertTrue(any(token in combined for token in ("comparison", "alternatives", "vs", "对比", "替代")))

    def test_exemplar_queries_frontload_real_glasses_brands(self) -> None:
        queries = self.agent._build_exemplar_queries(self.request, self.task)

        self.assertIn("Ray-Ban Meta smart glasses", queries)
        self.assertIn("Rokid ai glasses", queries)

    def test_hardware_topic_preferred_domains_drop_saas_directories(self) -> None:
        strategy = self.agent._search_strategy_for_task(self.task)
        preferred_domains = self.agent._effective_preferred_domains(self.request, self.task, strategy, limit=6)

        self.assertIn("meta.com", preferred_domains)
        self.assertIn("global.rokid.com", preferred_domains)
        self.assertNotIn("g2.com", preferred_domains)
        self.assertNotIn("capterra.com", preferred_domains)

    def test_hardware_topic_rejects_g2_results_as_low_signal(self) -> None:
        result = {
            "url": "https://www.g2.com/products/g2/reviews",
            "title": "G2 Marketing Solutions Reviews 2026: Details, Pricing, & Features | G2",
            "snippet": "Software marketplace reviews and pricing overview.",
            "score": 80,
            "query": "ai glasses",
        }

        self.assertTrue(self.agent._is_low_signal_result(result, self.task, request=self.request))

    def test_round_pipeline_keeps_known_competitor_terms(self) -> None:
        pipeline = self.agent._build_round_pipeline(
            self.request,
            self.task,
            queries=["AI眼镜 对比 Ray-Ban Meta"],
            competitor_names=["Ray-Ban Meta", "XREAL"],
        )

        entity_terms = pipeline["entity_terms"]
        self.assertIn("Ray-Ban Meta", entity_terms)
        self.assertIn("XREAL", entity_terms)

    def test_access_blocked_snippet_preserves_competitor_name(self) -> None:
        class BrowserStub:
            def __init__(self) -> None:
                self.open_calls = 0

            def is_available(self):
                return True

            def open(self, url):
                self.open_calls += 1
                return {"status": "ready", "url": url}

        async def run_case():
            browser = BrowserStub()
            request_url = "https://www.zhihu.com/question/123"
            forbidden_error = httpx.HTTPStatusError(
                "Client error '403 Forbidden' for url 'https://www.zhihu.com/question/123'",
                request=httpx.Request("GET", request_url),
                response=httpx.Response(403, request=httpx.Request("GET", request_url)),
            )
            results = [
                {
                    "url": request_url,
                    "title": "AI眼镜哪家体验更好？",
                    "snippet": "讨论 Ray-Ban Meta、XREAL 与闪极 AI 眼镜的功能、续航和佩戴体验差异。",
                }
            ]
            with patch.object(self.agent, "_build_queries", return_value=["AI眼镜 Ray-Ban Meta XREAL 对比"]), patch.object(
                self.agent,
                "_research_is_sufficient",
                return_value=True,
            ), patch.object(
                self.agent.search_provider,
                "search",
                AsyncMock(return_value=results),
            ), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(side_effect=forbidden_error),
            ):
                evidence = await self.agent.collect_evidence(self.request, self.task, ["Ray-Ban Meta", "XREAL"], browser)
            return browser, evidence

        browser, evidence = asyncio.run(run_case())

        self.assertEqual(browser.open_calls, 1)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["competitor_name"], "Ray-Ban Meta")
        self.assertIn("access-blocked-snippet", evidence[0]["tags"])


if __name__ == "__main__":
    unittest.main()
