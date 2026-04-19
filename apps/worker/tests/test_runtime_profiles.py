import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.tools.runtime_profiles import (
    hydrate_runtime_config,
    infer_runtime_profile_id,
    merge_runtime_configs,
)


class RuntimeProfilesTest(unittest.TestCase):
    def test_infer_respects_profile_ids(self):
        self.assertEqual(
            infer_runtime_profile_id({"profile_id": "dev_fallback"}),
            "dev_fallback",
        )
        self.assertEqual(
            infer_runtime_profile_id({"runtime_profile_id": "dev_fallback"}),
            "dev_fallback",
        )
        self.assertEqual(
            infer_runtime_profile_id({"llm_profile": {"profile_id": "dev_fallback"}}),
            "dev_fallback",
        )

    def test_infer_detects_dev_fallback_conditions(self):
        self.assertEqual(infer_runtime_profile_id({"provider": "minimax"}), "dev_fallback")
        self.assertEqual(infer_runtime_profile_id({"model": "gpt-4.2-mini"}), "dev_fallback")
        self.assertEqual(
            infer_runtime_profile_id({"debug_policy": {"auto_open_mode": "always"}}),
            "dev_fallback",
        )
        self.assertEqual(
            infer_runtime_profile_id({"debug_policy": {"verbose_diagnostics": True}}),
            "dev_fallback",
        )

    def test_hydrate_defaults_to_flagship_profile(self):
        hydrated = hydrate_runtime_config({"provider": "openai_compatible"})
        self.assertEqual(hydrated["profile_id"], "premium_default")
        self.assertEqual(hydrated["quality_policy"]["min_report_claims"], 3)
        self.assertGreaterEqual(hydrated["quality_policy"]["min_formal_evidence"], 5)
        self.assertTrue(hydrated["quality_policy"]["require_official_coverage"])
        self.assertEqual(hydrated["retrieval_profile"]["primary_search_provider"], "searxng")
        self.assertIn(
            "bing_rss", hydrated["retrieval_profile"]["fallback_search_providers"]
        )

    def test_merge_preserves_api_key_on_profile_switch(self):
        saved = {
            "profile_id": "premium_default",
            "provider": "openai_compatible",
            "model": "gpt-5.4",
            "base_url": "https://api.openai.com/v1",
            "api_key": "secret-key",
        }
        override = {"model": "gpt-5.4-mini"}
        merged = merge_runtime_configs(saved, override)
        self.assertEqual(merged["profile_id"], "dev_fallback")
        self.assertEqual(merged["api_key"], "secret-key")
        self.assertEqual(
            merged["retrieval_profile"]["primary_search_provider"], "bing_rss"
        )


if __name__ == "__main__":
    unittest.main()
