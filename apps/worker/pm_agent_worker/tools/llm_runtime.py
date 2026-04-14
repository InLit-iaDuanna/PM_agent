import os
from typing import Any, Dict, Optional

from pm_agent_worker.tools.minimax_client import MiniMaxChatClient
from pm_agent_worker.tools.minimax_settings import MiniMaxSettings, build_minimax_settings, is_placeholder_api_key, load_minimax_settings
from pm_agent_worker.tools.openai_compatible_client import OpenAICompatibleChatClient
from pm_agent_worker.tools.openai_compatible_settings import (
    OpenAICompatibleSettings,
    build_openai_compatible_settings,
    load_openai_compatible_settings,
)


def normalize_provider(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"openai", "openai_compatible", "openai_compat", "openai-compatible"}:
        return "openai_compatible"
    return "minimax"


def load_llm_provider() -> str:
    configured = os.getenv("PM_AGENT_LLM_PROVIDER") or os.getenv("LLM_PROVIDER")
    if configured:
        return normalize_provider(configured)
    if os.getenv("OPENAI_COMPAT_API_KEY") or os.getenv("OPENAI_API_KEY"):
        return "openai_compatible"
    return "minimax"


def load_llm_settings() -> MiniMaxSettings | OpenAICompatibleSettings:
    provider = load_llm_provider()
    if provider == "openai_compatible":
        return load_openai_compatible_settings()
    return load_minimax_settings()


def build_llm_settings(runtime_config: Optional[Dict[str, Any]] = None) -> MiniMaxSettings | OpenAICompatibleSettings:
    runtime_config = runtime_config or {}
    provider = normalize_provider(runtime_config.get("provider") or load_llm_provider())
    if provider == "openai_compatible":
        return build_openai_compatible_settings({**runtime_config, "provider": provider})
    return build_minimax_settings({**runtime_config, "provider": provider})


def create_llm_client(runtime_config: Optional[Dict[str, Any]] = None) -> MiniMaxChatClient | OpenAICompatibleChatClient:
    settings = build_llm_settings(runtime_config)
    if isinstance(settings, OpenAICompatibleSettings):
        return OpenAICompatibleChatClient(settings)
    return MiniMaxChatClient(settings)


def infer_provider_from_settings(settings: MiniMaxSettings | OpenAICompatibleSettings) -> str:
    if isinstance(settings, OpenAICompatibleSettings):
        return "openai_compatible"
    return "minimax"


def runtime_api_key_configured(settings: MiniMaxSettings | OpenAICompatibleSettings) -> bool:
    api_key = str(settings.api_key or "").strip()
    return bool(api_key and not is_placeholder_api_key(api_key))
