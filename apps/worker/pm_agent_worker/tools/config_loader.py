import json
from functools import lru_cache
from typing import Any, Dict, List

from pm_agent_worker.tools.repo_paths import config_defaults_path, research_core_data_path


@lru_cache(maxsize=1)
def load_research_defaults() -> Dict[str, Any]:
    with config_defaults_path("research-defaults.json").open("r", encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def load_industry_templates() -> Dict[str, Any]:
    with research_core_data_path("industry-templates.json").open("r", encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def load_research_steps() -> List[Dict[str, Any]]:
    with research_core_data_path("research-steps.json").open("r", encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def load_orchestration_presets() -> Dict[str, Any]:
    with research_core_data_path("orchestration-presets.json").open("r", encoding="utf-8") as file:
        return json.load(file)
