from copy import deepcopy
from datetime import datetime, timezone
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from pm_agent_api.repositories.base import StateRepositoryProtocol
from pm_agent_api.runtime.repo_bootstrap import ensure_repo_paths

ensure_repo_paths()

from pm_agent_worker.tools.llm_runtime import (
    build_llm_settings,
    infer_provider_from_settings,
    load_llm_settings,
    normalize_provider,
    runtime_api_key_configured,
)
from pm_agent_worker.tools.runtime_profiles import (
    get_runtime_profile,
    hydrate_runtime_config,
    infer_runtime_profile_id,
    list_runtime_profiles,
    merge_runtime_configs,
)
from pm_agent_worker.workflows.research_workflow import ResearchWorkflowEngine


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_secret(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "••••••"
    if len(text) <= 16:
        return f"{text[:2]}••••{text[-2:]}"
    return f"{text[:4]}••••{text[-4:]}"


class RuntimeService:
    def __init__(self, repository: StateRepositoryProtocol) -> None:
        self.repository = repository

    def _saved_config(self, owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.repository.get_runtime_config(owner_user_id)

    def _effective_runtime_config(
        self,
        runtime_config: Optional[Dict[str, Any]] = None,
        owner_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        runtime_config = runtime_config or {}
        if runtime_config:
            return hydrate_runtime_config(runtime_config)
        saved = self._saved_config(owner_user_id)
        if saved:
            return hydrate_runtime_config(saved)
        env_settings = load_llm_settings()
        inferred_provider = infer_provider_from_settings(env_settings)
        env_runtime_config: Dict[str, Any] = {
            "provider": inferred_provider,
            "base_url": getattr(env_settings, "base_url", ""),
            "model": getattr(env_settings, "model", ""),
            "timeout_seconds": getattr(env_settings, "timeout_seconds", None),
        }
        if runtime_api_key_configured(env_settings):
            env_runtime_config["api_key"] = getattr(env_settings, "api_key", "")
        return hydrate_runtime_config(env_runtime_config)

    def _source_label(self, owner_user_id: Optional[str] = None) -> str:
        saved = self._saved_config(owner_user_id)
        if saved:
            return "saved"
        env_settings = load_llm_settings()
        if runtime_api_key_configured(env_settings):
            return "environment"
        return "default"

    def _browser_summary(self) -> Dict[str, Any]:
        summary = ResearchWorkflowEngine()._build_runtime_summary()
        return {
            "browser_mode": summary["browser_mode"],
            "browser_available": summary["browser_available"],
        }

    def _provider_label(self, provider: str) -> str:
        return "兼容 OpenAI" if provider == "openai_compatible" else "MiniMax"

    def _build_profile_entry(self, profile_id: Optional[str] = None) -> Dict[str, Any]:
        profile = get_runtime_profile(profile_id)
        runtime_config = hydrate_runtime_config(profile.get("runtime_config"))
        return {
            "profile_id": profile["profile_id"],
            "label": profile.get("label"),
            "description": profile.get("description"),
            "quality_mode": profile.get("quality_mode"),
            "recommended": bool(profile.get("recommended")),
            "runtime_config": runtime_config,
            "llm_profile": deepcopy(runtime_config.get("llm_profile") or {}),
            "retrieval_profile": deepcopy(runtime_config.get("retrieval_profile") or {}),
            "quality_policy": deepcopy(runtime_config.get("quality_policy") or {}),
            "debug_policy": deepcopy(runtime_config.get("debug_policy") or {}),
        }

    def _available_profiles(self) -> List[Dict[str, Any]]:
        return [self._build_profile_entry(item["profile_id"]) for item in list_runtime_profiles()]

    def _clean_text(self, value: Any) -> str:
        return str(value or "").strip()

    def _normalize_timeout_seconds(self, value: Any, fallback: float) -> float:
        if value in {None, ""}:
            return round(float(fallback), 1)
        try:
            normalized = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError("请求超时必须是数字。") from error
        if normalized < 5 or normalized > 180:
            raise ValueError("请求超时需要控制在 5 到 180 秒之间。")
        return round(normalized, 1)

    def _normalize_base_url(self, value: str, provider: str) -> str:
        text = self._clean_text(value)
        if not text:
            return ""
        if "://" not in text:
            text = f"https://{text}"

        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL 格式不正确。")

        host = parsed.hostname or ""
        if provider == "minimax" and host == "api.minimax.com":
            raise ValueError("`api.minimax.com` 无法解析。国内用户请改成 `https://api.minimaxi.com/v1`，国际用户请改成 `https://api.minimax.io/v1`。")

        path = parsed.path.rstrip("/")
        if provider == "minimax" and host in {"api.minimax.io", "api.minimaxi.com"} and not path:
            path = "/v1"
        if provider == "openai_compatible" and host == "api.openai.com" and not path:
            path = "/v1"

        try:
            socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as error:
            raise ValueError(f"Base URL 域名 `{host}` 无法解析，请检查是否填写正确。") from error

        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    def _normalize_backup_configs(
        self,
        backup_configs: Any,
        provider: str,
        current_backups: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        normalized_backups: List[Dict[str, Any]] = []
        current_backups = current_backups or []
        seen_urls = set()
        for index, item in enumerate(backup_configs or []):
            if not isinstance(item, dict):
                continue
            normalized_base_url = self._normalize_base_url(item.get("base_url"), provider)
            if not normalized_base_url or normalized_base_url in seen_urls:
                continue
            seen_urls.add(normalized_base_url)
            current_item = current_backups[index] if index < len(current_backups) else {}
            matched_current = next(
                (
                    existing
                    for existing in current_backups
                    if self._clean_text(existing.get("base_url")) == normalized_base_url
                ),
                current_item,
            )
            normalized_item: Dict[str, Any] = {
                "label": self._clean_text(item.get("label")),
                "base_url": normalized_base_url,
            }
            incoming_api_key = self._clean_text(item.get("api_key"))
            preserved_api_key = self._clean_text(matched_current.get("api_key"))
            preserved_base_url = self._clean_text(matched_current.get("base_url"))
            if incoming_api_key:
                normalized_item["api_key"] = incoming_api_key
            elif preserved_api_key and preserved_base_url == normalized_base_url:
                normalized_item["api_key"] = preserved_api_key
            normalized_backups.append(normalized_item)
        return normalized_backups

    def _normalize_runtime_config(self, runtime_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resolved_runtime_config = hydrate_runtime_config(runtime_config)
        settings = build_llm_settings(resolved_runtime_config)
        provider = normalize_provider(resolved_runtime_config.get("provider") or infer_provider_from_settings(settings))
        backup_configs = self._normalize_backup_configs((resolved_runtime_config or {}).get("backup_configs"), provider)
        timeout_seconds = self._normalize_timeout_seconds((resolved_runtime_config or {}).get("timeout_seconds"), settings.timeout_seconds)
        profile_id = infer_runtime_profile_id(resolved_runtime_config)
        llm_profile = deepcopy(resolved_runtime_config.get("llm_profile") or {})
        llm_profile["profile_id"] = self._clean_text(llm_profile.get("profile_id")) or profile_id
        llm_profile["provider"] = provider
        llm_profile["model"] = settings.model
        llm_profile["base_url"] = self._normalize_base_url(settings.base_url, provider)
        retrieval_profile = deepcopy(resolved_runtime_config.get("retrieval_profile") or {})
        retrieval_profile["profile_id"] = self._clean_text(retrieval_profile.get("profile_id")) or profile_id
        quality_policy = deepcopy(resolved_runtime_config.get("quality_policy") or {})
        quality_policy["profile_id"] = self._clean_text(quality_policy.get("profile_id")) or profile_id
        debug_policy = deepcopy(resolved_runtime_config.get("debug_policy") or {})
        auto_open_mode = self._clean_text(debug_policy.get("auto_open_mode")).lower()
        if auto_open_mode not in {"off", "debug_only", "always"}:
            auto_open_mode = "debug_only" if bool(debug_policy.get("browser_auto_open")) else "off"
        debug_policy["auto_open_mode"] = auto_open_mode
        debug_policy["browser_auto_open"] = auto_open_mode in {"debug_only", "always"}
        return {
            "profile_id": profile_id,
            "provider": provider,
            "api_key": settings.api_key,
            "model": settings.model,
            "base_url": self._normalize_base_url(settings.base_url, provider),
            "timeout_seconds": timeout_seconds,
            "backup_configs": backup_configs,
            "llm_profile": llm_profile,
            "retrieval_profile": retrieval_profile,
            "quality_policy": quality_policy,
            "debug_policy": debug_policy,
        }

    def get_status(self, owner_user_id: Optional[str] = None) -> Dict[str, Any]:
        saved = self._saved_config(owner_user_id)
        runtime_config = self._effective_runtime_config(owner_user_id=owner_user_id)
        selected_profile_id = infer_runtime_profile_id(runtime_config)
        selected_profile = self._build_profile_entry(selected_profile_id)
        normalized_runtime_config = deepcopy(runtime_config)
        browser_summary = self._browser_summary()
        summary: Dict[str, Any] = {}
        validation_status = "invalid"
        effective_settings = build_llm_settings(runtime_config or None)
        provider = normalize_provider((runtime_config or {}).get("provider") or infer_provider_from_settings(effective_settings))
        provider_label = self._provider_label(provider)
        validation_message = f"{provider_label} API Key 未配置，或仍是占位值"

        try:
            normalized_runtime_config = self._normalize_runtime_config(runtime_config or None)
            workflow = ResearchWorkflowEngine(runtime_config=normalized_runtime_config or None)
            summary = workflow._build_runtime_summary()
            effective_settings = workflow.llm_client.settings
            provider = summary["provider"]
            provider_label = self._provider_label(provider)
            validation_status = summary["validation_status"]
            validation_message = summary["validation_message"]
            browser_summary = {
                "browser_mode": summary["browser_mode"],
                "browser_available": summary["browser_available"],
            }
        except ValueError as error:
            validation_message = str(error)

        api_key = str(effective_settings.api_key or "").strip()
        api_key_configured = runtime_api_key_configured(effective_settings)
        configured = api_key_configured and validation_status == "valid"
        primary_base_url = str(runtime_config.get("base_url") or effective_settings.base_url or "").strip()
        active_base_url = summary.get("active_base_url")
        backup_configs = []
        for item in (runtime_config.get("backup_configs") or normalized_runtime_config.get("backup_configs") or []):
            if not isinstance(item, dict):
                continue
            if self._clean_text(item.get("base_url")) == primary_base_url:
                continue
            backup_api_key = self._clean_text(item.get("api_key"))
            backup_configs.append(
                {
                    "label": self._clean_text(item.get("label")),
                    "base_url": self._clean_text(item.get("base_url")),
                    "api_key_configured": bool(backup_api_key) or api_key_configured,
                    "api_key_masked": mask_secret(backup_api_key) if backup_api_key else None,
                    "uses_primary_api_key": not bool(backup_api_key),
                    "priority": len(backup_configs) + 1,
                    "is_active": self._clean_text(item.get("base_url")) == active_base_url,
                }
            )
        available_profiles = self._available_profiles()

        return {
            "provider": provider,
            "model": effective_settings.model,
            "base_url": primary_base_url,
            "active_base_url": active_base_url,
            "timeout_seconds": float(getattr(effective_settings, "timeout_seconds", 0) or 0),
            "configured": configured,
            "api_key_configured": api_key_configured,
            "api_key_masked": mask_secret(api_key) if api_key_configured else None,
            "backup_count": len(backup_configs),
            "backup_configs": backup_configs,
            "source": self._source_label(owner_user_id),
            "validation_status": validation_status,
            "validation_message": validation_message,
            "browser_mode": browser_summary["browser_mode"],
            "browser_available": browser_summary["browser_available"],
            "selected_profile_id": selected_profile_id,
            "selected_profile_label": selected_profile.get("label"),
            "selected_profile": selected_profile,
            "available_profiles": available_profiles,
            "runtime_config": deepcopy(runtime_config),
            "resolved_runtime_config": deepcopy(normalized_runtime_config),
            "llm_profile": deepcopy(normalized_runtime_config.get("llm_profile") or {}),
            "retrieval_profile": deepcopy(normalized_runtime_config.get("retrieval_profile") or {}),
            "quality_policy": deepcopy(normalized_runtime_config.get("quality_policy") or {}),
            "debug_policy": deepcopy(normalized_runtime_config.get("debug_policy") or {}),
            "updated_at": saved.get("updated_at") if saved else None,
        }

    def save_settings(
        self,
        runtime_config: Dict[str, Any],
        replace_api_key: bool = False,
        owner_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        current = self._saved_config(owner_user_id) or {}
        merged_runtime_config = merge_runtime_configs(current, runtime_config)
        provider = normalize_provider(merged_runtime_config.get("provider") or current.get("provider"))
        default_settings = build_llm_settings({"provider": provider})
        current_is_same_provider = normalize_provider(current.get("provider")) == provider
        current_base_url = current.get("base_url") if current_is_same_provider else default_settings.base_url
        current_model = current.get("model") if current_is_same_provider else default_settings.model
        current_timeout = current.get("timeout_seconds") if current_is_same_provider else default_settings.timeout_seconds
        next_config = {
            "profile_id": infer_runtime_profile_id(merged_runtime_config),
            "provider": provider,
            "base_url": self._normalize_base_url(str(merged_runtime_config.get("base_url") or current_base_url or "").strip(), provider),
            "model": str(merged_runtime_config.get("model") or current_model or "").strip(),
            "timeout_seconds": self._normalize_timeout_seconds(merged_runtime_config.get("timeout_seconds"), current_timeout or default_settings.timeout_seconds),
        }
        incoming_api_key = str(runtime_config.get("api_key") or "").strip()
        if incoming_api_key or replace_api_key:
            next_config["api_key"] = incoming_api_key
        elif self._clean_text(merged_runtime_config.get("api_key")):
            next_config["api_key"] = merged_runtime_config["api_key"]
        elif current_is_same_provider and current.get("api_key"):
            next_config["api_key"] = current["api_key"]
        normalized_backups = self._normalize_backup_configs(
            merged_runtime_config.get("backup_configs"),
            provider,
            current.get("backup_configs"),
        )
        next_config["backup_configs"] = [item for item in normalized_backups if item.get("base_url") != next_config["base_url"]]
        next_config["llm_profile"] = deepcopy(merged_runtime_config.get("llm_profile") or {})
        next_config["llm_profile"]["provider"] = provider
        next_config["llm_profile"]["model"] = next_config["model"]
        next_config["llm_profile"]["base_url"] = next_config["base_url"]
        next_config["retrieval_profile"] = deepcopy(merged_runtime_config.get("retrieval_profile") or {})
        next_config["quality_policy"] = deepcopy(merged_runtime_config.get("quality_policy") or {})
        next_config["debug_policy"] = deepcopy(merged_runtime_config.get("debug_policy") or {})
        next_config["updated_at"] = iso_now()
        self.repository.set_runtime_config(next_config, owner_user_id)
        return self.get_status(owner_user_id=owner_user_id)

    def validate(self, runtime_config: Dict[str, Any], owner_user_id: Optional[str] = None) -> Dict[str, Any]:
        resolved_runtime_config = merge_runtime_configs(self._saved_config(owner_user_id), runtime_config)
        selected_profile_id = infer_runtime_profile_id(resolved_runtime_config)
        provider = normalize_provider(resolved_runtime_config.get("provider"))
        provider_label = self._provider_label(provider)
        try:
            normalized_runtime_config = self._normalize_runtime_config(resolved_runtime_config)
        except ValueError as error:
            browser_summary = self._browser_summary()
            settings = build_llm_settings(resolved_runtime_config)
            return {
                "ok": False,
                "provider": provider,
                "model": settings.model,
                "message": str(error),
                "browser_mode": browser_summary["browser_mode"],
                "browser_available": browser_summary["browser_available"],
                "selected_profile_id": selected_profile_id,
            }

        workflow = ResearchWorkflowEngine(runtime_config=normalized_runtime_config)
        summary = workflow._build_runtime_summary()
        if summary["validation_status"] != "valid":
            return {
                "ok": False,
                "provider": summary["provider"],
                "model": summary["model"],
                "message": summary["validation_message"],
                "browser_mode": summary["browser_mode"],
                "browser_available": summary["browser_available"],
                "selected_profile_id": selected_profile_id,
            }
        try:
            response = workflow.llm_client.complete(
                [{"role": "user", "content": "Reply with OK only."}],
                temperature=0.0,
                max_tokens=8,
            )
            active_base_url = getattr(workflow.llm_client, "active_base_url", None)
            message = f"{provider_label} 连接成功。" if "ok" in response.lower() else f"{provider_label} 可访问，但返回内容不是预期的 OK。"
            if active_base_url and active_base_url != normalized_runtime_config.get("base_url"):
                message = f"{message} 已自动切换到备用连接：{active_base_url}"
            return {
                "ok": True,
                "provider": summary["provider"],
                "model": summary["model"],
                "message": message,
                "browser_mode": summary["browser_mode"],
                "browser_available": summary["browser_available"],
                "selected_profile_id": selected_profile_id,
            }
        except Exception as error:
            return {
                "ok": False,
                "provider": summary["provider"],
                "model": summary["model"],
                "message": str(error),
                "browser_mode": summary["browser_mode"],
                "browser_available": summary["browser_available"],
                "selected_profile_id": selected_profile_id,
            }
