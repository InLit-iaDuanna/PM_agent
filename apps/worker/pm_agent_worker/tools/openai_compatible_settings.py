import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pm_agent_worker.tools.env_loader import load_local_env
from pm_agent_worker.tools.minimax_settings import DEFAULT_LLM_TIMEOUT_SECONDS, _clean_string, _clean_timeout_seconds


load_local_env()


@dataclass(frozen=True)
class OpenAICompatibleConnectionSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    label: str = ""

    @property
    def chat_completions_urls(self) -> list[str]:
        normalized = self.base_url.rstrip("/")
        if not normalized:
            return []
        if normalized.endswith("/v1"):
            return [normalized + "/chat/completions"]
        return [normalized + "/v1/chat/completions", normalized + "/chat/completions"]

    @property
    def responses_urls(self) -> list[str]:
        normalized = self.base_url.rstrip("/")
        if not normalized:
            return []
        if normalized.endswith("/v1"):
            return [normalized + "/responses"]
        return [normalized + "/v1/responses", normalized + "/responses"]


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    backup_connections: tuple[OpenAICompatibleConnectionSettings, ...] = ()

    @property
    def chat_completions_urls(self) -> list[str]:
        return self.primary_connection.chat_completions_urls

    @property
    def responses_urls(self) -> list[str]:
        return self.primary_connection.responses_urls

    @property
    def primary_connection(self) -> OpenAICompatibleConnectionSettings:
        return OpenAICompatibleConnectionSettings(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            label="Primary",
        )

    @property
    def connections(self) -> list[OpenAICompatibleConnectionSettings]:
        return [self.primary_connection, *self.backup_connections]


def load_openai_compatible_settings() -> OpenAICompatibleSettings:
    return OpenAICompatibleSettings(
        api_key=os.getenv("OPENAI_COMPAT_API_KEY", os.getenv("OPENAI_API_KEY", "")),
        model=os.getenv("OPENAI_COMPAT_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4")),
        base_url=os.getenv("OPENAI_COMPAT_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")),
        timeout_seconds=_clean_timeout_seconds(
            os.getenv("OPENAI_COMPAT_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS))
        ),
    )


def build_openai_compatible_settings(runtime_config: Optional[Dict[str, Any]] = None) -> OpenAICompatibleSettings:
    default_settings = load_openai_compatible_settings()
    runtime_config = runtime_config or {}
    primary_api_key = _clean_string(runtime_config.get("api_key"), default_settings.api_key)
    primary_model = _clean_string(runtime_config.get("model"), default_settings.model)
    primary_base_url = _clean_string(runtime_config.get("base_url"), default_settings.base_url)
    timeout_seconds = _clean_timeout_seconds(runtime_config.get("timeout_seconds"), default_settings.timeout_seconds)
    backup_connections = []
    for item in runtime_config.get("backup_configs") or []:
        if not isinstance(item, dict):
            continue
        base_url = _clean_string(item.get("base_url"))
        if not base_url:
            continue
        backup_connections.append(
            OpenAICompatibleConnectionSettings(
                api_key=_clean_string(item.get("api_key"), primary_api_key),
                model=primary_model,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                label=_clean_string(item.get("label")),
            )
        )
    return OpenAICompatibleSettings(
        api_key=primary_api_key,
        model=primary_model,
        base_url=primary_base_url,
        timeout_seconds=timeout_seconds,
        backup_connections=tuple(backup_connections),
    )
