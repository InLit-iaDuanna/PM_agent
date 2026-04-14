"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  Activity,
  ArrowRight,
  Clock3,
  FileText,
  FolderSearch2,
  Layers3,
  MessageSquareText,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { orchestrationPresetCatalog } from "@pm-agent/research-core";
import type { ResearchJobRecord, WorkflowCommandId } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, Input, ProgressBar } from "@pm-agent/ui";

import { fetchHealthStatus, fetchResearchJobs, getApiErrorMessage } from "../../../lib/api-client";
import { isTerminalJobStatus } from "../../../lib/polling";
import { useDraftStore } from "../store/draft-store";
import { RequestStateCard } from "./request-state-card";
import { activityLevelLabel, commandIcons, commandUsage, formatSkillPack, formatWorkflowCommand, taskStatusLabel, taskStatusTone } from "./research-ui-utils";

function statusTone(status: ResearchJobRecord["status"]) {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "warning";
  return "warning";
}

function jobStatusTone(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode === "diagnostic") return "warning";
  return statusTone(job.status);
}

function statusLabel(status: ResearchJobRecord["status"]) {
  if (status === "completed") return "已完成";
  if (status === "failed") return "已失败";
  if (status === "cancelled") return "已取消";
  if (status === "planning") return "规划中";
  if (status === "verifying") return "校验中";
  if (status === "synthesizing") return "成文中";
  return "执行中";
}

function jobStatusLabel(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode === "diagnostic") return "诊断完成";
  return statusLabel(job.status);
}

function phaseLabel(phase: ResearchJobRecord["current_phase"]) {
  if (phase === "scoping") return "界定范围";
  if (phase === "planning") return "任务规划";
  if (phase === "collecting") return "证据采集";
  if (phase === "verifying") return "结论校验";
  if (phase === "synthesizing") return "初稿成文";
  if (phase === "finalizing") return "终稿整理";
  return phase;
}

function sortJobsByUpdated(jobs: ResearchJobRecord[]) {
  return [...jobs].sort((left, right) => {
    const leftTimestamp = left.updated_at || left.completed_at || left.created_at || "";
    const rightTimestamp = right.updated_at || right.completed_at || right.created_at || "";
    return rightTimestamp.localeCompare(leftTimestamp);
  });
}

function matchesQuery(values: Array<string | undefined>, query: string) {
  if (!query) return true;
  return values.some((value) => value?.toLowerCase().includes(query));
}

function compactNumber(value: number) {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return String(value);
}

function MetricTile({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="rounded-[26px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.62)]">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{value}</p>
      <p className="mt-1 text-sm text-[color:var(--muted)]">{helper}</p>
    </div>
  );
}

export function HomeDashboard() {
  const router = useRouter();
  const draftCommand = useDraftStore((state) => state.newResearchForm.workflow_command);
  const patchNewResearchForm = useDraftStore((state) => state.patchNewResearchForm);
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const jobsQuery = useQuery({
    queryKey: ["research-jobs"],
    queryFn: fetchResearchJobs,
    refetchInterval: ({ state }) => (state.data?.some((job) => !isTerminalJobStatus(job.status)) ? 3000 : 10000),
  });
  const healthQuery = useQuery({
    queryKey: ["api-health"],
    queryFn: fetchHealthStatus,
    refetchInterval: 5000,
  });

  if (jobsQuery.error) {
    return (
      <RequestStateCard
        title="研究历史加载失败"
        description={getApiErrorMessage(jobsQuery.error, "无法读取研究历史，请检查 API 是否已启动。")}
        actionLabel="重试"
        onAction={() => {
          void jobsQuery.refetch();
        }}
      />
    );
  }

  const jobs = sortJobsByUpdated(jobsQuery.data ?? []);
  const activeJobs = jobs.filter((job) => !["completed", "failed", "cancelled"].includes(job.status));
  const latestCompletedJob =
    jobs.find((job) => job.status === "completed" && job.completion_mode !== "diagnostic") ?? jobs.find((job) => job.status === "completed");
  const focusJob = activeJobs[0] ?? latestCompletedJob ?? jobs[0];
  const focusCommand = focusJob?.workflow_command || draftCommand || "deep_general_scan";
  const focusPreset = orchestrationPresetCatalog[focusCommand];
  const lastSyncedLabel = jobsQuery.dataUpdatedAt ? new Date(jobsQuery.dataUpdatedAt).toLocaleString() : null;
  const activeTaskCount = activeJobs.reduce((sum, job) => sum + job.tasks.filter((task) => task.status === "running").length, 0);
  const queuedTaskCount = activeJobs.reduce((sum, job) => sum + job.tasks.filter((task) => task.status === "queued").length, 0);
  const totalSources = jobs.reduce((sum, job) => sum + job.source_count, 0);
  const totalClaims = jobs.reduce((sum, job) => sum + job.claims_count, 0);
  const totalReportBackedJobs = jobs.filter((job) => job.report_version_id).length;
  const totalReportContextJobs = jobs.filter((job) => job.report_version_id && job.status !== "failed").length;
  const continueLabel = activeJobs.length ? "继续当前研究" : "查看最近研究";
  const launchLabel = draftCommand ? `发起新研究（${orchestrationPresetCatalog[draftCommand].label}）` : "发起新研究";
  const activityFeed = jobs
    .flatMap((job) =>
      (job.activity_log ?? []).map((log) => ({
        ...log,
        jobId: job.id,
        topic: job.topic,
        status: job.status,
      })),
    )
    .sort((left, right) => right.timestamp.localeCompare(left.timestamp))
    .slice(0, 8);
  const swarmRows = (activeJobs.length ? activeJobs : jobs.slice(0, 1))
    .flatMap((job) =>
      job.tasks.map((task) => ({
        jobId: job.id,
        jobTopic: job.topic,
        jobStatus: job.status,
        task,
      })),
    )
    .filter(({ jobTopic, task }) =>
      matchesQuery(
        [jobTopic, task.title, task.brief, task.agent_name, task.current_action, ...(task.search_queries ?? []), ...(task.skill_packs ?? [])],
        normalizedQuery,
      ),
    )
    .sort((left, right) => {
      const leftRank = left.task.status === "running" ? 0 : left.task.status === "queued" ? 1 : left.task.status === "failed" ? 2 : 3;
      const rightRank = right.task.status === "running" ? 0 : right.task.status === "queued" ? 1 : right.task.status === "failed" ? 2 : 3;
      if (leftRank !== rightRank) return leftRank - rightRank;
      return (right.task.progress ?? 0) - (left.task.progress ?? 0);
    })
    .slice(0, 10);
  const commandEntries = (Object.entries(orchestrationPresetCatalog) as Array<
    [WorkflowCommandId, (typeof orchestrationPresetCatalog)[WorkflowCommandId]]
  >)
    .filter(([commandId, preset]) =>
      matchesQuery(
        [commandId, preset.label, preset.summary, preset.focusInstruction, ...(preset.recommendedFor ?? []), ...(preset.defaultSkillPacks ?? [])],
        normalizedQuery,
      ),
    )
    .slice(0, 5);
  const filteredJobs = jobs
    .filter((job) =>
      matchesQuery([job.topic, job.workflow_label, job.project_memory, job.orchestration_summary, job.report_version_id], normalizedQuery),
    )
    .slice(0, 8);

  const applyCommandToDraft = (commandId: WorkflowCommandId) => {
    patchNewResearchForm({
      workflow_command: commandId,
      research_mode: "deep",
    });
  };

  return (
    <div className="space-y-6">
      <section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="data-grid-bg relative overflow-hidden">
          <div className="absolute inset-x-0 top-0 h-28 bg-[radial-gradient(circle_at_top_left,_rgba(29,76,116,0.18),_transparent_60%)]" />
          <div className="relative space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="success">研究首页</Badge>
                <Badge>{focusPreset.label}</Badge>
                <Badge tone={healthQuery.error ? "warning" : "success"}>
                  {healthQuery.error ? "连接待检查" : "连接正常"}
                </Badge>
              </div>
              {lastSyncedLabel ? <p className="text-xs text-[color:var(--muted)]">{`最近同步：${lastSyncedLabel}`}</p> : null}
            </div>

            <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
              <div className="space-y-5">
                <div className="space-y-3">
                  <p className="text-xs uppercase tracking-[0.3em] text-[color:var(--muted)]">继续你的研究流</p>
                  <CardTitle className="max-w-4xl text-4xl leading-[1.05] sm:text-[3.4rem]">
                    先续接，再扩展，不再从零开始。
                  </CardTitle>
                  <CardDescription className="max-w-3xl text-base leading-7">
                    首页默认只做两件事: 带你回到正在推进的研究，或立即发起新的研究任务。
                  </CardDescription>
                </div>

                <div className="flex flex-wrap gap-3">
                  <Button asChild>
                    <Link href="/research/new">{launchLabel}</Link>
                  </Button>
                  {focusJob ? (
                    <Button asChild variant="secondary">
                      <Link href={`/research/jobs/${focusJob.id}`}>{continueLabel}</Link>
                    </Button>
                  ) : (
                    <Button disabled type="button" variant="secondary">
                      暂无研究任务
                    </Button>
                  )}
                  <Button asChild variant="ghost">
                    <Link href="/settings/runtime">系统设置</Link>
                  </Button>
                </div>

                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  <MetricTile label="可继续研究" value={compactNumber(activeJobs.length)} helper="正在执行、校验或成文中的任务" />
                  <MetricTile label="本轮推进任务" value={compactNumber(activeTaskCount)} helper="当前仍在运行的研究子任务" />
                  <MetricTile label="已沉淀来源" value={compactNumber(totalSources)} helper="累计可追溯的外部来源数量" />
                  <MetricTile label="含报告版本" value={compactNumber(totalReportBackedJobs)} helper="至少生成过一版报告的任务数" />
                </div>
              </div>

              <div className="space-y-4">
                <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.64)]">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">当前应继续的研究</p>
                      <p className="mt-2 text-lg font-semibold tracking-[-0.03em] text-[color:var(--ink)]">
                        {focusJob?.topic ?? "还没有研究任务"}
                      </p>
                    </div>
                    <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50/80 px-3 py-1 text-xs font-medium text-emerald-800">
                      <span className="signal-dot" />
                      {healthQuery.error ? "连接待检查" : "系统在线"}
                    </div>
                  </div>
                  {focusJob ? (
                    <>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <Badge tone={jobStatusTone(focusJob)}>{jobStatusLabel(focusJob)}</Badge>
                        <Badge>{phaseLabel(focusJob.current_phase)}</Badge>
                        {focusJob.workflow_label ? <Badge>{focusJob.workflow_label}</Badge> : null}
                        {focusJob.report_version_id ? <Badge>{focusJob.report_version_id}</Badge> : null}
                      </div>
                      <div className="mt-4">
                        <div className="mb-2 flex items-center justify-between text-sm text-[color:var(--muted)]">
                          <span>主任务进度</span>
                          <span>{focusJob.overall_progress}%</span>
                        </div>
                        <ProgressBar aria-label="焦点任务进度" value={focusJob.overall_progress} />
                      </div>
                      <div className="mt-4 grid gap-3 sm:grid-cols-2">
                        <div className="rounded-2xl bg-[rgba(247,241,231,0.8)] p-4">
                          <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">现在拿到了什么</p>
                          <p className="mt-2 text-sm text-[color:var(--ink)]">
                            {`${focusJob.source_count} 条来源，${focusJob.claims_count} 条判断，${focusJob.completed_task_count}/${focusJob.tasks.length} 个子任务已完成。`}
                          </p>
                        </div>
                        <div className="rounded-2xl bg-[rgba(247,241,231,0.8)] p-4">
                          <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">下一步建议</p>
                          <p className="mt-2 text-sm text-[color:var(--ink)]">
                            {focusJob.orchestration_summary || "可继续查看证据、报告版本，或基于当前结果发起追问。"}
                          </p>
                        </div>
                      </div>
                    </>
                  ) : (
                    <p className="mt-4 text-sm leading-7 text-[color:var(--muted)]">
                      先发起一条研究任务，系统会在后续自动保留进展、来源和报告，方便你随时续接。
                    </p>
                  )}
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">等待推进</p>
                    <p className="mt-2 text-xl font-semibold text-[color:var(--ink)]">{queuedTaskCount}</p>
                    <p className="mt-1 text-sm text-[color:var(--muted)]">待开始的子任务</p>
                  </div>
                  <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">可读报告</p>
                    <p className="mt-2 text-xl font-semibold text-[color:var(--ink)]">{totalReportBackedJobs}</p>
                    <p className="mt-1 text-sm text-[color:var(--muted)]">至少生成过一版报告的任务数</p>
                  </div>
                  <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">报告上下文</p>
                    <p className="mt-2 text-xl font-semibold text-[color:var(--ink)]">{totalReportContextJobs}</p>
                    <p className="mt-1 text-sm text-[color:var(--muted)]">可作为后续对话基础的任务（以页面实际可用为准）</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </Card>

        <div className="space-y-6">
          <Card className="space-y-5">
            <div className="flex items-start gap-3">
              <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.74)] p-3 text-[color:var(--accent)]">
                <FolderSearch2 className="h-5 w-5" />
              </div>
              <div>
                <CardTitle>快速续接</CardTitle>
                <CardDescription>输入关键词后，可直接跳回任务，或选模板跳转到新建页继续发起。</CardDescription>
              </div>
            </div>

            <Input
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索主题、模板、任务动作或标签..."
              value={query}
            />

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">可用模板（点击进入新建页）</p>
                {commandEntries.length ? (
                  commandEntries.map(([commandId, preset]) => {
                    const Icon = commandIcons[commandId];
                    return (
                      <button
                        key={commandId}
                        className="w-full rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] px-4 py-4 text-left transition hover:border-[color:var(--border-strong)] hover:bg-white"
                        onClick={() => {
                          applyCommandToDraft(commandId);
                          router.push("/research/new");
                        }}
                        type="button"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-3">
                            <div className="rounded-2xl bg-[rgba(29,76,116,0.1)] p-3 text-[color:var(--accent)]">
                              <Icon className="h-4 w-4" />
                            </div>
                            <div>
                              <p className="text-sm font-semibold text-[color:var(--ink)]">{preset.label}</p>
                              <p className="mt-1 text-sm text-[color:var(--muted)]">{preset.summary}</p>
                            </div>
                          </div>
                          {draftCommand === commandId ? <Badge tone="success">已选</Badge> : null}
                        </div>
                      </button>
                    );
                  })
                ) : (
                  <div className="rounded-[24px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.44)] px-4 py-6 text-sm text-[color:var(--muted)]">
                    没找到匹配模板，换个关键词再试。
                  </div>
                )}
              </div>

              <div className="space-y-3">
                <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">可继续任务</p>
                {filteredJobs.length ? (
                  filteredJobs.map((job) => (
                    <button
                      key={job.id}
                      className="w-full rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] px-4 py-4 text-left transition hover:border-[color:var(--border-strong)] hover:bg-white"
                      onClick={() => router.push(`/research/jobs/${job.id}`)}
                      type="button"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-[color:var(--ink)]">{job.topic}</p>
                          <p className="mt-1 text-sm text-[color:var(--muted)]">{`${phaseLabel(job.current_phase)} · ${job.source_count} 来源 · ${job.claims_count} 判断`}</p>
                        </div>
                        <Badge tone={jobStatusTone(job)}>{jobStatusLabel(job)}</Badge>
                      </div>
                    </button>
                  ))
                ) : (
                  <div className="rounded-[24px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.44)] px-4 py-6 text-sm text-[color:var(--muted)]">
                    没找到匹配任务，试试产品名、报告版本号或任务标题。
                  </div>
                )}
              </div>
            </div>
          </Card>

          <Card className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle>系统状态（辅助信息）</CardTitle>
                <CardDescription>仅在排查异常时查看，不影响你继续研究。</CardDescription>
              </div>
              <Button onClick={() => void jobsQuery.refetch()} type="button" variant="secondary">
                <RefreshCw className={`mr-2 h-4 w-4 ${jobsQuery.isFetching ? "animate-spin" : ""}`} />
                刷新
              </Button>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] px-4 py-3">
                <div className="flex items-center gap-3">
                  <ShieldCheck className="h-4 w-4 text-[color:var(--accent)]" />
                  <span className="text-sm text-[color:var(--ink)]">服务连接</span>
                </div>
                <Badge tone={healthQuery.error ? "warning" : "success"}>
                  {healthQuery.error ? "待检查" : "在线"}
                </Badge>
              </div>
              <div className="flex items-center justify-between rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] px-4 py-3">
                <div className="flex items-center gap-3">
                  <Sparkles className="h-4 w-4 text-[color:var(--accent)]" />
                  <span className="text-sm text-[color:var(--ink)]">模型配置</span>
                </div>
                <Badge tone={healthQuery.data?.runtime_configured ? "success" : "warning"}>
                  {healthQuery.data?.runtime_configured ? "已就绪" : "需要配置"}
                </Badge>
              </div>
              <div className="flex items-center justify-between rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] px-4 py-3">
                <div className="flex items-center gap-3">
                  <Activity className="h-4 w-4 text-[color:var(--accent)]" />
                  <span className="text-sm text-[color:var(--ink)]">后台处理</span>
                </div>
                <Badge>{healthQuery.data ? `${healthQuery.data.active_detached_worker_count} 个` : "--"}</Badge>
              </div>
            </div>

            <p className="text-sm leading-7 text-[color:var(--muted)]">
              {healthQuery.data
                ? `当前有 ${healthQuery.data.active_job_count} 个研究仍在进行，后台执行进程 ${healthQuery.data.active_detached_worker_count} 个。`
                : healthQuery.error
                ? getApiErrorMessage(healthQuery.error, "健康检查失败。")
                : "正在读取服务状态。"}
            </p>
          </Card>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[0.96fr_1.04fr]">
        <Card className="space-y-5">
          <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle>发起新研究（模板可选）</CardTitle>
                <CardDescription>当你需要新的研究分支时，在这里一键套用模板。</CardDescription>
              </div>
              <Badge>{`${commandEntries.length || Object.keys(orchestrationPresetCatalog).length} 个模板`}</Badge>
            </div>

          <div className="grid gap-4">
            {(normalizedQuery ? commandEntries : (Object.entries(orchestrationPresetCatalog) as Array<
              [WorkflowCommandId, (typeof orchestrationPresetCatalog)[WorkflowCommandId]]
            >)).map(([commandId, preset]) => {
              const Icon = commandIcons[commandId];
              const usage = commandUsage(jobs, commandId);
              const isSelected = draftCommand === commandId;
              return (
                <div
                  key={commandId}
                  className={`rounded-[28px] border p-5 transition ${
                    isSelected
                      ? "border-[color:var(--accent)] bg-[linear-gradient(135deg,_rgba(29,76,116,0.1),_rgba(255,255,255,0.78))]"
                      : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div className={`rounded-[20px] p-3 ${isSelected ? "bg-[color:var(--accent)] text-white" : "bg-[rgba(29,76,116,0.1)] text-[color:var(--accent)]"}`}>
                        <Icon className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="text-base font-semibold text-[color:var(--ink)]">{preset.label}</p>
                        <p className="mt-1 text-sm leading-6 text-[color:var(--muted)]">{preset.summary}</p>
                      </div>
                    </div>
                    {isSelected ? <Badge tone="success">当前选择</Badge> : <Badge>{formatWorkflowCommand(commandId)}</Badge>}
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <div className="rounded-2xl bg-[rgba(247,241,231,0.82)] p-4">
                      <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">研究焦点</p>
                      <p className="mt-2 text-sm text-[color:var(--ink)]">{preset.focusInstruction}</p>
                    </div>
                    <div className="rounded-2xl bg-[rgba(247,241,231,0.82)] p-4">
                      <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">历史使用</p>
                      <p className="mt-2 text-sm text-[color:var(--ink)]">
                        {usage.total ? `已有 ${usage.total} 条任务使用此模板` : "当前还没有历史使用记录"}
                      </p>
                      <p className="mt-1 text-xs text-[color:var(--muted)]">{usage.latest?.topic ?? "适合直接发起新的研究任务"}</p>
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {(preset.defaultSkillPacks ?? []).map((item) => (
                      <Badge key={item}>{formatSkillPack(item)}</Badge>
                    ))}
                    {(preset.recommendedFor ?? []).map((item) => (
                      <Badge key={item} tone="success">
                        {item}
                      </Badge>
                    ))}
                  </div>

                  <div className="mt-5 flex flex-wrap gap-3">
                    <Button
                      onClick={() => applyCommandToDraft(commandId)}
                      type="button"
                      variant={isSelected ? "primary" : "secondary"}
                    >
                      设为当前模板
                    </Button>
                    <Button
                      onClick={() => {
                        applyCommandToDraft(commandId);
                        router.push("/research/new");
                      }}
                      type="button"
                      variant="ghost"
                    >
                      以此模板新建
                    </Button>
                    {usage.latest ? (
                      <Button onClick={() => router.push(`/research/jobs/${usage.latest?.id}`)} type="button" variant="ghost">
                        打开最近任务
                      </Button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        <div className="space-y-6">
          <Card className="space-y-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle>继续中的研究项</CardTitle>
                <CardDescription>优先看正在推进或阻塞的项，快速决定下一步动作。</CardDescription>
              </div>
              <Badge>{`${swarmRows.length} 条可见研究项`}</Badge>
            </div>

            <div className="space-y-3">
              {swarmRows.length ? (
                swarmRows.map(({ jobId, jobTopic, task }) => (
                  <button
                    key={`${jobId}-${task.id}`}
                    className="w-full rounded-[26px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] px-4 py-4 text-left transition hover:border-[color:var(--border-strong)] hover:bg-white"
                    onClick={() => router.push(`/research/jobs/${jobId}`)}
                    type="button"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">{jobTopic}</p>
                        <p className="mt-2 text-base font-semibold text-[color:var(--ink)]">{task.title}</p>
                        <p className="mt-1 text-sm text-[color:var(--muted)]">{task.current_action || task.brief}</p>
                      </div>
                      <Badge tone={taskStatusTone(task.status)}>{taskStatusLabel(task.status)}</Badge>
                    </div>
                    <div className="mt-4">
                        <div className="mb-2 flex items-center justify-between text-xs text-[color:var(--muted)]">
                        <span>{task.agent_name || "研究环节"}</span>
                        <span>{`${task.progress ?? 0}%`}</span>
                      </div>
                      <ProgressBar aria-label={`${task.title}进度`} value={task.progress ?? 0} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge>{`${task.source_count} 来源`}</Badge>
                      {task.command_label ? <Badge>{task.command_label}</Badge> : null}
                      {(task.skill_packs ?? []).slice(0, 2).map((item) => (
                        <Badge key={item} tone="success">
                          {formatSkillPack(item)}
                        </Badge>
                      ))}
                    </div>
                  </button>
                ))
              ) : (
                <div className="rounded-[26px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.4)] px-4 py-8 text-sm text-[color:var(--muted)]">
                  当前没有匹配到进行中的任务。可以清空搜索条件，或先发起新的研究任务。
                </div>
              )}
            </div>
          </Card>

          <Card className="space-y-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle>最近活动（辅助）</CardTitle>
                <CardDescription>这里保留系统事件流水，供你在需要时回看。</CardDescription>
              </div>
              <Badge tone="success">自动刷新</Badge>
            </div>

            <div className="space-y-3">
              {activityFeed.length ? (
                activityFeed.map((log) => (
                  <button
                    key={log.id}
                    className="w-full rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-4 text-left transition hover:border-[color:var(--border-strong)] hover:bg-white"
                    onClick={() => router.push(`/research/jobs/${log.jobId}`)}
                    type="button"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <Badge tone={log.level === "error" ? "danger" : log.level === "warning" ? "warning" : "default"}>
                          {activityLevelLabel(log.level)}
                        </Badge>
                        <span className="text-xs text-[color:var(--muted)]">{log.topic}</span>
                      </div>
                      <span className="text-xs text-[color:var(--muted)]">{new Date(log.timestamp).toLocaleString()}</span>
                    </div>
                    <p className="mt-3 text-sm text-[color:var(--ink)]">{log.message}</p>
                  </button>
                ))
              ) : (
                <div className="rounded-[24px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.4)] px-4 py-8 text-sm text-[color:var(--muted)]">
                  当前还没有活动记录。研究开始后，这里会持续记录关键进展。
                </div>
              )}
            </div>
          </Card>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
        <Card className="space-y-5">
          <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle>最近研究任务</CardTitle>
                <CardDescription>从这里直接回到研究页或报告页，继续上次上下文。</CardDescription>
              </div>
            <Badge>{`${jobs.length} 条记录`}</Badge>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {jobs.length ? (
              jobs.slice(0, 8).map((job) => (
                <div key={job.id} className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-[color:var(--ink)]">{job.topic}</p>
                      <p className="mt-1 text-xs text-[color:var(--muted)]">
                        {job.updated_at ? new Date(job.updated_at).toLocaleString() : "刚刚更新"}
                      </p>
                    </div>
                    <Badge tone={jobStatusTone(job)}>{jobStatusLabel(job)}</Badge>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <Badge>{`${job.source_count} 来源`}</Badge>
                    <Badge>{`${job.claims_count} 判断`}</Badge>
                    {job.workflow_label ? <Badge>{job.workflow_label}</Badge> : null}
                    {job.report_version_id ? <Badge>{job.report_version_id}</Badge> : null}
                  </div>

                  <div className="mt-4 space-y-2">
                    <div className="flex items-center justify-between text-sm text-[color:var(--muted)]">
                      <span>{phaseLabel(job.current_phase)}</span>
                      <span>{job.overall_progress}%</span>
                    </div>
                    <ProgressBar aria-label={`${job.topic}进度`} value={job.overall_progress} />
                  </div>

                  <div className="mt-5 flex flex-wrap gap-3">
                    <Button asChild variant="secondary">
                      <Link href={`/research/jobs/${job.id}`}>打开研究页</Link>
                    </Button>
                    {job.report_version_id ? (
                      <Button asChild variant="ghost">
                        <Link href={`/research/jobs/${job.id}/report`}>
                          查看报告
                          <ArrowRight className="ml-2 h-4 w-4" />
                        </Link>
                      </Button>
                    ) : null}
                  </div>
                </div>
              ))
            ) : jobsQuery.isLoading ? (
              <div className="rounded-[28px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.4)] px-4 py-8 text-sm text-[color:var(--muted)]">
                正在读取历史任务…
              </div>
            ) : (
              <div className="rounded-[28px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.4)] px-4 py-8 text-sm text-[color:var(--muted)]">
                还没有研究记录。先创建一条任务，后续这里会自动保留任务、报告和追问入口。
              </div>
            )}
          </div>
        </Card>

        <div className="space-y-6">
          <Card className="space-y-5">
            <div>
              <CardTitle>研究沉淀</CardTitle>
              <CardDescription>快速查看这批任务已经沉淀了多少可用依据和成文成果。</CardDescription>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
                <div className="flex items-center gap-2 text-[color:var(--accent)]">
                  <SearchCheck className="h-4 w-4" />
                  <p className="text-sm font-semibold text-[color:var(--ink)]">证据覆盖</p>
                </div>
                <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{compactNumber(totalSources)}</p>
                <p className="mt-1 text-sm text-[color:var(--muted)]">累计来源数量，用于判断覆盖是否足够。</p>
              </div>
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
                <div className="flex items-center gap-2 text-[color:var(--accent)]">
                  <Layers3 className="h-4 w-4" />
                  <p className="text-sm font-semibold text-[color:var(--ink)]">结论条目</p>
                </div>
                <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{compactNumber(totalClaims)}</p>
                <p className="mt-1 text-sm text-[color:var(--muted)]">累计结论条目，可回溯支持报告和追问。</p>
              </div>
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
                <div className="flex items-center gap-2 text-[color:var(--accent)]">
                  <FileText className="h-4 w-4" />
                  <p className="text-sm font-semibold text-[color:var(--ink)]">成文版本</p>
                </div>
                <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{totalReportBackedJobs}</p>
                <p className="mt-1 text-sm text-[color:var(--muted)]">已经产出报告版本的任务数。</p>
              </div>
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4">
                <div className="flex items-center gap-2 text-[color:var(--accent)]">
                  <MessageSquareText className="h-4 w-4" />
                  <p className="text-sm font-semibold text-[color:var(--ink)]">报告上下文任务</p>
                </div>
                <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{totalReportContextJobs}</p>
                <p className="mt-1 text-sm text-[color:var(--muted)]">已沉淀报告上下文，可作为后续对话基础。</p>
              </div>
            </div>
          </Card>

          <Card className="space-y-4">
            <div>
              <CardTitle>建议动作</CardTitle>
              <CardDescription>保持节奏: 先续接进行中的研究，再决定是否开新分支。</CardDescription>
            </div>
            <div className="space-y-3">
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-4">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-[color:var(--accent)]" />
                  <p className="text-sm font-semibold text-[color:var(--ink)]">1. 先续接当前研究</p>
                </div>
                <p className="mt-2 text-sm text-[color:var(--muted)]">优先处理正在推进的任务，先把当前证据链补完整。</p>
              </div>
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-4">
                <div className="flex items-center gap-2">
                  <Clock3 className="h-4 w-4 text-[color:var(--accent)]" />
                  <p className="text-sm font-semibold text-[color:var(--ink)]">2. 看缺口再开新分支</p>
                </div>
                <p className="mt-2 text-sm text-[color:var(--muted)]">确认还缺哪些关键依据后，再选择模板发起补证任务。</p>
              </div>
              <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-4">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-[color:var(--accent)]" />
                  <p className="text-sm font-semibold text-[color:var(--ink)]">3. 通过报告继续追问</p>
                </div>
                <p className="mt-2 text-sm text-[color:var(--muted)]">把阶段结论沉淀到报告，再基于报告继续追问和迭代。</p>
              </div>
            </div>
          </Card>
        </div>
      </section>
    </div>
  );
}
