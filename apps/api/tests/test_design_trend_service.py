import asyncio
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.services.design_trend_service import DesignTrendService, TREND_CATEGORY_ORDER


class DesignTrendServiceTest(unittest.TestCase):
    def _build_service(self) -> DesignTrendService:
        state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(state_dir.cleanup)
        repository = SimpleNamespace(_state_root=Path(state_dir.name))
        return DesignTrendService(repository)

    def test_build_daily_pool_requires_live_web_results(self) -> None:
        service = self._build_service()

        async def fake_gather(category: str, _target_date):
            return {"category": category, "queries": [f"{category} latest"], "results": [], "pages": []}

        async def fake_extract(category: str, context, _target_date, fetched_at: str):
            if not context["results"]:
                return []
            return [
                service._sanitize_trend(
                    category,
                    {
                        "name": f"{category}实时趋势",
                        "description": "基于站外搜索结果提炼。",
                        "keywords": ["实时", "站外"],
                        "color_palette": ["#111827", "#1D4ED8", "#38BDF8", "#E2E8F0", "#F8FAFC"],
                        "mood_keywords": ["最新"],
                        "difficulty": 2,
                        "example_prompt": "围绕实时趋势做一版页面。",
                    },
                    fetched_at=fetched_at,
                    source_urls=[item["url"] for item in context["results"]],
                )
            ]

        service._gather_category_context = fake_gather  # type: ignore[method-assign]
        service._extract_with_llm = fake_extract  # type: ignore[method-assign]

        with self.assertRaisesRegex(ValueError, "站外设计趋势"):
            asyncio.run(service._build_daily_pool(date(2026, 4, 18)))

    def test_build_daily_pool_uses_live_heuristics_without_llm(self) -> None:
        service = self._build_service()
        target_date = date(2026, 4, 18)

        async def fake_gather(category: str, _target_date):
            if category not in {"视觉风格", "色彩体系"}:
                return {"category": category, "queries": [f"{category} latest"], "results": [], "pages": []}
            return {
                "category": category,
                "queries": [f"{category} latest"],
                "results": [
                    {
                        "title": f"{category} 最新趋势",
                        "snippet": "来自站外网站的最新设计趋势总结。",
                        "url": f"https://example.com/{category}",
                        "source_label": "Creative Bloq",
                        "published_at": "Fri, 18 Apr 2026 08:00:00 GMT",
                        "result_kind": "google_news_rss",
                    }
                ],
                "pages": [{"title": f"{category} 页面", "text": "latest design trend", "url": f"https://example.com/{category}"}],
            }

        async def fake_extract(_category: str, _context, _target_date, _fetched_at: str):
            return []

        service._gather_category_context = fake_gather  # type: ignore[method-assign]
        service._extract_with_llm = fake_extract  # type: ignore[method-assign]

        payload = asyncio.run(service._build_daily_pool(target_date))

        self.assertEqual(payload["available_category_count"], 2)
        self.assertEqual(len(payload["pool"]), 2)
        self.assertTrue(all(item["source_urls"] for item in payload["pool"]))
        self.assertTrue(payload["live_only"])
        self.assertTrue(all(item["summary_mode"] == "heuristic" for item in payload["pool"]))
        self.assertTrue(service._cache_path(target_date).exists())

    def test_roll_trend_for_user_keeps_category_consistent_with_trend(self) -> None:
        service = self._build_service()
        target_date = date(2026, 4, 18)
        payload = {
            "date": "2026-04-18",
            "pool_fetched_at": "2026-04-18T00:00:00+00:00",
            "pool": [
                {
                    "id": "trend-color",
                    "name": "色彩趋势",
                    "category": "色彩体系",
                },
                {
                    "id": "trend-interaction",
                    "name": "交互趋势",
                    "category": "交互模式",
                },
            ],
        }

        rolled = service.roll_trend_for_user("designer-1", payload, target_date=target_date)

        self.assertEqual(rolled["trend"]["category"], rolled["dice_category"])
        self.assertEqual(rolled["dice_face"], TREND_CATEGORY_ORDER.index(rolled["dice_category"]) + 1)

    def test_heuristic_translation_prefers_chinese_display_name(self) -> None:
        service = self._build_service()
        translated = service._translate_trend_name("材质纹理", "High Low Material Mix")
        keywords = service._translated_keywords_for("材质纹理", translated, "High Low Material Mix")

        self.assertEqual(translated, "高低材质混搭")
        self.assertIn("材质混搭", keywords)


if __name__ == "__main__":
    unittest.main()
