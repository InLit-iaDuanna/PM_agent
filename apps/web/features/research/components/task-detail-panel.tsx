"use client";

import { useState } from "react";
import { ExternalLink, Globe2, ScanSearch, Sparkles, TerminalSquare } from "lucide-react";

import type {
  ResearchJobRecord,
  ResearchQuerySummaryRecord,
  ResearchRoundRecord,
  SearchProviderAttemptRecord,
} from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, ProgressBar } from "@pm-agent/ui";

import { getApiErrorMessage, openTaskSource } from "../../../lib/api-client";
import { useResearchUiStore } from "../store/ui-store";
import { formatBrowserMode, taskStatusLabel, taskStatusTone } from "./research-ui-utils";

const COVERAGE_TAG_LABELS: Record<string, string> = {
  official: "官网/一手信息",
  analysis: "第三方分析",
  community: "用户反馈",
  comparison: "竞品对比",
  pricing: "定价信息",
};

const SKILL_THEME_LABELS: Record<string, string> = {
  market_intel: "市场情报",
  voice_of_customer: "用户声音",
  competition: "竞品格局",
  experience: "体验拆解",
  pricing: "定价策略",
  channels: "增长渠道",
  decision: "决策支持",
};

const SKILL_PACK_LABELS: Record<string, string> = {
  "source-triangulation": "交叉验证",
  "coverage-tracking": "覆盖跟踪",
  "decision-memo": "决策摘要",
  "market-sizing-lite": "规模估算",
  "trend-triangulation": "趋势交叉验证",
  "benchmark-scouting": "标杆扫描",
  "jtbd-extraction": "任务场景提炼",
  "pain-point-ranking": "痛点排序",
  "voice-snippet-capture": "用户原声摘录",
  "review-clustering": "评论聚类",
  "voice-of-customer": "用户声音",
  "signal-polarity": "口碑倾向判断",
  "competitive-mapping": "竞品映射",
  "segment-layering": "细分分层",
  "positioning-diff": "定位差异",
  "feature-diffing": "功能差异",
  "flow-teardown": "流程拆解",
  "friction-mapping": "摩擦点梳理",
  "pricing-benchmarking": "定价对标",
  "packaging-analysis": "套餐结构分析",
  "value-metric-check": "价值指标检查",
  "channel-diagnostics": "渠道诊断",
  "distribution-mapping": "分发路径映射",
  "growth-loop-check": "增长循环检查",
  "conversion-risk-review": "转化风险审视",
  "launch-risk-audit": "发布风险审计",
  "channel-readiness": "渠道准备度",
  "positioning-check": "定位检查",
  "opportunity-ranking": "机会排序",
  "execution-risk-audit": "执行风险审视",
  "decision-briefing": "决策简报",
};

const SEARCH_PROVIDER_LABELS: Record<string, string> = {
  bing: "Bing HTML",
  "bing-rss": "Bing RSS",
  brave: "Brave",
  duckduckgo: "DuckDuckGo",
  preferred_domain_seed: "官方补种",
  topic_exemplar: "题材补种",
};

const SEARCH_PROVIDER_STATUS_LABELS: Record<string, string> = {
  results: "命中结果",
  empty: "无结果",
  unavailable: "暂不可用",
  error: "执行异常",
  skipped_backoff: "冷却跳过",
};

const SEARCH_PROVIDER_REASON_LABELS: Record<string, string> = {
  cooldown: "冷却跳过",
  timeout: "超时",
  challenge: "挑战页/风控",
  parser_mismatch: "解析失配",
  request_error: "请求异常",
  http_429: "429 限流",
  http_403: "403 拒绝",
  http_451: "451 限制",
  unavailable: "暂不可用",
};

function formatCoverageTag(tag: unknown) {
  const normalized = String(tag || "").trim();
  return COVERAGE_TAG_LABELS[normalized] ?? normalized;
}

function formatSkillTheme(theme: unknown) {
  const normalized = String(theme || "").trim();
  return SKILL_THEME_LABELS[normalized] ?? normalized;
}

function formatSkillPack(pack: string) {
  return SKILL_PACK_LABELS[pack] ?? pack.replace(/[-_]/g, " ");
}

function formatSearchProvider(provider: unknown) {
  const normalized = String(provider || "").trim().toLowerCase();
  return SEARCH_PROVIDER_LABELS[normalized] ?? (normalized || "provider");
}

function formatSearchProviderStatus(status: unknown) {
  const normalized = String(status || "").trim().toLowerCase();
  return SEARCH_PROVIDER_STATUS_LABELS[normalized] ?? (normalized || "未知状态");
}

function formatSearchProviderReason(reason: unknown) {
  const normalized = String(reason || "").trim().toLowerCase();
  return SEARCH_PROVIDER_REASON_LABELS[normalized] ?? (normalized || "未知原因");
}

function formatOrchestrationNotes(notes?: string) {
  return String(notes || "")
    .replace(/^Workflow command:\s*/i, "研究路径：")
    .replace(/\.?\s*Focus:\s*/i, "。重点：")
    .trim();
}

function browserModeLabel(mode?: string) {
  const normalized = String(mode || "").trim().toLowerCase();
  if (!normalized || normalized === "unavailable") {
    return "仅查看抓取结果";
  }
  return formatBrowserMode(normalized);
}

function browserModeHint(mode?: string) {
  if (mode === "opencli") {
    return "如需核对原文，可直接在浏览器中打开当前来源。";
  }
  if (mode === "mac-open" || mode === "xdg-open") {
    return "当前会通过系统浏览器打开原文页面。";
  }
  return "当前仅保留抓取结果和搜索摘要，可继续查看已收集内容。";
}

function logLevelLabel(level?: string) {
  if (level === "error") return "错误";
  if (level === "warning") return "警告";
  return "信息";
}

function roundStatusLabel(round: ResearchRoundRecord) {
  return round.completed_at ? "已完成" : "进行中";
}

function roundStatusTone(round: ResearchRoundRecord) {
  return round.completed_at ? "success" : "warning";
}

function roundTitle(round: ResearchRoundRecord, fallbackIndex: number) {
  if (round.label?.trim()) {
    return round.label;
  }
  const waveNumber = typeof round.wave === "number" ? round.wave : fallbackIndex + 1;
  return `第 ${waveNumber} 轮搜索`;
}

function roundDiagnosticItems(round: ResearchRoundRecord) {
  const diagnostics = round.diagnostics ?? {};
  const items = [
    { key: "admitted", label: "纳入证据", value: diagnostics.admitted, tone: "success" as const },
    { key: "fetch_fallbacks", label: "保留摘要", value: diagnostics.fetch_fallbacks, tone: "warning" as const },
    { key: "rejected", label: "未纳入", value: diagnostics.rejected, tone: "warning" as const },
    { key: "low_signal", label: "低相关跳过", value: diagnostics.low_signal, tone: "warning" as const },
    { key: "duplicates", label: "重复去重", value: diagnostics.duplicates, tone: "default" as const },
    { key: "host_quota", label: "同站点已够", value: diagnostics.host_quota, tone: "default" as const },
    { key: "search_errors", label: "搜索异常", value: diagnostics.search_errors, tone: "danger" as const },
    { key: "browser_opens", label: "打开原文", value: diagnostics.browser_opens, tone: "default" as const },
  ];
  return items.filter((item) => Number(item.value || 0) > 0);
}

const RETENTION_REASON_META = {
  lowSignal: {
    label: "结果偏题或信息太泛",
    shortLabel: "低相关筛掉",
    tone: "warning" as const,
    helper: "搜索引擎有返回，但标题/摘要和任务主题不够贴，或信息量太弱。",
  },
  rejected: {
    label: "正文不够支撑判断",
    shortLabel: "正文核验未过",
    tone: "warning" as const,
    helper: "页面抓到正文后仍然偏营销、偏空泛，没沉淀成可引用依据。",
  },
  hostQuota: {
    label: "同站点结果被限流",
    shortLabel: "同站点已够",
    tone: "default" as const,
    helper: "为了保证域名多样性，系统不会让单一站点吃掉太多名额。",
  },
  duplicates: {
    label: "搜索结果重复",
    shortLabel: "重复去重",
    tone: "default" as const,
    helper: "不同搜索词命中了同一页面，系统只会保留一份。",
  },
  negativeKeywordBlocks: {
    label: "被负例词主动拦截",
    shortLabel: "负例词拦截",
    tone: "warning" as const,
    helper: "命中了运行时配置中的负例词，被系统直接排除。",
  },
  fetchFallbacks: {
    label: "原文受限，仅保留摘要",
    shortLabel: "原文抓取受限",
    tone: "warning" as const,
    helper: "页面正文抓不到时会先保留摘要，避免整轮研究卡住。",
  },
  searchErrors: {
    label: "搜索源一度异常",
    shortLabel: "搜索异常",
    tone: "danger" as const,
    helper: "搜索源超时、限流或临时不可用，系统已自动继续后续检索。",
  },
};

type RetentionReasonKey = keyof typeof RETENTION_REASON_META;

function topRetentionReasons(reasonCounts: Record<RetentionReasonKey, number>) {
  return (Object.keys(RETENTION_REASON_META) as RetentionReasonKey[])
    .map((key) => ({
      key,
      count: Number(reasonCounts[key] || 0),
      ...RETENTION_REASON_META[key],
    }))
    .filter((item) => item.count > 0)
    .sort((left, right) => right.count - left.count);
}

function formatRetentionSummary({
  totalSearchResults,
  visitedPageCount,
  sourceCount,
  uniqueDomainCount,
  topReasons,
  runningQueryCount,
}: {
  totalSearchResults: number;
  visitedPageCount: number;
  sourceCount: number;
  uniqueDomainCount: number;
  topReasons: Array<{ key: RetentionReasonKey; count: number; label: string }>;
  runningQueryCount: number;
}) {
  if (totalSearchResults <= 0 && runningQueryCount > 0) {
    return "这项任务还在继续跑搜索，当前先不用急着判断来源够不够。";
  }
  if (totalSearchResults <= 0 && sourceCount > 0) {
    return `外部搜索结果暂时还不稳定，但系统仍通过直达官网/种子来源保留了 ${sourceCount} 条依据。当前来源偏少，更像是搜索源候选不足，而不只是筛选过严。`;
  }
  if (totalSearchResults <= 0) {
    return "当前还没有拿回足够多的搜索结果，系统仍在继续改写关键词和补搜。";
  }
  const headline = `这一任务共拿回 ${totalSearchResults} 个搜索结果，实际核对 ${visitedPageCount} 个页面，最终保留 ${sourceCount} 条可引用依据，覆盖 ${uniqueDomainCount} 个独立域名。`;
  if (!topReasons.length) {
    return `${headline} 当前没有明显的单一阻塞项，更多是随着后续轮次继续补齐来源多样性。`;
  }
  const topLine = topReasons
    .slice(0, 3)
    .map((item) => `${item.label} ${item.count} 次`)
    .join("，");
  return `${headline} 来源偏少主要是因为：${topLine}。`;
}

function roundFunnelSummary(round: ResearchRoundRecord) {
  const diagnostics = round.diagnostics ?? {};
  const resultCount = Number(round.result_count || 0);
  const reviewedCount =
    Number(diagnostics.admitted || 0) +
    Number(diagnostics.rejected || 0) +
    Number(diagnostics.fetch_fallbacks || 0);
  const evidenceCount = Number(round.evidence_added || 0);
  if (!resultCount && !reviewedCount && !evidenceCount) {
    return "";
  }
  const parts = [`搜索返回 ${resultCount}`];
  if (reviewedCount > 0) {
    parts.push(`重点核对 ${reviewedCount}`);
  }
  parts.push(`最终沉淀 ${evidenceCount}`);
  return parts.join(" -> ");
}

function aggregateProviderAttempts(attempts: SearchProviderAttemptRecord[]) {
  const grouped = new Map<
    string,
    {
      provider: string;
      total: number;
      results: number;
      empty: number;
      failures: number;
      skippedBackoff: number;
      topReasons: string[];
    }
  >();
  for (const attempt of attempts) {
    const provider = String(attempt.provider || "").trim().toLowerCase();
    if (!provider) continue;
    const current =
      grouped.get(provider) ??
      {
        provider,
        total: 0,
        results: 0,
        empty: 0,
        failures: 0,
        skippedBackoff: 0,
        topReasons: [],
      };
    current.total += 1;
    const status = String(attempt.status || "").trim().toLowerCase();
    if (status === "results") current.results += 1;
    else if (status === "empty") current.empty += 1;
    else if (status === "skipped_backoff") current.skippedBackoff += 1;
    else if (status === "unavailable" || status === "error") current.failures += 1;
    const reason = String(attempt.reason_code || attempt.reason || "").trim();
    if (reason && !current.topReasons.includes(reason)) {
      current.topReasons.push(reason);
    }
    grouped.set(provider, current);
  }
  return Array.from(grouped.values()).sort((left, right) => right.total - left.total);
}

function formatMissingCoverage(missingTags: unknown[]) {
  const normalized = missingTags.map((item) => formatCoverageTag(item)).filter(Boolean);
  if (!normalized.length) {
    return "当前覆盖基本满足";
  }
  return `仍需补充 ${normalized.slice(0, 2).join(" / ")}`;
}

function querySummaryTone(summary: ResearchQuerySummaryRecord) {
  if (summary.status === "evidence_added") return "success";
  if (summary.status === "search_error") return "danger";
  if (summary.effective_query || (summary.retry_attempts ?? []).length) return "default";
  return "warning";
}

function querySummaryLabel(summary: ResearchQuerySummaryRecord) {
  if (summary.status === "evidence_added") {
    return `+${summary.evidence_added ?? 0} 依据`;
  }
  if (summary.status === "zero_results") {
    return "没搜到合适结果";
  }
  if (summary.status === "search_error") {
    return "搜索异常";
  }
  if (summary.status === "running") {
    return "执行中";
  }
  if (summary.effective_query && (summary.search_result_count ?? 0) > 0) {
    return "已继续补搜";
  }
  if ((summary.retry_attempts ?? []).length) {
    return "已系统续查";
  }
  return "结果不够可用";
}

function roundQuerySummaryText(round: ResearchRoundRecord) {
  const querySummaries = round.query_summaries ?? [];
  if (!querySummaries.length) {
    return "本轮关键词已生成，系统正在逐条执行。";
  }
  const evidenceCount = querySummaries.filter((item) => item.status === "evidence_added").length;
  const zeroResultCount = querySummaries.filter((item) => item.status === "zero_results").length;
  const filteredCount = querySummaries.filter((item) => item.status === "filtered").length;
  const errorCount = querySummaries.filter((item) => item.status === "search_error").length;
  const runningCount = querySummaries.filter((item) => item.status === "running").length;
  const retriedCount = querySummaries.filter((item) => Boolean(item.effective_query) || (item.retry_attempts ?? []).length > 0).length;
  const parts = [];
  if (evidenceCount) parts.push(`${evidenceCount} 条整理成可引用依据`);
  if (filteredCount) parts.push(`${filteredCount} 条未纳入`);
  if (zeroResultCount) parts.push(`${zeroResultCount} 条待补结果`);
  if (errorCount) parts.push(`${errorCount} 条搜索异常`);
  if (runningCount) parts.push(`${runningCount} 条继续检索`);
  if (retriedCount) parts.push(`${retriedCount} 条已系统续查`);
  return parts.length ? `本轮已跑 ${querySummaries.length} 条搜索词：${parts.join("，")}。` : "本轮关键词正在执行。";
}

function retryStatusLabel(status?: string) {
  if (status === "results_found") return "已找到结果";
  if (status === "search_error") return "重试异常";
  return "未命中";
}

function queryReasonLabel(query: string) {
  const lowered = String(query || "").toLowerCase();
  if (lowered.startsWith("site:") || /official|官网|docs|文档|help|support/.test(lowered)) {
    return "补官网/一手信息";
  }
  if (/reddit|forum|community|社区|论坛|reviews|评价|评测|g2|capterra/.test(lowered)) {
    return "补用户反馈";
  }
  if (/comparison|alternatives|vs|对比|替代|竞品/.test(lowered)) {
    return "补竞品对比";
  }
  if (/benchmark|analysis|report|趋势|市场|案例|调研/.test(lowered)) {
    return "补趋势分析";
  }
  return "继续收敛主题";
}

function hasRetryActivity(summary: ResearchQuerySummaryRecord) {
  return Boolean(summary.effective_query) || (summary.retry_attempts ?? []).length > 0 || (summary.retry_queries ?? []).length > 0;
}

function candidateLeadCount(
  task: ResearchJobRecord["tasks"][number],
  querySummaries: ResearchQuerySummaryRecord[],
) {
  const visited = (task.visited_sources ?? []).length;
  const queryHits = querySummaries.filter((summary) => Number(summary.search_result_count || 0) > 0).length;
  return Math.max(visited, queryHits);
}

function querySummaryNarrative(summary: ResearchQuerySummaryRecord) {
  const resultCount = Number(summary.search_result_count || 0);
  const evidenceAdded = Number(summary.evidence_added || 0);
  const retryCount = (summary.retry_attempts ?? []).length || (summary.retry_queries ?? []).length;

  if (summary.status === "evidence_added") {
    return `这条关键词带回了 ${resultCount} 个候选结果，其中整理出 ${evidenceAdded} 条可引用依据。`;
  }
  if (summary.effective_query && summary.effective_query !== summary.query) {
    if (resultCount > 0) {
      return `原词不够稳定，系统已改写为“${summary.effective_query}”继续搜索，并拿回 ${resultCount} 个结果。`;
    }
    return `原词不够稳定，系统已改写为“${summary.effective_query}”继续搜索。`;
  }
  if (summary.status === "zero_results") {
    return retryCount > 0 ? `原词没有命中可用结果，系统又补试了 ${retryCount} 个更短版本。` : "这条关键词暂时没有命中可用结果。";
  }
  if (summary.status === "search_error") {
    return retryCount > 0 ? `搜索一度异常，系统已自动继续尝试其他改写版本。` : "这条关键词搜索时遇到异常，系统会自动继续后续检索。";
  }
  if (summary.status === "running") {
    return "系统正在执行这条关键词，结果稍后会自动补进。";
  }
  if (retryCount > 0) {
    return `系统已经尝试过 ${retryCount} 个续查版本，但这一轮还没有整理出可引用依据。`;
  }
  if (resultCount > 0) {
    return `这条关键词拿回了 ${resultCount} 个结果，但当前还没有整理出可引用依据。`;
  }
  return "这条关键词还没有沉淀出可引用依据。";
}

function searchMetricPalette(emphasis: "default" | "success" | "warning") {
  if (emphasis === "success") {
    return "border-emerald-200 bg-emerald-50/80";
  }
  if (emphasis === "warning") {
    return "border-amber-200 bg-amber-50/80";
  }
  return "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)]";
}

function SearchMetricCard({
  label,
  value,
  helper,
  emphasis = "default",
}: {
  label: string;
  value: string;
  helper: string;
  emphasis?: "default" | "success" | "warning";
}) {
  return (
    <div className={`rounded-2xl border px-4 py-4 ${searchMetricPalette(emphasis)}`}>
      <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{value}</p>
      <p className="mt-2 text-sm leading-6 text-[color:var(--muted)]">{helper}</p>
    </div>
  );
}

export function TaskDetailPanel({ job }: { job: ResearchJobRecord }) {
  const { selectedTaskId } = useResearchUiStore();
  const [openingUrl, setOpeningUrl] = useState<string | null>(null);
  const [openFeedback, setOpenFeedback] = useState<string | null>(null);
  const task = job.tasks.find((item) => item.id === selectedTaskId) ?? job.tasks[0];

  if (!task) {
    return null;
  }

  const coverageStatus = (task.coverage_status ?? {}) as Record<string, unknown>;
  const skillRuntime = (task.skill_runtime ?? {}) as Record<string, unknown>;
  const skillThemes = Array.isArray(coverageStatus.skill_themes) ? coverageStatus.skill_themes : Array.isArray(skillRuntime.skill_themes) ? skillRuntime.skill_themes : [];
  const coveredTags = Array.isArray(coverageStatus.covered_query_tags) ? coverageStatus.covered_query_tags : [];
  const missingTags = Array.isArray(coverageStatus.missing_required) ? coverageStatus.missing_required : [];
  const missingSkillTargets =
    coverageStatus.missing_skill_targets && typeof coverageStatus.missing_skill_targets === "object"
      ? Object.entries(coverageStatus.missing_skill_targets as Record<string, unknown>).filter(([, value]) => Number(value) > 0)
      : [];
  const queryTagCounts =
    coverageStatus.query_tag_counts && typeof coverageStatus.query_tag_counts === "object"
      ? Object.entries(coverageStatus.query_tag_counts as Record<string, unknown>)
      : [];
  const researchRounds = (task.research_rounds ?? []).filter((round): round is ResearchRoundRecord => Boolean(round && typeof round === "object"));
  const visibleResearchRounds = researchRounds.slice().reverse();
  const aggregateDiagnostics = researchRounds.reduce(
    (accumulator, round) => {
      const diagnostics = round.diagnostics ?? {};
      accumulator.admitted += Number(diagnostics.admitted || 0);
      accumulator.rejected += Number(diagnostics.rejected || 0);
      accumulator.lowSignal += Number(diagnostics.low_signal || 0);
      accumulator.duplicates += Number(diagnostics.duplicates || 0);
      accumulator.hostQuota += Number(diagnostics.host_quota || 0);
      accumulator.fetchFallbacks += Number(diagnostics.fetch_fallbacks || 0);
      accumulator.browserOpens += Number(diagnostics.browser_opens || 0);
      accumulator.searchErrors += Number(diagnostics.search_errors || 0);
      accumulator.negativeKeywordBlocks += Number(diagnostics.negative_keyword_blocks || 0);
      return accumulator;
    },
    {
      admitted: 0,
      rejected: 0,
      lowSignal: 0,
      duplicates: 0,
      hostQuota: 0,
      fetchFallbacks: 0,
      browserOpens: 0,
      searchErrors: 0,
      negativeKeywordBlocks: 0,
    },
  );
  const aggregateProviderHealth = researchRounds.reduce(
    (accumulator, round) => {
      const pipeline = (round.pipeline ?? {}) as Record<string, unknown>;
      accumulator.attempts += Number(pipeline.provider_attempt_count || 0);
      accumulator.results += Number(pipeline.provider_result_count || 0);
      accumulator.empty += Number(pipeline.provider_empty_count || 0);
      accumulator.failures += Number(pipeline.provider_failure_count || 0);
      accumulator.skippedBackoff += Number(pipeline.provider_backoff_skip_count || 0);
      return accumulator;
    },
    { attempts: 0, results: 0, empty: 0, failures: 0, skippedBackoff: 0 },
  );
  const latestRound = visibleResearchRounds[0];
  const latestPipeline = (latestRound?.pipeline ?? {}) as NonNullable<ResearchRoundRecord["pipeline"]>;
  const pipelineEntityTerms = latestPipeline.entity_terms ?? [];
  const pipelineOfficialDomains = latestPipeline.official_domains ?? [];
  const pipelineNegativeKeywords = latestPipeline.negative_keywords ?? [];
  const pipelinePlannedQueryCount = Number(latestPipeline.planned_query_count || latestRound?.queries?.length || 0);
  const pipelineRecalledResultCount = Number(latestPipeline.recalled_result_count || latestRound?.result_count || 0);
  const pipelineRerankedResultCount = Number(latestPipeline.reranked_result_count || 0);
  const pipelineFetchAttemptCount = Number(latestPipeline.fetch_attempt_count || 0);
  const pipelineExtractedPageCount = Number(latestPipeline.extracted_page_count || 0);
  const pipelineNormalizedEvidenceCount = Number(latestPipeline.normalized_evidence_count || 0);
  const pipelineOfficialHitCount = Number(latestPipeline.official_hit_count || 0);
  const pipelineNegativeBlockCount = Number(
    latestPipeline.negative_keyword_block_count || aggregateDiagnostics.negativeKeywordBlocks || 0,
  );
  const querySummaries = researchRounds.flatMap((round) => round.query_summaries ?? []);
  const latestRoundProviderAttempts = (latestRound?.query_summaries ?? []).flatMap((summary) => summary.provider_attempts ?? []);
  const latestRoundProviderHealth = aggregateProviderAttempts(latestRoundProviderAttempts);
  const completedQueryTexts = new Set(researchRounds.flatMap((round) => (round.query_summaries ?? []).map((item) => item.query)));
  const pendingQueries = (task.search_queries ?? []).filter((query) => !completedQueryTexts.has(query));
  const evidenceQueryCount = querySummaries.filter((summary) => summary.status === "evidence_added").length;
  const retriedQueryCount = querySummaries.filter((summary) => hasRetryActivity(summary)).length;
  const zeroResultQueryCount = querySummaries.filter((summary) => summary.status === "zero_results").length;
  const filteredQueryCount = querySummaries.filter((summary) => summary.status === "filtered").length;
  const runningQueryCount = querySummaries.filter((summary) => summary.status === "running").length;
  const queryHitCount = querySummaries.filter((summary) => Number(summary.search_result_count || 0) > 0).length;
  const leadCount = candidateLeadCount(task, querySummaries);
  const totalSearchResults = querySummaries.reduce((sum, summary) => sum + Number(summary.search_result_count || 0), 0);
  const visitedPageCount = (task.visited_sources ?? []).length;
  const uniqueDomainCount = Number(coverageStatus.unique_domains || 0);
  const processedCandidateCount =
    aggregateDiagnostics.admitted +
    aggregateDiagnostics.rejected +
    aggregateDiagnostics.lowSignal +
    aggregateDiagnostics.duplicates +
    aggregateDiagnostics.hostQuota +
    aggregateDiagnostics.negativeKeywordBlocks;
  const retentionRate =
    processedCandidateCount > 0 ? `${Math.round((aggregateDiagnostics.admitted / processedCandidateCount) * 100)}%` : "—";
  const retentionReasons = topRetentionReasons({
    lowSignal: aggregateDiagnostics.lowSignal,
    rejected: aggregateDiagnostics.rejected,
    hostQuota: aggregateDiagnostics.hostQuota,
    duplicates: aggregateDiagnostics.duplicates,
    negativeKeywordBlocks: aggregateDiagnostics.negativeKeywordBlocks,
    fetchFallbacks: aggregateDiagnostics.fetchFallbacks,
    searchErrors: aggregateDiagnostics.searchErrors,
  });
  const retentionSummary = formatRetentionSummary({
    totalSearchResults,
    visitedPageCount,
    sourceCount: task.source_count,
    uniqueDomainCount,
    topReasons: retentionReasons,
    runningQueryCount,
  });
  const isCoverageSummarizing =
    task.source_count > 0 &&
    coveredTags.length === 0 &&
    queryTagCounts.length === 0 &&
    (task.status === "running" || querySummaries.some((summary) => summary.status === "running"));
  const summaryText = (() => {
    if (!researchRounds.length) {
      return "系统正在生成更合适的检索方向，稍后会在这里解释搜索判断。";
    }
    if (isCoverageSummarizing) {
      return "已拿到首批可引用依据，系统正在把它们归到用户反馈、案例分析等研究视角，稍后会补齐覆盖判断。";
    }
    if (researchRounds.some((round) => round.key === "convergence")) {
      return "前几轮结果分散，系统已收敛主题并改写关键词继续搜索。";
    }
    if (aggregateDiagnostics.fetchFallbacks > 0) {
      return "部分页面无法直接抓取，系统已保留摘要并转向其他可用页面。";
    }
    if (task.source_count > 0 && missingTags.length > 0) {
      return `已完成 ${researchRounds.length} 轮检索，已有初步可引用依据，但${formatMissingCoverage(missingTags)}。`;
    }
    if (task.source_count > 0) {
      return `已完成 ${researchRounds.length} 轮检索，整理出 ${task.source_count} 条可引用依据，当前覆盖基本满足。`;
    }
    if (task.status === "completed") {
      if (aggregateDiagnostics.searchErrors > 0 && leadCount === 0) {
        return "这一步已经跑完，但搜索来源一度不稳定，系统没拿到足够可复核页面。建议稍后重试，或补充官网域名/英文产品名后继续。";
      }
      if (leadCount > 0 || queryHitCount > 0 || filteredQueryCount > 0) {
        return "这一步已经跑完，系统找到过候选页面，但暂时没沉淀出可引用依据。可展开下方查询记录查看是页面受限还是结果偏离主题。";
      }
      return "这一步已经跑完，但当前关键词还没命中足够相关的公开结果。建议补充更具体的产品名、地区或官网域名后继续。";
    }
    if (leadCount > 0) {
      return `已命中 ${leadCount} 条候选线索，正在核验并沉淀为可引用依据。`;
    }
    if (queryHitCount > 0) {
      return `已跑 ${researchRounds.length} 轮检索，${queryHitCount} 条关键词拿回了结果，正在筛选高相关页面。`;
    }
    return `已完成 ${researchRounds.length} 轮检索，正在继续寻找更相关来源。`;
  })();
  const coverageLine =
    isCoverageSummarizing
      ? "已拿到依据，正在汇总覆盖结构"
      : task.source_count > 0
        ? formatMissingCoverage(missingTags)
        : task.status === "completed" && aggregateDiagnostics.searchErrors > 0 && leadCount === 0
          ? "已跑完本轮，搜索来源曾不稳定"
          : task.status === "completed" && (leadCount > 0 || queryHitCount > 0 || filteredQueryCount > 0)
            ? "已跑完本轮，候选线索未能沉淀成依据"
            : task.status === "completed"
              ? "已跑完本轮，建议补充更具体关键词"
        : leadCount > 0
          ? "已命中候选线索，正在核验归档"
          : "正在形成首批可引用依据";
  const actionLine =
    latestRound?.key === "gap_fill"
      ? "已追加缺口补搜"
      : latestRound?.key === "convergence"
        ? "已做主题收敛"
        : "继续常规检索";
  const sourceHandlingLine =
    aggregateDiagnostics.fetchFallbacks > 0
      ? `已核对 ${(task.visited_sources ?? []).length} 个页面，其中 ${aggregateDiagnostics.fetchFallbacks} 个仅保留摘要`
      : `已核对 ${(task.visited_sources ?? []).length} 个页面${aggregateDiagnostics.browserOpens > 0 ? `，并打开 ${aggregateDiagnostics.browserOpens} 个原文页面` : ""}`;

  const handleOpenSource = async (url: string) => {
    setOpeningUrl(url);
    setOpenFeedback(null);
    try {
      const result = await openTaskSource(job.id, task.id, url);
      const status = String(result.status ?? "");
      const mode = String(result.mode ?? task.browser_mode ?? "");
      if (status === "ready" && mode === "opencli") {
        setOpenFeedback("已在浏览器中打开原文。");
      } else if (status === "ready") {
        setOpenFeedback("已通过系统浏览器打开原文。");
      } else if (status === "degraded") {
        setOpenFeedback("当前无法自动打开原文，已保留抓取结果。");
      } else {
        setOpenFeedback(getApiErrorMessage(result.reason, "打开页面失败。"));
      }
    } catch (error) {
      setOpenFeedback(getApiErrorMessage(error, "打开页面失败。"));
    } finally {
      setOpeningUrl(null);
    }
  };

  return (
    <Card className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <CardTitle>研究详情</CardTitle>
          <CardDescription>查看执行节奏、检索路径和已核对页面。</CardDescription>
        </div>
        <Badge tone={taskStatusTone(task.status)}>{taskStatusLabel(task.status)}</Badge>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.88fr_1.12fr]">
        <div className="space-y-4">
          <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5">
            <div className="flex items-center gap-2">
              <TerminalSquare className="h-4 w-4 text-[color:var(--accent)]" />
              <p className="text-sm font-semibold text-[color:var(--ink)]">任务概览</p>
            </div>
            <p className="mt-3 text-lg font-semibold text-[color:var(--ink)]">{task.agent_name ?? "研究任务"}</p>
            <p className="mt-2 text-sm text-[color:var(--muted)]">{task.current_action ?? "等待开始"}</p>
            {task.command_label ? <p className="mt-2 text-sm text-[color:var(--muted)]">{`研究路径：${task.command_label}`}</p> : null}
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between text-xs text-[color:var(--muted)]">
                <span>执行进度</span>
                <span>{task.progress ?? 0}%</span>
              </div>
              <ProgressBar aria-label={`${task.title}执行进度`} value={task.progress ?? 0} />
            </div>
          </div>

          <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5">
            <div className="flex items-center gap-2">
              <Globe2 className="h-4 w-4 text-[color:var(--accent)]" />
              <p className="text-sm font-semibold text-[color:var(--ink)]">来源访问</p>
            </div>
            <p className="mt-3 text-sm font-medium text-[color:var(--ink)]">{browserModeLabel(task.browser_mode)}</p>
            <p className="mt-2 break-all text-sm text-[color:var(--muted)]">{task.current_url ?? "当前还没有正在处理的页面"}</p>
            <p className="mt-2 text-sm text-[color:var(--muted)]">{browserModeHint(task.browser_mode)}</p>
            {task.current_url ? (
              <Button
                className="mt-4"
                disabled={openingUrl === task.current_url}
                onClick={() => handleOpenSource(task.current_url || "")}
                type="button"
                variant="secondary"
              >
                <ExternalLink className="mr-2 h-4 w-4" />
                {openingUrl === task.current_url ? "打开中..." : task.browser_mode === "opencli" ? "打开当前来源" : "在浏览器中查看"}
              </Button>
            ) : null}
            {openFeedback ? <p className="mt-3 text-xs text-[color:var(--muted)]">{openFeedback}</p> : null}
          </div>

          {pipelinePlannedQueryCount > 0 ? (
            <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5">
              <div className="flex flex-wrap items-center gap-2">
                <ScanSearch className="h-4 w-4 text-[color:var(--accent)]" />
                <p className="text-sm font-semibold text-[color:var(--ink)]">检索流水线</p>
                {latestPipeline.retrieval_profile_id ? <Badge tone="warning">{latestPipeline.retrieval_profile_id}</Badge> : null}
              </div>
              <p className="mt-3 text-sm leading-7 text-[color:var(--muted)]">
                当前轮次会先根据实体词做查询计划，再结合官方域名偏置和负例词拦截进行召回筛选，最后把抓取结果归一化成可引用证据。
              </p>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <SearchMetricCard
                  label="查询计划"
                  value={`${pipelineEntityTerms.length} / ${pipelinePlannedQueryCount}`}
                  helper="左侧为实体词数量，右侧为这一轮实际执行的查询数。"
                  emphasis="success"
                />
                <SearchMetricCard
                  label="召回与筛选"
                  value={`${pipelineRecalledResultCount} / ${pipelineRerankedResultCount}`}
                  helper="左侧是召回候选，右侧是通过低信号与域名筛选后进入抓取的页面。"
                  emphasis="default"
                />
                <SearchMetricCard
                  label="抽取与归一"
                  value={`${pipelineExtractedPageCount} / ${pipelineNormalizedEvidenceCount}`}
                  helper={`已发起 ${pipelineFetchAttemptCount} 次抓取；右侧是最终沉淀成 evidence 的数量。`}
                  emphasis="success"
                />
                <SearchMetricCard
                  label="官方与拦截"
                  value={`${pipelineOfficialHitCount} / ${pipelineNegativeBlockCount}`}
                  helper="左侧是官方域名命中，右侧是被 profile 负例词主动拦截的离题结果。"
                  emphasis={pipelineNegativeBlockCount > 0 ? "warning" : "default"}
                />
              </div>
              {pipelineEntityTerms.length ? (
                <div className="mt-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">实体词</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {pipelineEntityTerms.map((item) => (
                      <Badge key={item}>{item}</Badge>
                    ))}
                  </div>
                </div>
              ) : null}
              {pipelineOfficialDomains.length ? (
                <div className="mt-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">官方域名白名单</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {pipelineOfficialDomains.map((item) => (
                      <Badge key={item} tone="success">
                        {item}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
              {pipelineNegativeKeywords.length ? (
                <div className="mt-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">负例词</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {pipelineNegativeKeywords.map((item) => (
                      <Badge key={item} tone="warning">
                        {item}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {task.skill_packs?.length ? (
            <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-[color:var(--accent)]" />
                <p className="text-sm font-semibold text-[color:var(--ink)]">执行能力</p>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {task.skill_packs.map((item) => (
                  <Badge key={item}>{formatSkillPack(item)}</Badge>
                ))}
              </div>
              {task.orchestration_notes ? <p className="mt-4 text-sm leading-7 text-[color:var(--muted)]">{formatOrchestrationNotes(task.orchestration_notes)}</p> : null}
            </div>
          ) : null}
        </div>

        <div className="space-y-4">
          {task.skill_packs?.length ? (
            <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold text-[color:var(--ink)]">研究覆盖</p>
                {coverageStatus.skill_runtime_active ? <Badge tone="success">已启用</Badge> : <Badge>未启用</Badge>}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {skillThemes.map((item) => (
                  <Badge key={String(item)} tone="warning">
                    {formatSkillTheme(item)}
                  </Badge>
                ))}
              </div>

              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <div className="rounded-2xl bg-[rgba(247,241,231,0.86)] p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">已覆盖视角</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {coveredTags.length ? (
                      coveredTags.map((item) => <Badge key={String(item)} tone="success">{formatCoverageTag(item)}</Badge>)
                    ) : (
                      <span className="text-sm text-[color:var(--muted)]">{isCoverageSummarizing ? "归因汇总中" : "尚未覆盖"}</span>
                    )}
                  </div>
                </div>
                <div className="rounded-2xl bg-[rgba(247,241,231,0.86)] p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">待补视角</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {isCoverageSummarizing ? (
                      <span className="text-sm text-[color:var(--muted)]">首轮归因完成后再判断是否需要补搜</span>
                    ) : missingTags.length ? (
                      missingTags.map((item) => <Badge key={String(item)} tone="warning">{formatCoverageTag(item)}</Badge>)
                    ) : (
                      <span className="text-sm text-[color:var(--muted)]">核心覆盖已满足</span>
                    )}
                  </div>
                </div>
                <div className="rounded-2xl bg-[rgba(247,241,231,0.86)] p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">覆盖结构</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {queryTagCounts.length ? (
                      queryTagCounts.map(([key, value]) => <Badge key={key}>{`${formatCoverageTag(key)} ${Number(value)}`}</Badge>)
                    ) : (
                      <span className="text-sm text-[color:var(--muted)]">{isCoverageSummarizing ? "已拿到依据，正在整理结构" : "等待依据进入"}</span>
                    )}
                  </div>
                </div>
              </div>

              {missingSkillTargets.length && !isCoverageSummarizing ? (
                <p className="mt-4 text-sm text-[color:var(--muted)]">
                  当前仍有待补充的研究项：
                  {missingSkillTargets.map(([key, value]) => `${formatCoverageTag(key)} x${Number(value)}`).join(" · ")}
                </p>
              ) : null}
            </div>
          ) : null}

          {task.latest_error ? (
            <div className="rounded-[24px] border border-rose-200 bg-rose-50/90 p-4 text-sm leading-7 text-rose-800">{task.latest_error}</div>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5">
              <div className="flex items-center gap-2">
                <ScanSearch className="h-4 w-4 text-[color:var(--accent)]" />
                <p className="text-sm font-semibold text-[color:var(--ink)]">搜索进展</p>
              </div>
              <p className="mt-3 text-sm leading-7 text-[color:var(--muted)]">说明这项任务为什么还在继续找、下一步补什么，以及当前结果是否已经够支撑判断。</p>
              <div className="mt-4 rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.82)] px-4 py-4">
                <p className="text-sm font-medium text-[color:var(--ink)]">{summaryText}</p>
                <div className="mt-4 space-y-2 text-sm text-[color:var(--muted)]">
                  <p>{`当前覆盖：${coverageLine}`}</p>
                  <p>{`下一步动作：${actionLine}`}</p>
                  {task.source_count === 0 && leadCount > 0 ? <p>{`线索命中：已发现 ${leadCount} 条候选线索，正在逐条核验可信度和相关性。`}</p> : null}
                  <p>{`来源处理：${sourceHandlingLine}`}</p>
                  {aggregateDiagnostics.searchErrors > 0 ? <p>{`搜索异常：本任务共遇到 ${aggregateDiagnostics.searchErrors} 次搜索异常，系统已自动继续后续检索。`}</p> : null}
                </div>
              </div>
              <div className="mt-4 rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.78)] px-4 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">来源保留诊断</p>
                    <p className="mt-2 text-sm font-medium leading-7 text-[color:var(--ink)]">{retentionSummary}</p>
                  </div>
                  <Badge tone={task.source_count > 0 ? "success" : retentionReasons.length ? "warning" : "default"}>{`保留率 ${retentionRate}`}</Badge>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <SearchMetricCard
                    label="搜索返回"
                    value={String(totalSearchResults)}
                    helper="所有搜索词累计拿回的候选结果数。"
                    emphasis={totalSearchResults > 0 ? "success" : "default"}
                  />
                  <SearchMetricCard
                    label="实际核对"
                    value={String(visitedPageCount)}
                    helper="真正进入页面抓取或摘要保留的页面数。"
                    emphasis={visitedPageCount > 0 ? "success" : totalSearchResults > 0 ? "warning" : "default"}
                  />
                  <SearchMetricCard
                    label="最终依据"
                    value={String(task.source_count)}
                    helper="最后沉淀成 evidence、能进报告/判断的来源数。"
                    emphasis={task.source_count > 0 ? "success" : totalSearchResults > 0 ? "warning" : "default"}
                  />
                  <SearchMetricCard
                    label="独立域名"
                    value={String(uniqueDomainCount)}
                    helper="来源多样性；太集中时系统会主动限制单站点占比。"
                    emphasis={uniqueDomainCount >= 2 ? "success" : task.source_count > 0 ? "warning" : "default"}
                  />
                </div>
                {retentionReasons.length ? (
                  <div className="mt-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">主要损耗原因</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {retentionReasons.slice(0, 5).map((item) => (
                        <Badge key={item.key} tone={item.tone}>{`${item.shortLabel} ${item.count}`}</Badge>
                      ))}
                    </div>
                    <div className="mt-3 space-y-2">
                      {retentionReasons.slice(0, 3).map((item) => (
                        <div key={`reason-${item.key}`} className="rounded-xl border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.58)] px-3 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <p className="text-sm font-medium text-[color:var(--ink)]">{item.label}</p>
                            <Badge tone={item.tone}>{`${item.count} 次`}</Badge>
                          </div>
                          <p className="mt-2 text-xs leading-6 text-[color:var(--muted)]">{item.helper}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
              <div className="mt-4 rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.78)] px-4 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">搜索源健康度</p>
                    <p className="mt-2 text-sm font-medium leading-7 text-[color:var(--ink)]">
                      {aggregateProviderHealth.attempts > 0
                        ? `本任务共记录 ${aggregateProviderHealth.attempts} 次 provider 尝试，其中 ${aggregateProviderHealth.results} 次拿回结果，${aggregateProviderHealth.failures} 次失败，${aggregateProviderHealth.skippedBackoff} 次因冷却被跳过。`
                        : task.source_count > 0
                          ? "这项任务的来源主要来自官方补种或题材补种，外部 provider 没有留下足够稳定的尝试记录。"
                          : "当前还没有足够多的 provider 尝试记录。"}
                    </p>
                  </div>
                  <Badge tone={aggregateProviderHealth.failures > 0 ? "warning" : aggregateProviderHealth.results > 0 ? "success" : "default"}>
                    {aggregateProviderHealth.failures > 0 ? "需关注" : aggregateProviderHealth.results > 0 ? "基本可用" : "待观察"}
                  </Badge>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <SearchMetricCard
                    label="Provider 尝试"
                    value={String(aggregateProviderHealth.attempts)}
                    helper="所有轮次累计发出的 provider 请求次数。"
                    emphasis={aggregateProviderHealth.attempts > 0 ? "success" : "default"}
                  />
                  <SearchMetricCard
                    label="拿回结果"
                    value={String(aggregateProviderHealth.results)}
                    helper="provider 真正返回候选结果的次数。"
                    emphasis={aggregateProviderHealth.results > 0 ? "success" : "default"}
                  />
                  <SearchMetricCard
                    label="空结果"
                    value={String(aggregateProviderHealth.empty)}
                    helper="provider 正常返回，但没有带回候选结果。"
                    emphasis={aggregateProviderHealth.empty > 0 ? "warning" : "default"}
                  />
                  <SearchMetricCard
                    label="失败 / 冷却"
                    value={`${aggregateProviderHealth.failures} / ${aggregateProviderHealth.skippedBackoff}`}
                    helper="左侧是超时/挑战/解析失败，右侧是被冷却跳过。"
                    emphasis={aggregateProviderHealth.failures > 0 || aggregateProviderHealth.skippedBackoff > 0 ? "warning" : "default"}
                  />
                </div>
                {latestRoundProviderHealth.length ? (
                  <div className="mt-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">最近一轮 Provider 体感</p>
                    <div className="mt-3 space-y-2">
                      {latestRoundProviderHealth.map((item) => (
                        <div key={`provider-${item.provider}`} className="rounded-xl border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.58)] px-3 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <p className="text-sm font-medium text-[color:var(--ink)]">{formatSearchProvider(item.provider)}</p>
                            <div className="flex flex-wrap gap-2">
                              {item.results > 0 ? <Badge tone="success">{`命中 ${item.results}`}</Badge> : null}
                              {item.empty > 0 ? <Badge tone="default">{`空结果 ${item.empty}`}</Badge> : null}
                              {item.failures > 0 ? <Badge tone="warning">{`失败 ${item.failures}`}</Badge> : null}
                              {item.skippedBackoff > 0 ? <Badge tone="warning">{`冷却 ${item.skippedBackoff}`}</Badge> : null}
                            </div>
                          </div>
                          {item.topReasons.length ? (
                            <p className="mt-2 text-xs leading-6 text-[color:var(--muted)]">
                              最近原因：{item.topReasons.slice(0, 2).map((reason) => formatSearchProviderReason(reason)).join(" / ")}
                            </p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <SearchMetricCard
                  emphasis={task.source_count > 0 || evidenceQueryCount > 0 ? "success" : leadCount > 0 ? "warning" : "default"}
                  helper={
                    task.source_count > 0 || evidenceQueryCount > 0
                      ? `累计整理 ${task.source_count} 条可引用依据`
                      : leadCount > 0
                        ? "候选线索已命中，正在核验沉淀"
                        : "系统还在形成首批可引用依据"
                  }
                  label={task.source_count > 0 || evidenceQueryCount > 0 ? "可引用依据" : "候选线索"}
                  value={String(task.source_count > 0 || evidenceQueryCount > 0 ? evidenceQueryCount : leadCount)}
                />
                <SearchMetricCard
                  emphasis={runningQueryCount > 0 ? "warning" : retriedQueryCount > 0 ? "warning" : "default"}
                  helper={
                    runningQueryCount > 0
                      ? "这一轮仍在继续检索，命中后会自动补进"
                      : retriedQueryCount > 0
                        ? "原词不稳时，系统会自动换一种搜法继续补查"
                        : "当前还没触发系统续查"
                  }
                  label={runningQueryCount > 0 ? "继续检索" : "系统续查"}
                  value={String(runningQueryCount > 0 ? runningQueryCount : retriedQueryCount)}
                />
                <SearchMetricCard
                  emphasis={zeroResultQueryCount > 0 ? "warning" : "success"}
                  helper={zeroResultQueryCount > 0 ? "这些搜索词暂时还没拿回可用结果" : "当前没有完全空结果的搜索词"}
                  label="待补结果"
                  value={String(zeroResultQueryCount)}
                />
                <SearchMetricCard
                  emphasis={aggregateDiagnostics.fetchFallbacks > 0 ? "warning" : "success"}
                  helper={
                    aggregateDiagnostics.fetchFallbacks > 0
                      ? "部分页面先保留摘要，避免整轮研究卡住"
                      : filteredQueryCount > 0
                        ? "当前主要是结果筛选，没有大规模抓取降级"
                        : "当前来源大多可以直接抓取正文"
                  }
                  label="摘要保留"
                  value={String(aggregateDiagnostics.fetchFallbacks)}
                />
              </div>
              <div className="mt-4 space-y-3">
                {visibleResearchRounds.length ? (
                  visibleResearchRounds.map((round, index) => {
                    const diagnosticItems = roundDiagnosticItems(round);
                    const roundQuerySummaries = round.query_summaries ?? [];
                    const queryDetailCount = roundQuerySummaries.length || round.queries?.length || 0;
                    const roundLeadCount = roundQuerySummaries.filter((summary) => Number(summary.search_result_count || 0) > 0).length;
                    const roundRetryCount = roundQuerySummaries.filter((summary) => hasRetryActivity(summary)).length;
                    return (
                      <div key={`${round.wave ?? index}-${round.key ?? "round"}-${round.started_at ?? round.label ?? index}`} className="rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-3 py-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="text-sm font-medium text-[color:var(--ink)]">{roundTitle(round, visibleResearchRounds.length - index - 1)}</p>
                              <Badge tone={roundStatusTone(round)}>{roundStatusLabel(round)}</Badge>
                            </div>
                            <p className="mt-2 text-sm text-[color:var(--muted)]">{roundQuerySummaryText(round)}</p>
                            {roundFunnelSummary(round) ? (
                              <p className="mt-2 text-xs uppercase tracking-[0.16em] text-[color:var(--muted)]">{roundFunnelSummary(round)}</p>
                            ) : null}
                            <p className="mt-2 text-xs text-[color:var(--muted)]">
                              {round.started_at ? `开始于 ${new Date(round.started_at).toLocaleTimeString()}` : "已进入搜索阶段"}
                              {round.completed_at ? ` · 完成于 ${new Date(round.completed_at).toLocaleTimeString()}` : ""}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {typeof round.result_count === "number" ? <Badge>{`${round.result_count} 结果`}</Badge> : null}
                            {typeof round.evidence_added === "number" ? (
                              <Badge tone={round.evidence_added > 0 ? "success" : "warning"}>{`+${round.evidence_added} 依据`}</Badge>
                            ) : null}
                          </div>
                        </div>
                        {diagnosticItems.length ? (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {diagnosticItems.map((item) => (
                              <Badge key={`${round.key ?? "round"}-${item.key}`} tone={item.tone}>
                                {`${item.label} ${Number(item.value)}`}
                              </Badge>
                            ))}
                          </div>
                        ) : null}
                        {Number(round.diagnostics?.fetch_fallbacks || 0) > 0 ? (
                          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/80 px-3 py-2">
                            <p className="text-xs leading-6 text-amber-900">这一轮有页面原文抓取受限，系统已先保留搜索摘要，避免整轮研究被卡住。</p>
                          </div>
                        ) : null}
                        {round.queries?.length ? (
                          <details className="mt-3 rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.48)] px-3 py-3">
                            <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3">
                              <div>
                                <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">本轮搜索词</p>
                                <p className="mt-1 text-sm text-[color:var(--muted)]">
                                  {roundLeadCount > 0
                                    ? `已命中 ${roundLeadCount} 条线索${roundRetryCount > 0 ? `，其中 ${roundRetryCount} 条已系统续查` : ""}。`
                                    : roundRetryCount > 0
                                      ? `本轮已有 ${roundRetryCount} 条搜索词触发系统续查。`
                                      : "默认先看轮次摘要；需要时再展开查看搜索词细节。"}
                                </p>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                <Badge>{`${queryDetailCount} 条搜索词`}</Badge>
                                {roundLeadCount > 0 ? <Badge tone="success">{`${roundLeadCount} 条命中线索`}</Badge> : null}
                              </div>
                            </summary>
                            {roundQuerySummaries.length ? (
                              <div className="mt-3 space-y-2">
                                {roundQuerySummaries.map((summary) => (
                                  <div
                                    key={`${round.key ?? "round"}-${summary.query}`}
                                    className="rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.76)] px-3 py-3 text-sm"
                                  >
                                    <div className="flex flex-wrap items-center justify-between gap-3">
                                      <span className="min-w-0 flex-1 break-words text-[color:var(--ink)]">{summary.query}</span>
                                      <div className="flex flex-wrap gap-2">
                                        <Badge tone={querySummaryTone(summary)}>{querySummaryLabel(summary)}</Badge>
                                        {typeof summary.search_result_count === "number" ? <Badge>{`${summary.search_result_count} 结果`}</Badge> : null}
                                      </div>
                                    </div>
                                    <p className="mt-2 text-xs leading-6 text-[color:var(--muted)]">{querySummaryNarrative(summary)}</p>
                                    {summary.provider_attempts?.length ? (
                                      <div className="mt-2 flex flex-wrap gap-2">
                                        {summary.provider_attempts.slice(0, 4).map((attempt, attemptIndex) => (
                                          <Badge key={`${summary.query}-provider-${attempt.provider}-${attemptIndex}`} tone={attempt.status === "results" ? "success" : attempt.status === "empty" ? "default" : "warning"}>
                                            {`${formatSearchProvider(attempt.provider)} · ${formatSearchProviderStatus(attempt.status)}`}
                                          </Badge>
                                        ))}
                                      </div>
                                    ) : null}
                                    {summary.effective_query && summary.effective_query !== summary.query ? (
                                      <div className="mt-2 rounded-xl border border-emerald-200 bg-emerald-50/80 px-3 py-2">
                                        <p className="text-[11px] uppercase tracking-[0.16em] text-emerald-800">系统继续检索的写法</p>
                                        <p className="mt-1 text-xs leading-6 text-emerald-900">{summary.effective_query}</p>
                                      </div>
                                    ) : null}
                                    {(summary.retry_attempts ?? []).length || (summary.retry_queries ?? []).length ? (
                                      <details className="mt-2 rounded-xl border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.74)] px-3 py-2">
                                        <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--muted)]">
                                          查看系统续查路径
                                        </summary>
                                        {(summary.retry_attempts ?? []).length ? (
                                          <div className="mt-2 flex flex-wrap gap-2">
                                            {(summary.retry_attempts ?? []).map((attempt) => (
                                              <Badge key={`${summary.query}-${attempt.query}`} tone={attempt.status === "results_found" ? "success" : attempt.status === "search_error" ? "danger" : "default"}>
                                                {`${retryStatusLabel(attempt.status)} · ${attempt.query}`}
                                              </Badge>
                                            ))}
                                          </div>
                                        ) : (
                                          <p className="mt-2 text-xs leading-6 text-[color:var(--muted)]">
                                            已尝试续查：{(summary.retry_queries ?? []).join(" / ")}
                                          </p>
                                        )}
                                      </details>
                                    ) : null}
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {round.queries.map((query) => (
                                  <Badge key={`${round.key ?? "round"}-${query}`}>{query}</Badge>
                                ))}
                              </div>
                            )}
                          </details>
                        ) : null}
                      </div>
                    );
                  })
                ) : (
                  <div className="rounded-2xl border border-dashed border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.68)] px-3 py-6 text-sm text-[color:var(--muted)]">
                    系统正在生成更合适的检索方向，稍后会在这里解释搜索判断。
                  </div>
                )}
              </div>
              <div className="mt-5 border-t border-[color:var(--border-soft)] pt-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">下一轮关键词</p>
                  {pendingQueries.length ? <Badge>{`${pendingQueries.length} 条`}</Badge> : null}
                </div>
                <div className="mt-3 space-y-2">
                  {pendingQueries.length ? (
                    pendingQueries.map((query) => (
                      <div key={query} className="rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-3 py-3 text-sm text-[color:var(--ink)]">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <span className="min-w-0 flex-1 break-words">{query}</span>
                          <Badge>{queryReasonLabel(query)}</Badge>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-dashed border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.68)] px-3 py-6 text-sm text-[color:var(--muted)]">
                      {(task.search_queries ?? []).length ? "当前轮次内的关键词结果已记录在上方。" : "还没生成检索语句，通常表示任务刚启动或还在等待调度。"}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5">
              <div className="flex items-center gap-2">
                <Globe2 className="h-4 w-4 text-[color:var(--accent)]" />
                <p className="text-sm font-semibold text-[color:var(--ink)]">已核对页面</p>
              </div>
              <div className="mt-4 space-y-2">
                {(task.visited_sources ?? []).length ? (
                  (task.visited_sources ?? []).map((source) => (
                    <div key={source.url} className="rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.82)] px-3 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-[color:var(--ink)]">{source.title}</p>
                          <a className="block break-all text-xs text-[color:var(--muted)] underline-offset-2 hover:underline" href={source.url} rel="noreferrer" target="_blank">
                            {source.url}
                          </a>
                        </div>
                        <div className="flex items-center gap-2">
                          {source.opened_in_browser ? <Badge tone="success">已自动打开</Badge> : null}
                          <Button disabled={openingUrl === source.url} onClick={() => handleOpenSource(source.url)} type="button" variant="ghost">
                            {openingUrl === source.url ? "打开中..." : "查看来源"}
                          </Button>
                        </div>
                      </div>
                      <p className="mt-2 text-sm text-[color:var(--muted)]">{source.snippet}</p>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.68)] px-3 py-6 text-sm text-[color:var(--muted)]">
                    {job.source_count > 0
                      ? `当前任务暂无可引用依据，全局已整理 ${job.source_count} 条，可能来自其他任务或补研。`
                      : "还没有页面记录。检索和抓取开始后，这里会持续补进已核对页面。"}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5">
        <p className="text-sm font-semibold text-[color:var(--ink)]">重要进展</p>
        <div className="mt-4 space-y-3">
          {(task.logs ?? []).length ? (
            (task.logs ?? []).slice(-8).reverse().map((log) => (
              <div key={log.id} className="rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.82)] px-4 py-4">
                <div className="flex items-center justify-between gap-3">
                  <Badge tone={log.level === "error" ? "danger" : log.level === "warning" ? "warning" : "default"}>{logLevelLabel(log.level)}</Badge>
                  <span className="text-xs text-[color:var(--muted)]">{new Date(log.timestamp).toLocaleTimeString()}</span>
                </div>
                <p className="mt-3 text-sm text-[color:var(--ink)]">{log.message}</p>
              </div>
            ))
          ) : (
            <div className="rounded-[22px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.68)] px-4 py-6 text-sm text-[color:var(--muted)]">
              还没有关键进展。任务进入搜索、抓取或重试后，这里会持续记录重要动作。
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
