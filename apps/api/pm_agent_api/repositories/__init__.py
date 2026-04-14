from __future__ import annotations

import os

from pm_agent_api.repositories.base import StateRepositoryProtocol
from pm_agent_api.repositories.flagship_store import FlagshipStateRepository
from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository


def create_state_repository() -> StateRepositoryProtocol:
    backend = str(os.getenv("PM_AGENT_STORAGE_BACKEND", "json") or "json").strip().lower()
    if backend in {"json", "file", "in_memory"}:
        return InMemoryStateRepository()
    if backend in {"flagship", "postgres", "hybrid"}:
        return FlagshipStateRepository.from_env()
    raise RuntimeError(f"Unsupported PM_AGENT_STORAGE_BACKEND: {backend}")


__all__ = [
    "StateRepositoryProtocol",
    "InMemoryStateRepository",
    "FlagshipStateRepository",
    "create_state_repository",
]
