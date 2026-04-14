"use client";

import { useState } from "react";

import { Activity, BarChart3, Database, Flag, Layers3, Search } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useQueryClient } from "@tanstack/react-query";

import type { ResearchAssetsRecord, ResearchJobRecord, CompetitorRecord } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, ProgressBar, StatCard } from "@pm-agent/ui";

import { cancelResearchJob, getApiErrorMessage } from "../../../lib/api-client";
import { useResearchUiStore } from "../store/ui-store";
import { getActiveReportVersionId, getReportVersions, getStableReportVersionId } from "./report-version-utils";
import { activityLevelLabel, formatBrowserMode, formatMarketStep } from "./research-ui-utils";
import { TaskDetailPanel } from "./task-detail-panel";
import { AgentSwarmBoard } from "./workbench/agent-swarm-board";

const sourceColors = ["#1d4c74", "#355f88", "#8d9ab0", "#d7b786"];

function phaseLabel(phase?: string) {
  if (phase === "scoping") return "界定范围";
  if (phase === "planning") return "任务规划";
  if (phase === "collecting") return "证据采集";
  if (phase === "verifying") return "结论校验";
  if (phase === "synthesizing") return "初稿成文";
  if (phase === "finalizing") return "终稿整理";
  return phase || "未知阶段";
}

function reportStageLabel(stage?: string) {
  if (stage === "final") return "稳定版";
  if (stage === "feedback_pending") return "补研待合入";
  if (stage === "draft") return "草稿";
  if (stage === "draft_pending") return "生成中";
  return "待初稿";
}

function reportReadinessLabel(readiness?: string) {
  if (readiness === "stable") return "可分享版";
  if (readiness === "final") return "可分享版";
  if (readiness === "draft") return "工作草稿";
  if (readiness === "blocked") return "门槛未过";
  return "待评估";
}

type CompetitorProfile = {
  name: string;
  category?: string;
  positioning?: string;
  pricing?: string;
  differentiation?: string;
  coverage_gap?: string;
  evidence_count?: number;
  source_count?: number;
  key_sources?: string[];
};

function normalizeCompetitorProfiles(
  competitors?: Array<CompetitorRecord | Record<string, unknown>>,
): CompetitorProfile[] {
  if (!Array.isArray(competitors)) {
    return [];
  }
  const toStringValue = (value: unknown) => {
    if (typeof value === "string") {
      const trimmed = value.trim();
      return trimmed || undefined;
    }
    if (value === undefined || value === null) {
      return undefined;
    }
    const coerced = String(value).trim();
    return coerced || undefined;
  };
  const toNumberValue = (value: unknown) => {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (!trimmed) {
        return undefined;
      }
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? parsed : undefined;
    }
    return undefined;
  };
  const profiles: CompetitorProfile[] = [];
  for (const entry of competitors) {
    if (!entry || typeof entry !== "object") {
      continue;
    }
    const record = entry as Record<string, unknown>;
    const name = toStringValue(record.name) || toStringValue(record.competitor_name);
    if (!name) {
      continue;
    }
    const normalizedKeySources = Array.isArray(record.key_sources)
      ? (record.key_sources as unknown[])
          .map((item) => toStringValue(item))
          .filter((item): item is string => Boolean(item))
      : [];
    profiles.push({
      name,
      category: toStringValue(record.category),
      positioning: toStringValue(record.positioning),
      pricing: toStringValue(record.pricing),
      differentiation: toStringValue(record.differentiation),
      coverage_gap: toStringValue(record.coverage_gap),
      evidence_count: toNumberValue(record.evidence_count),
      source_count: toNumberValue(record.source_count),
      key_sources: normalizedKeySources,
    });
  }
  return profiles;
}

function isDiagnosticJob(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  return job.status === "completed" && job.completion_mode === "diagnostic";
}

function jobStatusLabel(status: ResearchJobRecord["status"], workerActive = false, completionMode?: ResearchJobRecord["completion_mode"]) {
  if (status === "completed" && completionMode === "diagnostic") return "诊断完成";
  if (status === "completed") return "已完成";
  if (status === "failed") return "已失败";
  if (status === "cancelled") return workerActive ? "取消中" : "已取消";
  if (status === "planning") return "规划中";
  if (status === "verifying") return "校验中";
  if (status === "synthesizing") return "成文中";
  return "执行中";
}

function executionModeLabel(mode?: string) {
  if (mode === "worker") return "共享 Worker";
  if (mode === "subprocess") return "后台执行";
  if (mode === "inline") return "页面内执行";
  return mode || "未标记";
}

function browserDiagnosticsText(mode?: string, available?: boolean) {
  if (mode === "opencli") {
    return "抓取受限时，会继续打开来源页面辅助判断。";
  }
  if (mode === "mac-open" || mode === "xdg-open") {
    return "可通过系统浏览器继续查看来源页面。";
  }
  if (available) {
    return "当前环境可以打开本地浏览器。";
  }
  return "当前环境无法自动打开浏览器，会优先保留静态抓取结果和搜索摘要。";
}

function browserModeLabel(mode?: string) {
  return formatBrowserMode(mode);
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item || "").trim()).filter(Boolean);
}

function coverageTagLabel(tag: string) {
  if (tag === "official") return "官网/官方口径";
  if (tag === "community") return "社区/用户反馈";
  if (tag === "comparison") return "竞品对比";
  if (tag === "analysis") return "分析解读";
  if (tag === "pricing") return "定价信息";
  return tag;
}

function taskSearchSignals(task: ResearchJobRecord["tasks"][number]) {
  const visitedSourceCount = task.visited_sources?.length ?? 0;
  const researchRounds = task.research_rounds ?? [];
  const roundCount = researchRounds.length;
  const querySummaries = researchRounds.flatMap((round) => round.query_summaries ?? []);
  const completedQueryTexts = new Set(querySummaries.map((item) => item.query));
  const pendingQueryCount = (task.search_queries ?? []).filter((query) => !completedQueryTexts.has(query)).length;
  const runningQueryCount = querySummaries.filter((item) => item.status === "running").length;
  const aggregateDiagnostics = researchRounds.reduce(
    (accumulator, round) => {
      const diagnostics = round.diagnostics ?? {};
      accumulator.fetchFallbacks += Number(diagnostics.fetch_fallbacks || 0);
      accumulator.browserOpens += Number(diagnostics.browser_opens || 0);
      return accumulator;
    },
    { fetchFallbacks: 0, browserOpens: 0 },
  );

  return {
    visitedSourceCount,
    roundCount,
    pendingQueryCount,
    runningQueryCount,
    fetchFallbacks: aggregateDiagnostics.fetchFallbacks,
    browserOpens: aggregateDiagnostics.browserOpens,
    candidateLeadCount: Math.max(visitedSourceCount, task.source_count ?? 0),
  };
}

function collectJobSearchSignals(job: ResearchJobRecord) {
  return job.tasks.reduce(
    (accumulator, task) => {
      const signals = taskSearchSignals(task);
      accumulator.candidateLeadCount += signals.candidateLeadCount;
      accumulator.roundCount += signals.roundCount;
      accumulator.pendingQueryCount += signals.pendingQueryCount;
      accumulator.runningQueryCount += signals.runningQueryCount;
      accumulator.fetchFallbacks += signals.fetchFallbacks;
      accumulator.browserOpens += signals.browserOpens;
      return accumulator;
    },
    {
      candidateLeadCount: 0,
      roundCount: 0,
      pendingQueryCount: 0,
      runningQueryCount: 0,
      fetchFallbacks: 0,
      browserOpens: 0,
    },
  );
}

function buildResearchNarrative(
  job: ResearchJobRecord,
  searchSignals: ReturnType<typeof collectJobSearchSignals>,
) {
  const coveredTags = new Set<string>();
  const missingTags = new Set<string>();
  for (const task of job.tasks ?? []) {
    const coverage = (task.coverage_status ?? {}) as Record<string, unknown>;
    for (const tag of asStringList(coverage.covered_query_tags)) {
      coveredTags.add(tag);
    }
    for (const tag of asStringList(coverage.missing_required)) {
      missingTags.add(tag);
    }
  }

  const coveredLabels = Array.from(coveredTags).map(coverageTagLabel);
  const missingLabels = Array.from(missingTags)
    .filter((tag) => !coveredTags.has(tag))
    .map(coverageTagLabel);
  const runningTask = job.tasks.find((task) => task.status === "running") ?? job.tasks.find((task) => task.current_action);
  const candidateLeadCount = searchSignals.candidateLeadCount;
  const pendingLeadCount = Math.max(candidateLeadCount - job.source_count, 0);
  const activeSearchCount = searchSignals.pendingQueryCount + searchSignals.runningQueryCount;

  const evidenceLine =
    job.source_count > 0
      ? pendingLeadCount > 0
        ? `已锁定 ${candidateLeadCount} 条研究线索，其中 ${job.source_count} 条已整理成可引用依据，覆盖 ${job.completed_task_count}/${job.tasks.length || 1} 个子任务。`
        : `已沉淀 ${job.source_count} 条可引用依据，覆盖 ${job.completed_task_count}/${job.tasks.length || 1} 个子任务。`
      : candidateLeadCount > 0
        ? `已锁定 ${candidateLeadCount} 条候选线索，正在抽取正文并整理成可引用依据。`
        : activeSearchCount > 0
          ? `已发出 ${activeSearchCount} 条搜索词，正在筛掉低相关和不可引用结果。`
          : "还在搭建首批可引用依据，当前以官网和高相关来源为主。";
  const gapLine = missingLabels.length
    ? `仍待补齐：${missingLabels.join("、")}。`
    : job.source_count === 0 && candidateLeadCount > 0
      ? searchSignals.fetchFallbacks > 0
        ? `其中 ${searchSignals.fetchFallbacks} 个受限页面已先保留摘要，系统会继续补可引用正文。`
        : "这些线索还在核对可信度和可引用性，确认后会自动更新为可引用依据。"
    : job.source_count > 0
      ? "关键覆盖项已基本齐备，可继续生成报告或进入研究对话。"
      : activeSearchCount > 0
        ? "正在先收敛首批高相关线索，再决定是否扩展补搜。"
        : "目前尚未形成可复用证据，系统会继续扩展查询和来源。";
  const nextLine =
    runningTask?.current_action ||
    (job.source_count === 0 && candidateLeadCount > 0
      ? "下一步会优先核对已命中的候选线索，并把可引用部分转成可引用依据。"
      : undefined) ||
    (missingLabels.length
      ? `下一步优先补齐 ${missingLabels.slice(0, 2).join("、")}。`
      : job.status === "completed"
        ? "下一步可直接查看报告结论，或发起增量追问。"
        : "下一步继续推进当前任务并补齐可引用依据。");

  const headline =
    job.status === "completed"
      ? missingLabels.length
        ? "研究已完成，仍有少量覆盖缺口待补证。"
        : "研究已完成，当前结论具备较好的证据支撑。"
      : job.status === "failed"
        ? "研究中断，已保留当前进度和可用依据。"
        : job.status === "cancelled"
          ? "研究已停止，当前现场可继续查看。"
          : job.source_count === 0 && candidateLeadCount > 0
            ? "研究正在核对首批线索，可引用依据即将补齐。"
            : job.source_count === 0 && activeSearchCount > 0
              ? "研究正在筛选首批高相关线索。"
              : job.source_count > 0
                ? "研究正在推进，已拿到首批可引用依据。"
                : "研究正在启动，系统在建立首批依据。";

  return {
    headline,
    evidenceLine,
    gapLine,
    nextLine,
    coveredLabels,
    missingLabels,
    candidateLeadCount,
    pendingLeadCount,
    activeSearchCount,
  };
}

function productizeJobFeedback(
  message?: string | null,
  status?: ResearchJobRecord["status"],
  diagnostic = false,
) {
  const text = String(message || "").trim();
  if (!text) {
    return null;
  }
  const lowered = text.toLowerCase();
  if (lowered.includes("429") || lowered.includes("too many requests") || lowered.includes("频率限制")) {
    return "部分来源触发访问频率限制，系统正在切换其他可用来源继续采集。";
  }
  if (lowered.includes("403") || lowered.includes("forbidden") || lowered.includes("限制访问")) {
    return "部分来源限制访问，系统已自动跳过，并继续补充其他可用来源。";
  }
  if (lowered.includes("api 地址") || lowered.includes("无法连接到 api") || lowered.includes("无法连接到 api。")) {
    return "当前暂时无法连接研究服务，请稍后重试。";
  }
  if (
    lowered.includes("证据不足")
    || lowered.includes("外部可引用证据不足")
    || lowered.includes("没有沉淀出可用证据")
    || lowered.includes("还没有沉淀出可复用的外部证据")
  ) {
    return diagnostic
      ? "当前结果已先保留为诊断结果；补充更具体的产品名、地区或官网域名后，可以继续研究。"
      : "这轮研究暂时还没拿到足够可靠的外部依据。";
  }
  if (status === "failed" && lowered.includes("执行失败")) {
    return "这轮研究中途停止了，系统已保留当前进度，稍后可以继续查看或重新发起。";
  }
  return text;
}

export function JobDashboard({ job, assets }: { job: ResearchJobRecord; assets: ResearchAssetsRecord }) {
  const { selectedTaskId, setSelectedTaskId } = useResearchUiStore();
  const queryClient = useQueryClient();
  const [cancelPending, setCancelPending] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const snapshot = assets.progress_snapshot as {
    source_growth: Array<{ label: string; value: number }>;
    source_mix: Array<{ name: string; value: number }>;
    competitor_coverage: Array<{ name: string; value: number }>;
  };
  const competitorCoverageItems = snapshot?.competitor_coverage ?? [];
  const competitorCount = Number(job.competitor_count || 0);
  const hasCompetitorSamples = competitorCount > 0;
  const competitorCoverageDisplayItems = hasCompetitorSamples ? competitorCoverageItems : [];
  const normalizedSnapshot = {
    source_growth: snapshot?.source_growth?.length ? snapshot.source_growth : [{ label: "采集", value: job.source_count }],
    source_mix: snapshot?.source_mix?.length ? snapshot.source_mix : [{ name: "web", value: job.source_count }],
    competitor_coverage: competitorCoverageDisplayItems,
  };
  const diagnosticJob = isDiagnosticJob(job);
  const jobTone = diagnosticJob ? "warning" : job.status === "completed" ? "success" : job.status === "failed" ? "danger" : job.status === "cancelled" ? "warning" : "warning";
  const isCancellable = !["completed", "failed", "cancelled"].includes(job.status);
  const backgroundProcess = (job.background_process ?? {}) as Record<string, unknown>;
  const workerPid = Number(backgroundProcess.worker_pid || backgroundProcess.pid || 0) || null;
  const workerActive = Boolean(backgroundProcess.active);
  const focusTask =
    job.tasks.find((task) => task.id === selectedTaskId) ??
    job.tasks.find((task) => (task.visited_sources?.length ?? 0) > 0 || (task.source_count ?? 0) > 0) ??
    job.tasks[0];
  const stableVersionId = getStableReportVersionId(job);
  const activeVersionId = getActiveReportVersionId(job);
  const hasStableVersion = Boolean(stableVersionId);
  const hasVersionMismatch = Boolean(stableVersionId && activeVersionId && stableVersionId !== activeVersionId);
  const reportVersions = getReportVersions(assets, job);
  const activeSnapshot = reportVersions.find((item) => item.version_id === activeVersionId);
  const stableSnapshot = reportVersions.find((item) => item.version_id === stableVersionId);
  const activeStage = activeSnapshot?.stage ?? assets.report?.stage;
  const stableStage = stableSnapshot?.stage ?? (stableVersionId ? assets.report?.stage : undefined);
  const qualityGate = activeSnapshot?.quality_gate ?? assets.report?.quality_gate;
  const finalizeBlocked = !qualityGate?.pending && qualityGate?.passed === false;
  const qualitySummary = job.quality_score_summary ?? {};
  const qualityReadiness = reportReadinessLabel(String(qualitySummary.report_readiness || "").trim().toLowerCase());
  const qualityScore =
    typeof qualitySummary.report_quality_score === "number" && Number.isFinite(qualitySummary.report_quality_score)
      ? qualitySummary.report_quality_score
      : null;
  const formalClaimCount = Number(qualitySummary.formal_claim_count || qualityGate?.metrics?.formal_claim_count || 0);
  const formalEvidenceCount = Number(qualitySummary.formal_evidence_count || qualityGate?.metrics?.formal_evidence_count || 0);
  const formalDomainCount = Number(qualitySummary.formal_domain_count || qualityGate?.metrics?.formal_domain_count || 0);
  const requiresFinalize = Boolean(qualitySummary.requires_finalize);
  const searchSignals = collectJobSearchSignals(job);
  const focusTaskSignals = focusTask ? taskSearchSignals(focusTask) : null;
  const rawJobFeedback =
    actionFeedback ||
    (job.status === "cancelled" ? job.cancellation_reason : diagnosticJob ? job.latest_warning || job.latest_error : job.latest_error || job.latest_warning) ||
    (job.cancel_requested ? "取消请求已发送，后台进程正在停止。" : null);
  const jobFeedback = productizeJobFeedback(rawJobFeedback, job.status, diagnosticJob);
  const narrative = buildResearchNarrative(job, searchSignals);
  const sourceHelper =
    narrative.pendingLeadCount > 0
      ? `另有 ${narrative.pendingLeadCount} 条候选线索待核验`
      : searchSignals.candidateLeadCount > job.source_count && job.source_count === 0
        ? `已发现 ${searchSignals.candidateLeadCount} 条候选线索`
        : "已进入研究资产、可被继续引用的依据";
  const competitorProfiles = normalizeCompetitorProfiles(assets.competitors);
  const highlightedCompetitors = competitorProfiles.slice(0, 3);
  const autoDetectingCompetitorsCopy = "竞品样本尚未形成，系统正在自动识别并整理对手线索。";
  const competitorHelperText = hasCompetitorSamples
    ? "直接/间接竞品均已纳入对比"
    : "尚未形成可用竞品样本，系统正在自动识别。";
  const competitorCoverageDescription = hasCompetitorSamples
    ? "深度调查模式下，竞品深挖程度可直接可视化。"
    : autoDetectingCompetitorsCopy;
  const competitorCoverageEmptyCopy = autoDetectingCompetitorsCopy;

  const handleCancelJob = async () => {
    setCancelPending(true);
    setActionFeedback(null);
    try {
      const nextJob = await cancelResearchJob(job.id, "已由用户从研究工作台取消。");
      queryClient.setQueryData(["research-job", job.id], nextJob);
      queryClient.setQueryData(["chat-session-job", job.id], nextJob);
      queryClient.setQueryData<ResearchJobRecord[]>(["research-jobs"], (currentJobs) =>
        (currentJobs ?? []).map((item) => (item.id === nextJob.id ? nextJob : item)),
      );
      setActionFeedback(nextJob.cancellation_reason || "研究任务已取消。");
    } catch (error) {
      setActionFeedback(getApiErrorMessage(error, "取消任务失败。"));
    } finally {
      setCancelPending(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card className="data-grid-bg relative overflow-hidden">
        <div className="absolute inset-x-0 top-0 h-24 bg-[radial-gradient(circle_at_top_left,_rgba(29,76,116,0.16),_transparent_60%)]" />
        <div className="relative grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={jobTone}>{jobStatusLabel(job.status, workerActive, job.completion_mode)}</Badge>
              <Badge>{phaseLabel(job.current_phase)}</Badge>
              {job.report_version_id ? <Badge>{job.report_version_id}</Badge> : null}
              {job.workflow_label ? <Badge>{job.workflow_label}</Badge> : null}
              <Badge tone={job.failure_policy === "strict" ? "danger" : "warning"}>{job.failure_policy === "strict" ? "严谨模式" : "标准模式"}</Badge>
              {searchSignals.roundCount > 0 ? <Badge>{`搜索轮次 ${searchSignals.roundCount}`}</Badge> : null}
              {searchSignals.candidateLeadCount > job.source_count ? <Badge tone="warning">{`候选线索 ${searchSignals.candidateLeadCount}`}</Badge> : null}
              {diagnosticJob ? <Badge tone="warning">诊断结果</Badge> : null}
              {job.cancel_requested && job.status !== "cancelled" ? <Badge tone="warning">取消中</Badge> : null}
            </div>

            <div className="space-y-3">
              <CardTitle className="text-3xl sm:text-[2.7rem]">{job.topic}</CardTitle>
              <CardDescription className="max-w-4xl text-base leading-7">
                {narrative.headline}
              </CardDescription>
              <div className="mt-2 flex flex-wrap gap-2">
                {stableVersionId ? (
                  <Badge tone="success">{`稳定 ${stableVersionId}`}</Badge>
                ) : (
                  <Badge tone="default">暂无稳定版</Badge>
                )}
                {activeVersionId ? (
                  <Badge tone={hasVersionMismatch ? "warning" : "default"}>{`工作稿 ${activeVersionId}`}</Badge>
                ) : null}
                {hasVersionMismatch ? (
                  <Badge tone="warning">草稿与稳定版存在差异</Badge>
                ) : hasStableVersion ? (
                  <Badge tone="success">版本同步</Badge>
                ) : (
                  <Badge tone="default">等待稳定版</Badge>
                )}
              </div>
              {job.orchestration_summary ? <p className="text-sm leading-7 text-[color:var(--muted)]">{job.orchestration_summary}</p> : null}
              {job.project_memory ? (
                <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] px-4 py-4 text-sm leading-7 text-[color:var(--muted)]">
                  <span className="font-medium text-[color:var(--ink)]">项目背景：</span>
                  {job.project_memory}
                </div>
              ) : null}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">当前重点研究</p>
                <p className="mt-2 text-base font-semibold text-[color:var(--ink)]">{focusTask?.agent_name || focusTask?.title || "等待任务接管"}</p>
                <p className="mt-2 text-sm text-[color:var(--muted)]">{focusTask?.current_action || focusTask?.brief || "任务开始后，这里会显示当前正在处理的内容。"}</p>
                {focusTask ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Badge>{formatMarketStep(focusTask.market_step)}</Badge>
                    <Badge tone={focusTask.source_count > 0 ? "success" : "warning"}>
                      {focusTaskSignals && focusTaskSignals.candidateLeadCount > focusTask.source_count
                        ? `已锁定 ${focusTaskSignals.candidateLeadCount} 条线索`
                        : `${focusTask.source_count} 条依据`}
                    </Badge>
                    {focusTaskSignals?.roundCount ? <Badge>{`${focusTaskSignals.roundCount} 轮检索`}</Badge> : null}
                    {focusTaskSignals && focusTaskSignals.pendingQueryCount + focusTaskSignals.runningQueryCount > 0 ? (
                      <Badge>{`${focusTaskSignals.pendingQueryCount + focusTaskSignals.runningQueryCount} 条搜索进行中`}</Badge>
                    ) : null}
                    {focusTask.command_label ? <Badge>{focusTask.command_label}</Badge> : null}
                  </div>
                ) : null}
                {focusTaskSignals ? (
                  <p className="mt-3 text-sm leading-7 text-[color:var(--muted)]">
                    {focusTask.source_count > 0
                      ? focusTaskSignals.candidateLeadCount > focusTask.source_count
                        ? `当前任务已命中 ${focusTaskSignals.candidateLeadCount} 条线索，其中 ${focusTask.source_count} 条已整理成可引用依据。`
                        : `当前任务已沉淀 ${focusTask.source_count} 条可引用依据。`
                      : focusTaskSignals.candidateLeadCount > 0
                        ? `当前任务已命中 ${focusTaskSignals.candidateLeadCount} 条候选线索，正在核对正文与可引用内容。`
                        : focusTaskSignals.pendingQueryCount + focusTaskSignals.runningQueryCount > 0
                          ? `当前任务已有 ${focusTaskSignals.pendingQueryCount + focusTaskSignals.runningQueryCount} 条搜索词在推进，结果会自动补进。`
                          : "当前任务刚开始，还在形成第一批搜索线索。"}
                  </p>
                ) : null}
              </div>
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">研究推进摘要</p>
                <p className="mt-2 text-sm text-[color:var(--ink)]">{narrative.evidenceLine}</p>
                <p className="mt-2 text-sm text-[color:var(--muted)]">{narrative.gapLine}</p>
                <p className="mt-2 text-sm text-[color:var(--ink)]">{narrative.nextLine}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {narrative.coveredLabels.slice(0, 3).map((tag) => (
                    <Badge key={`covered-${tag}`} tone="success">{`已覆盖 · ${tag}`}</Badge>
                  ))}
                  {narrative.missingLabels.slice(0, 2).map((tag) => (
                    <Badge key={`missing-${tag}`} tone="warning">{`待补 · ${tag}`}</Badge>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.64)]">
              <div className="flex items-center justify-between text-sm text-[color:var(--muted)]">
                <span>总体进度</span>
                <span>{job.overall_progress}%</span>
              </div>
              <div className="mt-3">
                <ProgressBar aria-label="总体进度" value={job.overall_progress} />
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-[color:var(--muted)]">
                <span>{`当前阶段：${phaseLabel(job.current_phase)}`}</span>
                <span>
                  {job.status === "failed" || job.status === "cancelled" ? "已停止" : job.eta_seconds === 0 ? "已完成" : `预计 ${Math.round(job.eta_seconds / 60)} 分钟`}
                </span>
              </div>
              {isCancellable ? (
                <Button className="mt-4 w-full bg-rose-600 text-white hover:bg-rose-500" disabled={cancelPending} onClick={() => void handleCancelJob()} type="button">
                  {cancelPending ? "取消中..." : "取消任务"}
                </Button>
              ) : null}
            </div>

            {jobFeedback ? (
              <div
                className={`rounded-[24px] border px-4 py-4 text-sm leading-7 ${
                  job.status === "cancelled"
                    ? "border-amber-200 bg-amber-50/90 text-amber-900"
                    : diagnosticJob
                    ? "border-amber-200 bg-amber-50/90 text-amber-900"
                    : job.status === "failed"
                    ? "border-rose-200 bg-rose-50/90 text-rose-800"
                    : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] text-[color:var(--ink)]"
                }`}
              >
                {jobFeedback}
              </div>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">阶段推进</p>
                <p className="mt-2 text-sm text-[color:var(--ink)]">{`${job.completed_task_count}/${job.tasks.length} 个子任务已完成`}</p>
                <p className="mt-1 text-sm text-[color:var(--muted)]">{`${job.running_task_count} 个运行中 · ${job.failed_task_count} 个失败`}</p>
              </div>
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">
                  {searchSignals.candidateLeadCount > job.source_count ? "候选线索" : "报告状态"}
                </p>
                <p className="mt-2 text-sm text-[color:var(--ink)]">
                  {searchSignals.candidateLeadCount > job.source_count
                    ? `${searchSignals.candidateLeadCount} 条已命中待整理`
                    : hasVersionMismatch
                      ? `${reportStageLabel(activeStage)} · 有新草稿待确认`
                      : hasStableVersion
                        ? reportStageLabel(stableStage || activeStage)
                        : `${reportStageLabel(activeStage)} · 待生成稳定版`}
                </p>
                <p className="mt-1 text-sm text-[color:var(--muted)]">
                  {searchSignals.candidateLeadCount > job.source_count
                    ? searchSignals.fetchFallbacks > 0
                      ? `${searchSignals.fetchFallbacks} 个受限页面已先保留摘要，系统还在补正文。`
                      : "这些线索通过核对后会自动进入可引用依据。"
                    : diagnosticJob
                      ? "当前是诊断结果，适合继续补充研究，不建议直接作为正式结论。"
                    : finalizeBlocked
                        ? "当前工作稿暂不满足正式版要求"
                        : hasVersionMismatch
                          ? "稳定版可继续分享，工作稿需要生成稳定版后再替换"
                          : hasStableVersion
                            ? "当前版本可继续进入研究对话或作为分享基线"
                            : "当前还只有工作稿，生成稳定版后才会得到可分享版本"}
                </p>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="可引用依据" value={`${job.source_count}`} helper={sourceHelper} icon={<Database className="h-4 w-4 text-[color:var(--muted)]" />} />
        <StatCard label="竞品数量" value={`${job.competitor_count}`} helper={competitorHelperText} icon={<Flag className="h-4 w-4 text-[color:var(--muted)]" />} />
        <StatCard label="结论条目" value={`${job.claims_count}`} helper="支持报告与对话双向追溯" icon={<Layers3 className="h-4 w-4 text-[color:var(--muted)]" />} />
        <StatCard
          label="搜索推进"
          value={`${searchSignals.pendingQueryCount + searchSignals.runningQueryCount}`}
          helper={
            searchSignals.candidateLeadCount > job.source_count
              ? `另有 ${searchSignals.candidateLeadCount - job.source_count} 条候选线索在核验中`
              : searchSignals.fetchFallbacks > 0
                ? `${searchSignals.fetchFallbacks} 个受限页面已先保留摘要`
                : "当前搜索与筛选节奏"
          }
          icon={<Activity className="h-4 w-4 text-[color:var(--muted)]" />}
        />
      </div>

      <Card className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>竞品结构化概览</CardTitle>
            <CardDescription>展示竞品角色、定价与差异线索，配合证据足迹帮助快速对标。</CardDescription>
          </div>
          <Badge tone={highlightedCompetitors.length ? "success" : "default"}>
            {highlightedCompetitors.length
              ? `${highlightedCompetitors.length} 个样本`
              : job.competitor_count
                ? `${job.competitor_count} 个竞品待补`
                : "暂无竞品数据"}
          </Badge>
        </div>
        {highlightedCompetitors.length ? (
          <div className="space-y-4">
            {highlightedCompetitors.map((item) => (
              <div
                key={item.name}
                className="rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.76)] p-4 shadow-[0_16px_34px_rgba(23,32,51,0.08)]"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-base font-semibold text-[color:var(--ink)]">{item.name}</p>
                    {item.category ? <p className="text-xs text-[color:var(--muted)]">{item.category}</p> : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {typeof item.evidence_count === "number" ? (
                      <Badge tone="success">{`证据 ${item.evidence_count}`}</Badge>
                    ) : null}
                    {typeof item.source_count === "number" ? (
                      <Badge tone="default">{`来源 ${item.source_count}`}</Badge>
                    ) : null}
                  </div>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">定位 / 角色</p>
                    <p className="mt-1 text-sm text-[color:var(--ink)]">
                      {item.positioning || "正在整理该竞品的定位描述。"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">定价线索</p>
                    <p className="mt-1 text-sm text-[color:var(--ink)]">{item.pricing || "暂无定价线索"}</p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">核心差异</p>
                    <p className="mt-1 text-sm text-[color:var(--ink)]">
                      {item.differentiation || item.coverage_gap || "尚待补齐差异化证据。"}
                    </p>
                  </div>
                </div>
                {item.key_sources?.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {item.key_sources.map((source) => (
                      <Badge key={`${item.name}-${source}`} tone="default">
                        {source}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-[28px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.68)] px-4 py-6 text-sm text-[color:var(--muted)]">
            {job.competitor_count
              ? "已有竞品轮廓，继续补充角色/定价/差异描述即可完成结构化概览。"
              : "尚未识别竞品；待证据沉淀后，系统会自动填充竞品角色、定位与差异线索。"}
          </div>
        )}
      </Card>

      <Card className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>成稿门槛</CardTitle>
            <CardDescription>可分享版默认至少需要 1 条正式结论、2 条正式外部证据和 2 个独立域名。</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={finalizeBlocked ? "warning" : qualityReadiness === "可分享版" ? "success" : "default"}>{qualityReadiness}</Badge>
            {qualityScore !== null ? <Badge>{`质量分 ${qualityScore}`}</Badge> : null}
            {requiresFinalize ? <Badge tone="warning">有新草稿待生成稳定版</Badge> : null}
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">正式结论</p>
            <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{formalClaimCount}</p>
            <p className="mt-1 text-sm text-[color:var(--muted)]">{formalClaimCount >= 1 ? "已达到分享门槛" : "至少需要 1 条可追溯结论"}</p>
          </div>
          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">正式证据</p>
            <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{formalEvidenceCount}</p>
            <p className="mt-1 text-sm text-[color:var(--muted)]">{formalEvidenceCount >= 2 ? "数量已足够" : "至少需要 2 条正式外部证据"}</p>
          </div>
          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">独立域名</p>
            <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{formalDomainCount}</p>
            <p className="mt-1 text-sm text-[color:var(--muted)]">{formalDomainCount >= 2 ? "来源分散度已达标" : "至少需要 2 个独立来源域名"}</p>
          </div>
        </div>
        <p className="text-sm text-[color:var(--muted)]">
          {finalizeBlocked
            ? (qualityGate?.reasons || []).join("；") || "当前工作稿还不满足可分享版要求。"
            : requiresFinalize
              ? "PM Chat 已经沉淀了新的补研结果，先审阅最新草稿，再决定是否生成新的可分享版。"
              : "当前分数和门槛会随着证据、结论和版本状态实时刷新。"}
        </p>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1.12fr_0.88fr]">
        <AgentSwarmBoard job={job} onSelectTask={setSelectedTaskId} selectedTaskId={selectedTaskId} />

        <div className="space-y-6">
          <Card className="space-y-4">
            <div>
              <CardTitle>系统细节（可选）</CardTitle>
              <CardDescription>默认聚焦研究结论与缺口；需要排查时再展开运行环境和诊断信息。</CardDescription>
            </div>
            <details className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-3">
              <summary className="cursor-pointer list-none text-sm font-medium text-[color:var(--ink)]">
                展开运行环境、浏览器能力与报告门槛
              </summary>
              <div className="mt-3 grid gap-3">
                <div className="rounded-[24px] bg-[rgba(247,241,231,0.86)] p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">分析模型</p>
                  <div className="mt-2 flex items-center gap-2">
                    <Badge tone={job.runtime_summary?.llm_enabled ? "success" : "warning"}>{job.runtime_summary?.llm_enabled ? "可用" : "降级"}</Badge>
                    <span className="text-sm text-[color:var(--ink)]">{job.runtime_summary?.model ?? "未识别模型"}</span>
                  </div>
                  <p className="mt-2 text-sm text-[color:var(--muted)]">{job.runtime_summary?.validation_message ?? "暂无运行时说明"}</p>
                </div>
                <div className="rounded-[24px] bg-[rgba(247,241,231,0.86)] p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">浏览器能力</p>
                  <div className="mt-2 flex items-center gap-2">
                    <Badge tone={job.runtime_summary?.browser_available ? "success" : "warning"}>
                      {job.runtime_summary?.browser_available ? "可打开来源" : "仅静态抓取"}
                    </Badge>
                    <span className="text-sm text-[color:var(--ink)]">{browserModeLabel(job.runtime_summary?.browser_mode)}</span>
                  </div>
                  <p className="mt-2 text-sm text-[color:var(--muted)]">
                    {browserDiagnosticsText(job.runtime_summary?.browser_mode, job.runtime_summary?.browser_available)}
                  </p>
                </div>
                <div className="rounded-[24px] bg-[rgba(247,241,231,0.86)] p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">运行方式</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Badge tone={job.execution_mode === "subprocess" || job.execution_mode === "worker" ? "success" : "default"}>{executionModeLabel(job.execution_mode)}</Badge>
                    {workerActive ? (
                      <Badge tone="success">{job.execution_mode === "worker" ? "Worker 已领取" : "进程运行中"}</Badge>
                    ) : (
                      <Badge tone="warning">{job.execution_mode === "worker" ? "等待 Worker" : "未启动独立进程"}</Badge>
                    )}
                    {workerPid ? <Badge>{`PID ${workerPid}`}</Badge> : null}
                  </div>
                  <p className="mt-2 text-sm text-[color:var(--muted)]">
                    {job.execution_mode === "worker"
                      ? "任务会被投递到共享 worker 服务中执行，适合持续运行和服务端部署。"
                      : job.execution_mode === "subprocess"
                      ? "任务会在后台继续运行，即使离开当前页面也能继续推进。"
                      : "当前任务没有独立执行进程，通常只出现在演示或页面内执行场景。"}
                  </p>
                </div>
                <div className="rounded-[24px] bg-[rgba(247,241,231,0.86)] p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">报告阶段</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge tone={stableStage === "final" ? "success" : "warning"}>
                      {stableVersionId ? `稳定 · ${reportStageLabel(stableStage)}` : "稳定 · 待生成"}
                    </Badge>
                    {activeVersionId ? (
                      <Badge tone={hasVersionMismatch ? "warning" : "default"}>{`工作稿 · ${reportStageLabel(activeStage)}`}</Badge>
                    ) : null}
                    {finalizeBlocked ? <Badge tone="warning">终稿门槛未过</Badge> : null}
                    {typeof activeSnapshot?.revision_count === "number" ? <Badge>{`修订 ${activeSnapshot.revision_count}`}</Badge> : null}
                    {typeof activeSnapshot?.feedback_count === "number" ? <Badge>{`反馈 ${activeSnapshot.feedback_count}`}</Badge> : null}
                  </div>
                  <p className="mt-2 text-sm text-[color:var(--muted)]">
                    {finalizeBlocked
                      ? (qualityGate?.reasons || []).join("；") || "当前工作稿暂不满足正式版要求，系统已保留草稿。"
                      : hasVersionMismatch
                        ? "研究对话已经沉淀了新的补充结果，当前工作稿待生成稳定版后才会替换稳定版。"
                        : !hasStableVersion
                          ? "当前还没有稳定版。确认工作稿质量后生成稳定版，系统才会产出可分享版本。"
                          : activeStage === "feedback_pending"
                          ? "研究对话已经沉淀了新的补充结果，但还没重新整理进报告；需要你手动生成正式版。"
                          : "当前可以继续阅读报告、审查证据，或进入研究对话补充问题。"}
                  </p>
                </div>
              </div>
            </details>
          </Card>

          <Card className="space-y-4">
            <div>
              <CardTitle>最近活动</CardTitle>
              <CardDescription>按时间顺序查看任务推进、搜索结果和异常提示。</CardDescription>
            </div>
            <div className="space-y-3">
              {(job.activity_log ?? []).slice(-10).reverse().map((log) => (
                <div key={log.id} className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Activity className="h-4 w-4 text-[color:var(--accent)]" />
                      <Badge tone={log.level === "error" ? "danger" : log.level === "warning" ? "warning" : "default"}>
                        {activityLevelLabel(log.level)}
                      </Badge>
                    </div>
                    <span className="text-xs text-[color:var(--muted)]">{new Date(log.timestamp).toLocaleString()}</span>
                  </div>
                  <p className="mt-3 text-sm text-[color:var(--ink)]">{log.message}</p>
                </div>
              ))}
              {!(job.activity_log ?? []).length ? (
                <div className="rounded-[24px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.44)] px-4 py-8 text-sm text-[color:var(--muted)]">
                  当前还没有活动日志，任务开始执行后这里会持续追加搜索、抓取和成文过程。
                </div>
              ) : null}
            </div>
          </Card>
        </div>
      </div>

      <TaskDetailPanel job={job} />

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="space-y-4">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-[color:var(--muted)]" />
            <CardTitle>来源增长</CardTitle>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={normalizedSnapshot.source_growth}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d3dbe7" />
                <XAxis dataKey="label" stroke="#8090a5" />
                <YAxis stroke="#8090a5" />
                <Tooltip />
                <Line type="monotone" dataKey="value" stroke="#1d4c74" strokeWidth={2.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="space-y-4">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-[color:var(--muted)]" />
            <CardTitle>来源类型分布</CardTitle>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={normalizedSnapshot.source_mix}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d3dbe7" />
                <XAxis dataKey="name" stroke="#8090a5" />
                <YAxis stroke="#8090a5" />
                <Tooltip />
                <Bar dataKey="value" radius={[12, 12, 0, 0]}>
                  {normalizedSnapshot.source_mix.map((entry, index) => (
                    <Cell key={entry.name} fill={sourceColors[index % sourceColors.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="space-y-4">
          <div>
            <CardTitle>竞品覆盖</CardTitle>
            <CardDescription>{competitorCoverageDescription}</CardDescription>
          </div>
          <div className="space-y-3">
            {normalizedSnapshot.competitor_coverage.length ? (
              normalizedSnapshot.competitor_coverage.map((item) => (
                <div key={item.name}>
                  <div className="mb-2 flex items-center justify-between text-sm text-[color:var(--muted)]">
                    <span>{item.name}</span>
                    <span>{item.value} / 10</span>
                  </div>
                  <ProgressBar aria-label={`${item.name}竞品覆盖`} value={item.value * 10} />
                </div>
              ))
            ) : (
              <div className="rounded-[24px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.44)] px-4 py-6 text-sm text-[color:var(--muted)]">
                {competitorCoverageEmptyCopy}
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
