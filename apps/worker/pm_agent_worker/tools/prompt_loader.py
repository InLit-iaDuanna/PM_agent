from functools import lru_cache

from pm_agent_worker.tools.repo_paths import repo_root


@lru_cache(maxsize=None)
def load_prompt_template(name: str) -> str:
    prompt_path = repo_root() / "packages" / "prompts" / "templates" / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")

