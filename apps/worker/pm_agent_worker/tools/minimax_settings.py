import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pm_agent_worker.tools.env_loader import load_local_env


load_local_env()

DEFAULT_LLM_TIMEOUT_SECONDS = 45.0
MIN_LLM_TIMEOUT_SECONDS = 5.0
MAX_LLM_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True)
class MiniMaxConnectionSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    label: str = ""

    @property
    def chat_completions_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


@dataclass(frozen=True)
class MiniMaxSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    backup_connections: tuple[MiniMaxConnectionSettings, ...] = ()

    @property
    def chat_completions_url(self) -> str:
        return self.primary_connection.chat_completions_url

    @property
    def primary_connection(self) -> MiniMaxConnectionSettings:
        return MiniMaxConnectionSettings(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            label="Primary",
        )

    @property
    def connections(self) -> list[MiniMaxConnectionSettings]:
        return [self.primary_connection, *self.backup_connections]


def _clean_string(value: Optional[str], fallback: str = "") -> str:
    if value is None:
        return fallback
    normalized = str(value).strip()
    return normalized or fallback


def _clean_timeout_seconds(value: Any, fallback: float = DEFAULT_LLM_TIMEOUT_SECONDS) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        normalized = float(fallback)
    if normalized < MIN_LLM_TIMEOUT_SECONDS:
        return MIN_LLM_TIMEOUT_SECONDS
    if normalized > MAX_LLM_TIMEOUT_SECONDS:
        return MAX_LLM_TIMEOUT_SECONDS
    return normalized


def is_placeholder_api_key(api_key: str) -> bool:
    normalized = api_key.strip().lower()
    return normalized in {
        "",
        "v",
        "xxx",
        "your-key",
        "your-key-here",
        "placeholder",
        "test",
    }


def load_minimax_settings() -> MiniMaxSettings:
    return MiniMaxSettings(
        api_key=os.getenv("MINIMAX_API_KEY", ""),
        model=os.getenv("MINIMAX_MODEL", "MiniMax-M2.7"),
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"),
        timeout_seconds=_clean_timeout_seconds(os.getenv("MINIMAX_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS)),
    )


def build_minimax_settings(runtime_config: Optional[Dict[str, Any]] = None) -> MiniMaxSettings:
    default_settings = load_minimax_settings()
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
            MiniMaxConnectionSettings(
                api_key=_clean_string(item.get("api_key"), primary_api_key),
                model=primary_model,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                label=_clean_string(item.get("label")),
            )
        )
    return MiniMaxSettings(
        api_key=primary_api_key,
        model=primary_model,
        base_url=primary_base_url,
        timeout_seconds=timeout_seconds,
        backup_connections=tuple(backup_connections),
    )
