"use client";

import { useEffect, useMemo, useState } from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  RuntimeBackupConfigDto,
  RuntimeConfigDto,
  RuntimeDebugPolicyDto,
  RuntimeLlmProfileDto,
  RuntimeProfileRecord,
  RuntimeProvider,
  RuntimeQualityPolicyDto,
  RuntimeRetrievalProfileDto,
  RuntimeStatusRecord,
} from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, Input, Label, Select } from "@pm-agent/ui";

import {
  fetchRuntimeStatus,
  getApiErrorMessage,
  saveRuntimeSettings,
  validateRuntimeSettings,
} from "../../../lib/api-client";
import { RequestStateCard } from "./request-state-card";
import { formatBrowserMode, formatRuntimeSource } from "./research-ui-utils";

const MINIMAX_MODEL_OPTIONS = [
  "MiniMax-M2.7",
  "MiniMax-M2.7-highspeed",
  "MiniMax-M2.5",
  "MiniMax-M2.5-highspeed",
  "MiniMax-M2.1",
  "MiniMax-M2.1-highspeed",
];

const OPENAI_COMPAT_MODEL_OPTIONS = [
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.3",
  "gpt-4.1",
];

interface RuntimeBrandPreset {
  id: string;
  label: string;
  provider: RuntimeProvider;
  base_url: string;
  model: string;
  model_options: string[];
  description: string;
  base_url_hint: string;
}

interface RuntimeProfilePreset {
  id: string;
  label: string;
  description: string;
  isDevFallback: boolean;
  isHighQuality: boolean;
  provider: RuntimeProvider;
  timeout_seconds: number;
  llm_profile: RuntimeLlmProfileDto;
  retrieval_profile: RuntimeRetrievalProfileDto;
  quality_policy: RuntimeQualityPolicyDto;
  debug_policy: RuntimeDebugPolicyDto;
}

const RUNTIME_BRAND_PRESETS: RuntimeBrandPreset[] = [
  {
    id: "minimax_cn",
    label: "MiniMax 国内官方",
    provider: "minimax",
    base_url: "https://api.minimaxi.com/v1",
    model: "MiniMax-M2.7",
    model_options: MINIMAX_MODEL_OPTIONS,
    description: "适合中国大陆账号，使用 MiniMax 官方国内入口。",
    base_url_hint: "国内账号请优先使用 `https://api.minimaxi.com/v1`；如果是国际账号，再改用国际入口。",
  },
  {
    id: "minimax_global",
    label: "MiniMax 国际官方",
    provider: "minimax",
    base_url: "https://api.minimax.io/v1",
    model: "MiniMax-M2.7",
    model_options: MINIMAX_MODEL_OPTIONS,
    description: "适合国际账号，使用 MiniMax 官方国际入口。",
    base_url_hint: "国际账号使用 `https://api.minimax.io/v1`；国内账号请改回 `https://api.minimaxi.com/v1`。",
  },
  {
    id: "openai_official",
    label: "OpenAI 官方",
    provider: "openai_compatible",
    base_url: "https://api.openai.com/v1",
    model: "gpt-5.4",
    model_options: ["gpt-5.4", "gpt-5.4-mini", "gpt-5.3", "gpt-4.1"],
    description: "直接连接 OpenAI 官方接口，适合原生 OpenAI Key。",
    base_url_hint: "OpenAI 官方入口使用 `https://api.openai.com/v1`。",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    provider: "openai_compatible",
    base_url: "https://openrouter.ai/api/v1",
    model: "openai/gpt-5.2",
    model_options: ["openai/gpt-5.2"],
    description: "聚合多个模型供应商，模型名通常带上供应商前缀。",
    base_url_hint: "OpenRouter 官方入口使用 `https://openrouter.ai/api/v1`，模型名通常类似 `openai/gpt-5.2`。",
  },
  {
    id: "deepseek",
    label: "DeepSeek 官方",
    provider: "openai_compatible",
    base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    model_options: ["deepseek-chat", "deepseek-reasoner"],
    description: "DeepSeek 提供 OpenAI 兼容接口，适合直接接入官方 Key。",
    base_url_hint: "DeepSeek 官方兼容入口可填 `https://api.deepseek.com/v1`。",
  },
  {
    id: "dashscope_cn",
    label: "阿里云百炼 北京",
    provider: "openai_compatible",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen3.6-plus",
    model_options: ["qwen3.6-plus", "qwen3-coder-next", "qwen-plus"],
    description: "百炼 OpenAI 兼容入口，适合中国内地地域的 Qwen 模型调用。",
    base_url_hint: "百炼北京地域入口使用 `https://dashscope.aliyuncs.com/compatible-mode/v1`。",
  },
  {
    id: "dashscope_sg",
    label: "阿里云百炼 新加坡",
    provider: "openai_compatible",
    base_url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    model: "qwen3.6-plus",
    model_options: ["qwen3.6-plus", "qwen3-coder-next", "qwen-plus"],
    description: "百炼国际入口，适合新加坡地域账号或海外部署。",
    base_url_hint: "百炼新加坡地域入口使用 `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`。",
  },
  {
    id: "moonshot",
    label: "Moonshot Kimi 官方",
    provider: "openai_compatible",
    base_url: "https://api.moonshot.ai/v1",
    model: "kimi-k2.5",
    model_options: ["kimi-k2.5", "kimi-k2-thinking", "kimi-k2-turbo-preview"],
    description: "Kimi API 官方入口，适合代码、Agent 和长思考场景。",
    base_url_hint: "Moonshot 官方入口使用 `https://api.moonshot.ai/v1`。",
  },
  {
    id: "hunyuan",
    label: "腾讯混元官方",
    provider: "openai_compatible",
    base_url: "https://api.hunyuan.cloud.tencent.com/v1",
    model: "hunyuan-turbos-latest",
    model_options: ["hunyuan-turbos-latest"],
    description: "腾讯混元的 OpenAI 兼容入口，适合直接迁移兼容 SDK。",
    base_url_hint: "腾讯混元兼容入口使用 `https://api.hunyuan.cloud.tencent.com/v1`。",
  },
];

const DEFAULT_TIMEOUT_SECONDS = 45;

const PROVIDER_DEFAULTS: Record<RuntimeProvider, { base_url: string; model: string; timeout_seconds: number }> = {
  minimax: {
    base_url: "https://api.minimaxi.com/v1",
    model: "MiniMax-M2.7",
    timeout_seconds: DEFAULT_TIMEOUT_SECONDS,
  },
  openai_compatible: {
    base_url: "https://api.openai.com/v1",
    model: "gpt-5.4",
    timeout_seconds: DEFAULT_TIMEOUT_SECONDS,
  },
};

const RUNTIME_PROFILE_PRESETS: RuntimeProfilePreset[] = [
  {
    id: "premium_default",
    label: "旗舰研究质量优先",
    description: "面向正式研究交付，优先高质量检索、严格证据门槛和稳定版报告。",
    isDevFallback: false,
    isHighQuality: true,
    provider: "openai_compatible",
    timeout_seconds: 60,
    llm_profile: {
      profile_id: "premium_default",
      label: "高质量写作与校验",
      model: "gpt-5.4",
      provider: "openai_compatible",
      base_url: "https://api.openai.com/v1",
      quality_tier: "premium",
    },
    retrieval_profile: {
      profile_id: "premium_default",
      label: "质量优先检索链",
      primary_search_provider: "bing_html",
      fallback_search_providers: ["brave_html", "bing_rss", "duckduckgo_html"],
      reranker: "quality_weighted_alias_official",
      extractor: "quote_first_content_extractor",
      writer_model: "gpt-5.4",
      official_domains: ["openai.com", "apple.com", "meta.com", "figma.com", "notion.so"],
      negative_keywords: ["font install", "template", "download", "crack", "pirated"],
      alias_expansion: true,
      official_source_bias: true,
    },
    quality_policy: {
      profile_id: "premium_default",
      min_report_claims: 3,
      min_formal_evidence: 5,
      min_formal_domains: 3,
      require_official_coverage: true,
      auto_finalize: false,
      auto_create_draft_on_delta: true,
    },
    debug_policy: {
      auto_open_mode: "off",
      browser_auto_open: false,
      verbose_diagnostics: false,
      collect_raw_pages: true,
    },
  },
  {
    id: "dev_fallback",
    label: "开发调试兜底",
    description: "面向本地开发和演示，保留证据结构与版本化，但降低模型和检索成本。",
    isDevFallback: true,
    isHighQuality: false,
    provider: "minimax",
    timeout_seconds: 30,
    llm_profile: {
      profile_id: "dev_fallback",
      label: "开发兜底模型",
      model: "MiniMax-M2.7-highspeed",
      provider: "minimax",
      base_url: "https://api.minimaxi.com/v1",
      quality_tier: "fallback",
    },
    retrieval_profile: {
      profile_id: "dev_fallback",
      label: "开发兜底检索链",
      primary_search_provider: "bing_rss",
      fallback_search_providers: ["bing_html", "duckduckgo_html"],
      reranker: "lightweight_rule_based",
      extractor: "summary_first_extractor",
      writer_model: "MiniMax-M2.7-highspeed",
      official_domains: ["openai.com", "apple.com", "meta.com"],
      negative_keywords: ["font install", "template", "download", "crack", "pirated"],
      alias_expansion: true,
      official_source_bias: true,
    },
    quality_policy: {
      profile_id: "dev_fallback",
      min_report_claims: 1,
      min_formal_evidence: 3,
      min_formal_domains: 2,
      require_official_coverage: false,
      auto_finalize: false,
      auto_create_draft_on_delta: true,
    },
    debug_policy: {
      auto_open_mode: "debug_only",
      browser_auto_open: true,
      verbose_diagnostics: true,
      collect_raw_pages: false,
    },
  },
];

const DEFAULT_PROFILE_PRESET = RUNTIME_PROFILE_PRESETS[0];

type RuntimeFeedbackTone = "success" | "warning" | "danger";

interface RuntimeFeedback {
  tone: RuntimeFeedbackTone;
  text: string;
}

function providerLabel(provider: RuntimeProvider) {
  return provider === "openai_compatible" ? "兼容 OpenAI" : "MiniMax";
}

function listBrandPresets(provider: RuntimeProvider) {
  return RUNTIME_BRAND_PRESETS.filter((preset) => preset.provider === provider);
}

function findBrandPresetById(presetId: string) {
  return RUNTIME_BRAND_PRESETS.find((preset) => preset.id === presetId) || null;
}

function findBrandPresetForForm(form: RuntimeConfigDto) {
  const normalizedBaseUrl = (form.base_url || "").trim();
  if (!normalizedBaseUrl) {
    return null;
  }
  return (
    RUNTIME_BRAND_PRESETS.find(
      (preset) => preset.provider === form.provider && preset.base_url === normalizedBaseUrl,
    ) || null
  );
}

function blankBackupConfig(): RuntimeBackupConfigDto {
  return {
    label: "",
    base_url: "",
    api_key: "",
  };
}

function profileRecordToPreset(profile: RuntimeProfileRecord): RuntimeProfilePreset {
  const qualityMode = profile.quality_mode ?? (profile.profile_id === "dev_fallback" ? "fallback" : "premium");
  return {
    id: profile.profile_id,
    label: profile.label || profile.profile_id,
    description: profile.description || "",
    isDevFallback: qualityMode === "fallback" || profile.profile_id === "dev_fallback",
    isHighQuality: qualityMode === "premium",
    provider: profile.runtime_config.provider,
    timeout_seconds: profile.runtime_config.timeout_seconds ?? DEFAULT_TIMEOUT_SECONDS,
    llm_profile: {
      profile_id: profile.llm_profile?.profile_id || profile.profile_id,
      label: profile.llm_profile?.label || profile.label || profile.profile_id,
      provider: profile.llm_profile?.provider || profile.runtime_config.provider,
      model: profile.llm_profile?.model || profile.runtime_config.model,
      base_url: profile.llm_profile?.base_url || profile.runtime_config.base_url,
      quality_tier: profile.llm_profile?.quality_tier,
    },
    retrieval_profile: {
      profile_id: profile.retrieval_profile?.profile_id || profile.profile_id,
      label: profile.retrieval_profile?.label,
      primary_search_provider: profile.retrieval_profile?.primary_search_provider,
      fallback_search_providers: profile.retrieval_profile?.fallback_search_providers || [],
      reranker: profile.retrieval_profile?.reranker,
      extractor: profile.retrieval_profile?.extractor,
      writer_model: profile.retrieval_profile?.writer_model,
      official_domains: profile.retrieval_profile?.official_domains || [],
      negative_keywords: profile.retrieval_profile?.negative_keywords || [],
      alias_expansion: profile.retrieval_profile?.alias_expansion,
      official_source_bias: profile.retrieval_profile?.official_source_bias,
    },
    quality_policy: {
      profile_id: profile.quality_policy?.profile_id || profile.profile_id,
      min_report_claims: profile.quality_policy?.min_report_claims,
      min_formal_evidence: profile.quality_policy?.min_formal_evidence,
      min_formal_domains: profile.quality_policy?.min_formal_domains,
      require_official_coverage: profile.quality_policy?.require_official_coverage,
      auto_finalize: profile.quality_policy?.auto_finalize,
      auto_create_draft_on_delta: profile.quality_policy?.auto_create_draft_on_delta,
    },
    debug_policy: {
      auto_open_mode: profile.debug_policy?.auto_open_mode,
      browser_auto_open: profile.debug_policy?.browser_auto_open,
      verbose_diagnostics: profile.debug_policy?.verbose_diagnostics,
      collect_raw_pages: profile.debug_policy?.collect_raw_pages,
    },
  };
}

function getRuntimeProfilePresets(status?: RuntimeStatusRecord): RuntimeProfilePreset[] {
  if (status?.available_profiles?.length) {
    return status.available_profiles.map(profileRecordToPreset);
  }
  return RUNTIME_PROFILE_PRESETS;
}

function buildDefaultRuntimeForm(provider: RuntimeProvider): RuntimeConfigDto {
  const providerPreset =
    RUNTIME_PROFILE_PRESETS.find((preset) => preset.provider === provider) ||
    (provider === "openai_compatible" ? DEFAULT_PROFILE_PRESET : RUNTIME_PROFILE_PRESETS.find((preset) => preset.id === "dev_fallback")) ||
    DEFAULT_PROFILE_PRESET;
  return applyProfilePresetToForm(
    {
      profile_id: providerPreset.id,
      provider,
      base_url: PROVIDER_DEFAULTS[provider].base_url,
      model: PROVIDER_DEFAULTS[provider].model,
      api_key: "",
      timeout_seconds: providerPreset.timeout_seconds ?? PROVIDER_DEFAULTS[provider].timeout_seconds,
      backup_configs: [],
    },
    providerPreset,
  );
}

function cloneProfileFields(profile?: RuntimeLlmProfileDto | RuntimeRetrievalProfileDto | RuntimeQualityPolicyDto | RuntimeDebugPolicyDto) {
  if (!profile) {
    return undefined;
  }
  return { ...profile };
}

function applyProfilePresetToForm(form: RuntimeConfigDto, preset: RuntimeProfilePreset): RuntimeConfigDto {
  return {
    ...form,
    profile_id: preset.id,
    llm_profile: cloneProfileFields(preset.llm_profile) as RuntimeLlmProfileDto,
    retrieval_profile: cloneProfileFields(preset.retrieval_profile) as RuntimeRetrievalProfileDto,
    quality_policy: cloneProfileFields(preset.quality_policy) as RuntimeQualityPolicyDto,
    debug_policy: cloneProfileFields(preset.debug_policy) as RuntimeDebugPolicyDto,
  };
}

function cloneRuntimeConfig(config: RuntimeConfigDto): RuntimeConfigDto {
  return {
    ...config,
    llm_profile: cloneProfileFields(config.llm_profile) as RuntimeLlmProfileDto | undefined,
    retrieval_profile: cloneProfileFields(config.retrieval_profile) as RuntimeRetrievalProfileDto | undefined,
    quality_policy: cloneProfileFields(config.quality_policy) as RuntimeQualityPolicyDto | undefined,
    debug_policy: cloneProfileFields(config.debug_policy) as RuntimeDebugPolicyDto | undefined,
    backup_configs: (config.backup_configs || []).map((item) => ({
      label: item.label || "",
      base_url: item.base_url || "",
      api_key: item.api_key || "",
    })),
  };
}

function buildFormFromStatus(status: RuntimeStatusRecord, fallback?: RuntimeConfigDto): RuntimeConfigDto {
  const presets = getRuntimeProfilePresets(status);
  const base = fallback ? cloneRuntimeConfig(fallback) : buildDefaultRuntimeForm(status.provider);
  const resolvedConfig = cloneRuntimeConfig(status.resolved_runtime_config || status.runtime_config || {});
  const activePreset =
    presets.find((preset) => preset.id === status.selected_profile_id) ||
    presets.find((preset) => preset.id === resolvedConfig.profile_id) ||
    presets.find((preset) => preset.id === resolvedConfig.llm_profile?.profile_id) ||
    null;

  const nextForm: RuntimeConfigDto = {
    ...base,
    ...resolvedConfig,
    profile_id: status.selected_profile_id || resolvedConfig.profile_id || activePreset?.id || base.profile_id,
    provider: status.provider,
    base_url: status.base_url || resolvedConfig.base_url || PROVIDER_DEFAULTS[status.provider].base_url,
    model: status.model || resolvedConfig.model || PROVIDER_DEFAULTS[status.provider].model,
    timeout_seconds: status.timeout_seconds || resolvedConfig.timeout_seconds || PROVIDER_DEFAULTS[status.provider].timeout_seconds,
    backup_configs: (status.runtime_config?.backup_configs || status.backup_configs || []).map((item) => ({
      label: item.label || "",
      base_url: item.base_url,
      api_key: "",
    })),
    llm_profile: status.llm_profile || resolvedConfig.llm_profile || base.llm_profile,
    retrieval_profile: status.retrieval_profile || resolvedConfig.retrieval_profile || base.retrieval_profile,
    quality_policy: status.quality_policy || resolvedConfig.quality_policy || base.quality_policy,
    debug_policy: status.debug_policy || resolvedConfig.debug_policy || base.debug_policy,
  };

  if (activePreset) {
    return {
      ...applyProfilePresetToForm(nextForm, activePreset),
      profile_id: nextForm.profile_id,
      llm_profile: nextForm.llm_profile,
      retrieval_profile: nextForm.retrieval_profile,
      quality_policy: nextForm.quality_policy,
      debug_policy: nextForm.debug_policy,
    };
  }
  return nextForm;
}

function normalizeComparableRuntimeForm(form: RuntimeConfigDto) {
  return {
    profile_id: form.profile_id || form.llm_profile?.profile_id || "",
    provider: form.provider,
    base_url: (form.base_url || "").trim(),
    model: (form.model || "").trim(),
    api_key: (form.api_key || "").trim(),
    timeout_seconds: Number(form.timeout_seconds ?? DEFAULT_TIMEOUT_SECONDS),
    llm_profile: cloneProfileFields(form.llm_profile),
    retrieval_profile: cloneProfileFields(form.retrieval_profile),
    quality_policy: cloneProfileFields(form.quality_policy),
    debug_policy: cloneProfileFields(form.debug_policy),
    backup_configs: (form.backup_configs || []).map((item) => ({
      label: (item.label || "").trim(),
      base_url: (item.base_url || "").trim(),
      api_key: (item.api_key || "").trim(),
    })),
  };
}

function validateRuntimeForm(form: RuntimeConfigDto): string | null {
  if (!form.base_url?.trim()) {
    return "请填写主 API 地址。";
  }
  if (!form.model?.trim()) {
    return "请填写模型名。";
  }

  const timeoutSeconds = Number(form.timeout_seconds);
  if (!Number.isFinite(timeoutSeconds) || timeoutSeconds < 5 || timeoutSeconds > 180) {
    return "超时时间需在 5 到 180 秒之间。";
  }

  const primaryBaseUrl = form.base_url.trim();
  const seenBackupBaseUrls = new Set<string>();
  for (const [index, backup] of (form.backup_configs || []).entries()) {
    const baseUrl = backup.base_url.trim();
    if (!baseUrl) {
      return `备用连接 ${index + 1} 缺少 Base URL。`;
    }
    if (baseUrl === primaryBaseUrl) {
      return `备用连接 ${index + 1} 与主 API 地址重复。`;
    }
    if (seenBackupBaseUrls.has(baseUrl)) {
      return `备用连接 ${index + 1} 与前面的备用地址重复。`;
    }
    seenBackupBaseUrls.add(baseUrl);
  }

  return null;
}

export function RuntimeSettingsPage() {
  const queryClient = useQueryClient();
  const runtimeQuery = useQuery({
    queryKey: ["runtime-status"],
    queryFn: fetchRuntimeStatus,
    refetchInterval: 10000,
  });
  const [form, setForm] = useState<RuntimeConfigDto>(buildDefaultRuntimeForm("minimax"));
  const [providerDrafts, setProviderDrafts] = useState<Record<RuntimeProvider, RuntimeConfigDto>>({
    minimax: buildDefaultRuntimeForm("minimax"),
    openai_compatible: buildDefaultRuntimeForm("openai_compatible"),
  });
  const [initialized, setInitialized] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [feedback, setFeedback] = useState<RuntimeFeedback | null>(null);
  const runtimeProfilePresets = useMemo(() => getRuntimeProfilePresets(runtimeQuery.data), [runtimeQuery.data]);
  const activeProfilePreset = useMemo(
    () => runtimeProfilePresets.find((preset) => preset.id === (form.profile_id || form.llm_profile?.profile_id)) ?? null,
    [form, runtimeProfilePresets],
  );
  const selectedProfileId = form.profile_id || activeProfilePreset?.id || "custom";
  const manualOverrideTags = useMemo(() => {
    if (!activeProfilePreset) {
      return [];
    }
    const overrides: string[] = [];
    if (form.provider !== activeProfilePreset.provider) {
      overrides.push("服务商");
    }
    const normalizedBaseUrl = (form.base_url || "").trim();
    const presetBaseUrl = (activeProfilePreset.llm_profile?.base_url || "").trim();
    if (normalizedBaseUrl && presetBaseUrl && normalizedBaseUrl !== presetBaseUrl) {
      overrides.push("API 地址");
    }
    const normalizedModel = (form.model || "").trim();
    const presetModel = (activeProfilePreset.llm_profile?.model || "").trim();
    if (normalizedModel && presetModel && normalizedModel !== presetModel) {
      overrides.push("模型");
    }
    const presetTimeout = Number(activeProfilePreset.timeout_seconds ?? DEFAULT_TIMEOUT_SECONDS);
    const timeoutSeconds = Number(form.timeout_seconds ?? presetTimeout);
    if (!Number.isNaN(timeoutSeconds) && timeoutSeconds !== presetTimeout) {
      overrides.push("超时");
    }
    return overrides;
  }, [activeProfilePreset, form]);

  useEffect(() => {
    if (!runtimeQuery.data || initialized) {
      return;
    }
    const hydratedForm = buildFormFromStatus(runtimeQuery.data);
    setForm(hydratedForm);
    setProviderDrafts({
      minimax: hydratedForm.provider === "minimax" ? cloneRuntimeConfig(hydratedForm) : buildDefaultRuntimeForm("minimax"),
      openai_compatible:
        hydratedForm.provider === "openai_compatible" ? cloneRuntimeConfig(hydratedForm) : buildDefaultRuntimeForm("openai_compatible"),
    });
    setInitialized(true);
  }, [initialized, runtimeQuery.data]);

  const commitForm = (nextForm: RuntimeConfigDto) => {
    const normalizedNextForm = cloneRuntimeConfig(nextForm);
    setForm(normalizedNextForm);
    setProviderDrafts((current) => ({
      ...current,
      [normalizedNextForm.provider]: cloneRuntimeConfig(normalizedNextForm),
    }));
  };

  const handleProfilePresetChange = (presetId: string) => {
    const preset = runtimeProfilePresets.find((item) => item.id === presetId);
    if (!preset) {
      return;
    }
    const presetBaseUrl = preset.llm_profile.base_url ?? PROVIDER_DEFAULTS[preset.provider].base_url;
    const presetModel = preset.llm_profile.model ?? PROVIDER_DEFAULTS[preset.provider].model;
    const presetTimeout = preset.timeout_seconds ?? PROVIDER_DEFAULTS[preset.provider].timeout_seconds;
    commitForm(
      applyProfilePresetToForm(
        {
          ...cloneRuntimeConfig(form),
          provider: preset.provider,
          base_url: presetBaseUrl,
          model: presetModel,
          timeout_seconds: presetTimeout,
        },
        preset,
      ),
    );
    setFeedback(null);
  };

  const handleSave = async (replaceApiKey = false) => {
    const validationError = validateRuntimeForm(form);
    if (validationError) {
      setFeedback({ tone: "danger", text: validationError });
      return;
    }

    setSaving(true);
    setFeedback(null);
    try {
      const status = await saveRuntimeSettings({ runtime_config: cloneRuntimeConfig(form), replace_api_key: replaceApiKey });
      const savedForm = buildFormFromStatus(status);
      commitForm(savedForm);
      setFeedback({
        tone: "success",
        text: replaceApiKey && !form.api_key ? "已清空已保存的 API key。" : "服务配置已保存，新建研究会自动继承。",
      });
      await queryClient.invalidateQueries({ queryKey: ["runtime-status"] });
    } catch (error) {
      setFeedback({ tone: "danger", text: getApiErrorMessage(error, "保存服务配置失败。") });
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    const validationError = validateRuntimeForm(form);
    if (validationError) {
      setFeedback({ tone: "danger", text: validationError });
      return;
    }

    setValidating(true);
    setFeedback(null);
    try {
      const result = await validateRuntimeSettings(cloneRuntimeConfig(form));
      setFeedback({ tone: result.ok ? "success" : "warning", text: result.message });
    } catch (error) {
      setFeedback({ tone: "danger", text: getApiErrorMessage(error, "测试服务配置失败。") });
    } finally {
      setValidating(false);
    }
  };

  if (runtimeQuery.error) {
    return (
      <RequestStateCard
        title="服务配置加载失败"
        description={getApiErrorMessage(runtimeQuery.error, "无法读取当前服务配置。")}
        actionLabel="重试"
        onAction={() => {
          void runtimeQuery.refetch();
        }}
      />
    );
  }

  if (!runtimeQuery.data) {
    return <RequestStateCard title="正在加载服务配置" description="读取当前 API key、模型和浏览器能力。" loading />;
  }

  const status = runtimeQuery.data;
  const savedForm = buildFormFromStatus(status);
  const editingSavedProvider = form.provider === status.provider;
  const isDirty = JSON.stringify(normalizeComparableRuntimeForm(form)) !== JSON.stringify(normalizeComparableRuntimeForm(savedForm));
  const providerDefaults = PROVIDER_DEFAULTS[form.provider];
  const activeBrandPreset = findBrandPresetForForm(form);
  const availableBrandPresets = listBrandPresets(form.provider);
  const modelSuggestions = [
    ...new Set([
      form.model || "",
      ...(activeBrandPreset?.model_options || (form.provider === "openai_compatible" ? OPENAI_COMPAT_MODEL_OPTIONS : MINIMAX_MODEL_OPTIONS)),
    ].filter(Boolean)),
  ];
  const apiKeyPlaceholder =
    form.provider === "openai_compatible"
      ? editingSavedProvider && status.api_key_masked
        ? `当前已保存：${status.api_key_masked}`
        : activeBrandPreset
          ? `输入新的 ${activeBrandPreset.label} API key`
          : "输入新的兼容 OpenAI API Key"
      : editingSavedProvider && status.api_key_masked
        ? `当前已保存：${status.api_key_masked}`
        : "输入新的 MiniMax API key";
  const baseUrlHint =
    activeBrandPreset?.base_url_hint
      ? activeBrandPreset.base_url_hint
      : form.provider === "openai_compatible"
      ? "官方可用 `https://api.openai.com/v1`；自定义兼容地址可直接填 `https://aixj.vip`，系统会自动兼容 `/v1/chat/completions` 或 `/chat/completions`。"
      : "国内用户使用 `https://api.minimaxi.com/v1`，国际用户使用 `https://api.minimax.io/v1`。";
  const backupStatuses = editingSavedProvider ? status.backup_configs || [] : [];

  const updateBackupConfig = (index: number, patch: Partial<RuntimeBackupConfigDto>) => {
    commitForm({
      ...form,
      backup_configs: (form.backup_configs || []).map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)),
    });
  };

  const removeBackupConfig = (index: number) => {
    commitForm({
      ...form,
      backup_configs: (form.backup_configs || []).filter((_, itemIndex) => itemIndex !== index),
    });
  };

  const moveBackupConfig = (index: number, direction: "up" | "down") => {
    const backups = [...(form.backup_configs || [])];
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= backups.length) {
      return;
    }
    [backups[index], backups[targetIndex]] = [backups[targetIndex], backups[index]];
    commitForm({
      ...form,
      backup_configs: backups,
    });
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
      <Card className="space-y-5">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>服务设置</CardTitle>
            <Badge tone={isDirty ? "warning" : "success"}>{isDirty ? "有未保存修改" : "已同步到保存状态"}</Badge>
            <Badge>按账号隔离</Badge>
          </div>
          <CardDescription>这里保存的是当前账号自己的服务地址、API Key 和模型。切换到其他账号后互不影响，后续新建研究也会继承当前账号这套配置。</CardDescription>
        </div>

        <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-slate-900">策略预设</p>
              <p className="text-xs text-slate-500">
                预设会同步 LLM / 检索 / 质量 / 调试策略。手工修改的字段会被标记为「手动覆盖」，可在下方看到。
              </p>
            </div>
            <div className="min-w-[220px]">
              <Label htmlFor="runtime-profile">当前预设</Label>
              <Select id="runtime-profile" value={selectedProfileId} onChange={(event) => handleProfilePresetChange(event.target.value)}>
                {runtimeProfilePresets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.label}
                  </option>
                ))}
                {!activeProfilePreset ? <option value="custom">自定义策略</option> : null}
              </Select>
            </div>
          </div>
          {activeProfilePreset ? (
            <div className="flex flex-wrap gap-2">
              {activeProfilePreset.isHighQuality ? <Badge tone="success">高质量</Badge> : null}
              {activeProfilePreset.isDevFallback ? <Badge tone="warning">开发兜底</Badge> : null}
              {activeProfilePreset.quality_policy?.auto_finalize ? (
                <Badge tone="success">自动转稳定版</Badge>
              ) : (
                <Badge tone="default">需手动转稳定版</Badge>
              )}
              {activeProfilePreset.quality_policy?.auto_create_draft_on_delta ? (
                <Badge tone="default">补研自动起草</Badge>
              ) : (
                <Badge tone="default">补研需手动起草</Badge>
              )}
            </div>
          ) : null}
          <p className="text-sm text-slate-600">
            {activeProfilePreset
              ? manualOverrideTags.length
                ? `当前手动覆盖了：${manualOverrideTags.join("、")}，其余字段沿用预设策略。`
                : "当前未覆盖预设字段，所有策略均由预设控制。"
              : "当前处于自定义模式，下方字段全部由你手动掌控；保存后会作为新的默认策略。"}
          </p>
          {activeProfilePreset ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-slate-100 bg-white p-3">
                <p className="text-xs text-slate-500">LLM / 模型</p>
                <p className="font-medium text-slate-900">{activeProfilePreset.llm_profile.label}</p>
                <p className="text-sm text-slate-700">{activeProfilePreset.llm_profile.model}</p>
                <p className="text-xs text-slate-500">{activeProfilePreset.llm_profile.base_url ?? "使用服务商默认入口"}</p>
              </div>
              <div className="rounded-2xl border border-slate-100 bg-white p-3">
                <p className="text-xs text-slate-500">检索</p>
                <p className="font-medium text-slate-900">{activeProfilePreset.retrieval_profile.primary_search_provider}</p>
                <p className="text-sm text-slate-700">{activeProfilePreset.retrieval_profile.reranker}</p>
                <p className="text-xs text-slate-500">
                  {activeProfilePreset.retrieval_profile.official_domains?.length
                    ? `${activeProfilePreset.retrieval_profile.official_domains.length} 个官方域名`
                    : "未指定官方域名"}
                </p>
              </div>
              <div className="rounded-2xl border border-slate-100 bg-white p-3">
                <p className="text-xs text-slate-500">质量门槛</p>
                <p className="text-sm text-slate-700">结论 ≥ {activeProfilePreset.quality_policy.min_report_claims}</p>
                <p className="text-sm text-slate-700">证据 ≥ {activeProfilePreset.quality_policy.min_formal_evidence}</p>
                <p className="text-sm text-slate-700">域名 ≥ {activeProfilePreset.quality_policy.min_formal_domains}</p>
              </div>
              <div className="rounded-2xl border border-slate-100 bg-white p-3">
                <p className="text-xs text-slate-500">调试与浏览器</p>
                <p className="text-sm text-slate-700">
                  浏览器：{activeProfilePreset.debug_policy.browser_auto_open ? "可调试" : "仅抓取模式"}
                </p>
                <p className="text-xs text-slate-500">
                  {activeProfilePreset.debug_policy.auto_open_mode === "always"
                    ? "始终开启浏览器"
                    : activeProfilePreset.debug_policy.auto_open_mode === "debug_only"
                      ? "仅失败时自动打开"
                      : "浏览器关闭"}
                </p>
              </div>
            </div>
          ) : (
            <div className="rounded-2xl border border-slate-100 bg-white px-3 py-2 text-sm text-slate-600">
              当前为自定义模式，表单的每一项都可独立控制；若想回到预设，可重新从上方选择。
            </div>
          )}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <Label htmlFor="runtime-provider">服务商</Label>
            <Select
              id="runtime-provider"
              value={form.provider}
              onChange={(event) => {
                const provider = event.target.value as RuntimeProvider;
                const nextDrafts = {
                  ...providerDrafts,
                  [form.provider]: cloneRuntimeConfig(form),
                };
                setProviderDrafts(nextDrafts);
                setForm(cloneRuntimeConfig(nextDrafts[provider] || buildDefaultRuntimeForm(provider)));
                setFeedback(null);
              }}
            >
              <option value="minimax">MiniMax</option>
              <option value="openai_compatible">OpenAI 兼容接口</option>
            </Select>
          </div>
          <div>
            <Label htmlFor="runtime-brand">品牌/平台预设</Label>
            <Select
              id="runtime-brand"
              value={activeBrandPreset?.id || "custom"}
              onChange={(event) => {
                const presetId = event.target.value;
                if (presetId === "custom") {
                  return;
                }
                const preset = findBrandPresetById(presetId);
                if (!preset) {
                  return;
                }
                commitForm({
                  ...form,
                  provider: preset.provider,
                  base_url: preset.base_url,
                  model: preset.model,
                });
                setFeedback(null);
              }}
            >
              <option value="custom">自定义</option>
              {availableBrandPresets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.label}
                </option>
              ))}
            </Select>
            <p className="mt-2 text-sm text-slate-500">
              {activeBrandPreset ? activeBrandPreset.description : "保留自定义 Base URL 和模型，适合私有网关、代理或聚合平台。"}
            </p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-[1.2fr_0.8fr]">
          <div>
            <Label htmlFor="runtime-model">模型</Label>
            <Input
              id="runtime-model"
              value={form.model}
              placeholder="例如：gpt-5.4 / deepseek-chat / qwen3.6-plus"
              onChange={(event) => commitForm({ ...form, model: event.target.value })}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {modelSuggestions.map((model) => (
                <Button
                  key={model}
                  type="button"
                  variant={model === form.model ? "secondary" : "ghost"}
                  onClick={() => commitForm({ ...form, model })}
                >
                  {model}
                </Button>
              ))}
            </div>
          </div>
          <div>
            <Label htmlFor="runtime-timeout">切换超时（秒）</Label>
            <Input
              id="runtime-timeout"
              type="number"
              min={5}
              max={180}
              step={1}
              value={form.timeout_seconds ?? ""}
              onChange={(event) => {
                const nextValue = event.target.value.trim();
                commitForm({
                  ...form,
                  timeout_seconds: nextValue ? Number(nextValue) : undefined,
                });
              }}
            />
          </div>
        </div>

        <div>
          <Label htmlFor="runtime-base-url">API 地址</Label>
          <Input id="runtime-base-url" value={form.base_url} onChange={(event) => commitForm({ ...form, base_url: event.target.value })} />
          <p className="mt-2 text-sm text-slate-500">{baseUrlHint}</p>
          <p className="mt-2 text-sm text-slate-500">
            当前单条线路最多等待 {form.timeout_seconds ?? providerDefaults.timeout_seconds} 秒；超时后会按下面的优先级自动切到下一条连接。
          </p>
          {form.base_url === providerDefaults.base_url ? null : (
            <p className="mt-2 text-xs text-slate-400">{`当前 provider 默认地址：${providerDefaults.base_url}`}</p>
          )}
        </div>

        <div>
          <Label htmlFor="runtime-api-key">API Key</Label>
          <Input
            id="runtime-api-key"
            placeholder={apiKeyPlaceholder}
            type="password"
            value={form.api_key ?? ""}
            onChange={(event) => commitForm({ ...form, api_key: event.target.value })}
          />
          <p className="mt-2 text-sm text-slate-500">
            留空保存时会保留当前已保存的 key；点“清空已保存 Key”才会真正清掉。
          </p>
        </div>

        <div className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <Label>备用 API 连接</Label>
              <p className="mt-1 text-sm text-slate-500">
                当主连接超时或报错时，系统会按顺序尝试这些备用连接。你可以上下调整优先级。备用连接默认沿用主模型；如果 API key 留空，会沿用主 key。
              </p>
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={() => commitForm({ ...form, backup_configs: [...(form.backup_configs || []), blankBackupConfig()] })}
            >
              添加备用连接
            </Button>
          </div>

          {(form.backup_configs || []).length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-4 text-sm text-slate-500">
              当前没有配置备用连接。建议至少加 1 条备用 API 地址，避免单线路卡住时整次研究挂起。
            </div>
          ) : null}

          {(form.backup_configs || []).map((backup, index) => {
            const savedBackup = backupStatuses[index];
            const backupApiKeyPlaceholder =
              savedBackup?.api_key_masked && !savedBackup.uses_primary_api_key
                ? `当前已保存：${savedBackup.api_key_masked}`
                : "留空则沿用主 API key";
            return (
              <div key={`${backup.base_url || "backup"}-${index}`} className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-slate-900">{`备用连接 ${index + 1}`}</p>
                    <p className="text-xs text-slate-500">{`触发顺序：第 ${index + 1} 优先级`}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button disabled={index === 0} type="button" variant="ghost" onClick={() => moveBackupConfig(index, "up")}>
                      上移
                    </Button>
                    <Button
                      disabled={index === (form.backup_configs || []).length - 1}
                      type="button"
                      variant="ghost"
                      onClick={() => moveBackupConfig(index, "down")}
                    >
                      下移
                    </Button>
                    <Button type="button" variant="ghost" onClick={() => removeBackupConfig(index)}>
                      删除
                    </Button>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <Label htmlFor={`backup-label-${index}`}>备注</Label>
                    <Input
                      id={`backup-label-${index}`}
                      placeholder="例如：AIXJ 备用 / 海外直连"
                      value={backup.label || ""}
                      onChange={(event) => updateBackupConfig(index, { label: event.target.value })}
                    />
                  </div>
                  <div>
                    <Label htmlFor={`backup-api-key-${index}`}>备用 API Key</Label>
                    <Input
                      id={`backup-api-key-${index}`}
                      type="password"
                      placeholder={backupApiKeyPlaceholder}
                      value={backup.api_key || ""}
                      onChange={(event) => updateBackupConfig(index, { api_key: event.target.value })}
                    />
                  </div>
                </div>
                <div>
                  <Label htmlFor={`backup-base-url-${index}`}>备用 Base URL</Label>
                  <Input
                    id={`backup-base-url-${index}`}
                    placeholder={form.provider === "openai_compatible" ? "https://your-backup-gateway.example" : "https://api.minimax.io/v1"}
                    value={backup.base_url}
                    onChange={(event) => updateBackupConfig(index, { base_url: event.target.value })}
                  />
                </div>
                <p className="text-xs text-slate-500">
                  {savedBackup
                    ? savedBackup.uses_primary_api_key
                      ? "当前这条备用线会复用主 API key。"
                      : "当前这条备用线已保存独立 API key；留空保存会继续保留它。"
                    : "新添加的备用连接如果不填 API key，会直接复用主 key。"}
                </p>
              </div>
            );
          })}
        </div>

        <div className="flex flex-wrap gap-3">
          <Button disabled={saving} onClick={() => void handleSave(false)} type="button">
            {saving ? "保存中..." : "保存配置"}
          </Button>
          <Button disabled={validating} onClick={() => void handleValidate()} type="button" variant="secondary">
            {validating ? "测试中..." : "测试连接"}
          </Button>
          <Button
            disabled={!isDirty && !form.api_key?.trim()}
            onClick={() => {
              setForm(cloneRuntimeConfig(savedForm));
              setProviderDrafts((current) => ({
                ...current,
                [savedForm.provider]: cloneRuntimeConfig(savedForm),
              }));
              setFeedback({ tone: "warning", text: "已恢复为当前已保存的服务配置。" });
            }}
            type="button"
            variant="ghost"
          >
            恢复已保存配置
          </Button>
          <Button disabled={saving} onClick={() => void handleSave(true)} type="button" variant="ghost">
            清空已保存 Key
          </Button>
        </div>
        {feedback ? (
          <p
            className={`text-sm ${
              feedback.tone === "success" ? "text-emerald-700" : feedback.tone === "warning" ? "text-amber-700" : "text-rose-700"
            }`}
          >
            {feedback.text}
          </p>
        ) : null}
      </Card>

      <div className="space-y-6">
        <Card className="space-y-4">
          <div>
            <CardTitle>当前状态</CardTitle>
            <CardDescription>这里显示当前账号新研究默认会继承的服务能力。</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={status.configured ? "success" : "warning"}>{status.configured ? "已配置" : "未配置"}</Badge>
            <Badge>{providerLabel(status.provider)}</Badge>
            <Badge>{status.model}</Badge>
            <Badge>{`${status.timeout_seconds}s 超时切换`}</Badge>
            <Badge>{formatBrowserMode(status.browser_mode)}</Badge>
            <Badge>{formatRuntimeSource(status.source)}</Badge>
            <Badge>{`备选 ${status.backup_count ?? 0}`}</Badge>
          </div>
          {status.provider !== form.provider ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              你当前正在编辑 {providerLabel(form.provider)} 草稿，右侧状态仍显示真正已保存并会被新任务继承的 {providerLabel(status.provider)} 配置。
            </div>
          ) : null}
          <div className="space-y-2 text-sm text-slate-600">
            <p>服务商：{providerLabel(status.provider)}</p>
            <p>API 地址：{status.base_url}</p>
            <p>当前活跃线路：{status.active_base_url ?? status.base_url}</p>
            <p>切换超时：{status.timeout_seconds} 秒</p>
            <p>API Key：{status.api_key_masked ?? "未保存"}</p>
            <p>LLM 状态：{status.validation_message}</p>
            <p>浏览器能力：{status.browser_available ? "可调用本地浏览器打开器" : "仅静态抓取"}</p>
            {(status.backup_configs || []).length > 0 ? (
              <div className="rounded-2xl border border-slate-100 bg-slate-50 p-3">
                <p className="font-medium text-slate-800">备用连接</p>
                <div className="mt-2 space-y-2">
                  {(status.backup_configs || []).map((backup, index) => (
                    <div key={`${backup.base_url}-${index}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm text-slate-800">{backup.label || `备用连接 ${index + 1}`}</p>
                        <Badge tone={backup.is_active ? "success" : undefined}>
                          {backup.is_active ? "当前活跃" : `优先级 ${backup.priority}`}
                        </Badge>
                      </div>
                      <p className="text-xs text-slate-500">{backup.base_url}</p>
                      <p className="text-xs text-slate-500">
                        {backup.uses_primary_api_key ? "沿用主 API key" : `独立 API key：${backup.api_key_masked ?? "已配置"}`}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </Card>

        <Card className="space-y-4">
          <div>
            <CardTitle>使用说明</CardTitle>
            <CardDescription>这里保存的是当前账号默认服务配置，不会回写已经创建的历史任务。</CardDescription>
          </div>
          <div className="space-y-3 text-sm text-slate-600">
            <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">新任务会快照当前配置，保证后续补研和成文都沿用同一套模型配置。</div>
            <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">每个账号的 API Key、Base URL 和模型互相隔离。切换到其他账号后，只会看到对方自己的配置，不会共用。</div>
            <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">如果当前 key 无效，研究仍可在 deterministic fallback 模式下运行，但报告质量会明显下降。</div>
            <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">这页刷新后会继续显示已保存配置，不会再退回默认模型说明。</div>
            <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">如果你用的是代理或聚合平台，建议先选 `OpenAI 兼容接口`，再从上面的“品牌/平台预设”开始，最后按你自己的模型名微调。</div>
            <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">如果某条线路会卡住，可以把同 provider 的其他入口填进备用连接。系统会优先记住最近成功的线路，并在失败后暂时降低故障线路优先级。</div>
          </div>
        </Card>
      </div>
    </div>
  );
}
