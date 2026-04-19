import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.tools.config_loader import load_industry_templates, load_research_defaults, load_research_steps


class TemplateLoaderTest(unittest.TestCase):
    def test_industry_templates_cover_required_verticals(self) -> None:
        templates = load_industry_templates()
        self.assertIn("industrial_design", templates)
        self.assertIn("ecommerce", templates)
        self.assertGreaterEqual(len(templates["saas"]["taskCategories"]), 6)

    def test_defaults_expose_depth_presets(self) -> None:
        defaults = load_research_defaults()
        self.assertEqual(defaults["depthPresets"]["deep"]["max_sources"], 220)

    def test_steps_cover_complete_market_flow(self) -> None:
        steps = load_research_steps()
        self.assertEqual(len(steps), 10)


if __name__ == "__main__":
    unittest.main()
