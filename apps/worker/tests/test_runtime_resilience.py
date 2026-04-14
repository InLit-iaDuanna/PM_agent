import asyncio
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository
from pm_agent_api.services.chat_service import ChatService
from pm_agent_api.services.research_job_service import ResearchJobService
from pm_agent_api.services.runtime_service import RuntimeService
from pm_agent_worker.agents.dialogue_agent import DialogueAgent
from pm_agent_worker.agents.planner_agent import PlannerAgent
from pm_agent_worker.agents.research_worker_agent import ResearchWorkerAgent
from pm_agent_worker.agents.synthesizer_agent import SynthesizerAgent
from pm_agent_worker.agents.verifier_agent import VerifierAgent
from pm_agent_worker.tools.content_extractor import PrivateAccessError, UnsafeRedirectError, fetch_and_extract_page
from pm_agent_worker.tools.minimax_client import MiniMaxChatClient
from pm_agent_worker.tools.minimax_settings import MiniMaxSettings
from pm_agent_worker.tools.opencli_browser_tool import OpenCliBrowserTool
from pm_agent_worker.tools.openai_compatible_client import OpenAICompatibleChatClient
from pm_agent_worker.tools.openai_compatible_settings import OpenAICompatibleSettings
from pm_agent_worker.tools.search_provider import DuckDuckGoSearchProvider, SearchProviderUnavailable
from pm_agent_worker.workflows.research_models import DeltaResearchResult, build_report_version_snapshot
from pm_agent_worker.workflows.research_workflow import ResearchWorkflowEngine


class ReportVersionSnapshotTest(unittest.TestCase):
    def test_build_report_version_snapshot_captures_bound_claims_evidence_and_domains(self) -> None:
        snapshot = build_report_version_snapshot(
            "job-1-report-v2",
            {
                "markdown": "## 核心结论摘要\n- test",
                "generated_at": "2026-04-10T00:00:00+00:00",
                "stage": "final",
            },
            claims=[
                {"id": "claim-1"},
                {"id": "claim-2"},
                {"id": "claim-1"},
            ],
            evidence=[
                {"id": "e1", "source_url": "https://www.example.com/report"},
                {"id": "e2", "source_domain": "insights.example.org"},
                {"id": "e2", "source_url": "https://insights.example.org/dup"},
            ],
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["claim_ids"], ["claim-1", "claim-2"])
        self.assertEqual(snapshot["evidence_ids"], ["e1", "e2"])
        self.assertEqual(snapshot["source_domains"], ["example.com", "insights.example.org"])
        self.assertEqual(snapshot["evidence_count"], 2)


class SearchProviderFallbackTest(unittest.TestCase):
    def test_prefers_english_market_for_mixed_query_with_english_bias(self) -> None:
        provider = DuckDuckGoSearchProvider()

        self.assertTrue(provider._prefers_english_market("ai 眼镜 growth adoption 市场 趋势 报告 benchmark"))
        self.assertFalse(provider._prefers_english_market("ai 眼镜 官网 产品介绍"))

    def test_search_returns_bing_html_without_duckduckgo_when_enough_results(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_bing_html = AsyncMock(
            return_value=[
                {
                    "url": "https://example.com/report",
                    "title": "PM agent market report",
                    "snippet": "PM agent pricing and positioning report.",
                    "query": "pm agent",
                }
            ]
        )
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])
        provider._search_duckduckgo_html = AsyncMock(side_effect=RuntimeError("duckduckgo should not run"))

        results = asyncio.run(provider.search("pm agent", max_results=1))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://example.com/report")
        provider._search_bing_html.assert_awaited_once()
        provider._search_bing_rss.assert_not_awaited()
        provider._search_duckduckgo_html.assert_not_awaited()

    def test_search_uses_bing_rss_when_html_sources_return_empty(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(
            return_value=[
                {
                    "url": "https://example.com/pricing-models",
                    "title": "SaaS pricing models",
                    "snippet": "Seat-based, usage-based, and hybrid pricing examples.",
                    "query": "saas pricing",
                }
            ]
        )
        provider._search_duckduckgo_html = AsyncMock(side_effect=RuntimeError("duckduckgo should not run"))

        results = asyncio.run(provider.search("saas pricing", max_results=3))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://example.com/pricing-models")
        provider._search_bing_rss.assert_awaited_once()
        provider._search_duckduckgo_html.assert_not_awaited()

    def test_search_skips_duckduckgo_when_bing_rss_completes_with_results(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_bing_html = AsyncMock(
            return_value=[
                {
                    "url": "https://openai.com/api/pricing/",
                    "title": "OpenAI API Pricing",
                    "snippet": "Official pricing and token cost details.",
                    "query": "openai pricing",
                }
            ]
        )
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])
        provider._search_duckduckgo_html = AsyncMock(side_effect=RuntimeError("duckduckgo should not run"))

        results = asyncio.run(provider.search("openai pricing", max_results=3))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://openai.com/api/pricing")
        provider._search_duckduckgo_html.assert_not_awaited()

    def test_bing_html_parser_decodes_base64_tracking_links(self) -> None:
        provider = DuckDuckGoSearchProvider()
        html = """
        <ol id="b_results">
          <li class="b_algo">
            <h2>
              <a href="https://www.bing.com/ck/a?!&&u=a1aHR0cHM6Ly9vcGVuYWkuY29tL2FwaS9wcmljaW5nLw&ntb=1">
                OpenAI API Pricing
              </a>
            </h2>
            <div class="b_caption"><p>Official pricing and token cost details.</p></div>
          </li>
        </ol>
        """

        results = provider._parse_bing_html_results(html, "openai pricing", max_results=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://openai.com/api/pricing/")

    def test_bing_html_retries_alternate_params_when_first_attempt_has_no_results(self) -> None:
        provider = DuckDuckGoSearchProvider()
        empty_html = "<html><head><title>openai pricing - Search</title></head><body><div id='b_content'></div></body></html>"
        valid_html = """
        <ol id="b_results">
          <li class="b_algo">
            <h2>
              <a href="https://www.bing.com/ck/a?!&&u=a1aHR0cHM6Ly9vcGVuYWkuY29tL2FwaS9wcmljaW5nLw&ntb=1">
                OpenAI API Pricing
              </a>
            </h2>
            <div class="b_caption"><p>Official pricing and token cost details.</p></div>
          </li>
        </ol>
        """
        provider._fetch_html = AsyncMock(side_effect=[empty_html, valid_html])

        results = asyncio.run(provider._search_bing_html("openai pricing", max_results=5))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://openai.com/api/pricing/")
        self.assertGreaterEqual(provider._fetch_html.await_count, 2)
        first_params = provider._fetch_html.await_args_list[0].args[1]
        second_params = provider._fetch_html.await_args_list[1].args[1]
        self.assertNotEqual(first_params, second_params)

    def test_entity_host_match_prefers_official_pricing_page(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(
            return_value=[
                {
                    "url": "https://aipricing.org/brands/openai",
                    "title": "OpenAI API Pricing 2026 | Models, Token Cost & Calculator",
                    "snippet": "Third-party pricing tracker for OpenAI API costs.",
                    "query": "openai pricing",
                },
                {
                    "url": "https://openai.com/api/pricing/",
                    "title": "OpenAI API Pricing",
                    "snippet": "Explore OpenAI API pricing for GPT-5.4 and tools.",
                    "query": "openai pricing",
                },
            ]
        )
        provider._search_duckduckgo_html = AsyncMock(side_effect=RuntimeError("duckduckgo should not run"))

        results = asyncio.run(provider.search("openai pricing", max_results=2))

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["url"], "https://openai.com/api/pricing")
        provider._search_duckduckgo_html.assert_not_awaited()

    def test_search_returns_empty_when_duckduckgo_timeout_follows_empty_primary_sources(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])
        provider._search_duckduckgo_html = AsyncMock(side_effect=httpx.ConnectTimeout("duckduckgo timed out"))

        first_results = asyncio.run(provider.search("AI 产品研究助手 官网 定价", max_results=3))
        second_results = asyncio.run(provider.search("site:meta.com ray ban meta smart glasses pricing", max_results=3))

        self.assertEqual(first_results, [])
        self.assertEqual(second_results, [])
        provider._search_duckduckgo_html.assert_awaited_once()

    def test_bing_rss_raises_unavailable_for_html_payload_instead_of_returning_empty(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._fetch_html = AsyncMock(return_value="<html><body>temporary upstream html page</body></html>")

        with self.assertRaises(SearchProviderUnavailable):
            asyncio.run(provider._search_bing_rss("openai pricing", max_results=3))

    def test_brave_html_raises_unavailable_for_unrecognized_empty_markup(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._fetch_html = AsyncMock(return_value="<html><body><div id='results'>unexpected brave markup</div></body></html>")

        with self.assertRaises(SearchProviderUnavailable):
            asyncio.run(provider._search_brave_html("openai pricing", max_results=3))

    def test_search_ranks_primary_source_over_generic_roundup(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(
            return_value=[
                {
                    "url": "https://randomblog.example.com/best-ai-glasses-2024",
                    "title": "Best AI Glasses in 2024",
                    "snippet": "A roundup of the top AI glasses tools and gadgets.",
                    "query": "site:meta.com ray-ban meta smart glasses pricing",
                },
                {
                    "url": "https://www.meta.com/smart-glasses/ai-glasses/",
                    "title": "Ray-Ban Meta smart glasses",
                    "snippet": "Official product page with features and product details.",
                    "query": "site:meta.com ray-ban meta smart glasses pricing",
                },
            ]
        )
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])

        results = asyncio.run(
            provider.search(
                "site:meta.com ray-ban meta smart glasses pricing",
                max_results=2,
                preferred_source_types=("web", "pricing", "documentation"),
                preferred_domains=("meta.com",),
            )
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertIn("meta.com", results[0]["url"])

    def test_official_query_prefers_docs_over_community_result(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(
            return_value=[
                {
                    "url": "https://www.reddit.com/r/example/comments/123/ray_ban_meta/",
                    "title": "Ray-Ban Meta discussion",
                    "snippet": "Community reactions and comments.",
                    "query": "ray-ban meta official docs help center",
                },
                {
                    "url": "https://docs.meta.com/ray-ban-meta/get-started",
                    "title": "Ray-Ban Meta help center",
                    "snippet": "Official setup and onboarding guide.",
                    "query": "ray-ban meta official docs help center",
                },
            ]
        )
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])

        results = asyncio.run(
            provider.search(
                "ray-ban meta official docs help center",
                max_results=2,
                preferred_source_types=("documentation", "web"),
                preferred_domains=("meta.com",),
            )
        )

        self.assertEqual(results[0]["source_type"], "documentation")
        self.assertIn("meta.com", results[0]["url"])

    def test_site_query_discards_offsite_results_when_matching_domain_exists(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(
            return_value=[
                {
                    "url": "https://www.zhihu.com/question/123",
                    "title": "AI 眼镜讨论",
                    "snippet": "无关站点结果。",
                    "query": "site:capterra.com ai 眼镜 定价",
                },
                {
                    "url": "https://www.capterra.com/p/123/example-ai-glasses/",
                    "title": "Example AI 眼镜 Reviews 2025",
                    "snippet": "Capterra AI 眼镜 product and pricing overview.",
                    "query": "site:capterra.com ai 眼镜 定价",
                },
            ]
        )
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])

        results = asyncio.run(provider.search("site:capterra.com ai 眼镜 定价", max_results=5))

        self.assertEqual(len(results), 1)
        self.assertIn("capterra.com", results[0]["url"])

    def test_site_query_returns_empty_when_engine_ignores_domain_constraint(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(
            return_value=[
                {
                    "url": "https://www.zhihu.com/question/123",
                    "title": "AI 眼镜讨论",
                    "snippet": "无关站点结果。",
                    "query": "site:capterra.com ai 眼镜 定价",
                }
            ]
        )
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])

        results = asyncio.run(provider.search("site:capterra.com ai 眼镜 定价", max_results=5))

        self.assertEqual(results, [])

    def test_search_discards_sparse_single_word_overlap_results(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(return_value=[])
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(
            return_value=[
                {
                    "url": "https://creativepark.canon/en/contents/CNT-0010164/index.html",
                    "title": "Manta Ray - Marine Animals - Paper Craft - Canon Creative Park",
                    "snippet": "Canon Inc. provides a wealth of free download materials on this site.",
                    "query": "ray ban meta smart glasses pricing",
                }
            ]
        )

        results = asyncio.run(provider.search("ray ban meta smart glasses pricing", max_results=5))

        self.assertEqual(results, [])

    def test_search_returns_empty_when_all_results_topic_mismatch(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(return_value=[])
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(
            return_value=[
                {
                    "url": "https://www.zhihu.com/question/1903860201389548284",
                    "title": "如何彻底禁用搜狗输入法的旺仔AI？ - 知乎",
                    "snippet": "最近升级后一直弹出。",
                    "query": "AI 产品研究助手 官网 定价",
                }
            ]
        )

        results = asyncio.run(provider.search("AI 产品研究助手 官网 定价", max_results=5))

        self.assertEqual(results, [])

    def test_search_keeps_strong_result_when_long_focus_terms_make_topic_match_too_strict(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(return_value=[])
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(
            return_value=[
                {
                    "url": "https://www.meta.com/ai-glasses/",
                    "title": "Meta AI Glasses: Ray-Ban Meta & Oakley Meta | Meta Store",
                    "snippet": "Official AI glasses overview with product details and use cases.",
                    "query": "ai glasses pain points use cases customer feedback case study analysis best practices us",
                }
            ]
        )

        results = asyncio.run(
            provider.search(
                "ai glasses pain points use cases customer feedback case study analysis best practices us",
                max_results=5,
                preferred_source_types=("web", "article"),
                preferred_domains=("meta.com",),
            )
        )

        self.assertEqual(len(results), 1)
        self.assertIn("meta.com", results[0]["url"])
        self.assertGreaterEqual(int(results[0].get("strong_query_hits", 0) or 0), 1)

    def test_topic_mismatch_generic_hosts_do_not_outrank_topic_result(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(
            return_value=[
                {
                    "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
                    "title": "Artificial intelligence - Wikipedia",
                    "snippet": "General AI encyclopedia page.",
                    "query": "ai 眼镜 smart glasses pricing",
                },
                {
                    "url": "https://openai.com/",
                    "title": "OpenAI",
                    "snippet": "Research and deployment company for AI.",
                    "query": "ai 眼镜 smart glasses pricing",
                },
                {
                    "url": "https://www.xreal.com/glasses/",
                    "title": "XREAL smart glasses",
                    "snippet": "Official smart glasses product and pricing info.",
                    "query": "ai 眼镜 smart glasses pricing",
                },
            ]
        )
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])

        results = asyncio.run(
            provider.search(
                "ai 眼镜 smart glasses pricing",
                max_results=3,
                preferred_source_types=("web", "pricing", "documentation"),
            )
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertIn("xreal.com", results[0]["url"])
        self.assertFalse(bool(results[0].get("topic_mismatch")))

    def test_smart_glasses_query_filters_out_smart_principle_pages(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_duckduckgo_html = AsyncMock(
            return_value=[
                {
                    "url": "https://www.zhihu.com/question/657097690",
                    "title": "什么是 SMART 原则？怎么在设定目标时应用它？ - 知乎",
                    "snippet": "SMART 原则介绍。",
                    "query": "smart glasses market report",
                },
                {
                    "url": "https://www.xreal.com/glasses/",
                    "title": "XREAL smart glasses",
                    "snippet": "Official smart glasses product and pricing info.",
                    "query": "smart glasses market report",
                },
            ]
        )
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(return_value=[])

        results = asyncio.run(
            provider.search(
                "smart glasses market report",
                max_results=3,
                preferred_source_types=("web", "documentation"),
                preferred_domains=("xreal.com",),
            )
        )

        self.assertEqual(len(results), 1)
        self.assertIn("xreal.com", results[0]["url"])

    def test_search_uses_bing_rss_before_brave_when_results_are_already_strong(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(
            return_value=[
                {
                    "url": "https://openai.com/api/pricing/",
                    "title": "Pricing | OpenAI",
                    "snippet": "OpenAI API pricing and token costs.",
                    "query": "openai pricing",
                },
                {
                    "url": "https://chatgpt.com/pricing/",
                    "title": "ChatGPT Plans",
                    "snippet": "ChatGPT plans and pricing.",
                    "query": "openai pricing",
                },
            ]
        )
        provider._search_brave_html = AsyncMock(side_effect=AssertionError("brave should not run"))
        provider._search_duckduckgo_html = AsyncMock(side_effect=AssertionError("duckduckgo should not run"))

        results = asyncio.run(provider.search("openai pricing", max_results=2))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://openai.com/api/pricing")
        provider._search_bing_rss.assert_awaited_once()

    def test_search_continues_after_weak_bing_rss_results_until_official_source_appears(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_bing_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(
            return_value=[
                {
                    "url": "https://www.reddit.com/r/OpenAI/comments/123/pricing/",
                    "title": "OpenAI pricing discussion",
                    "snippet": "Community discussion about API pricing.",
                    "query": "openai api pricing",
                }
            ]
        )
        provider._search_brave_html = AsyncMock(
            return_value=[
                {
                    "url": "https://openai.com/api/pricing/",
                    "title": "API Pricing - OpenAI",
                    "snippet": "Official API pricing and billing details.",
                    "query": "openai api pricing",
                }
            ]
        )
        provider._search_duckduckgo_html = AsyncMock(return_value=[])

        results = asyncio.run(
            provider.search(
                "openai api pricing",
                max_results=2,
                preferred_source_types=("pricing", "documentation", "web"),
            )
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(any(item["url"] == "https://openai.com/api/pricing" for item in results))
        provider._search_brave_html.assert_awaited_once()

    def test_search_skips_provider_during_backoff_after_unavailable_error(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider._search_bing_html = AsyncMock(side_effect=SearchProviderUnavailable("bing challenge", cooldown_seconds=300))
        provider._search_brave_html = AsyncMock(return_value=[])
        provider._search_bing_rss = AsyncMock(
            return_value=[
                {
                    "url": "https://example.com/pricing-models",
                    "title": "SaaS pricing models",
                    "snippet": "Seat-based, usage-based, and hybrid pricing examples.",
                    "query": "saas pricing",
                }
            ]
        )
        provider._search_duckduckgo_html = AsyncMock(side_effect=AssertionError("duckduckgo should not run"))

        first_results = asyncio.run(provider.search("saas pricing", max_results=3))
        second_results = asyncio.run(provider.search("saas pricing", max_results=3))

        self.assertEqual(len(first_results), 1)
        self.assertEqual(len(second_results), 1)
        self.assertEqual(provider._search_bing_html.await_count, 1)


class ResearchWorkerQuerySanitizationTest(unittest.TestCase):
    def test_fallback_queries_avoid_meta_test_topic_noise(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_fallback_queries(
            {
                "topic": "Smoke Test - Sub Agents",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
            },
            {
                "category": "market_trends",
                "title": "AI 产品 · 市场规模与趋势",
                "brief": "围绕 Smoke Test - Sub Agents 调研市场规模与趋势，重点关注模型能力和工作流嵌入。",
                "market_step": "market-trends",
            },
        )

        self.assertTrue(all("smoke test" not in query.lower() for query in queries))
        self.assertTrue(all("围绕" not in query for query in queries))
        self.assertTrue(any("ai product" in query.lower() for query in queries))

    def test_sanitize_queries_rewrites_verbose_brief_style_query(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._sanitize_queries(
            [
                "Smoke Test - Sub Agents 围绕 Smoke Test - Sub Agents 调研 市场规模与趋势，重点关注 模型能力, 工作流嵌入。 中国",
            ],
            {
                "topic": "Smoke Test - Sub Agents",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
            },
            {
                "category": "market_trends",
                "title": "AI 产品 · 市场规模与趋势",
                "brief": "围绕 Smoke Test - Sub Agents 调研市场规模与趋势，重点关注模型能力和工作流嵌入。",
                "market_step": "market-trends",
            },
        )

        self.assertGreaterEqual(len(queries), 1)
        self.assertTrue(all("围绕" not in query for query in queries))
        self.assertTrue(all("重点关注" not in query for query in queries))
        self.assertTrue(all("smoke test" not in query.lower() for query in queries))

    def test_fallback_queries_cover_multiple_search_intents(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_fallback_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "competitor_landscape",
                "title": "AI眼镜 · 竞品格局",
                "brief": "关注 AI 眼镜的竞品、替代方案、社区评价和官网信息。",
                "market_step": "competitor-analysis",
            },
        )

        combined = " || ".join(queries).lower()
        self.assertGreaterEqual(len(queries), 4)
        self.assertIn("竞品", combined)
        self.assertTrue(any(token in combined for token in ("官网", "official", "docs", "文档")))
        self.assertTrue(any(token in combined for token in ("评测", "reviews", "reddit", "社区")))

    def test_english_topic_uses_english_query_pack_even_with_chinese_output_locale(self) -> None:
        agent = ResearchWorkerAgent()
        request = {
            "topic": "Ray-Ban Meta AI glasses",
            "industry_template": "ai_product",
            "geo_scope": ["美国"],
            "output_locale": "zh-CN",
            "language": "zh-CN",
        }
        task = {
            "category": "competitor_landscape",
            "title": "竞品格局",
            "brief": "调研 Ray-Ban Meta AI glasses 的竞品格局、定价和差异化。",
            "market_step": "competitor-analysis",
        }

        queries = agent._build_fallback_queries(request, task)
        combined = " || ".join(queries).lower()

        self.assertFalse(agent._prefers_chinese_queries(request))
        self.assertIn("us", combined)
        self.assertNotIn("美国", combined)
        self.assertNotIn("竞品格局", combined)
        self.assertTrue(any(token in combined for token in ("official product overview", "reviews customer feedback", "alternatives comparison")))

    def test_task_focus_terms_keep_chinese_context_when_task_copy_is_chinese(self) -> None:
        agent = ResearchWorkerAgent()

        task_focus = agent._task_focus_terms(
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            }
        )

        self.assertIn("眼镜", task_focus)
        self.assertNotIn("growth adoption", task_focus)

    def test_market_trend_queries_stay_aligned_to_trend_intent(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_fallback_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            },
        )

        combined = " || ".join(queries).lower()
        self.assertTrue(any(token in combined for token in ("official", "market launch", "趋势", "报告", "benchmark")))
        self.assertFalse(any(token in combined for token in ("reddit", "g2", "capterra", "社区 论坛")))

    def test_chinese_topic_frontloads_generic_aliases_before_exemplar_queries(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_fallback_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": [],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            },
        )

        self.assertGreaterEqual(len(queries), 4)
        self.assertTrue(any(query in {"ai 眼镜", "ai glasses", "ai smart glasses"} for query in queries[:2]))
        self.assertIn("Ray-Ban Meta ai glasses official product overview", queries[:4])
        self.assertTrue(
            any(
                query in {"Rokid ai glasses market trends benchmark report", "Ray-Ban Meta ai glasses official product overview"}
                for query in queries[:4]
            )
        )
        self.assertTrue(any(query in {"ai 眼镜", "ai glasses", "ai smart glasses"} for query in queries))

    def test_user_research_queries_avoid_market_launch_bias(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_fallback_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "user_jobs_and_pains",
                "title": "AI眼镜 · 用户研究",
                "brief": "确认目标用户、使用场景、替代方案和高频痛点。",
                "market_step": "user-research",
                "skill_packs": ["voice-of-customer", "review-clustering"],
            },
        )

        combined = " || ".join(queries).lower()
        self.assertNotIn("market launch", combined)
        self.assertTrue(any(token in combined for token in ("review", "reddit", "community", "feedback pain points")))
        self.assertTrue(any(token in combined for token in ("ai glasses", "smart glasses")))

    def test_english_topic_uses_english_queries_even_when_output_locale_is_chinese(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_fallback_queries(
            {
                "topic": "Ray-Ban Meta AI glasses",
                "industry_template": "ai_product",
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "市场趋势",
                "brief": "关注 Ray-Ban Meta AI glasses 的市场趋势与 adoption。",
                "market_step": "market-trends",
            },
        )

        self.assertTrue(any("official" in query.lower() and "us" in query.lower() for query in queries))
        self.assertTrue(any("market trends" in query.lower() or "benchmark" in query.lower() for query in queries))
        self.assertFalse(any("美国" in query for query in queries if "official" in query.lower()))

    def test_prefers_english_queries_for_english_topic(self) -> None:
        agent = ResearchWorkerAgent()

        self.assertFalse(
            agent._prefers_chinese_queries(
                {
                    "topic": "Ray-Ban Meta AI glasses",
                    "geo_scope": ["美国"],
                    "output_locale": "zh-CN",
                }
            )
        )

    def test_sanitize_queries_prefers_task_aligned_market_trend_queries(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._sanitize_queries(
            [
                "site:meta.com Ray-Ban Meta smart glasses features AI pricing",
                "Ray-Ban Meta smart glasses review Reddit",
                "AI眼镜 对比 Ray-Ban Meta Solos XREAL",
                "AI smart glasses market trends report 2024 2025",
            ],
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            },
        )

        combined = " || ".join(queries).lower()
        self.assertTrue(any("site:" in query for query in queries))
        self.assertTrue(any(token in combined for token in ("market trends", "趋势", "报告", "benchmark")))
        self.assertFalse(any(token in combined for token in ("reddit", "solos xreal", "对比 ray-ban")))

    def test_sanitize_queries_retains_english_alias_for_chinese_topic(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._sanitize_queries(
            [
                "AI眼镜 市场趋势 报告",
                "AI眼镜 官网 产品介绍",
                "AI眼镜 案例 分析",
            ],
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            },
        )

        self.assertTrue(any("site:" in query for query in queries))
        self.assertTrue(any("ai glasses" in query.lower() or "smart glasses" in query.lower() for query in queries))

    def test_pricing_skill_pack_pushes_pricing_queries_and_coverage(self) -> None:
        agent = ResearchWorkerAgent()

        task = {
            "category": "pricing_and_business_model",
            "title": "AI眼镜 · 定价与商业模式",
            "brief": "关注 AI 眼镜的套餐、定价与付费逻辑。",
            "market_step": "business-and-channels",
            "skill_packs": ["pricing-benchmarking", "packaging-analysis"],
        }
        queries = agent._build_fallback_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
            },
            task,
        )

        combined = " || ".join(queries).lower()
        required = agent._required_query_coverage(task)
        self.assertIn("pricing", required)
        self.assertIn("official", required)
        self.assertIn("comparison", required)
        self.assertIn("community", required)
        self.assertTrue(any(token in combined for token in ("定价", "套餐", "计费", "pricing", "billing", "value metric")))

    def test_pricing_fallback_queries_frontload_direct_topic_queries(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_fallback_queries(
            {
                "topic": "OpenAI API pricing",
                "industry_template": "ai_product",
                "geo_scope": [],
                "output_locale": "zh-CN",
                "language": "en-US",
            },
            {
                "category": "pricing_and_business_model",
                "title": "AI Product · Pricing and business model",
                "brief": "Confirm pricing model, packaging, billing and user value feedback for OpenAI API pricing.",
                "market_step": "business-and-channels",
                "must_cover": ["pricing plans", "billing model", "value feedback"],
                "completion_criteria": [
                    "at least one official pricing source",
                    "at least one third-party comparison",
                    "at least one user feedback signal",
                ],
            },
        )

        self.assertGreaterEqual(len(queries), 4)
        self.assertEqual(queries[0], "openai api pricing")
        self.assertTrue(any("official" in query.lower() for query in queries[:3]))
        self.assertFalse(any("business model channels" in query.lower() for query in queries))

    def test_query_search_preferences_skip_non_domain_strategy_tokens(self) -> None:
        agent = ResearchWorkerAgent()
        strategy = agent._search_strategy_for_task({"category": "pricing_and_business_model"})

        preferences = agent._query_search_preferences(
            "openai api pricing",
            strategy,
            {"category": "pricing_and_business_model"},
        )

        self.assertEqual(preferences["preferred_domains"], ())

    def test_query_search_preferences_include_runtime_official_domains_for_official_queries(self) -> None:
        agent = ResearchWorkerAgent()
        strategy = agent._search_strategy_for_task({"category": "pricing_and_business_model"})

        preferences = agent._query_search_preferences(
            "openai api official pricing",
            strategy,
            {"category": "pricing_and_business_model"},
            request={
                "runtime_config": {
                    "retrieval_profile": {
                        "profile_id": "premium_default",
                        "official_domains": ["openai.com", "platform.openai.com"],
                        "official_source_bias": True,
                    }
                }
            },
        )

        self.assertIn("openai.com", preferences["preferred_domains"])
        self.assertIn("platform.openai.com", preferences["preferred_domains"])

    def test_query_topic_anchors_include_alias_for_chinese_topic(self) -> None:
        agent = ResearchWorkerAgent()

        anchors = agent._query_topic_anchors(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
            }
        )

        combined = " || ".join(anchors).lower()
        self.assertTrue(any("眼镜" in anchor for anchor in anchors))
        self.assertTrue(any(token in combined for token in ("ai glasses", "smart glasses", "glasses")))

    def test_strategy_queries_use_english_phrases_for_english_alias_anchor(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_strategy_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            },
            agent._search_strategy_for_task({"category": "market_trends"}),
        )

        combined = " || ".join(queries).lower()
        self.assertTrue(
            any(
                "ai glasses" in query.lower()
                and any(token in query.lower() for token in ("benchmark case study", "reviews customer feedback", "alternatives comparison"))
                for query in queries
            )
        )
        self.assertNotIn("ai glasses 案例", combined)

    def test_topic_seed_queries_frontload_english_alias_for_chinese_topic(self) -> None:
        agent = ResearchWorkerAgent()

        seeds = agent._topic_seed_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国", "美国"],
                "output_locale": "zh-CN",
            }
        )

        self.assertGreaterEqual(len(seeds), 2)
        self.assertEqual(seeds[0], "ai glasses")
        self.assertIn("ai 眼镜", seeds)

    def test_convergence_queries_keep_short_topic_aliases_for_zero_result_topics(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_convergence_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": [],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            },
            ["site:mckinsey.com ai 眼镜 市场规模 TAM SAM SOM growth adoption"],
        )

        self.assertTrue(queries)
        self.assertTrue(any(query in {"ai 眼镜", "ai glasses", "ai smart glasses"} for query in queries[:2]))

    def test_zero_result_retry_queries_keep_short_english_alias_for_chinese_topic(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_zero_result_retry_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "user_jobs_and_pains",
                "title": "AI眼镜 · 用户研究",
                "brief": "确认目标用户、使用场景和真实反馈。",
                "market_step": "user-research",
                "skill_packs": ["voice-of-customer"],
            },
            "site:reddit.com ai 眼镜 reddit 论坛 社区 讨论 用户研究 用户痛点",
        )

        combined = " || ".join(queries).lower()
        self.assertTrue(queries)
        self.assertTrue(any("ai glasses" in query.lower() or "smart glasses" in query.lower() for query in queries))
        self.assertIn("reddit", combined)
        self.assertFalse(any("用户研究 用户痛点" in query for query in queries))

    def test_zero_result_retry_queries_drop_stale_year_noise_for_analysis_queries(self) -> None:
        agent = ResearchWorkerAgent()

        queries = agent._build_zero_result_retry_queries(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            },
            "AI smart glasses market trends 2024 analysis",
        )

        combined = " || ".join(queries).lower()
        self.assertTrue(queries)
        self.assertTrue(any("ai glasses" in query.lower() or "smart glasses" in query.lower() for query in queries))
        self.assertTrue(any(token in combined for token in ("market analysis", "market trends")))
        self.assertFalse(any("2024" in query for query in queries))

    def test_query_coverage_tags_ignore_soft_site_official_noise(self) -> None:
        agent = ResearchWorkerAgent()

        tags = agent._query_coverage_tags("site:reddit.com ai glasses review")
        explicit_official_tags = agent._query_coverage_tags("site:reddit.com ai glasses official review")

        self.assertIn("community", tags)
        self.assertNotIn("official", tags)
        self.assertIn("official", explicit_official_tags)

    def test_voice_of_customer_skill_frontloads_community_research(self) -> None:
        agent = ResearchWorkerAgent()

        task = {
            "category": "user_jobs_and_pains",
            "market_step": "user-research",
            "search_intents": ["official", "analysis"],
            "skill_packs": ["voice-of-customer", "review-clustering"],
        }
        queries = [
            "AI眼镜 reddit forum community discussion",
            "site:example.com AI眼镜 official product overview",
            "AI眼镜 market trends benchmark report",
        ]

        waves = agent._build_search_waves(task, queries)

        self.assertEqual(waves[0]["key"], "anchor")
        self.assertIn("reddit forum community discussion", waves[0]["queries"][0])

    def test_voice_of_customer_anchor_wave_prioritizes_review_queries_when_bucket_overflows(self) -> None:
        agent = ResearchWorkerAgent()

        task = {
            "category": "user_jobs_and_pains",
            "market_step": "user-research",
            "search_intents": ["community", "analysis"],
            "skill_packs": ["voice-of-customer", "review-clustering"],
        }
        queries = [
            "ai glasses",
            "ai 眼镜",
            "Rokid ai glasses user review feedback pain points",
            "ai 眼镜 reddit forum community discussion us",
            "site:reddit.com ai 眼镜 reddit forum community discussion",
        ]

        waves = agent._build_search_waves(task, queries)

        self.assertTrue("review" in waves[0]["queries"][0].lower() or "reddit" in waves[0]["queries"][0].lower())
        self.assertNotIn("ai glasses", waves[0]["queries"])
        self.assertTrue(any("ai glasses" in wave["queries"] for wave in waves[1:]))

    def test_fallback_analysis_accepts_english_alias_page_for_chinese_topic(self) -> None:
        agent = ResearchWorkerAgent()

        analysis = agent._fallback_analysis(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国", "美国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "market_trends",
                "title": "AI眼镜 · 市场趋势",
                "brief": "关注 AI 眼镜市场趋势、技术成熟度和 adoption。",
                "market_step": "market-trends",
            },
            title="AI Glasses Guide: What They Are and How They Work",
            summary="This guide explains AI glasses product capabilities, smart eyewear use cases, and market adoption signals.",
            quote="AI glasses combine smart eyewear hardware with assistants and multimodal features.",
            source_url="https://example.com/ai-glasses-guide",
            is_snippet=False,
        )

        self.assertTrue(analysis["keep"])

    def test_fallback_analysis_rejects_off_topic_generic_source(self) -> None:
        agent = ResearchWorkerAgent()

        analysis = agent._fallback_analysis(
            {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
            },
            {
                "category": "product_experience_teardown",
                "title": "AI眼镜 · 产品体验拆解",
                "brief": "关注 AI 眼镜的产品结构、交互和体验问题。",
                "market_step": "experience-teardown",
            },
            title="AI productivity guide",
            summary="This article discusses general AI productivity workflows for enterprise teams.",
            quote="General guidance for AI productivity tools.",
            source_url="https://example.com/ai-productivity-guide",
            is_snippet=False,
        )

        self.assertFalse(analysis["keep"])

    def test_low_signal_listicle_result_is_rejected_for_experience_task(self) -> None:
        agent = ResearchWorkerAgent()

        self.assertTrue(
            agent._is_low_signal_result(
                {
                    "url": "https://example.com/best-ai-glasses-2025",
                    "title": "Best AI Glasses in 2025",
                    "snippet": "A roundup of top smart glasses tools.",
                    "score": 6,
                },
                {
                    "category": "product_experience_teardown",
                    "market_step": "experience-teardown",
                },
            )
        )


class PlannerAgentTest(unittest.TestCase):
    def test_light_plan_uses_balanced_categories_instead_of_first_two_only(self) -> None:
        agent = PlannerAgent()

        tasks = agent.build_tasks(
            {
                "job_id": "job-1",
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "research_mode": "standard",
                "max_subtasks": 2,
            }
        )

        self.assertEqual(len(tasks), 2)
        self.assertEqual([task["category"] for task in tasks], ["market_trends", "user_jobs_and_pains"])
        self.assertEqual(tasks[0]["agent_mode"], "deep_research_harness")
        self.assertEqual(tasks[0]["command_id"], "deep_general_scan")
        self.assertTrue(tasks[0]["skill_packs"])
        self.assertTrue(tasks[0]["search_intents"])
        self.assertTrue(tasks[0]["completion_criteria"])

    def test_sanitize_tasks_fills_missing_categories_when_llm_duplicates(self) -> None:
        agent = PlannerAgent()
        raw_tasks = [
            {
                "id": "task-a",
                "category": "market_trends",
                "title": "市场趋势 A",
                "brief": "趋势角度一",
                "market_step": "market-trends",
            },
            {
                "id": "task-b",
                "category": "market_trends",
                "title": "市场趋势 B",
                "brief": "趋势角度二",
                "market_step": "market-trends",
            },
        ]

        sanitized = agent._sanitize_tasks(
            {
                "job_id": "job-1",
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "research_mode": "standard",
                "workflow_command": "deep_general_scan",
                "max_subtasks": 2,
            },
            ["market_trends", "user_jobs_and_pains"],
            raw_tasks,
            {
                "label": "AI 产品",
                "focusAreas": ["模型能力", "工作流嵌入"],
                "taskCategories": [
                    "market_trends",
                    "user_jobs_and_pains",
                    "competitor_landscape",
                ],
            },
            [
                {"id": "market-trends", "title": "市场趋势"},
                {"id": "user-research", "title": "用户需求与 JTBD"},
                {"id": "competitor-analysis", "title": "竞品格局"},
            ],
            "deep_general_scan",
            {
                "label": "全景深度扫描",
                "summary": "先形成全景判断",
                "focusInstruction": "先广覆盖，再收窄。",
                "defaultSkillPacks": ["source-triangulation"],
            },
        )

        self.assertEqual([task["category"] for task in sanitized], ["market_trends", "user_jobs_and_pains"])

    def test_fallback_task_contains_deep_research_blueprint(self) -> None:
        agent = PlannerAgent()

        tasks = agent.build_tasks(
            {
                "job_id": "job-1",
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "research_mode": "deep",
                "max_subtasks": 1,
            }
        )

        self.assertEqual(tasks[0]["agent_mode"], "deep_research_harness")
        self.assertIsInstance(tasks[0]["research_goal"], str)
        self.assertGreaterEqual(len(tasks[0]["search_intents"]), 3)
        self.assertGreaterEqual(len(tasks[0]["must_cover"]), 2)
        self.assertGreaterEqual(len(tasks[0]["completion_criteria"]), 2)

    def test_workflow_command_reprioritizes_categories_and_injects_skill_packs(self) -> None:
        agent = PlannerAgent()

        tasks = agent.build_tasks(
            {
                "job_id": "job-2",
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "research_mode": "deep",
                "workflow_command": "competitor_war_room",
                "project_memory": "面向管理层，优先强调竞品差异和价格打法。",
                "max_subtasks": 3,
            }
        )

        self.assertEqual([task["category"] for task in tasks], ["competitor_landscape", "product_experience_teardown", "pricing_and_business_model"])
        self.assertEqual(tasks[0]["command_id"], "competitor_war_room")
        self.assertIn("competitive-mapping", tasks[0]["skill_packs"])
        self.assertIn("pricing-benchmarking", tasks[2]["skill_packs"])
        self.assertIn("竞品差异", tasks[0]["orchestration_notes"])

    def test_build_tasks_falls_back_when_llm_planner_times_out(self) -> None:
        class SlowPlannerClient:
            def is_enabled(self) -> bool:
                return True

            def complete_json(self, _messages, temperature=0.2, max_tokens=1800):
                del temperature, max_tokens
                import time

                time.sleep(0.05)
                return {
                    "tasks": [
                        {
                            "id": "task-slow",
                            "category": "market_trends",
                            "title": "慢响应任务",
                            "brief": "不会被真正采用。",
                            "market_step": "market-trends",
                        }
                    ]
                }

        agent = PlannerAgent(SlowPlannerClient())

        with patch.dict(os.environ, {"PM_AGENT_PLANNER_LLM_TIMEOUT_SECONDS": "0.01"}):
            tasks = agent.build_tasks(
                {
                    "job_id": "job-timeout",
                    "topic": "AI眼镜",
                    "industry_template": "ai_product",
                    "research_mode": "standard",
                    "max_subtasks": 2,
                }
            )

        self.assertEqual(len(tasks), 2)
        self.assertEqual([task["category"] for task in tasks], ["market_trends", "user_jobs_and_pains"])
        self.assertEqual(tasks[0]["agent_mode"], "deep_research_harness")


class ResearchWorkflowEngineBlueprintTest(unittest.TestCase):
    def test_job_blueprint_persists_workflow_command_and_project_memory(self) -> None:
        workflow = ResearchWorkflowEngine()
        job = workflow.build_job_blueprint(
            {
                "job_id": "job-blueprint",
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "research_mode": "deep",
                "depth_preset": "light",
                "failure_policy": "strict",
                "workflow_command": "user_voice_first",
                "project_memory": "面向 PM 和设计负责人，优先保留用户原声。",
                "max_sources": 20,
                "max_subtasks": 3,
                "max_competitors": 4,
                "review_sample_target": 80,
                "time_budget_minutes": 20,
                "geo_scope": ["中国"],
                "language": "zh-CN",
                "output_locale": "zh-CN",
            }
        )

        self.assertEqual(job["workflow_command"], "user_voice_first")
        self.assertEqual(job["failure_policy"], "strict")
        self.assertEqual(job["completion_mode"], "formal")
        self.assertEqual(job["workflow_label"], "用户原声优先")
        self.assertIn("用户原声", job["project_memory"])
        self.assertTrue(job["orchestration_summary"])


class ChatServiceDeltaResearchTest(unittest.TestCase):
    def test_delta_research_keeps_report_pending_final_compose(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-1",
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
                        "completed_task_count": 0,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "claims_count": 0,
                        "report_version_id": "job-1-report-v1",
                        "phase_progress": [],
                        "tasks": [],
                    }
                )
                repository.set_assets(
                    "job-1",
                    {
                        "claims": [],
                        "evidence": [],
                        "report": {"markdown": "## Executive Summary\n- Initial report", "generated_at": "2026-03-30T00:00:00+00:00"},
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )
                repository.create_chat_session({"id": "session-1", "research_job_id": "job-1", "messages": []})

                service = ChatService(repository)
                with patch.object(
                    ResearchWorkflowEngine,
                    "run_delta_research",
                    AsyncMock(
                        return_value=DeltaResearchResult(
                            delta_job_id="delta-1",
                            claim={
                                "id": "delta-1-claim-1",
                                "claim_text": "应先验证核心转化路径，再决定是否扩展功能范围。",
                                "market_step": "recommendations",
                                "evidence_ids": ["delta-1-evidence-1"],
                                "counter_evidence_ids": [],
                                "confidence": 0.72,
                                "status": "verified",
                                "caveats": ["仍需补充付费意愿样本"],
                                "competitor_ids": [],
                                "priority": "high",
                                "actionability_score": 0.86,
                                "last_verified_at": "2026-04-03T00:00:00+00:00",
                            },
                            evidence=[
                                {
                                    "id": "delta-1-evidence-1",
                                    "task_id": "delta-1-task",
                                    "market_step": "recommendations",
                                    "source_url": "https://example.com/delta",
                                    "source_domain": "example.com",
                                    "source_type": "article",
                                    "source_tier": "t2",
                                    "source_tier_label": "T2 高可信交叉来源",
                                    "citation_label": "[S1]",
                                    "title": "Delta evidence",
                                    "captured_at": "2026-04-03T00:00:00+00:00",
                                    "quote": "Teams should validate the core conversion path first.",
                                    "summary": "样本指出当前应优先验证核心转化路径。",
                                    "extracted_fact": "先验证转化路径再扩展功能更稳妥。",
                                    "authority_score": 0.74,
                                    "freshness_score": 0.82,
                                    "confidence": 0.76,
                                    "injection_risk": 0.0,
                                    "tags": ["delta", "recommendations"],
                                    "competitor_name": None,
                                }
                            ],
                            follow_up_message="建议先验证核心转化路径和付费意愿。",
                        )
                    ),
                ):
                    asyncio.run(service._finish_delta_research("session-1", "job-1", "delta-1", "下一步先做什么？"))

                assets = repository.get_assets("job-1")
                job = repository.get_job("job-1")
                session = repository.get_chat_session("session-1")

                self.assertEqual(len(assets["claims"]), 1)
                self.assertGreaterEqual(len(assets["evidence"]), 1)
                self.assertEqual(assets["report"]["stage"], "feedback_pending")
                self.assertEqual(assets["report"]["feedback_count"], 1)
                self.assertEqual(assets["report"]["markdown"], "## Executive Summary\n- Initial report")
                self.assertEqual(assets["report"]["feedback_notes"][0]["question"], "下一步先做什么？")
                self.assertEqual(job["claims_count"], 1)
                self.assertGreaterEqual(job["source_count"], 1)
                self.assertEqual(job["report_version_id"], "job-1-report-v2")
                self.assertEqual(job["active_report_version_id"], "job-1-report-v2")
                self.assertIsNone(job.get("stable_report_version_id"))
                self.assertEqual([item["version_id"] for item in assets["report_versions"]], ["job-1-report-v2"])
                self.assertEqual(assets["report_versions"][0]["generated_from_question"], "下一步先做什么？")
                self.assertEqual(len(session["messages"]), 1)
                self.assertEqual(session["messages"][0]["answer_mode"], "delta_draft")
                self.assertEqual(session["messages"][0]["draft_version_id"], "job-1-report-v2")
                self.assertTrue(session["messages"][0]["requires_finalize"])
                self.assertTrue(all(item.get("source_url") for item in assets["evidence"]))

    def test_delta_research_marks_internal_context_evidence_as_non_finalizable(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-ctx",
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
                        "completed_task_count": 0,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "claims_count": 0,
                        "report_version_id": "job-ctx-report-v1",
                        "phase_progress": [],
                        "tasks": [],
                    }
                )
                repository.set_assets(
                    "job-ctx",
                    {
                        "claims": [],
                        "evidence": [],
                        "report": {"markdown": "## Executive Summary\n- Initial report", "generated_at": "2026-03-30T00:00:00+00:00"},
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )
                repository.create_chat_session({"id": "session-ctx", "research_job_id": "job-ctx", "messages": []})

                service = ChatService(repository)
                with patch.object(
                    ResearchWorkflowEngine,
                    "run_delta_research",
                    AsyncMock(
                        return_value=DeltaResearchResult(
                            delta_job_id="delta-ctx",
                            claim={
                                "id": "delta-ctx-claim-1",
                                "claim_text": "建议先验证关键假设。",
                                "market_step": "recommendations",
                                "evidence_ids": ["delta-ctx-evidence-1"],
                                "counter_evidence_ids": [],
                                "confidence": 0.52,
                                "status": "inferred",
                                "caveats": [],
                                "competitor_ids": [],
                                "priority": "medium",
                                "actionability_score": 0.7,
                                "last_verified_at": "2026-04-03T00:00:00+00:00",
                            },
                            evidence=[
                                {
                                    "id": "delta-ctx-evidence-1",
                                    "task_id": "delta-ctx-task",
                                    "market_step": "recommendations",
                                    "source_url": "internal://delta-context/delta-ctx",
                                    "source_type": "internal",
                                    "title": "Delta context fallback",
                                    "summary": "仅有内部上下文线索。",
                                    "confidence": 0.52,
                                }
                            ],
                            follow_up_message="先列出关键假设再补外部验证。",
                        )
                    ),
                ):
                    asyncio.run(service._finish_delta_research("session-ctx", "job-ctx", "delta-ctx", "下一步先做什么？"))

                assets = repository.get_assets("job-ctx")
                self.assertEqual(assets["evidence"][0]["evidence_role"], "context_only")
                self.assertEqual(assets["evidence"][0]["final_eligibility"], "requires_external_evidence")
                self.assertEqual(assets["claims"][0]["final_eligibility"], "requires_external_evidence")
                self.assertIn("需补充外部证据", assets["report"]["feedback_notes"][0]["action"])
                self.assertEqual(assets["report"]["stage"], "feedback_pending")

    def test_delta_research_sync_failure_appends_fallback_message(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-1",
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
                        "completed_task_count": 0,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "claims_count": 0,
                        "report_version_id": "job-1-report-v1",
                        "phase_progress": [],
                        "tasks": [],
                    }
                )
                repository.set_assets(
                    "job-1",
                    {
                        "claims": [],
                        "evidence": [],
                        "report": {"markdown": "## Executive Summary\n- Initial report", "generated_at": "2026-03-30T00:00:00+00:00"},
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )
                repository.create_chat_session({"id": "session-1", "research_job_id": "job-1", "messages": []})

                service = ChatService(repository)
                with patch.object(service, "_finish_delta_research", AsyncMock(side_effect=RuntimeError("delta exploded"))):
                    service._finish_delta_research_sync("session-1", "job-1", "delta-1", "下一步先做什么？")

                session = repository.get_chat_session("session-1")
                queue = repository.get_job_queue("job-1")
                event = queue.get_nowait()
                if event["event"] == "chat.session.updated":
                    event = queue.get_nowait()

                self.assertTrue(session["messages"])
                self.assertEqual(session["messages"][-1]["role"], "assistant")
                self.assertIn("补充研究", session["messages"][-1]["content"])
                self.assertEqual(session["messages"][-1]["answer_mode"], "delta_failed")
                self.assertEqual(event["event"], "delta_research.failed")


class ResearchWorkflowDeltaResearchTest(unittest.TestCase):
    def test_delta_research_falls_back_when_collection_times_out(self) -> None:
        workflow = ResearchWorkflowEngine()

        async def run_case():
            with patch.object(
                workflow.research_worker,
                "collect_evidence",
                AsyncMock(side_effect=asyncio.TimeoutError()),
            ):
                return await workflow.run_delta_research(
                    {
                        "job_id": "job-timeout",
                        "topic": "AI PM",
                        "industry_template": "ai_product",
                        "max_sources": 6,
                        "max_competitors": 4,
                        "time_budget_minutes": 5,
                    },
                    "下一步先做什么？",
                    "delta-timeout",
                )

        result = asyncio.run(run_case())

        self.assertEqual(result.delta_job_id, "delta-timeout")
        self.assertEqual(result.claim["id"], "delta-timeout-claim-1")
        self.assertTrue(result.evidence)
        self.assertEqual(result.evidence[0]["source_type"], "internal")

    def test_delta_research_re_raises_unexpected_collection_errors(self) -> None:
        workflow = ResearchWorkflowEngine()

        async def run_case():
            with patch.object(
                workflow.research_worker,
                "collect_evidence",
                AsyncMock(side_effect=RuntimeError("delta exploded")),
            ):
                return await workflow.run_delta_research(
                    {
                        "job_id": "job-runtime-error",
                        "topic": "AI PM",
                        "industry_template": "ai_product",
                        "max_sources": 6,
                        "max_competitors": 4,
                        "time_budget_minutes": 5,
                    },
                    "下一步先做什么？",
                    "delta-runtime-error",
                )

        with self.assertRaisesRegex(RuntimeError, "delta exploded"):
            asyncio.run(run_case())


class ResearchWorkerUserFacingErrorTest(unittest.TestCase):
    def test_search_error_message_is_productized(self) -> None:
        agent = ResearchWorkerAgent()

        message = agent._user_facing_runtime_error(httpx.ConnectTimeout("search timeout"), "search")

        self.assertEqual(message, "部分搜索来源响应较慢，系统已跳过超时来源并继续检索。")

    def test_fetch_error_message_hides_raw_403_details(self) -> None:
        agent = ResearchWorkerAgent()
        request = httpx.Request("GET", "https://www.zhihu.com/question/123")
        response = httpx.Response(403, request=request)
        error = httpx.HTTPStatusError("403 Forbidden", request=request, response=response)

        message = agent._user_facing_runtime_error(error, "fetch")

        self.assertEqual(message, "部分页面限制直接访问，系统已保留搜索摘要并继续补充其他来源。")
        self.assertNotIn("zhihu.com", message)
        self.assertNotIn("403", message)

    def test_fetch_error_message_productizes_private_page(self) -> None:
        agent = ResearchWorkerAgent()

        message = agent._user_facing_runtime_error(PrivateAccessError("requires sign in"), "fetch")

        self.assertEqual(message, "部分页面需要登录或属于受限页面，系统已回退到搜索摘要并继续补充其他来源。")


class ContentExtractorPreflightTest(unittest.TestCase):
    def test_fetch_and_extract_page_blocks_cross_host_redirect(self) -> None:
        async def run_case():
            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.host == "example.com":
                    return httpx.Response(
                        302,
                        headers={"location": "https://tracking.example.net/report"},
                        request=request,
                    )
                return httpx.Response(404, request=request)

            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport, timeout=5) as client:
                with self.assertRaises(UnsafeRedirectError):
                    await fetch_and_extract_page("https://example.com/report", client=client)

        asyncio.run(run_case())

    def test_fetch_and_extract_page_allows_www_redirect(self) -> None:
        async def run_case():
            html = """
            <html>
              <head>
                <title>AI Glasses report</title>
                <meta name="description" content="AI smart glasses market report" />
              </head>
              <body>
                <main>
                  <p>AI smart glasses market adoption keeps growing across retail and enterprise use cases with camera, audio, and assistant features.</p>
                </main>
              </body>
            </html>
            """

            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.host == "example.com":
                    return httpx.Response(
                        301,
                        headers={"location": "https://www.example.com/report"},
                        request=request,
                    )
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=html,
                    request=request,
                )

            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport, timeout=5) as client:
                page = await fetch_and_extract_page("https://example.com/report", client=client)
            return page

        page = asyncio.run(run_case())

        self.assertEqual(page["url"], "https://www.example.com/report")
        self.assertIn("AI smart glasses market adoption", page["text"])

    def test_fetch_and_extract_page_detects_login_wall(self) -> None:
        async def run_case():
            html = """
            <html>
              <head><title>Sign in - Example</title></head>
              <body>
                <form action="/login">
                  <label>Email</label>
                  <input type="password" />
                </form>
              </body>
            </html>
            """

            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=html,
                    request=request,
                )

            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport, timeout=5) as client:
                with self.assertRaises(PrivateAccessError):
                    await fetch_and_extract_page("https://example.com/login", client=client)

        asyncio.run(run_case())


class ResearchWorkflowFailureHandlingTest(unittest.TestCase):
    def test_run_research_completes_with_diagnostic_draft_when_no_evidence_is_collected_in_graceful_mode(self) -> None:
        workflow = ResearchWorkflowEngine()
        request = {
            "job_id": "job-empty-graceful",
            "topic": "AI PM",
            "industry_template": "ai_product",
            "research_mode": "standard",
            "depth_preset": "light",
            "failure_policy": "graceful",
            "workflow_command": "deep_general_scan",
            "project_memory": "",
            "max_sources": 8,
            "max_subtasks": 1,
            "max_competitors": 4,
            "review_sample_target": 40,
            "time_budget_minutes": 10,
            "geo_scope": [],
            "language": "zh-CN",
            "output_locale": "zh-CN",
        }
        job = workflow.build_job_blueprint(dict(request))
        events: list[str] = []

        async def publish(event_name, event_payload):
            del event_payload
            events.append(event_name)

        async def run_case():
            with patch.object(
                workflow.planner,
                "build_tasks",
                return_value=[
                    {
                        "id": "task-1",
                        "title": "市场趋势",
                        "category": "market_trends",
                        "brief": "调研市场趋势。",
                        "market_step": "market-trends",
                        "status": "queued",
                    }
                ],
            ), patch.object(workflow.research_worker, "collect_evidence", AsyncMock(return_value=[])):
                return await workflow.run_research(job, dict(request), publish)

        assets = asyncio.run(run_case())

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["completion_mode"], "diagnostic")
        self.assertIsNone(job["latest_error"])
        self.assertIn("研究快照", job["latest_warning"])
        self.assertIn("外部证据", job["latest_warning"])
        self.assertTrue(assets["report"]["markdown"].strip())
        self.assertEqual(assets["report"]["stage"], "draft")
        self.assertEqual(job["report_version_id"], "job-empty-graceful-report-v1")
        self.assertEqual(assets["market_map"]["report_context_source"], "no-evidence-diagnostic-draft")
        self.assertIn("job.progress", events)
        self.assertNotIn("job.failed", events)

    def test_run_research_marks_job_failed_when_no_evidence_is_collected(self) -> None:
        workflow = ResearchWorkflowEngine()
        request = {
            "job_id": "job-empty",
            "topic": "AI PM",
            "industry_template": "ai_product",
            "research_mode": "standard",
            "depth_preset": "light",
            "failure_policy": "strict",
            "workflow_command": "deep_general_scan",
            "project_memory": "",
            "max_sources": 8,
            "max_subtasks": 1,
            "max_competitors": 4,
            "review_sample_target": 40,
            "time_budget_minutes": 10,
            "geo_scope": [],
            "language": "zh-CN",
            "output_locale": "zh-CN",
        }
        job = workflow.build_job_blueprint(dict(request))
        events: list[str] = []

        async def publish(event_name, event_payload):
            events.append(event_name)

        async def run_case():
            with patch.object(
                workflow.planner,
                "build_tasks",
                return_value=[
                    {
                        "id": "task-1",
                        "title": "市场趋势",
                        "category": "market_trends",
                        "brief": "调研市场趋势。",
                        "market_step": "market-trends",
                        "status": "queued",
                    }
                ],
            ), patch.object(workflow.research_worker, "collect_evidence", AsyncMock(return_value=[])):
                return await workflow.run_research(job, dict(request), publish)

        assets = asyncio.run(run_case())

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["completion_mode"], "diagnostic")
        self.assertIn("外部证据", job["latest_error"])
        self.assertIn("研究快照", job["latest_error"])
        self.assertTrue(assets["report"]["markdown"].strip())
        self.assertEqual(assets["report"]["stage"], "draft")
        self.assertEqual(assets["report"]["claim_ids"], [])
        self.assertEqual(assets["report"]["evidence_ids"], [])
        self.assertEqual(assets["report"]["source_domains"], [])
        self.assertEqual(job["report_version_id"], "job-empty-report-v1")
        self.assertEqual(assets["report_versions"][0]["version_id"], "job-empty-report-v1")
        self.assertEqual(assets["report_versions"][0]["claim_ids"], [])
        self.assertEqual(assets["report_versions"][0]["evidence_ids"], [])
        self.assertEqual(assets["report_versions"][0]["source_domains"], [])
        self.assertEqual(assets["market_map"]["report_context_source"], "no-evidence-diagnostic-draft")
        self.assertIn("job.failed", events)

    def test_no_evidence_failure_message_explains_blocked_sources(self) -> None:
        workflow = ResearchWorkflowEngine()

        message = workflow._build_no_evidence_failure_message(
            {
                "tasks": [
                    {
                        "latest_error": "Client error '403 Forbidden' for url 'https://www.zhihu.com/question/123'",
                        "visited_sources": [{"url": "https://www.zhihu.com/question/123"}],
                    }
                ]
            }
        )

        self.assertIn("自动跳过部分来源限制访问", message)
        self.assertNotIn("403 Forbidden", message)
        self.assertIn("正式结论", message)
        self.assertIn("研究快照", message)

    def test_no_evidence_failure_message_explains_search_stage_instability(self) -> None:
        workflow = ResearchWorkflowEngine()

        message = workflow._build_no_evidence_failure_message(
            {
                "tasks": [
                    {
                        "latest_error": "",
                        "visited_sources": [],
                        "research_rounds": [
                            {
                                "query_summaries": [
                                    {"query": "AI PM pricing", "status": "search_error", "search_result_count": 0},
                                    {"query": "AI PM docs", "status": "search_error", "search_result_count": 0},
                                ]
                            }
                        ],
                    }
                ]
            }
        )

        self.assertIn("搜索阶段遇到较多连接异常", message)
        self.assertIn("官网域名", message)
        self.assertIn("研究快照", message)

    def test_no_evidence_failure_message_explains_filtered_candidates(self) -> None:
        workflow = ResearchWorkflowEngine()

        message = workflow._build_no_evidence_failure_message(
            {
                "tasks": [
                    {
                        "latest_error": "",
                        "visited_sources": [],
                        "research_rounds": [
                            {
                                "query_summaries": [
                                    {"query": "AI PM pricing", "status": "filtered", "search_result_count": 4},
                                ]
                            }
                        ],
                    }
                ]
            }
        )

        self.assertIn("命中过候选页面", message)
        self.assertIn("竞品锚点", message)
        self.assertIn("研究快照", message)

    def test_run_research_marks_job_cancelled_instead_of_failed(self) -> None:
        workflow = ResearchWorkflowEngine()
        request = {
            "job_id": "job-cancelled",
            "topic": "AI眼镜",
            "industry_template": "ai_product",
            "research_mode": "standard",
            "depth_preset": "light",
            "workflow_command": "deep_general_scan",
            "project_memory": "",
            "max_sources": 8,
            "max_subtasks": 1,
            "max_competitors": 4,
            "review_sample_target": 40,
            "time_budget_minutes": 10,
            "geo_scope": [],
            "language": "zh-CN",
            "output_locale": "zh-CN",
        }
        job = workflow.build_job_blueprint(dict(request))
        events: list[str] = []
        cancellation = {"reason": None}

        async def publish(event_name, event_payload):
            del event_payload
            events.append(event_name)

        async def fake_collect_evidence(*args, **kwargs):
            del args, kwargs
            cancellation["reason"] = "用户手动停止本次研究。"
            return []

        async def run_case():
            with patch.object(
                workflow.planner,
                "build_tasks",
                return_value=[
                    {
                        "id": "task-1",
                        "title": "市场趋势",
                        "category": "market_trends",
                        "brief": "调研市场趋势。",
                        "market_step": "market-trends",
                        "status": "queued",
                    }
                ],
            ), patch.object(workflow.research_worker, "collect_evidence", side_effect=fake_collect_evidence):
                return await workflow.run_research(
                    job,
                    dict(request),
                    publish,
                    check_cancelled=lambda: cancellation["reason"],
                )

        assets = asyncio.run(run_case())

        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["cancellation_reason"], "用户手动停止本次研究。")
        self.assertIsNone(job["latest_error"])
        self.assertEqual(job["tasks"][0]["status"], "cancelled")
        self.assertEqual(assets["evidence"], [])
        self.assertNotIn("job.failed", events)

    def test_task_progress_updates_job_source_count_before_task_completes(self) -> None:
        workflow = ResearchWorkflowEngine()
        request = {
            "job_id": "job-progress",
            "topic": "AI眼镜",
            "industry_template": "ai_product",
            "research_mode": "standard",
            "depth_preset": "light",
            "workflow_command": "deep_general_scan",
            "project_memory": "",
            "max_sources": 6,
            "max_subtasks": 1,
            "max_competitors": 4,
            "review_sample_target": 20,
            "time_budget_minutes": 5,
            "geo_scope": [],
            "language": "zh-CN",
            "output_locale": "zh-CN",
        }
        job = workflow.build_job_blueprint(dict(request))
        progress_events: list[tuple[str, int, int, int, int]] = []

        async def publish(event_name, event_payload):
            task_payload = event_payload.get("task") or {}
            job_payload = event_payload.get("job") or {}
            assets_payload = event_payload.get("assets") or {}
            coverage_payload = task_payload.get("coverage_status") or {}
            progress_events.append(
                (
                    event_name,
                    int(job_payload.get("source_count") or 0),
                    int(task_payload.get("source_count") or 0),
                    len(assets_payload.get("evidence") or []),
                    len(coverage_payload.get("covered_query_tags") or []),
                )
            )

        async def fake_collect_evidence(_request, task, _competitor_names, _browser, on_progress, cancel_probe=None):
            del cancel_probe
            live_evidence = [
                {
                    "id": "task-1-evidence-1",
                    "task_id": task["id"],
                    "market_step": task["market_step"],
                    "source_url": "https://example.com/source-1",
                    "source_domain": "example.com",
                    "source_type": "web",
                    "source_tier": "t2",
                    "source_tier_label": "T2 高可信交叉来源",
                    "citation_label": "[S1]",
                    "title": "Example Source 1",
                    "published_at": "2026-04-06T00:00:00+00:00",
                    "captured_at": "2026-04-06T00:00:00+00:00",
                    "quote": "Example quote 1",
                    "summary": "Example summary 1",
                    "extracted_fact": "Example fact 1",
                    "authority_score": 0.82,
                    "freshness_score": 0.8,
                    "confidence": 0.81,
                    "injection_risk": 0.0,
                    "tags": ["official"],
                    "competitor_name": None,
                },
                {
                    "id": "task-1-evidence-2",
                    "task_id": task["id"],
                    "market_step": task["market_step"],
                    "source_url": "https://example.com/source-2",
                    "source_domain": "example.com",
                    "source_type": "article",
                    "source_tier": "t2",
                    "source_tier_label": "T2 高可信交叉来源",
                    "citation_label": "[S2]",
                    "title": "Example Source 2",
                    "published_at": "2026-04-06T00:00:00+00:00",
                    "captured_at": "2026-04-06T00:00:00+00:00",
                    "quote": "Example quote 2",
                    "summary": "Example summary 2",
                    "extracted_fact": "Example fact 2",
                    "authority_score": 0.76,
                    "freshness_score": 0.8,
                    "confidence": 0.77,
                    "injection_risk": 0.0,
                    "tags": ["analysis"],
                    "competitor_name": None,
                },
            ]
            task["source_count"] = 2
            task["partial_evidence"] = live_evidence
            task["coverage_status"] = {
                "required_query_tags": ["official", "analysis"],
                "covered_query_tags": ["official", "analysis"],
                "missing_required": [],
                "query_tag_counts": {"official": 1, "analysis": 1},
                "target_sources": 3,
            }
            await on_progress(task, "已抓取 2 / 3 个来源。")
            return live_evidence

        async def run_case():
            with patch.object(
                workflow.planner,
                "build_tasks",
                return_value=[
                    {
                        "id": "task-1",
                        "title": "市场趋势",
                        "category": "market_trends",
                        "brief": "调研市场趋势。",
                        "market_step": "market-trends",
                        "status": "queued",
                        "source_count": 0,
                        "retry_count": 0,
                        "latest_error": None,
                    }
                ],
            ), patch.object(workflow.research_worker, "collect_evidence", side_effect=fake_collect_evidence), patch.object(
                workflow.verifier,
                "build_claims",
                return_value=[],
            ), patch.object(
                workflow.synthesizer,
                "extract_competitors",
                return_value=[],
            ), patch.object(
                workflow.synthesizer,
                "build_report",
                return_value={"markdown": "## Summary\n- OK", "generated_at": "2026-04-06T00:00:00+00:00", "stage": "draft"},
            ):
                return await workflow.run_research(job, dict(request), publish)

        assets = asyncio.run(run_case())

        self.assertEqual(job["source_count"], 2)
        self.assertEqual(len(assets["evidence"]), 2)
        self.assertEqual(assets["report"]["claim_ids"], [])
        self.assertEqual(assets["report"]["evidence_ids"], ["task-1-evidence-1", "task-1-evidence-2"])
        self.assertEqual(assets["report"]["source_domains"], ["example.com"])
        self.assertEqual(assets["report_versions"][0]["evidence_ids"], ["task-1-evidence-1", "task-1-evidence-2"])
        self.assertTrue(
            any(
                event == "task.progress"
                and job_count >= 2
                and task_count >= 2
                and asset_count >= 2
                and covered_count >= 2
                for event, job_count, task_count, asset_count, covered_count in progress_events
            )
        )


class ResearchJobServiceFinalizeReportTest(unittest.TestCase):
    def test_finalize_report_generates_final_version_from_structured_assets(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-2",
                        "topic": "AI PM",
                        "industry_template": "ai_product",
                        "research_mode": "standard",
                        "depth_preset": "light",
                        "status": "completed",
                        "overall_progress": 100,
                        "current_phase": "finalizing",
                        "eta_seconds": 0,
                        "source_count": 3,
                        "competitor_count": 0,
                        "completed_task_count": 1,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "claims_count": 1,
                        "report_version_id": "job-2-report-v1",
                        "phase_progress": [],
                        "tasks": [],
                    }
                )
                repository.set_assets(
                    "job-2",
                    {
                        "claims": [
                            {
                                "id": "claim-1",
                                "claim_text": "应先验证核心转化路径，再决定更重的功能建设。",
                                "market_step": "recommendations",
                                "confidence": 0.78,
                                "status": "verified",
                                "priority": "high",
                                "actionability_score": 0.88,
                                "caveats": ["仍需补充企业客户定价访谈"],
                                "evidence_ids": ["e1", "e2"],
                            }
                        ],
                        "evidence": [
                            {
                                "id": "e1",
                                "market_step": "recommendations",
                                "confidence": 0.74,
                                "authority_score": 0.72,
                                "freshness_score": 0.8,
                                "source_url": "https://example.com/research",
                                "source_type": "article",
                                "title": "Research summary",
                                "summary": "样本显示团队更看重转化验证和可追溯报告。",
                                "competitor_name": None,
                            },
                            {
                                "id": "e2",
                                "market_step": "recommendations",
                                "confidence": 0.71,
                                "authority_score": 0.76,
                                "freshness_score": 0.74,
                                "source_url": "https://insights.example.org/pm-notes",
                                "source_type": "analysis",
                                "title": "PM execution notes",
                                "summary": "多团队案例提示先验证付费意愿再扩展功能更稳妥。",
                                "competitor_name": None,
                            },
                            {
                                "id": "e3",
                                "market_step": "user-research",
                                "confidence": 0.67,
                                "authority_score": 0.69,
                                "freshness_score": 0.7,
                                "source_url": "https://signals.example.net/interviews",
                                "source_type": "report",
                                "title": "Interview summary",
                                "summary": "访谈样本强调目标用户更关注可衡量的转化闭环。",
                                "competitor_name": None,
                            },
                        ],
                        "report": {
                            "markdown": "## Executive Summary\n- Initial draft",
                            "generated_at": "2026-03-30T00:00:00+00:00",
                            "updated_at": "2026-03-30T00:00:00+00:00",
                            "stage": "feedback_pending",
                            "feedback_count": 1,
                            "feedback_notes": [
                                {
                                    "question": "这一段需要结合 PM 追问再展开",
                                    "response": "需要补进终稿",
                                    "action": "等待显式最终成文",
                                    "created_at": "2026-03-30T00:01:00+00:00",
                                }
                            ],
                        },
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )
                repository.create_chat_session(
                    {
                        "id": "session-2",
                        "research_job_id": "job-2",
                        "messages": [
                            {"id": "m1", "role": "user", "content": "能不能把重点放在先验证付费意愿？", "cited_claim_ids": [], "created_at": "2026-03-30T00:02:00+00:00"}
                        ],
                    }
                )

                service = ResearchJobService(repository)
                assets = service.finalize_report("job-2")
                job = repository.get_job("job-2")

                self.assertEqual(assets["report"]["stage"], "final")
                self.assertTrue(assets["report"]["long_report_ready"])
                self.assertIn("## PM 反馈整合", assets["report"]["markdown"])
                self.assertTrue(assets["report"]["board_brief_markdown"].strip())
                self.assertTrue(assets["report"]["executive_memo_markdown"].strip())
                self.assertTrue(assets["report"]["appendix_markdown"].strip())
                self.assertTrue(assets["report"]["conflict_summary_markdown"].strip())
                self.assertEqual(assets["report"]["decision_snapshot"]["readiness"], "偏低")
                self.assertTrue(assets["report"]["quality_gate"]["passed"])
                self.assertEqual(assets["report"]["claim_ids"], ["claim-1"])
                self.assertTrue({"e1", "e2"}.issubset(set(assets["report"]["evidence_ids"])))
                self.assertTrue(set(assets["report"]["evidence_ids"]).issubset({"e1", "e2", "e3"}))
                self.assertTrue({"example.com", "insights.example.org"}.issubset(set(assets["report"]["source_domains"])))
                self.assertEqual(job["report_version_id"], "job-2-report-v2")
                self.assertEqual([item["version_id"] for item in assets["report_versions"]], ["job-2-report-v1", "job-2-report-v2"])
                self.assertEqual(assets["report_versions"][0]["claim_ids"], ["claim-1"])
                self.assertEqual(assets["report_versions"][0]["evidence_ids"], ["e1", "e2", "e3"])
                self.assertEqual(assets["report_versions"][0]["source_domains"], ["example.com", "insights.example.org", "signals.example.net"])
                self.assertEqual(assets["report_versions"][-1]["stage"], "final")
                self.assertTrue(assets["report_versions"][-1]["board_brief_markdown"].strip())
                self.assertTrue(assets["report_versions"][-1]["executive_memo_markdown"].strip())
                self.assertEqual(assets["report_versions"][-1]["claim_ids"], ["claim-1"])
                self.assertEqual(assets["report_versions"][-1]["evidence_ids"], assets["report"]["evidence_ids"])
                self.assertEqual(assets["report_versions"][-1]["source_domains"], assets["report"]["source_domains"])
                self.assertEqual(assets["market_map"]["report_context_source"], "llm-dossier-rewrite-formal-evidence-only")

    def test_finalize_report_blocks_when_only_internal_delta_context_exists(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-3",
                        "topic": "AI PM",
                        "industry_template": "ai_product",
                        "research_mode": "standard",
                        "depth_preset": "light",
                        "status": "completed",
                        "overall_progress": 100,
                        "current_phase": "finalizing",
                        "eta_seconds": 0,
                        "source_count": 1,
                        "competitor_count": 0,
                        "completed_task_count": 1,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "claims_count": 1,
                        "report_version_id": "job-3-report-v1",
                        "phase_progress": [],
                        "tasks": [],
                    }
                )
                repository.set_assets(
                    "job-3",
                    {
                        "claims": [
                            {
                                "id": "delta-claim-1",
                                "claim_text": "先验证转化路径",
                                "market_step": "recommendations",
                                "confidence": 0.52,
                                "status": "inferred",
                                "priority": "medium",
                                "actionability_score": 0.7,
                                "evidence_ids": ["delta-e1"],
                                "caveats": ["仍需补充外部证据"],
                            }
                        ],
                        "evidence": [
                            {
                                "id": "delta-e1",
                                "market_step": "recommendations",
                                "confidence": 0.52,
                                "authority_score": 0.38,
                                "freshness_score": 0.58,
                                "source_url": "internal://delta-context/delta-1",
                                "source_type": "internal",
                                "title": "Delta fallback note",
                                "summary": "仅有内部上下文线索。",
                                "evidence_role": "context_only",
                                "tags": ["delta-context-fallback", "context-only"],
                                "competitor_name": None,
                            }
                        ],
                        "report": {
                            "markdown": "## Executive Summary\n- Pending finalize",
                            "generated_at": "2026-03-30T00:00:00+00:00",
                            "updated_at": "2026-03-30T00:00:00+00:00",
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
                assets = service.finalize_report("job-3")
                job = repository.get_job("job-3")
                event = repository.get_job_queue("job-3").get_nowait()

                self.assertEqual(assets["report"]["stage"], "feedback_pending")
                self.assertFalse(assets["report"]["long_report_ready"])
                self.assertFalse(assets["report"]["quality_gate"]["passed"])
                self.assertTrue(any("internal://delta-context" in reason for reason in assets["report"]["quality_gate"]["reasons"]))
                self.assertEqual(job["report_version_id"], "job-3-report-v1")
                self.assertEqual([item["version_id"] for item in assets["report_versions"]], ["job-3-report-v1"])
                self.assertEqual(assets["market_map"]["report_context_source"], "finalize-quality-gate-blocked")
                self.assertEqual(event["event"], "report.finalize_blocked")

    def test_finalize_report_blocks_when_only_snippet_t4_evidence_exists(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-snippet-only",
                        "topic": "AI PM",
                        "industry_template": "ai_product",
                        "research_mode": "standard",
                        "depth_preset": "light",
                        "status": "completed",
                        "overall_progress": 100,
                        "current_phase": "finalizing",
                        "eta_seconds": 0,
                        "source_count": 1,
                        "competitor_count": 0,
                        "completed_task_count": 1,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "claims_count": 1,
                        "report_version_id": "job-snippet-only-report-v1",
                        "phase_progress": [],
                        "tasks": [],
                    }
                )
                repository.set_assets(
                    "job-snippet-only",
                    {
                        "claims": [
                            {
                                "id": "claim-1",
                                "claim_text": "用户对 AI PM 工具仍在早期探索阶段。",
                                "market_step": "user-research",
                                "confidence": 0.5,
                                "status": "inferred",
                                "priority": "medium",
                                "actionability_score": 0.5,
                                "evidence_ids": ["snippet-e1"],
                                "caveats": ["当前只有摘要级线索。"],
                            }
                        ],
                        "evidence": [
                            {
                                "id": "snippet-e1",
                                "market_step": "user-research",
                                "confidence": 0.45,
                                "authority_score": 0.4,
                                "freshness_score": 0.58,
                                "source_url": "https://example.com/forum-post",
                                "source_type": "community",
                                "title": "Forum snippet",
                                "summary": "只有搜索摘要，没有抓到正文。",
                                "quote": "only snippet",
                                "extracted_fact": "用户在讨论 AI PM 工具。",
                                "tags": ["search-snippet"],
                                "source_tier": "t4",
                                "source_tier_label": "T4 待核验线索",
                                "competitor_name": None,
                            }
                        ],
                        "report": {
                            "markdown": "## Executive Summary\n- Pending finalize",
                            "generated_at": "2026-03-30T00:00:00+00:00",
                            "updated_at": "2026-03-30T00:00:00+00:00",
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
                assets = service.finalize_report("job-snippet-only")
                event = repository.get_job_queue("job-snippet-only").get_nowait()

                self.assertFalse(assets["report"]["quality_gate"]["passed"])
                self.assertEqual(assets["market_map"]["report_context_source"], "finalize-quality-gate-blocked")
                self.assertEqual(event["event"], "report.finalize_blocked")


class ResearchJobServiceFailureHandlingTest(unittest.TestCase):
    def test_get_job_reconciles_stale_task_coverage_from_saved_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-coverage",
                        "topic": "AI眼镜",
                        "industry_template": "ai_product",
                        "research_mode": "standard",
                        "depth_preset": "light",
                        "status": "completed",
                        "overall_progress": 100,
                        "current_phase": "finalizing",
                        "eta_seconds": 0,
                        "source_count": 2,
                        "competitor_count": 0,
                        "completed_task_count": 1,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "claims_count": 0,
                        "report_version_id": None,
                        "phase_progress": [],
                        "max_sources": 8,
                        "max_subtasks": 1,
                        "tasks": [
                            {
                                "id": "task-1",
                                "category": "user_jobs_and_pains",
                                "market_step": "user-research",
                                "source_count": 2,
                                "coverage_status": {
                                    "required_query_tags": ["community", "analysis"],
                                    "covered_query_tags": [],
                                    "missing_required": ["community", "analysis"],
                                    "query_tag_counts": {},
                                    "target_sources": 8,
                                },
                            }
                        ],
                    }
                )
                repository.set_assets(
                    "job-coverage",
                    {
                        "claims": [],
                        "evidence": [
                            {
                                "id": "e1",
                                "task_id": "task-1",
                                "source_url": "https://www.pcmag.com/reviews/rokid-glasses",
                                "source_type": "review",
                                "title": "Rokid Glasses review",
                                "summary": "Hands-on review covering comfort and tradeoffs.",
                                "quote": "Hands-on review",
                                "extracted_fact": "Users mention comfort tradeoffs.",
                                "confidence": 0.81,
                                "tags": ["anchor"],
                            },
                            {
                                "id": "e2",
                                "task_id": "task-1",
                                "source_url": "https://example.com/blog/ai-glasses-market-insights",
                                "source_type": "article",
                                "title": "AI glasses market insights and adoption analysis",
                                "summary": "Analysts outline current use cases and adoption signals.",
                                "quote": "market insights",
                                "extracted_fact": "The article summarizes current market insights.",
                                "confidence": 0.77,
                                "tags": ["anchor"],
                            },
                        ],
                        "report": {},
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )

                service = ResearchJobService(repository)
                job = service.get_job("job-coverage")
                coverage = job["tasks"][0]["coverage_status"]

                self.assertIn("community", coverage["covered_query_tags"])
                self.assertIn("analysis", coverage["covered_query_tags"])
                self.assertGreaterEqual(coverage["query_tag_counts"]["community"], 1)
                self.assertGreaterEqual(coverage["query_tag_counts"]["analysis"], 1)

    def test_run_job_sync_marks_job_failed_when_background_execution_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-1",
                        "topic": "AI PM",
                        "industry_template": "ai_product",
                        "research_mode": "standard",
                        "depth_preset": "light",
                        "status": "queued",
                        "overall_progress": 0,
                        "current_phase": "scoping",
                        "eta_seconds": 600,
                        "source_count": 0,
                        "competitor_count": 0,
                        "completed_task_count": 0,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "claims_count": 0,
                        "report_version_id": None,
                        "phase_progress": [],
                        "tasks": [],
                    }
                )
                repository.set_assets(
                    "job-1",
                    {
                        "claims": [],
                        "evidence": [],
                        "report": {},
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )

                service = ResearchJobService(repository)
                with patch.object(service, "_run_job", AsyncMock(side_effect=RuntimeError("workflow exploded"))):
                    service._run_job_sync("job-1", {})

                job = repository.get_job("job-1")
                event = repository.get_job_queue("job-1").get_nowait()

                self.assertEqual(job["status"], "failed")
                self.assertTrue(any("workflow exploded" in entry["message"] for entry in job["activity_log"]))
                self.assertEqual(event["event"], "job.failed")

    def test_run_job_persists_partial_task_state_when_job_is_cancelled_mid_run(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-cancel-sync",
                        "topic": "AI PM",
                        "industry_template": "ai_product",
                        "research_mode": "standard",
                        "depth_preset": "light",
                        "status": "researching",
                        "overall_progress": 40,
                        "current_phase": "collecting",
                        "eta_seconds": 300,
                        "source_count": 0,
                        "competitor_count": 0,
                        "completed_task_count": 0,
                        "running_task_count": 1,
                        "failed_task_count": 0,
                        "claims_count": 0,
                        "report_version_id": None,
                        "phase_progress": [],
                        "tasks": [
                            {
                                "id": "task-1",
                                "title": "市场趋势",
                                "category": "market_trends",
                                "brief": "调研市场趋势。",
                                "market_step": "market-trends",
                                "status": "running",
                                "source_count": 0,
                                "visited_sources": [],
                            }
                        ],
                    }
                )
                repository.set_assets(
                    "job-cancel-sync",
                    {
                        "claims": [],
                        "evidence": [],
                        "report": {},
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )

                service = ResearchJobService(repository)
                cancelled_assets = {
                    "claims": [],
                    "evidence": [
                        {
                            "id": "task-1-evidence-1",
                            "task_id": "task-1",
                            "market_step": "market-trends",
                            "source_url": "https://example.com/source-1",
                            "source_domain": "example.com",
                            "source_type": "web",
                            "source_tier": "t2",
                            "source_tier_label": "T2 高可信交叉来源",
                            "citation_label": "[S1]",
                            "title": "Example Source 1",
                            "published_at": "2026-04-10T00:00:00+00:00",
                            "captured_at": "2026-04-10T00:00:00+00:00",
                            "quote": "Example quote 1",
                            "summary": "Example summary 1",
                            "extracted_fact": "Example fact 1",
                            "authority_score": 0.82,
                            "freshness_score": 0.8,
                            "confidence": 0.81,
                            "injection_risk": 0.0,
                            "tags": ["official"],
                            "competitor_name": None,
                        }
                    ],
                    "report": {},
                    "competitors": [],
                    "market_map": {},
                    "progress_snapshot": {},
                }

                async def fake_run_research(job, payload, publish, check_cancelled=None):
                    del payload, publish, check_cancelled
                    current_job = repository.get_job("job-cancel-sync")
                    assert current_job is not None
                    current_job["status"] = "cancelled"
                    current_job["cancel_requested"] = True
                    current_job["cancellation_reason"] = "用户手动停止本次研究。"
                    repository.update_job("job-cancel-sync", current_job)

                    job["status"] = "cancelled"
                    job["cancel_requested"] = True
                    job["cancellation_reason"] = "用户手动停止本次研究。"
                    job["source_count"] = 1
                    job["running_task_count"] = 0
                    job["tasks"][0]["status"] = "cancelled"
                    job["tasks"][0]["source_count"] = 1
                    job["tasks"][0]["current_action"] = "已取消"
                    job["tasks"][0]["visited_sources"] = [
                        {
                            "url": "https://example.com/source-1",
                            "title": "Example Source 1",
                            "source_type": "web",
                        }
                    ]
                    return cancelled_assets

                workflow = Mock()
                workflow.run_research = AsyncMock(side_effect=fake_run_research)

                with patch.object(service, "_build_workflow", return_value=workflow):
                    asyncio.run(service._run_job("job-cancel-sync", {}))

                refreshed_job = repository.get_job("job-cancel-sync")
                refreshed_assets = repository.get_assets("job-cancel-sync")

                assert refreshed_job is not None
                assert refreshed_assets is not None
                self.assertEqual(refreshed_job["status"], "cancelled")
                self.assertEqual(refreshed_job["tasks"][0]["status"], "cancelled")
                self.assertEqual(refreshed_job["tasks"][0]["source_count"], 1)
                self.assertEqual(refreshed_job["tasks"][0]["current_action"], "已取消")
                self.assertEqual(refreshed_job["source_count"], 1)
                self.assertEqual(len(refreshed_assets["evidence"]), 1)

    def test_create_job_launches_detached_worker_process(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = InMemoryStateRepository()
                service = ResearchJobService(repository)

                class DummyProcess:
                    pid = 43210

                with patch("pm_agent_api.services.research_job_service.subprocess.Popen", return_value=DummyProcess()) as mocked_popen:
                    job = asyncio.run(
                        service.create_job(
                            {
                                "topic": "AI 眼镜",
                                "industry_template": "ai_product",
                                "research_mode": "standard",
                                "depth_preset": "light",
                                "workflow_command": "deep_general_scan",
                                "project_memory": "",
                                "max_sources": 6,
                                "max_subtasks": 1,
                                "time_budget_minutes": 10,
                                "max_competitors": 5,
                                "review_sample_target": 50,
                                "geo_scope": ["CN"],
                                "language": "zh-CN",
                                "output_locale": "zh-CN",
                            }
                        )
                    )

                self.assertTrue(mocked_popen.called)
                self.assertEqual(job["execution_mode"], "subprocess")
                self.assertEqual(job["background_process"]["pid"], 43210)
                self.assertTrue(job["background_process"]["active"])

    def test_create_job_enqueues_shared_worker_when_background_mode_is_worker(self) -> None:
        class QueueBackedRepository(InMemoryStateRepository):
            def __init__(self) -> None:
                super().__init__()
                self.enqueued_job_ids: list[str] = []

            def supports_background_worker(self) -> bool:
                return True

            def enqueue_background_job(self, job_id: str) -> None:
                self.enqueued_job_ids.append(job_id)

        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = QueueBackedRepository()
                service = ResearchJobService(repository, background_mode="worker")

                job = asyncio.run(
                    service.create_job(
                        {
                            "topic": "AI 眼镜",
                            "industry_template": "ai_product",
                            "research_mode": "standard",
                            "depth_preset": "light",
                            "workflow_command": "deep_general_scan",
                            "project_memory": "",
                            "max_sources": 6,
                            "max_subtasks": 1,
                            "time_budget_minutes": 10,
                            "max_competitors": 5,
                            "review_sample_target": 50,
                            "geo_scope": ["CN"],
                            "language": "zh-CN",
                            "output_locale": "zh-CN",
                        }
                    )
                )

                self.assertEqual(job["execution_mode"], "worker")
                self.assertEqual(job["background_process"]["mode"], "worker")
                self.assertEqual(job["background_process"]["queue"], "redis")
                self.assertTrue(job["background_process"]["active"])
                self.assertEqual(repository.enqueued_job_ids, [job["id"]])
                event = repository.get_job_queue(job["id"]).get_nowait()
                self.assertEqual(event["event"], "job.progress")
                self.assertIn("共享 worker 队列", event["payload"]["message"])

    def test_create_job_marks_failure_when_shared_worker_enqueue_fails(self) -> None:
        class FailingQueueRepository(InMemoryStateRepository):
            def supports_background_worker(self) -> bool:
                return True

            def enqueue_background_job(self, job_id: str) -> None:
                raise RuntimeError("redis unavailable")

        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}):
                repository = FailingQueueRepository()
                service = ResearchJobService(repository, background_mode="worker")

                job = asyncio.run(
                    service.create_job(
                        {
                            "topic": "AI 眼镜",
                            "industry_template": "ai_product",
                            "research_mode": "standard",
                            "depth_preset": "light",
                            "workflow_command": "deep_general_scan",
                            "project_memory": "",
                            "max_sources": 6,
                            "max_subtasks": 1,
                            "time_budget_minutes": 10,
                            "max_competitors": 5,
                            "review_sample_target": 50,
                            "geo_scope": ["CN"],
                            "language": "zh-CN",
                            "output_locale": "zh-CN",
                        }
                    )
                )

                self.assertEqual(job["status"], "failed")
                self.assertEqual(job["completion_mode"], "diagnostic")
                self.assertIn("共享 worker 入队失败", job["latest_error"])
                self.assertFalse(job["background_process"]["active"])


class RuntimeServiceTest(unittest.TestCase):
    def test_runtime_settings_reject_unresolvable_minimax_host(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()
                service = RuntimeService(repository)

                with self.assertRaisesRegex(ValueError, "api.minimax.com"):
                    service.save_settings(
                        {
                            "provider": "minimax",
                            "base_url": "https://api.minimax.com",
                            "model": "MiniMax-M2.7",
                            "api_key": "sk-test-1234567890abcdef",
                        }
                    )

    def test_runtime_status_flags_invalid_saved_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()
                repository.set_runtime_config(
                    {
                        "provider": "minimax",
                        "base_url": "https://api.minimax.com",
                        "model": "MiniMax-M2.7",
                        "api_key": "sk-test-1234567890abcdef",
                    }
                )

                service = RuntimeService(repository)
                status = service.get_status()

                self.assertEqual(status["validation_status"], "invalid")
                self.assertIn("api.minimax.com", status["validation_message"])

    def test_runtime_settings_persist_and_mask_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()
                service = RuntimeService(repository)
                service.save_settings(
                    {
                        "provider": "minimax",
                        "base_url": "https://api.minimaxi.com/v1",
                        "model": "MiniMax-M2.7",
                        "api_key": "sk-test-1234567890abcdef",
                    }
                )

                repository_reloaded = InMemoryStateRepository()
                reloaded_service = RuntimeService(repository_reloaded)
                status = reloaded_service.get_status()

                self.assertEqual(status["source"], "saved")
                self.assertTrue(status["api_key_configured"])
                self.assertIn("••••", status["api_key_masked"])
                self.assertEqual(status["selected_profile_id"], "dev_fallback")
                self.assertGreaterEqual(len(status["available_profiles"]), 2)
                self.assertEqual(status["runtime_config"]["profile_id"], "dev_fallback")
                self.assertEqual(status["resolved_runtime_config"]["retrieval_profile"]["profile_id"], "dev_fallback")

    def test_runtime_settings_file_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()
                repository.set_runtime_config(
                    {
                        "provider": "minimax",
                        "base_url": "https://api.minimaxi.com/v1",
                        "model": "MiniMax-M2.7",
                        "api_key": "sk-test-1234567890abcdef",
                    }
                )

                file_mode = stat.S_IMODE(os.stat(Path(state_dir) / "runtime_config.json").st_mode)

                self.assertEqual(file_mode, 0o600)

    def test_runtime_settings_support_openai_compatible_provider(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False), patch(
                "pm_agent_api.services.runtime_service.socket.getaddrinfo",
                return_value=[(0, 0, 0, "", ("127.0.0.1", 443))],
            ):
                repository = InMemoryStateRepository()
                service = RuntimeService(repository)
                service.save_settings(
                    {
                        "provider": "openai_compatible",
                        "base_url": "https://aixj.vip",
                        "model": "gpt-5.4",
                        "api_key": "sk-test-1234567890abcdef",
                    }
                )

                repository_reloaded = InMemoryStateRepository()
                reloaded_service = RuntimeService(repository_reloaded)
                status = reloaded_service.get_status()

                self.assertEqual(status["provider"], "openai_compatible")
                self.assertEqual(status["model"], "gpt-5.4")
                self.assertEqual(status["base_url"], "https://aixj.vip")
                self.assertTrue(status["api_key_configured"])

    def test_runtime_settings_store_timeout_and_backup_priority(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False), patch(
                "pm_agent_api.services.runtime_service.socket.getaddrinfo",
                return_value=[(0, 0, 0, "", ("127.0.0.1", 443))],
            ):
                repository = InMemoryStateRepository()
                service = RuntimeService(repository)
                status = service.save_settings(
                    {
                        "provider": "openai_compatible",
                        "base_url": "https://primary.aixj.vip/v1",
                        "model": "gpt-5.4",
                        "api_key": "sk-primary-1234567890abcdef",
                        "timeout_seconds": 18,
                        "backup_configs": [
                            {
                                "label": "聚合备用",
                                "base_url": "https://backup-1.aixj.vip/v1",
                            },
                            {
                                "label": "海外直连",
                                "base_url": "https://backup-2.aixj.vip/v1",
                                "api_key": "sk-backup-1234567890abcdef",
                            },
                        ],
                    }
                )

                self.assertEqual(status["timeout_seconds"], 18.0)
                self.assertEqual(status["backup_count"], 2)
                self.assertEqual(status["backup_configs"][0]["priority"], 1)
                self.assertEqual(status["backup_configs"][1]["priority"], 2)
                self.assertTrue(status["backup_configs"][0]["uses_primary_api_key"])
                self.assertFalse(status["backup_configs"][1]["uses_primary_api_key"])

    def test_runtime_settings_reject_timeout_out_of_range(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False), patch(
                "pm_agent_api.services.runtime_service.socket.getaddrinfo",
                return_value=[(0, 0, 0, "", ("127.0.0.1", 443))],
            ):
                repository = InMemoryStateRepository()
                service = RuntimeService(repository)

                with self.assertRaisesRegex(ValueError, "5 到 180"):
                    service.save_settings(
                        {
                            "provider": "openai_compatible",
                            "base_url": "https://aixj.vip",
                            "model": "gpt-5.4",
                            "api_key": "sk-test-1234567890abcdef",
                            "timeout_seconds": 3,
                        }
                    )

    def test_repository_sanitizes_null_claim_text_in_assets(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()
                repository.set_assets(
                    "job-1",
                    {
                        "claims": [
                            {
                                "id": "claim-1",
                                "claim_text": None,
                                "market_step": "recommendations",
                                "caveats": ["先验证转化路径"],
                            }
                        ],
                        "evidence": [],
                        "report": {},
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                    },
                )

                assets = repository.get_assets("job-1")

                self.assertEqual(assets["claims"][0]["claim_text"], "先验证转化路径")

    def test_repository_reconciles_live_task_source_count_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-live-count",
                        "topic": "AI眼镜",
                        "industry_template": "ai_product",
                        "research_mode": "standard",
                        "depth_preset": "light",
                        "status": "researching",
                        "current_phase": "collecting",
                        "overall_progress": 18,
                        "source_count": 0,
                        "claims_count": 0,
                        "completed_task_count": 0,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "phase_progress": [],
                        "tasks": [
                            {"id": "task-1", "status": "running", "source_count": 1},
                            {"id": "task-2", "status": "running", "source_count": 2},
                        ],
                    }
                )

                job = repository.get_job("job-live-count")
                listed_job = repository.list_jobs()[0]

                self.assertEqual(job["source_count"], 3)
                self.assertEqual(listed_job["source_count"], 3)
                self.assertEqual(job["running_task_count"], 2)

    def test_repository_quarantines_invalid_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            jobs_dir = Path(state_dir) / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            invalid_job_path = jobs_dir / "broken.json"
            invalid_job_path.write_text("{not valid json", encoding="utf-8")

            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()

                self.assertEqual(repository.list_jobs(), [])
                quarantined_paths = list(jobs_dir.glob("broken.json.corrupt-*"))
                self.assertTrue(quarantined_paths)
                self.assertFalse(invalid_job_path.exists())

    def test_research_job_service_merges_saved_runtime_key(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()
                repository.set_runtime_config(
                    {
                        "provider": "minimax",
                        "base_url": "https://api.minimaxi.com/v1",
                        "model": "MiniMax-M2.7",
                        "api_key": "sk-saved-1234567890",
                    }
                )

                service = ResearchJobService(repository)
                merged = service._resolve_runtime_config({"provider": "minimax", "model": "MiniMax-M2.5"})

                self.assertEqual(merged["model"], "MiniMax-M2.5")
                self.assertEqual(merged["api_key"], "sk-saved-1234567890")
                self.assertEqual(merged["profile_id"], "dev_fallback")
                self.assertEqual(merged["retrieval_profile"]["profile_id"], "dev_fallback")

    def test_research_job_service_backfills_task_coverage_from_saved_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False):
                repository = InMemoryStateRepository()
                repository.create_job(
                    {
                        "id": "job-coverage-backfill",
                        "topic": "AI眼镜",
                        "industry_template": "ai_product",
                        "research_mode": "deep",
                        "depth_preset": "standard",
                        "status": "completed",
                        "current_phase": "finalizing",
                        "overall_progress": 100,
                        "eta_seconds": 0,
                        "source_count": 2,
                        "claims_count": 0,
                        "completed_task_count": 1,
                        "running_task_count": 0,
                        "failed_task_count": 0,
                        "max_sources": 6,
                        "max_subtasks": 1,
                        "phase_progress": [],
                        "tasks": [
                            {
                                "id": "task-1",
                                "category": "user_jobs_and_pains",
                                "market_step": "user-research",
                                "status": "completed",
                                "source_count": 2,
                                "coverage_status": {
                                    "required_query_tags": ["community", "analysis"],
                                    "covered_query_tags": [],
                                    "missing_required": ["community", "analysis"],
                                    "query_tag_counts": {},
                                },
                            }
                        ],
                    }
                )
                repository.set_assets(
                    "job-coverage-backfill",
                    {
                        "report": {},
                        "claims": [],
                        "competitors": [],
                        "market_map": {},
                        "progress_snapshot": {},
                        "evidence": [
                            {
                                "id": "task-1-evidence-1",
                                "task_id": "task-1",
                                "market_step": "user-research",
                                "source_url": "https://www.pcmag.com/reviews/rokid-glasses",
                                "source_type": "review",
                                "title": "Rokid Glasses review",
                                "summary": "A detailed review covering comfort and caption quality.",
                                "quote": "Hands-on review.",
                                "extracted_fact": "Review highlights battery and comfort tradeoffs.",
                                "confidence": 0.78,
                                "tags": ["page-content"],
                            },
                            {
                                "id": "task-1-evidence-2",
                                "task_id": "task-1",
                                "market_step": "user-research",
                                "source_url": "https://www.techradar.com/wearables/ai-glasses-market-outlook",
                                "source_type": "article",
                                "title": "AI glasses market outlook",
                                "summary": "Article summarizes adoption and use-case trends.",
                                "quote": "Market outlook.",
                                "extracted_fact": "Editorial analysis points to consumer adoption signals.",
                                "confidence": 0.74,
                                "tags": ["page-content"],
                            },
                        ],
                    },
                )

                service = ResearchJobService(repository)
                job = service.get_job("job-coverage-backfill")
                coverage = job["tasks"][0]["coverage_status"]

                self.assertEqual(coverage["missing_required"], [])
                self.assertIn("community", coverage["covered_query_tags"])
                self.assertIn("analysis", coverage["covered_query_tags"])
                self.assertGreaterEqual(coverage["query_tag_counts"]["analysis"], 1)
                self.assertGreaterEqual(coverage["query_tag_counts"]["community"], 1)


class DialogueAgentTest(unittest.TestCase):
    def test_unmatched_question_triggers_delta_research(self) -> None:
        agent = DialogueAgent()
        response = agent.build_response(
            "这个问题完全超出当前报告",
            claims=[],
            evidence=[],
            report_markdown="## Executive Summary\n- 这是现有报告",
            job_id="job-1",
        )

        self.assertTrue(response["needs_delta_research"])

    def test_response_uses_report_context_when_relevant(self) -> None:
        agent = DialogueAgent()
        response = agent.build_response(
            "下一步建议是什么？",
            claims=[],
            evidence=[],
            report_markdown="## Recommended Actions\n- 先验证核心转化路径\n- 再补充用户访谈",
            job_id="job-1",
        )

        self.assertFalse(response["needs_delta_research"])
        self.assertIn("先验证核心转化路径", response["content"])

    def test_dialogue_agent_handles_null_claim_text(self) -> None:
        agent = DialogueAgent()
        response = agent.build_response(
            "转化路径应该怎么验证？",
            claims=[
                {
                    "id": "claim-1",
                    "claim_text": None,
                    "market_step": "recommendations",
                    "status": "inferred",
                    "confidence": 0.52,
                    "caveats": ["先验证转化路径与用户付费意愿。"],
                    "actionability_score": 0.72,
                }
            ],
            evidence=[],
            report_markdown="## Recommended Actions\n- 先验证核心转化路径",
            job_id="job-1",
        )

        self.assertIn("content", response)
        self.assertIsInstance(response["content"], str)
        self.assertTrue(response["content"])

    def test_social_message_does_not_trigger_delta_research(self) -> None:
        agent = DialogueAgent()
        response = agent.build_response(
            "你好",
            claims=[],
            evidence=[],
            report_markdown="## Executive Summary\n- 报告已经准备好",
            job_id="job-1",
        )

        self.assertFalse(response["needs_delta_research"])
        self.assertIn("你好", response["content"])

    def test_llm_can_answer_without_keyword_match(self) -> None:
        class LlmStub:
            def is_enabled(self):
                return True

            def complete_json(self, messages, temperature=0.2, max_tokens=1400):
                return {
                    "content": "你好，我已经接入当前报告上下文。",
                    "cited_claim_ids": [],
                    "needs_delta_research": False,
                }

        agent = DialogueAgent(llm_client=LlmStub())
        response = agent.build_response(
            "你好",
            claims=[],
            evidence=[],
            report_markdown="## Executive Summary\n- 报告已经准备好",
            job_id="job-1",
        )

        self.assertFalse(response["needs_delta_research"])
        self.assertEqual(response["content"], "你好，我已经接入当前报告上下文。")

    def test_run_delta_research_keeps_fallback_claim_text_when_llm_returns_null(self) -> None:
        class LlmStub:
            def is_enabled(self):
                return True

            def complete_json(self, messages, temperature=0.25, max_tokens=900):
                return {
                    "claim_text": None,
                    "caveats": None,
                    "follow_up_message": "先把关键假设列出来。",
                }

        agent = DialogueAgent(llm_client=LlmStub())
        result = agent.run_delta_research("job-1", "应该先做什么", "delta-1")

        self.assertIsInstance(result.claim["claim_text"], str)
        self.assertTrue(result.claim["claim_text"])
        self.assertEqual(result.claim["final_eligibility"], "requires_external_evidence")
        self.assertEqual(result.evidence[0]["evidence_role"], "context_only")
        self.assertEqual(result.evidence[0]["source_tier"], "t4")
        self.assertEqual(result.follow_up_message, "先把关键假设列出来。")


class SynthesizerAgentTest(unittest.TestCase):
    def test_fallback_report_contains_sections_and_evidence(self) -> None:
        agent = SynthesizerAgent()
        report = agent.build_report(
            {
                "topic": "AI PM 工作台",
                "industry_template": "ai_product",
                "research_mode": "deep",
                "depth_preset": "deep",
                "geo_scope": ["中国", "美国"],
            },
            claims=[
                {
                    "claim_text": "用户最看重可追溯报告和后续补研能力。",
                    "market_step": "user-research",
                    "confidence": 0.82,
                    "status": "verified",
                    "actionability_score": 0.9,
                    "caveats": [],
                }
            ],
            evidence=[
                {
                    "title": "G2 review",
                    "market_step": "user-research",
                    "citation_label": "[S1]",
                    "confidence": 0.74,
                    "authority_score": 0.7,
                    "freshness_score": 0.8,
                    "source_url": "https://example.com/review",
                    "source_domain": "example.com",
                    "source_tier": "t2",
                    "source_tier_label": "T2 高可信交叉来源",
                    "source_type": "review",
                    "summary": "评论显示用户希望报告和对话联动。",
                }
            ],
            competitor_names=["A", "B"],
        )

        self.assertIn("# AI PM 工作台 市场研究报告", report["markdown"])
        self.assertIn("## 核心结论摘要", report["markdown"])
        self.assertIn("## 决策快照", report["markdown"])
        self.assertIn("## 证据冲突与使用边界", report["markdown"])
        self.assertIn("## 关键证据摘录", report["markdown"])
        self.assertIn("| 维度 | 内容 |", report["markdown"])
        self.assertIn("| 优先级 | 建议动作 | 为什么现在做 | 证据状态 | 主要风险 |", report["markdown"])
        self.assertIn("评论显示用户希望报告和对话联动。", report["markdown"])
        self.assertIn("[S1]", report["markdown"])
        self.assertIn("T2 高可信交叉来源", report["markdown"])
        self.assertIn("之所以形成这一判断", report["markdown"])
        self.assertIn("判断依据：", report["markdown"])
        self.assertIn("决策简报", report["board_brief_markdown"])
        self.assertIn("一句话判断", report["board_brief_markdown"])
        self.assertIn("管理摘要", report["executive_memo_markdown"])
        self.assertIn("附录", report["appendix_markdown"])
        self.assertIn("冲突与验证边界", report["conflict_summary_markdown"])
        self.assertEqual(report["decision_snapshot"]["readiness"], "偏低")


class VerifierAgentTest(unittest.TestCase):
    def test_fallback_claims_default_to_verified_without_conflict(self) -> None:
        agent = VerifierAgent()
        claims = agent.build_claims(
            {"job_id": "job-1", "topic": "AI PM", "research_mode": "standard"},
            [
                {"id": "e1", "market_step": "user-research", "confidence": 0.8, "competitor_name": None, "quote": "", "summary": "", "extracted_fact": ""},
                {"id": "e2", "market_step": "user-research", "confidence": 0.74, "competitor_name": None, "quote": "", "summary": "", "extracted_fact": ""},
                {"id": "e3", "market_step": "user-research", "confidence": 0.7, "competitor_name": None, "quote": "", "summary": "", "extracted_fact": ""},
                {"id": "e4", "market_step": "user-research", "confidence": 0.68, "competitor_name": None, "quote": "", "summary": "", "extracted_fact": ""},
            ],
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], "verified")
        self.assertEqual(claims[0]["counter_evidence_ids"], [])


class ResearchWorkerAgentTest(unittest.TestCase):
    def test_build_evidence_record_adds_citation_and_source_tier(self) -> None:
        agent = ResearchWorkerAgent()

        record = agent._build_evidence_record(
            request={"topic": "AI PM", "industry_template": "ai_product"},
            task={"id": "task-1", "market_step": "user-research"},
            result={"title": "Official help center"},
            analysis={
                "quote": "Users want to trace claims back to source material.",
                "summary": "帮助中心内容显示产品强调可追溯性。",
                "extracted_fact": "可追溯性是核心价值点。",
                "confidence": 0.82,
                "tags": ["page-content", "official"],
                "competitor_name": None,
            },
            evidence_index=1,
            source_url="https://docs.example.com/help/traceability",
            source_type="documentation",
            published_at="2026-04-02T00:00:00+00:00",
            authority_score=0.9,
        )

        self.assertEqual(record["citation_label"], "[S1]")
        self.assertEqual(record["source_domain"], "docs.example.com")
        self.assertEqual(record["source_tier"], "t1")
        self.assertEqual(record["source_tier_label"], "T1 一手/高权威")

    def test_collect_evidence_attaches_retrieval_trace_and_query_plan_link(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {"id": "task-1", "category": "market_trends", "market_step": "market-trends", "status": "running", "source_count": 0, "retry_count": 0}
            request = {
                "topic": "AI 智能眼镜",
                "industry_template": "ai_product",
                "max_sources": 4,
                "max_subtasks": 1,
                "runtime_config": {
                    "retrieval_profile": {
                        "profile_id": "premium_default",
                        "official_domains": ["meta.com"],
                        "negative_keywords": ["font install"],
                    }
                },
            }

            class BrowserStub:
                def is_available(self):
                    return False

                def open(self, url):
                    return {"status": "unavailable", "url": url}

            with patch.object(agent, "_build_queries", return_value=["ai glasses official pricing"]), patch.object(
                agent,
                "_research_is_sufficient",
                return_value=True,
            ), patch.object(
                agent.search_provider,
                "search",
                AsyncMock(
                    return_value=[
                        {
                            "url": "https://www.meta.com/smart-glasses/",
                            "title": "Ray-Ban Meta smart glasses",
                            "snippet": "Official product page with features and pricing.",
                            "provider": "bing",
                            "score": 35.4,
                            "topic_match_score": 3.2,
                            "strong_query_hits": 4,
                            "alias_match_tokens": ["ai glasses"],
                        }
                    ]
                ),
            ), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(
                    return_value={
                        "url": "https://www.meta.com/smart-glasses/",
                        "title": "Ray-Ban Meta smart glasses",
                        "snippet": "Official product page with features and pricing.",
                        "text": "Ray-Ban Meta smart glasses include camera and AI assistant.",
                        "source_type": "web",
                        "published_at": "2026-04-01T00:00:00+00:00",
                        "authority_score": 0.88,
                    }
                ),
            ), patch.object(
                agent,
                "_analyze_with_llm",
                return_value={
                    "keep": True,
                    "summary": "官方页面给出了核心功能与定位。",
                    "quote": "Official product page with features and pricing.",
                    "extracted_fact": "Ray-Ban Meta 提供拍摄与 AI 助手能力。",
                    "competitor_name": "Ray-Ban Meta",
                    "confidence": 0.81,
                    "tags": ["official", "page-content"],
                },
            ):
                evidence = await agent.collect_evidence(request, task, [], BrowserStub())
            return task, evidence

        task, evidence = asyncio.run(run_case())

        self.assertEqual(len(evidence), 1)
        self.assertIn("query_plan", task)
        self.assertGreaterEqual(len(task["query_plan"]), 1)
        self.assertTrue(any(item.get("id") == evidence[0]["query_plan_id"] for item in task["query_plan"]))
        linked_query = next(item for item in task["query_plan"] if item.get("id") == evidence[0]["query_plan_id"])
        self.assertEqual(linked_query["query"], "ai glasses official pricing")
        self.assertEqual(evidence[0]["retrieval_trace"]["query"], "ai glasses official pricing")
        self.assertEqual(evidence[0]["retrieval_trace"]["provider"], "bing")
        self.assertEqual(evidence[0]["retrieval_trace"]["rank"], 1)
        self.assertEqual(evidence[0]["retrieval_trace"]["score"], 35.4)
        self.assertEqual(evidence[0]["retrieval_trace"]["wave_key"], "anchor")
        self.assertIn("official", evidence[0]["retrieval_trace"]["query_tags"])
        latest_round = task["research_rounds"][-1]
        self.assertEqual(latest_round["pipeline"]["retrieval_profile_id"], "premium_default")
        self.assertIn("meta.com", latest_round["pipeline"]["official_domains"])
        self.assertIn("font install", latest_round["pipeline"]["negative_keywords"])
        self.assertEqual(latest_round["pipeline"]["recalled_result_count"], 1)
        self.assertEqual(latest_round["pipeline"]["reranked_result_count"], 1)
        self.assertEqual(latest_round["pipeline"]["normalized_evidence_count"], 1)
        self.assertEqual(latest_round["pipeline"]["official_hit_count"], 1)

    def test_collect_evidence_blocks_runtime_negative_keyword_results(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {"id": "task-1", "category": "market_trends", "market_step": "market-trends", "status": "running", "source_count": 0, "retry_count": 0}
            request = {
                "topic": "Figma",
                "industry_template": "ai_product",
                "max_sources": 4,
                "max_subtasks": 1,
                "runtime_config": {
                    "retrieval_profile": {
                        "profile_id": "premium_default",
                        "negative_keywords": ["font install"],
                    }
                },
            }

            class BrowserStub:
                def is_available(self):
                    return False

                def open(self, url):
                    return {"status": "unavailable", "url": url}

            with patch.object(agent, "_build_queries", return_value=["figma official docs"]), patch.object(
                agent,
                "_research_is_sufficient",
                return_value=True,
            ), patch.object(
                agent.search_provider,
                "search",
                AsyncMock(
                    return_value=[
                        {
                            "url": "https://example.com/figma-font-install",
                            "title": "Figma font install guide",
                            "snippet": "How to install fonts in Figma.",
                            "provider": "bing",
                            "score": 8.0,
                        }
                    ]
                ),
            ):
                evidence = await agent.collect_evidence(request, task, [], BrowserStub())
            return task, evidence

        task, evidence = asyncio.run(run_case())

        self.assertEqual(evidence, [])
        latest_round = task["research_rounds"][-1]
        self.assertEqual(latest_round["diagnostics"]["negative_keyword_blocks"], 1)
        self.assertEqual(latest_round["pipeline"]["negative_keyword_block_count"], 1)

    def test_fetch_failure_can_auto_open_browser_once(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {"id": "task-1", "category": "market_trends", "market_step": "market-trends", "status": "running", "source_count": 0, "retry_count": 0}
            request = {
                "topic": "AI PM",
                "industry_template": "ai_product",
                "max_sources": 4,
                "max_subtasks": 1,
                "runtime_config": {"debug_policy": {"auto_open_mode": "debug_only"}},
            }

            class BrowserStub:
                def __init__(self):
                    self.open_calls = 0

                def is_available(self):
                    return True

                def open(self, url):
                    self.open_calls += 1
                    return {"status": "ready", "url": url}

            browser = BrowserStub()
            with patch.object(agent.search_provider, "search", AsyncMock(return_value=[{"url": "https://example.com/a", "title": "A", "snippet": "Snippet"}])), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(side_effect=RuntimeError("dynamic page")),
            ):
                evidence = await agent.collect_evidence(request, task, [], browser)
            return browser, task, evidence

        browser, task, evidence = asyncio.run(run_case())
        self.assertEqual(browser.open_calls, 1)
        self.assertEqual(len(evidence), 1)
        self.assertTrue(task["visited_sources"][0]["opened_in_browser"])
        self.assertGreaterEqual(len(task["research_rounds"]), 1)
        self.assertIn("required_query_tags", task["coverage_status"])

    def test_fetch_failure_does_not_auto_open_browser_without_debug_policy(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {"id": "task-1", "category": "market_trends", "market_step": "market-trends", "status": "running", "source_count": 0, "retry_count": 0}
            request = {"topic": "AI PM", "industry_template": "ai_product", "max_sources": 4, "max_subtasks": 1}

            class BrowserStub:
                def __init__(self):
                    self.open_calls = 0

                def is_available(self):
                    return True

                def open(self, url):
                    self.open_calls += 1
                    return {"status": "ready", "url": url}

            browser = BrowserStub()
            with patch.object(agent.search_provider, "search", AsyncMock(return_value=[{"url": "https://example.com/a", "title": "A", "snippet": "Snippet"}])), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(side_effect=RuntimeError("dynamic page")),
            ):
                evidence = await agent.collect_evidence(request, task, [], browser)
            return browser, task, evidence

        browser, task, evidence = asyncio.run(run_case())
        self.assertEqual(browser.open_calls, 0)
        self.assertEqual(len(evidence), 1)
        self.assertFalse(task["visited_sources"][0]["opened_in_browser"])

    def test_access_blocked_page_keeps_relevant_search_snippet(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {
                "id": "task-1",
                "category": "competitor_landscape",
                "market_step": "competitor-analysis",
                "title": "AI眼镜竞品格局",
                "brief": "调研 AI 眼镜竞品与替代品。",
                "status": "running",
                "source_count": 0,
                "retry_count": 0,
            }
            request = {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
                "max_sources": 4,
                "max_subtasks": 1,
                "runtime_config": {"debug_policy": {"auto_open_mode": "debug_only"}},
            }

            class BrowserStub:
                def __init__(self):
                    self.open_calls = 0

                def is_available(self):
                    return True

                def open(self, url):
                    self.open_calls += 1
                    return {"status": "ready", "url": url}

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
            with patch.object(agent.search_provider, "search", AsyncMock(return_value=results)), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(side_effect=forbidden_error),
            ):
                evidence = await agent.collect_evidence(request, task, [], browser)
            return browser, task, evidence

        browser, task, evidence = asyncio.run(run_case())
        self.assertEqual(browser.open_calls, 1)
        self.assertEqual(len(evidence), 1)
        self.assertTrue(task["visited_sources"][0]["opened_in_browser"])
        self.assertIn("access-blocked-snippet", evidence[0]["tags"])
        self.assertIsNone(task["latest_error"])

    def test_private_page_failure_keeps_snippet_without_opening_browser(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {
                "id": "task-1",
                "category": "user_jobs_and_pains",
                "market_step": "user-research",
                "title": "AI眼镜用户研究",
                "brief": "调研 AI 眼镜用户场景和真实反馈。",
                "status": "running",
                "source_count": 0,
                "retry_count": 0,
            }
            request = {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
                "max_sources": 4,
                "max_subtasks": 1,
            }

            class BrowserStub:
                def __init__(self):
                    self.open_calls = 0

                def is_available(self):
                    return True

                def open(self, url):
                    self.open_calls += 1
                    return {"status": "ready", "url": url}

            browser = BrowserStub()
            results = [
                {
                    "url": "https://example.com/ai-glasses-discussion",
                    "title": "AI眼镜用户反馈讨论",
                    "snippet": "用户比较 AI 眼镜的佩戴体验、续航表现和语音交互。",
                }
            ]
            with patch.object(agent.search_provider, "search", AsyncMock(return_value=results)), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(side_effect=PrivateAccessError("requires sign in")),
            ):
                evidence = await agent.collect_evidence(request, task, [], browser)
            return browser, task, evidence

        browser, task, evidence = asyncio.run(run_case())

        self.assertEqual(browser.open_calls, 0)
        self.assertEqual(len(evidence), 1)
        self.assertFalse(task["visited_sources"][0]["opened_in_browser"])
        self.assertIsNone(task["latest_error"])

    def test_fallback_analysis_uses_page_text_when_full_page_is_available(self) -> None:
        agent = ResearchWorkerAgent()

        analysis = agent._analyze_with_llm(
            request={"topic": "AI眼镜", "industry_template": "ai_product"},
            task={
                "category": "user_jobs_and_pains",
                "market_step": "user-research",
                "title": "AI眼镜用户研究",
                "brief": "研究 AI 眼镜用户场景和反馈。",
            },
            title="AI Glasses commuter review",
            source_url="https://example.com/ai-glasses-review",
            source_text=(
                "Users describe AI glasses as useful for commuting, hands-free photo capture, "
                "and live captions during meetings, while also calling out battery life tradeoffs."
            ),
            snippet="AI glasses review",
            is_snippet=False,
        )

        self.assertTrue(analysis["keep"])
        self.assertIn("hands-free photo capture", analysis["summary"])
        self.assertNotEqual(analysis["summary"], "AI glasses review")

    def test_gap_fill_queries_cover_missing_required_intents(self) -> None:
        agent = ResearchWorkerAgent()

        request = {
            "topic": "AI眼镜",
            "industry_template": "ai_product",
            "geo_scope": ["中国"],
            "output_locale": "zh-CN",
            "max_sources": 6,
            "max_subtasks": 1,
        }
        task = {
            "id": "task-1",
            "category": "competitor_landscape",
            "market_step": "competitor-analysis",
            "search_intents": ["official", "comparison", "community"],
        }
        snapshot = {
            "required_query_tags": ["official", "comparison", "community"],
            "covered_query_tags": ["official"],
            "missing_required": ["comparison", "community"],
            "unique_domains": 1,
            "high_confidence_evidence": 0,
        }

        queries = agent._build_gap_fill_queries(request, task, snapshot, ["site:example.com AI眼镜 官网 产品介绍"])

        combined = " || ".join(queries).lower()
        self.assertTrue(queries)
        self.assertTrue(any(token in combined for token in ("ai glasses", "smart glasses", "glasses")))
        self.assertTrue(any(token in combined for token in ("comparison", "alternatives", "vs", "对比", "替代")))
        self.assertTrue(any(token in combined for token in ("reddit", "reviews", "社区", "论坛", "评价")))

    def test_skill_runtime_snapshot_tracks_missing_targets(self) -> None:
        agent = ResearchWorkerAgent()

        task = {
            "id": "task-1",
            "category": "reviews_and_sentiment",
            "market_step": "reviews-and-sentiment",
            "skill_packs": ["voice-of-customer", "review-clustering"],
        }
        snapshot = agent._build_coverage_snapshot(
            task,
            [
                {
                    "source_url": "https://www.reddit.com/r/example",
                    "source_type": "community",
                    "confidence": 0.8,
                    "tags": ["community"],
                }
            ],
        )
        gaps = agent._coverage_gaps(task, snapshot, target_sources=3)

        self.assertEqual(snapshot["query_tag_counts"]["community"], 1)
        self.assertEqual(snapshot["skill_coverage_targets"]["community"], 2)
        self.assertEqual(snapshot["missing_skill_targets"]["community"], 1)
        self.assertEqual(gaps["missing_skill_targets"]["community"], 1)

    def test_query_coverage_tags_detect_natural_review_language(self) -> None:
        agent = ResearchWorkerAgent()

        tags = agent._query_coverage_tags("Rokid ai glasses user review feedback pain points")

        self.assertIn("community", tags)
        self.assertIn("analysis", tags)

    def test_coverage_snapshot_infers_tags_from_evidence_metadata(self) -> None:
        agent = ResearchWorkerAgent()

        task = {
            "id": "task-1",
            "category": "user_jobs_and_pains",
            "market_step": "user-research",
        }
        snapshot = agent._build_coverage_snapshot(
            task,
            [
                {
                    "source_url": "https://www.pcmag.com/reviews/rokid-glasses",
                    "source_type": "review",
                    "confidence": 0.82,
                    "title": "Rokid Glasses review",
                    "summary": "Hands-on review covering comfort and battery tradeoffs.",
                    "quote": "Hands-on review",
                    "extracted_fact": "Users mention comfort tradeoffs.",
                    "tags": ["anchor"],
                },
                {
                    "source_url": "https://example.com/blog/ai-glasses-market-insights",
                    "source_type": "article",
                    "confidence": 0.78,
                    "title": "AI glasses market insights and adoption analysis",
                    "summary": "Analysts outline current use cases and adoption signals.",
                    "quote": "market insights",
                    "extracted_fact": "The article summarizes current market insights.",
                    "tags": ["anchor"],
                },
            ],
        )

        self.assertIn("community", snapshot["covered_query_tags"])
        self.assertIn("analysis", snapshot["covered_query_tags"])
        self.assertGreaterEqual(snapshot["query_tag_counts"]["community"], 1)
        self.assertGreaterEqual(snapshot["query_tag_counts"]["analysis"], 1)

    def test_collect_evidence_injects_convergence_wave_after_consecutive_empty_queries(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {
                "id": "task-1",
                "category": "competitor_landscape",
                "market_step": "competitor-analysis",
                "status": "running",
                "source_count": 0,
                "retry_count": 0,
            }
            request = {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "max_sources": 3,
                "max_subtasks": 1,
                "geo_scope": ["中国"],
                "output_locale": "zh-CN",
            }

            class BrowserStub:
                def is_available(self):
                    return False

                def open(self, url):
                    return {"status": "unavailable", "url": url}

            async def search_side_effect(query, max_results=5, preferred_source_types=None, preferred_domains=None):
                if "眼镜" in query or "glasses" in query.lower():
                    return [
                        {
                            "url": "https://www.meta.com/smart-glasses/",
                            "title": "AI眼镜 Ray-Ban Meta smart glasses",
                            "snippet": "Official AI眼镜 smart glasses product details.",
                            "query": query,
                        }
                    ]
                return []

            with patch.object(agent, "_build_queries", return_value=["ai product official docs", "ai product market analysis"]), patch.object(
                agent,
                "_build_zero_result_retry_queries",
                return_value=[],
            ), patch.object(
                agent.search_provider,
                "search",
                AsyncMock(side_effect=search_side_effect),
            ), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(
                    return_value={
                        "url": "https://www.meta.com/smart-glasses/",
                        "title": "AI眼镜 Ray-Ban Meta smart glasses",
                        "snippet": "AI眼镜 setup and product details.",
                        "text": "Ray-Ban Meta AI眼镜 smart glasses provide camera, audio, and AI assistant features.",
                        "source_type": "web",
                        "published_at": "2026-04-01T00:00:00+00:00",
                        "authority_score": 0.9,
                    }
                ),
            ):
                evidence = await agent.collect_evidence(request, task, [], BrowserStub())
            return task, evidence

        task, evidence = asyncio.run(run_case())

        self.assertTrue(evidence)
        self.assertTrue(any(round_item.get("key") == "convergence" for round_item in task.get("research_rounds", [])))
        convergence_round = next(round_item for round_item in task["research_rounds"] if round_item.get("key") == "convergence")
        self.assertTrue(any(("眼镜" in query or "glasses" in query.lower()) for query in convergence_round.get("queries", [])))

    def test_collect_evidence_retries_shorter_query_after_zero_results(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {
                "id": "task-1",
                "category": "user_jobs_and_pains",
                "market_step": "user-research",
                "status": "running",
                "source_count": 0,
                "retry_count": 0,
            }
            request = {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "max_sources": 3,
                "max_subtasks": 1,
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            }

            class BrowserStub:
                def is_available(self):
                    return False

                def open(self, url):
                    return {"status": "unavailable", "url": url}

            async def search_side_effect(query, max_results=5, preferred_source_types=None, preferred_domains=None):
                del max_results, preferred_source_types, preferred_domains
                if query == "site:reddit.com ai 眼镜 reddit 论坛 社区 讨论 用户研究 用户痛点":
                    return []
                if query == "ai glasses reddit reviews us":
                    return [
                        {
                            "url": "https://www.reddit.com/r/example/comments/1/ai_glasses/",
                            "title": "AI glasses daily use review",
                            "snippet": "Users discuss battery life, captions and comfort tradeoffs.",
                            "query": query,
                        }
                    ]
                return []

            with patch.object(
                agent,
                "_build_queries",
                return_value=["site:reddit.com ai 眼镜 reddit 论坛 社区 讨论 用户研究 用户痛点"],
            ), patch.object(
                agent,
                "_build_zero_result_retry_queries",
                return_value=["ai glasses reddit reviews us"],
            ), patch.object(
                agent.search_provider,
                "search",
                AsyncMock(side_effect=search_side_effect),
            ), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(
                    return_value={
                        "url": "https://www.reddit.com/r/example/comments/1/ai_glasses/",
                        "title": "AI glasses daily use review",
                        "snippet": "Users discuss battery life, captions and comfort tradeoffs.",
                        "text": "Users rely on AI glasses for hands-free photos and captions but still mention comfort and battery tradeoffs.",
                        "source_type": "community",
                        "published_at": "2026-04-01T00:00:00+00:00",
                        "authority_score": 0.6,
                    }
                ),
            ):
                evidence = await agent.collect_evidence(request, task, [], BrowserStub())
            return task, evidence

        task, evidence = asyncio.run(run_case())

        self.assertTrue(evidence)
        query_summary = task["research_rounds"][0]["query_summaries"][0]
        self.assertEqual(query_summary["query"], "site:reddit.com ai 眼镜 reddit 论坛 社区 讨论 用户研究 用户痛点")
        self.assertEqual(query_summary["effective_query"], "ai glasses reddit reviews us")
        self.assertEqual(query_summary["search_result_count"], 1)
        self.assertEqual(query_summary["retry_queries"], ["ai glasses reddit reviews us"])
        self.assertEqual(query_summary["retry_attempts"][-1]["status"], "results_found")
        self.assertIn("community", evidence[0]["tags"])
        self.assertIn("analysis", evidence[0]["tags"])
        self.assertIn("community", task["coverage_status"]["covered_query_tags"])

    def test_collect_evidence_refreshes_live_coverage_before_round_finishes(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {
                "id": "task-1",
                "category": "user_jobs_and_pains",
                "market_step": "user-research",
                "status": "running",
                "source_count": 0,
                "retry_count": 0,
            }
            request = {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "max_sources": 3,
                "max_subtasks": 1,
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            }
            coverage_snapshots = []

            class BrowserStub:
                def is_available(self):
                    return False

                def open(self, url):
                    return {"status": "unavailable", "url": url}

            async def on_progress(updated_task, message):
                coverage = updated_task.get("coverage_status") or {}
                coverage_snapshots.append(
                    {
                        "message": message,
                        "covered": list(coverage.get("covered_query_tags") or []),
                        "counts": dict(coverage.get("query_tag_counts") or {}),
                    }
                )

            async def search_side_effect(query, max_results=5, preferred_source_types=None, preferred_domains=None):
                del query, max_results, preferred_source_types, preferred_domains
                return [
                    {
                        "url": "https://www.pcmag.com/reviews/ai-glasses",
                        "title": "AI glasses review",
                        "snippet": "Review covers comfort, battery, and captions tradeoffs.",
                    },
                    {
                        "url": "https://www.techradar.com/wearables/ai-glasses-market-outlook",
                        "title": "AI glasses market outlook",
                        "snippet": "Article summarizes adoption and use-case signals.",
                    },
                ]

            async def fetch_side_effect(url):
                if "pcmag.com" in url:
                    return {
                        "url": url,
                        "title": "AI glasses review",
                        "snippet": "Review covers comfort, battery, and captions tradeoffs.",
                        "text": "Reviewers describe comfort, caption quality, and battery tradeoffs for AI glasses.",
                        "source_type": "review",
                        "published_at": "2026-04-01T00:00:00+00:00",
                        "authority_score": 0.74,
                    }
                return {
                    "url": url,
                    "title": "AI glasses market outlook",
                    "snippet": "Article summarizes adoption and use-case signals.",
                    "text": "The article outlines AI glasses adoption signals and mainstream use cases.",
                    "source_type": "article",
                    "published_at": "2026-04-01T00:00:00+00:00",
                    "authority_score": 0.76,
                }

            with patch.object(agent, "_build_queries", return_value=["ai glasses"]), patch.object(
                agent.search_provider,
                "search",
                AsyncMock(side_effect=search_side_effect),
            ), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(side_effect=fetch_side_effect),
            ):
                evidence = await agent.collect_evidence(request, task, [], BrowserStub(), on_progress=on_progress)
            return task, evidence, coverage_snapshots

        task, evidence, coverage_snapshots = asyncio.run(run_case())

        self.assertTrue(evidence)
        live_snapshot = next(item for item in coverage_snapshots if item["message"].startswith("已抓取 1 /"))
        self.assertIn("community", live_snapshot["covered"])
        self.assertIn("analysis", live_snapshot["covered"])
        self.assertGreaterEqual(live_snapshot["counts"]["community"], 1)
        self.assertGreaterEqual(live_snapshot["counts"]["analysis"], 1)
        self.assertIn("community", task["coverage_status"]["covered_query_tags"])
        self.assertIn("analysis", task["coverage_status"]["covered_query_tags"])

    def test_zero_result_retry_prioritizes_community_query_before_analysis(self) -> None:
        agent = ResearchWorkerAgent()

        request = {
            "topic": "AI眼镜",
            "industry_template": "ai_product",
            "geo_scope": ["美国"],
            "output_locale": "zh-CN",
            "max_sources": 6,
            "max_subtasks": 1,
        }
        task = {
            "id": "task-1",
            "category": "user_jobs_and_pains",
            "market_step": "user-research",
            "search_intents": ["community", "analysis"],
        }

        queries = agent._build_zero_result_retry_queries(request, task, "ai 眼镜 社区 论坛 reddit 讨论 美国")

        self.assertTrue(queries)
        self.assertIn("community", agent._query_coverage_tags(queries[0]))
        self.assertTrue(any(token in queries[0].lower() for token in ("reddit", "review", "论坛", "社区")))

    def test_collect_evidence_does_not_consume_host_quota_for_rejected_results(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {
                "id": "task-1",
                "category": "market_trends",
                "market_step": "market-trends",
                "status": "running",
                "source_count": 0,
                "retry_count": 0,
            }
            request = {
                "topic": "AI眼镜",
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

            results = [
                {
                    "url": "https://meta.com/bad-1",
                    "title": "Meta AI glasses teaser",
                    "snippet": "AI glasses concept teaser without concrete product facts.",
                },
                {
                    "url": "https://meta.com/bad-2",
                    "title": "Meta AI glasses campaign",
                    "snippet": "AI glasses campaign page with generic lifestyle messaging.",
                },
                {
                    "url": "https://example.com/market-report",
                    "title": "AI glasses market report",
                    "snippet": "Third-party analysis on AI glasses adoption and market growth.",
                },
                {
                    "url": "https://meta.com/good-3",
                    "title": "Meta AI glasses official overview",
                    "snippet": "Official product overview for Meta AI glasses with feature details.",
                },
            ]

            async def fetch_side_effect(url):
                return {
                    "url": url,
                    "title": results[[item["url"] for item in results].index(url)]["title"],
                    "snippet": results[[item["url"] for item in results].index(url)]["snippet"],
                    "text": f"{url} full page content about AI glasses.",
                    "source_type": "web",
                    "published_at": "2026-04-01T00:00:00+00:00",
                    "authority_score": 0.8,
                }

            def analyze_side_effect(*, source_url, **kwargs):
                if source_url in {"https://meta.com/bad-1", "https://meta.com/bad-2"}:
                    return {
                        "keep": False,
                        "summary": "页面只有泛品牌信息，缺少可复核事实。",
                        "quote": "generic brand copy",
                        "extracted_fact": "",
                        "confidence": 0.25,
                        "tags": ["page-content"],
                        "competitor_name": None,
                    }
                return {
                    "keep": True,
                    "summary": "页面提供了可用于研究的 AI 眼镜信息。",
                    "quote": "useful source",
                    "extracted_fact": "该来源包含 AI 眼镜的有效事实。",
                    "confidence": 0.78,
                    "tags": ["page-content"],
                    "competitor_name": None,
                }

            with patch.object(agent, "_build_queries", return_value=["ai glasses"]), patch.object(
                agent.search_provider,
                "search",
                AsyncMock(return_value=results),
            ), patch.object(
                agent,
                "_is_low_signal_result",
                return_value=False,
            ), patch.object(
                agent,
                "_analyze_with_llm",
                side_effect=analyze_side_effect,
            ), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(side_effect=fetch_side_effect),
            ):
                evidence = await agent.collect_evidence(request, task, [], BrowserStub())
            return evidence

        evidence = asyncio.run(run_case())

        self.assertEqual(len(evidence), 2)
        self.assertEqual(
            [item["source_url"] for item in evidence],
            ["https://example.com/market-report", "https://meta.com/good-3"],
        )

    def test_collect_evidence_records_round_diagnostics_for_filtered_results(self) -> None:
        agent = ResearchWorkerAgent()

        async def run_case():
            task = {
                "id": "task-1",
                "category": "market_trends",
                "market_step": "market-trends",
                "status": "running",
                "source_count": 0,
                "retry_count": 0,
            }
            request = {
                "topic": "AI眼镜",
                "industry_template": "ai_product",
                "max_sources": 8,
                "max_subtasks": 1,
                "geo_scope": ["美国"],
                "output_locale": "zh-CN",
            }

            class BrowserStub:
                def is_available(self):
                    return False

                def open(self, url):
                    return {"status": "unavailable", "url": url}

            results = [
                {"url": "https://example.com/a", "title": "Example official", "snippet": "Official AI glasses overview."},
                {"url": "https://example.com/a", "title": "Example official duplicate", "snippet": "Duplicate result."},
                {"url": "https://low.example/b", "title": "Generic smart page", "snippet": "Generic content."},
                {"url": "https://host.com/1", "title": "Host report 1", "snippet": "Adoption report 1."},
                {"url": "https://host.com/2", "title": "Host report 2", "snippet": "Adoption report 2."},
                {"url": "https://host.com/3", "title": "Host report 3", "snippet": "Adoption report 3."},
                {"url": "https://fallback.example/f", "title": "Fallback source", "snippet": "Search snippet for fallback."},
                {"url": "https://reject.example/g", "title": "Weak source", "snippet": "Weak support for AI glasses."},
            ]

            async def fetch_side_effect(url):
                if url == "https://fallback.example/f":
                    raise RuntimeError("dynamic page")
                return {
                    "url": url,
                    "title": next(item["title"] for item in results if item["url"] == url),
                    "snippet": next(item["snippet"] for item in results if item["url"] == url),
                    "text": f"{url} full page content about AI glasses.",
                    "source_type": "web",
                    "published_at": "2026-04-01T00:00:00+00:00",
                    "authority_score": 0.8,
                }

            def low_signal_side_effect(result, _task, request=None):
                return result["url"] == "https://low.example/b"

            def analyze_side_effect(*, source_url, **kwargs):
                if source_url == "https://reject.example/g":
                    return {
                        "keep": False,
                        "summary": "内容太泛，无法支撑结论。",
                        "quote": "weak source",
                        "extracted_fact": "",
                        "confidence": 0.3,
                        "tags": ["page-content"],
                        "competitor_name": None,
                    }
                return {
                    "keep": True,
                    "summary": "来源可用于研究。",
                    "quote": "useful source",
                    "extracted_fact": "该来源包含有效信息。",
                    "confidence": 0.78,
                    "tags": ["page-content"],
                    "competitor_name": None,
                }

            with patch.object(agent, "_build_queries", return_value=["ai glasses"]), patch.object(
                agent.search_provider,
                "search",
                AsyncMock(return_value=results),
            ), patch.object(
                agent,
                "_is_low_signal_result",
                side_effect=low_signal_side_effect,
            ), patch.object(
                agent,
                "_analyze_with_llm",
                side_effect=analyze_side_effect,
            ), patch(
                "pm_agent_worker.agents.research_worker_agent.fetch_and_extract_page",
                AsyncMock(side_effect=fetch_side_effect),
            ):
                evidence = await agent.collect_evidence(request, task, [], BrowserStub())
            return task, evidence

        task, evidence = asyncio.run(run_case())

        self.assertEqual(len(evidence), 4)
        round_record = task["research_rounds"][0]
        diagnostics = round_record["diagnostics"]
        query_summary = round_record["query_summaries"][0]
        self.assertEqual(diagnostics["admitted"], 4)
        self.assertEqual(diagnostics["duplicates"], 1)
        self.assertEqual(diagnostics["low_signal"], 1)
        self.assertEqual(diagnostics["host_quota"], 1)
        self.assertEqual(diagnostics["fetch_fallbacks"], 1)
        self.assertEqual(diagnostics["rejected"], 1)
        self.assertEqual(query_summary["query"], "ai glasses")
        self.assertEqual(query_summary["status"], "evidence_added")
        self.assertEqual(query_summary["search_result_count"], 8)
        self.assertEqual(query_summary["evidence_added"], 4)


class MiniMaxChatClientTest(unittest.TestCase):
    def test_client_keeps_retrying_after_failed_request(self) -> None:
        invalid_test_key = "bad-key"
        client = MiniMaxChatClient(
            MiniMaxSettings(
                api_key=invalid_test_key,
                model="MiniMax-M2.7",
                base_url="https://api.minimaxi.com/v1",
                timeout_seconds=1,
            )
        )

        with patch("pm_agent_worker.tools.minimax_client.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = httpx.HTTPError("401 Unauthorized")
            with self.assertRaises(RuntimeError):
                client.complete([{"role": "user", "content": "hello"}])

        self.assertTrue(client.is_enabled())

    def test_client_falls_back_to_backup_connection_and_prefers_it(self) -> None:
        primary_test_key = "sk-primary-1234567890abcdef"
        backup_test_key = "sk-backup-1234567890abcdef"
        client = MiniMaxChatClient(
            MiniMaxSettings(
                api_key=primary_test_key,
                model="MiniMax-M2.7",
                base_url="https://primary.minimaxi.com/v1",
                timeout_seconds=1,
                backup_connections=(
                    __import__("pm_agent_worker.tools.minimax_settings", fromlist=["MiniMaxConnectionSettings"]).MiniMaxConnectionSettings(
                        api_key=backup_test_key,
                        model="MiniMax-M2.7",
                        base_url="https://backup.minimaxi.com/v1",
                        timeout_seconds=1,
                        label="Backup",
                    ),
                ),
            )
        )

        backup_ok_response = Mock()
        backup_ok_response.raise_for_status.return_value = None
        backup_ok_response.json.return_value = {"choices": [{"message": {"content": "OK from backup"}}]}

        backup_ok_response_again = Mock()
        backup_ok_response_again.raise_for_status.return_value = None
        backup_ok_response_again.json.return_value = {"choices": [{"message": {"content": "OK again"}}]}

        with patch("pm_agent_worker.tools.minimax_client.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = [
                httpx.ReadTimeout("primary timeout"),
                backup_ok_response,
                backup_ok_response_again,
            ]

            first = client.complete([{"role": "user", "content": "hello"}])
            second = client.complete([{"role": "user", "content": "hello again"}])

        self.assertEqual(first, "OK from backup")
        self.assertEqual(second, "OK again")
        self.assertEqual(client.active_base_url, "https://backup.minimaxi.com/v1")
        self.assertEqual(mock_client.post.call_args_list[0].args[0], "https://primary.minimaxi.com/v1/chat/completions")
        self.assertEqual(mock_client.post.call_args_list[1].args[0], "https://backup.minimaxi.com/v1/chat/completions")
        self.assertEqual(mock_client.post.call_args_list[2].args[0], "https://backup.minimaxi.com/v1/chat/completions")


class OpenAICompatibleChatClientTest(unittest.TestCase):
    def test_client_falls_back_between_chat_completion_paths(self) -> None:
        test_llm_key = "sk-test-1234567890abcdef"
        client = OpenAICompatibleChatClient(
            OpenAICompatibleSettings(
                api_key=test_llm_key,
                model="gpt-5.4",
                base_url="https://aixj.vip",
                timeout_seconds=1,
            )
        )

        not_found_response = Mock()
        not_found_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("POST", "https://aixj.vip/v1/chat/completions"),
            response=httpx.Response(404, request=httpx.Request("POST", "https://aixj.vip/v1/chat/completions")),
        )

        ok_response = Mock()
        ok_response.raise_for_status.return_value = None
        ok_response.json.return_value = {"choices": [{"message": {"content": "OK"}}]}

        with patch("pm_agent_worker.tools.openai_compatible_client.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = [not_found_response, ok_response]

            result = client.complete([{"role": "user", "content": "Reply with OK only."}], temperature=0.0, max_tokens=8)

        self.assertEqual(result, "OK")
        self.assertEqual(mock_client.post.call_args_list[0].args[0], "https://aixj.vip/v1/chat/completions")
        self.assertEqual(mock_client.post.call_args_list[1].args[0], "https://aixj.vip/chat/completions")

    def test_client_falls_back_to_responses_api(self) -> None:
        test_llm_key = "sk-test-1234567890abcdef"
        client = OpenAICompatibleChatClient(
            OpenAICompatibleSettings(
                api_key=test_llm_key,
                model="gpt-5.4",
                base_url="https://api.openai.com/v1",
                timeout_seconds=1,
            )
        )

        chat_response = Mock()
        chat_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request",
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            response=httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")),
        )

        responses_response = Mock()
        responses_response.raise_for_status.return_value = None
        responses_response.json.return_value = {
            "output_text": "OK",
        }

        with patch("pm_agent_worker.tools.openai_compatible_client.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = [chat_response, responses_response]

            result = client.complete([{"role": "user", "content": "Reply with OK only."}], temperature=0.0, max_tokens=8)

        self.assertEqual(result, "OK")
        self.assertEqual(mock_client.post.call_args_list[0].args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(mock_client.post.call_args_list[1].args[0], "https://api.openai.com/v1/responses")

    def test_client_falls_back_to_backup_connection_and_prefers_it(self) -> None:
        primary_test_key = "sk-primary-1234567890abcdef"
        backup_test_key = "sk-backup-1234567890abcdef"
        client = OpenAICompatibleChatClient(
            OpenAICompatibleSettings(
                api_key=primary_test_key,
                model="gpt-5.4",
                base_url="https://primary.aixj.vip/v1",
                timeout_seconds=1,
                backup_connections=(
                    __import__("pm_agent_worker.tools.openai_compatible_settings", fromlist=["OpenAICompatibleConnectionSettings"]).OpenAICompatibleConnectionSettings(
                        api_key=backup_test_key,
                        model="gpt-5.4",
                        base_url="https://backup.aixj.vip/v1",
                        timeout_seconds=1,
                        label="Backup",
                    ),
                ),
            )
        )

        backup_ok_response = Mock()
        backup_ok_response.raise_for_status.return_value = None
        backup_ok_response.json.return_value = {"choices": [{"message": {"content": "OK from backup"}}]}

        backup_ok_response_again = Mock()
        backup_ok_response_again.raise_for_status.return_value = None
        backup_ok_response_again.json.return_value = {"choices": [{"message": {"content": "OK again"}}]}

        with patch("pm_agent_worker.tools.openai_compatible_client.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = [
                httpx.ReadTimeout("primary chat timeout"),
                httpx.ReadTimeout("primary responses timeout"),
                backup_ok_response,
                backup_ok_response_again,
            ]

            first = client.complete([{"role": "user", "content": "hello"}])
            second = client.complete([{"role": "user", "content": "hello again"}])

        self.assertEqual(first, "OK from backup")
        self.assertEqual(second, "OK again")
        self.assertEqual(client.active_base_url, "https://backup.aixj.vip/v1")
        self.assertEqual(mock_client.post.call_args_list[0].args[0], "https://primary.aixj.vip/v1/chat/completions")
        self.assertEqual(mock_client.post.call_args_list[1].args[0], "https://primary.aixj.vip/v1/responses")
        self.assertEqual(mock_client.post.call_args_list[2].args[0], "https://backup.aixj.vip/v1/chat/completions")
        self.assertEqual(mock_client.post.call_args_list[3].args[0], "https://backup.aixj.vip/v1/chat/completions")


class OpenCliBrowserToolTest(unittest.TestCase):
    def test_opencli_command_env_supports_explicit_binary_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            opencli_path = Path(tmp_dir) / "opencli"
            opencli_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            opencli_path.chmod(opencli_path.stat().st_mode | stat.S_IEXEC)

            with patch.dict(os.environ, {"OPENCLI_COMMAND": str(opencli_path)}, clear=False):
                tool = OpenCliBrowserTool()

        self.assertTrue(tool.is_available())
        self.assertEqual(tool.mode(), "opencli")
        self.assertIn(str(opencli_path), tool.command or "")


if __name__ == "__main__":
    unittest.main()
