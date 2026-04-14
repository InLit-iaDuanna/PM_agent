from copy import deepcopy
from typing import Any, Dict, Optional

from pm_agent_worker.tools.llm_runtime import normalize_provider


DEFAULT_RUNTIME_PROFILE_ID = "premium_default"

_CANONICAL_RUNTIME_PROFILES: Dict[str, Dict[str, Any]] = {
    "premium_default": {
        "profile_id": "premium_default",
        "label": "旗舰研究质量优先",
        "description": "面向正式研究交付，优先高质量检索、严格证据门槛和稳定版报告。",
        "quality_mode": "premium",
        "recommended": True,
        "runtime_config": {
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5.4",
            "timeout_seconds": 60,
            "llm_profile": {
                "profile_id": "premium_default",
                "label": "高质量写作与校验",
                "provider": "openai_compatible",
                "model": "gpt-5.4",
                "base_url": "https://api.openai.com/v1",
                "quality_tier": "premium",
            },
            "retrieval_profile": {
                "profile_id": "premium_default",
                "label": "质量优先检索链",
                "primary_search_provider": "bing_html",
                "fallback_search_providers": ["brave_html", "bing_rss", "duckduckgo_html"],
                "reranker": "quality_weighted_alias_official",
                "extractor": "quote_first_content_extractor",
                "writer_model": "gpt-5.4",
                "official_domains": ["openai.com", "apple.com", "meta.com", "figma.com", "notion.so"],
                "negative_keywords": ["font install", "template", "download", "crack", "pirated"],
                "alias_expansion": True,
                "official_source_bias": True,
            },
            "quality_policy": {
                "profile_id": "premium_default",
                "min_report_claims": 3,
                "min_formal_evidence": 5,
                "min_formal_domains": 3,
                "require_official_coverage": True,
                "auto_finalize": False,
                "auto_create_draft_on_delta": True,
            },
            "debug_policy": {
                "auto_open_mode": "off",
                "browser_auto_open": False,
                "verbose_diagnostics": False,
                "collect_raw_pages": True,
            },
        },
    },
    "dev_fallback": {
        "profile_id": "dev_fallback",
        "label": "开发调试兜底",
        "description": "面向本地开发和演示，保留证据结构与版本化，但降低模型和检索成本。",
        "quality_mode": "fallback",
        "recommended": False,
        "runtime_config": {
            "provider": "minimax",
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M2.7-highspeed",
            "timeout_seconds": 30,
            "llm_profile": {
                "profile_id": "dev_fallback",
                "label": "开发兜底模型",
                "provider": "minimax",
                "model": "MiniMax-M2.7-highspeed",
                "base_url": "https://api.minimaxi.com/v1",
                "quality_tier": "fallback",
            },
            "retrieval_profile": {
                "profile_id": "dev_fallback",
                "label": "开发兜底检索链",
                "primary_search_provider": "bing_rss",
                "fallback_search_providers": ["bing_html", "duckduckgo_html"],
                "reranker": "lightweight_rule_based",
                "extractor": "summary_first_extractor",
                "writer_model": "MiniMax-M2.7-highspeed",
                "official_domains": ["openai.com", "apple.com", "meta.com"],
                "negative_keywords": ["font install", "template", "download", "crack", "pirated"],
                "alias_expansion": True,
                "official_source_bias": True,
            },
            "quality_policy": {
                "profile_id": "dev_fallback",
                "min_report_claims": 1,
                "min_formal_evidence": 3,
                "min_formal_domains": 2,
                "require_official_coverage": False,
                "auto_finalize": False,
                "auto_create_draft_on_delta": True,
            },
            "debug_policy": {
                "auto_open_mode": "debug_only",
                "browser_auto_open": True,
                "verbose_diagnostics": True,
                "collect_raw_pages": False,
            },
        },
    },
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _deep_merge(base: Optional[Dict[str, Any]], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = deepcopy(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif isinstance(value, list):
            merged[key] = deepcopy(value)
        else:
            merged[key] = value
    return merged


def list_runtime_profiles() -> list[Dict[str, Any]]:
    return [deepcopy(profile) for profile in _CANONICAL_RUNTIME_PROFILES.values()]


def get_runtime_profile(profile_id: Optional[str]) -> Dict[str, Any]:
    normalized_profile_id = _clean_text(profile_id) or DEFAULT_RUNTIME_PROFILE_ID
    return deepcopy(_CANONICAL_RUNTIME_PROFILES.get(normalized_profile_id) or _CANONICAL_RUNTIME_PROFILES[DEFAULT_RUNTIME_PROFILE_ID])


def infer_runtime_profile_id(runtime_config: Optional[Dict[str, Any]] = None) -> str:
    runtime_config = runtime_config or {}
    for key in ("profile_id", "runtime_profile_id"):
        candidate = _clean_text(runtime_config.get(key))
        if candidate in _CANONICAL_RUNTIME_PROFILES:
            return candidate

    for nested_key in ("llm_profile", "retrieval_profile", "quality_policy"):
        nested = runtime_config.get(nested_key) or {}
        candidate = _clean_text(nested.get("profile_id"))
        if candidate in _CANONICAL_RUNTIME_PROFILES:
            return candidate

    provider = normalize_provider(runtime_config.get("provider"))
    model = _clean_text(runtime_config.get("model")).lower()
    debug_policy = runtime_config.get("debug_policy") or {}
    auto_open_mode = _clean_text(debug_policy.get("auto_open_mode")).lower()
    if provider == "minimax":
        return "dev_fallback"
    if model.endswith("-mini") or "highspeed" in model or "mini" in model:
        return "dev_fallback"
    if auto_open_mode in {"debug_only", "always"} or bool(debug_policy.get("verbose_diagnostics")):
        return "dev_fallback"
    return DEFAULT_RUNTIME_PROFILE_ID


def _carry_forward_runtime_secrets(runtime_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    runtime_config = runtime_config or {}
    carried: Dict[str, Any] = {}
    if runtime_config.get("api_key") not in {None, ""}:
        carried["api_key"] = runtime_config.get("api_key")
    if runtime_config.get("backup_configs"):
        carried["backup_configs"] = deepcopy(runtime_config.get("backup_configs"))
    return carried


def hydrate_runtime_config(runtime_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    runtime_config = deepcopy(runtime_config or {})
    profile_id = infer_runtime_profile_id(runtime_config)
    profile = get_runtime_profile(profile_id)
    merged = _deep_merge(profile.get("runtime_config") or {}, runtime_config)

    provider = normalize_provider(merged.get("provider") or profile["runtime_config"].get("provider"))
    base_url = _clean_text(merged.get("base_url") or profile["runtime_config"].get("base_url"))
    model = _clean_text(merged.get("model") or profile["runtime_config"].get("model"))
    timeout_seconds = merged.get("timeout_seconds") or profile["runtime_config"].get("timeout_seconds")

    llm_profile = _deep_merge(profile["runtime_config"].get("llm_profile") or {}, merged.get("llm_profile") or {})
    llm_profile["profile_id"] = _clean_text(llm_profile.get("profile_id")) or profile_id
    llm_profile["provider"] = provider
    llm_profile["model"] = model
    llm_profile["base_url"] = base_url

    retrieval_profile = _deep_merge(profile["runtime_config"].get("retrieval_profile") or {}, merged.get("retrieval_profile") or {})
    retrieval_profile["profile_id"] = _clean_text(retrieval_profile.get("profile_id")) or profile_id
    retrieval_profile["label"] = _clean_text(retrieval_profile.get("label")) or profile["runtime_config"]["retrieval_profile"].get("label")
    retrieval_profile["fallback_search_providers"] = list(retrieval_profile.get("fallback_search_providers") or [])
    retrieval_profile["official_domains"] = list(retrieval_profile.get("official_domains") or [])
    retrieval_profile["negative_keywords"] = list(retrieval_profile.get("negative_keywords") or [])
    retrieval_profile["alias_expansion"] = bool(retrieval_profile.get("alias_expansion", True))
    retrieval_profile["official_source_bias"] = bool(retrieval_profile.get("official_source_bias", True))

    quality_policy = _deep_merge(profile["runtime_config"].get("quality_policy") or {}, merged.get("quality_policy") or {})
    quality_policy["profile_id"] = _clean_text(quality_policy.get("profile_id")) or profile_id
    quality_policy["auto_finalize"] = bool(quality_policy.get("auto_finalize", False))
    quality_policy["auto_create_draft_on_delta"] = bool(quality_policy.get("auto_create_draft_on_delta", True))
    quality_policy["require_official_coverage"] = bool(quality_policy.get("require_official_coverage", False))

    debug_policy = _deep_merge(profile["runtime_config"].get("debug_policy") or {}, merged.get("debug_policy") or {})
    auto_open_mode = _clean_text(debug_policy.get("auto_open_mode")).lower()
    if auto_open_mode not in {"off", "debug_only", "always"}:
        auto_open_mode = "debug_only" if bool(debug_policy.get("browser_auto_open")) else "off"
    debug_policy["auto_open_mode"] = auto_open_mode
    debug_policy["browser_auto_open"] = auto_open_mode in {"debug_only", "always"}
    debug_policy["verbose_diagnostics"] = bool(debug_policy.get("verbose_diagnostics", False))
    debug_policy["collect_raw_pages"] = bool(debug_policy.get("collect_raw_pages", auto_open_mode != "off"))

    merged["profile_id"] = profile_id
    merged["provider"] = provider
    merged["base_url"] = base_url
    merged["model"] = model
    merged["timeout_seconds"] = timeout_seconds
    merged["llm_profile"] = llm_profile
    merged["retrieval_profile"] = retrieval_profile
    merged["quality_policy"] = quality_policy
    merged["debug_policy"] = debug_policy
    return merged


def merge_runtime_configs(
    saved_runtime_config: Optional[Dict[str, Any]] = None,
    runtime_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    saved_runtime_config = deepcopy(saved_runtime_config or {})
    runtime_override = deepcopy(runtime_override or {})
    profile_id = infer_runtime_profile_id(runtime_override or saved_runtime_config)
    profile_switched = bool(runtime_override) and profile_id != infer_runtime_profile_id(saved_runtime_config)
    if profile_switched:
        base = _deep_merge(get_runtime_profile(profile_id).get("runtime_config") or {}, _carry_forward_runtime_secrets(saved_runtime_config))
    else:
        base = hydrate_runtime_config(saved_runtime_config)
    merged = _deep_merge(base, runtime_override)
    if _clean_text(saved_runtime_config.get("api_key")) and not _clean_text(runtime_override.get("api_key")):
        merged["api_key"] = saved_runtime_config["api_key"]
    return hydrate_runtime_config(merged)

