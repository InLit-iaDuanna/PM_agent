"use client";

/**
 * HomeDashboardRefactored
 *
 * 将原来 793 行的 home-dashboard 拆分为更清晰的结构：
 *
 * 1. ActiveResearchStrip  — 进行中的研究横向卡片
 * 2. MetricsGrid          — 4 个指标卡
 * 3. QuickLaunch          — 研究模板快速发起
 * 4. ActivityTimeline     — 最近活动时间线（分组显示）
 * 5. RecentJobsList       — 最近研究任务网格
 *
 * 所有业务逻辑（API 调用、filter、sort）来自原文件，只做 UI 层重构。
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, FileText, RefreshCw, ShieldCheck, Sparkles, Activity } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { orchestrationPresetCatalog } from "@pm-agent/research-core";
import type { ResearchJobRecord, WorkflowCommandId } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, ProgressBar, Skeleton, SkeletonCard, Timeline, type TimelineEvent } from "@pm-agent/ui";

import { fetchHealthStatus, fetchResearchJobs, getApiErrorMessage } from "../../../lib/api-client";
import { isTerminalJobStatus } from "../../../lib/polling";
import { useDraftStore } from "../store/draft-store";
import { RequestStateCard } from "./request-state-card";
import { commandIcons, formatSkillPack, formatWorkflowCommand, taskStatusTone, taskStatusLabel } from "./research-ui-utils";

// ─── Helpers (same as original) ────────────────────────────────────────────
function statusTone(s: ResearchJobRecord["status"]): "success" | "danger" | "warning" | "default" {
  if (s === "completed") return "success";
  if (s === "failed")    return "danger";
  if (s === "cancelled") return "warning";
  return "warning";
}

function statusLabel(s: ResearchJobRecord["status"]) {
  const map: Record<string, string> = {
    completed: "已完成", failed: "已失败", cancelled: "已取消",
    planning: "规划中", verifying: "校验中", synthesizing: "成文中",
  };
  return map[s] ?? "执行中";
}

function jobStatusTone(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode === "diagnostic") return "warning" as const;
  return statusTone(job.status);
}
function jobStatusLabel(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode === "diagnostic") return "诊断完成";
  return statusLabel(job.status);
}

function phaseLabel(phase: ResearchJobRecord["current_phase"]) {
  const map: Record<string, string> = {
    scoping: "界定范围", planning: "任务规划", collecting: "证据采集",
    verifying: "结论校验", synthesizing: "初稿成文", finalizing: "终稿整理",
  };
  return map[phase ?? ""] ?? phase ?? "";
}

function sortByUpdated(jobs: ResearchJobRecord[]) {
  return [...jobs].sort((a, b) => {
    const at = a.updated_at || a.completed_at || a.created_at || "";
    const bt = b.updated_at || b.completed_at || b.created_at || "";
    return bt.localeCompare(at);
  });
}

function compactNumber(n: number) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

// ─── Main Component ────────────────────────────────────────────────────────
export function HomeDashboardRefactored() {
  const router = useRouter();
  const draftCommand  = useDraftStore((s) => s.newResearchForm.workflow_command);
  const patchDraft    = useDraftStore((s) => s.patchNewResearchForm);

  const jobsQuery = useQuery({
    queryKey: ["research-jobs"],
    queryFn: fetchResearchJobs,
    refetchInterval: ({ state }) =>
      state.data?.some((j) => !isTerminalJobStatus(j.status)) ? 3000 : 10000,
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
        onAction={() => void jobsQuery.refetch()}
      />
    );
  }

  const allJobs    = sortByUpdated(jobsQuery.data ?? []);
  const activeJobs = allJobs.filter((j) => !isTerminalJobStatus(j.status));
  const latestCompleted = allJobs.find((j) => j.status === "completed" && j.completion_mode !== "diagnostic")
    ?? allJobs.find((j) => j.status === "completed");
  const focusJob = activeJobs[0] ?? latestCompleted ?? allJobs[0];

  const totalSources  = allJobs.reduce((s, j) => s + j.source_count, 0);
  const totalClaims   = allJobs.reduce((s, j) => s + j.claims_count, 0);
  const activeTaskCount  = activeJobs.reduce((s, j) => s + j.tasks.filter((t) => t.status === "running").length, 0);
  const totalReportJobs  = allJobs.filter((j) => j.report_version_id).length;

  // Activity timeline data
  const timelineEvents: TimelineEvent[] = allJobs
    .flatMap((j) =>
      (j.activity_log ?? []).map((log) => ({
        id: log.id,
        title: log.message,
        timestamp: log.timestamp,
        level: (log.level === "error" ? "error" : log.level === "warning" ? "warning" : "info") as TimelineEvent["level"],
        meta: j.topic,
      })),
    )
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
    .slice(0, 12);

  const applyCommand = (commandId: WorkflowCommandId) => {
    patchDraft({ workflow_command: commandId, research_mode: "deep" });
  };

  const isLoading = jobsQuery.isLoading;

  return (
    <div className="space-y-7">

      {/* ── Row 1: Metrics + Focus job ─────────────────────────────── */}
      <div className="grid gap-5 xl:grid-cols-[1fr_320px]">

        {/* Metrics grid */}
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {isLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                // eslint-disable-next-line react/no-array-index-key
                <div key={i} className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4 space-y-2">
                  <Skeleton h="0.7rem" w="50%" />
                  <Skeleton h="1.5rem" w="40%" />
                  <Skeleton h="0.7rem" w="70%" />
                </div>
              ))
            ) : (
              <>
                <MetricCard label="进行中研究" value={compactNumber(activeJobs.length)} helper="正在执行、校验或成文" />
                <MetricCard label="运行中任务" value={compactNumber(activeTaskCount)} helper="当前活跃子任务数" />
                <MetricCard label="沉淀来源"   value={compactNumber(totalSources)} helper="累计可追溯外部来源" />
                <MetricCard label="含报告版本" value={compactNumber(totalReportJobs)} helper="至少生成过一版报告" />
              </>
            )}
          </div>

          {/* Active jobs strip */}
          {activeJobs.length > 0 && (
            <div className="space-y-3">
              <p className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">进行中的研究</p>
              <div className="flex gap-3 overflow-x-auto pb-1">
                {activeJobs.map((job, i) => (
                  <button
                    key={job.id}
                    type="button"
                    onClick={() => router.push(`/research/jobs/${job.id}`)}
                    className="stagger-item min-w-[240px] flex-shrink-0 rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-4 text-left transition hover:border-[color:var(--accent)] hover:bg-white"
                    style={{ "--delay": `${i * 60}ms` } as React.CSSProperties}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <Badge tone="warning">{statusLabel(job.status)}</Badge>
                      <span className="text-[11px] text-[color:var(--muted)]">{job.overall_progress}%</span>
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm font-semibold text-[color:var(--ink)]">{job.topic}</p>
                    <div className="mt-2">
                      <ProgressBar aria-label={job.topic} value={job.overall_progress} />
                    </div>
                    <p className="mt-2 text-xs text-[color:var(--muted)]">{phaseLabel(job.current_phase)}</p>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Focus job + API status sidebar */}
        <div className="space-y-4">
          {/* Focus job */}
          {focusJob ? (
            <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.64)]">
              <p className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
                {activeJobs.length ? "当前重点研究" : "最近完成研究"}
              </p>
              <p className="mt-2 text-base font-semibold text-[color:var(--ink)] line-clamp-2">{focusJob.topic}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge tone={jobStatusTone(focusJob)}>{jobStatusLabel(focusJob)}</Badge>
                {focusJob.workflow_label && <Badge>{focusJob.workflow_label}</Badge>}
              </div>
              <div className="mt-3">
                <div className="mb-1.5 flex items-center justify-between text-xs text-[color:var(--muted)]">
                  <span>{phaseLabel(focusJob.current_phase)}</span>
                  <span>{focusJob.overall_progress}%</span>
                </div>
                <ProgressBar aria-label="焦点任务进度" value={focusJob.overall_progress} />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild variant="secondary">
                  <Link href={`/research/jobs/${focusJob.id}`}>打开研究页</Link>
                </Button>
                {focusJob.report_version_id && (
                  <Button asChild variant="ghost">
                    <Link href={`/research/jobs/${focusJob.id}/report`}>查看报告</Link>
                  </Button>
                )}
              </div>
            </div>
          ) : !isLoading ? (
            <div className="rounded-[28px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.4)] p-5 text-sm text-[color:var(--muted)]">
              还没有研究任务，先发起一条吧。
            </div>
          ) : (
            <SkeletonCard lines={5} />
          )}

          {/* System status mini */}
          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-[color:var(--muted)]">服务连接</span>
              <Badge tone={healthQuery.error ? "warning" : "success"}>
                {healthQuery.error ? "待检查" : "在线"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[color:var(--muted)]">模型配置</span>
              <Badge tone={healthQuery.data?.runtime_configured ? "success" : "warning"}>
                {healthQuery.data?.runtime_configured ? "已就绪" : "需配置"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[color:var(--muted)]">后台进程</span>
              <Badge>{healthQuery.data ? `${healthQuery.data.active_detached_worker_count} 个` : "--"}</Badge>
            </div>
          </div>
        </div>
      </div>

      {/* ── Row 2: Quick launch + Activity timeline ─────────────────── */}
      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">

        {/* Quick launch */}
        <Card className="space-y-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle>快速发起研究</CardTitle>
              <CardDescription>选择模板后直接跳转新建页，当前草稿会自动带入。</CardDescription>
            </div>
            <Button asChild>
              <Link href="/research/new">新建研究</Link>
            </Button>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            {(Object.entries(orchestrationPresetCatalog) as Array<
              [WorkflowCommandId, (typeof orchestrationPresetCatalog)[WorkflowCommandId]]
            >).map(([commandId, preset]) => {
              const Icon = commandIcons[commandId];
              const isSelected = draftCommand === commandId;
              return (
                <button
                  key={commandId}
                  type="button"
                  onClick={() => { applyCommand(commandId); router.push("/research/new"); }}
                  className={`card-lift rounded-[22px] border p-4 text-left transition ${
                    isSelected
                      ? "border-[color:var(--accent)] bg-[linear-gradient(135deg,rgba(29,76,116,0.08),rgba(255,255,255,0.9))]"
                      : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] hover:bg-white"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className={`shrink-0 rounded-[14px] p-2.5 ${isSelected ? "bg-[color:var(--accent)] text-white" : "bg-[rgba(29,76,116,0.1)] text-[color:var(--accent)]"}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-[color:var(--ink)]">{preset.label}</p>
                      <p className="mt-0.5 text-xs leading-5 text-[color:var(--muted)]">{preset.summary}</p>
                    </div>
                    {isSelected && <Badge tone="success" className="shrink-0">已选</Badge>}
                  </div>
                </button>
              );
            })}
          </div>
        </Card>

        {/* Activity timeline */}
        <Card className="space-y-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle>最近活动</CardTitle>
              <CardDescription>研究进展自动记录，按时间分组。</CardDescription>
            </div>
            <Button onClick={() => void jobsQuery.refetch()} type="button" variant="ghost">
              <RefreshCw className={`h-4 w-4 ${jobsQuery.isFetching ? "animate-spin" : ""}`} />
            </Button>
          </div>
          <Timeline events={timelineEvents} grouped />
        </Card>
      </div>

      {/* ── Row 3: Recent jobs grid ────────────────────────────────── */}
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
            最近研究任务
          </p>
          <Badge>{`${allJobs.length} 条记录`}</Badge>
        </div>

        {isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              // eslint-disable-next-line react/no-array-index-key
              <SkeletonCard key={i} lines={4} />
            ))}
          </div>
        ) : allJobs.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {allJobs.slice(0, 9).map((job, i) => (
              <div
                key={job.id}
                className="stagger-item card-lift rounded-[26px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-5"
                style={{ "--delay": `${i * 40}ms` } as React.CSSProperties}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-[color:var(--ink)]">{job.topic}</p>
                    <p className="mt-0.5 text-xs text-[color:var(--muted)]">
                      {job.updated_at ? new Date(job.updated_at).toLocaleString() : "刚刚更新"}
                    </p>
                  </div>
                  <Badge tone={jobStatusTone(job)}>{jobStatusLabel(job)}</Badge>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Badge>{`${job.source_count} 来源`}</Badge>
                  <Badge>{`${job.claims_count} 判断`}</Badge>
                  {job.report_version_id && <Badge tone="success">有报告</Badge>}
                </div>

                <div className="mt-3">
                  <div className="mb-1 flex items-center justify-between text-xs text-[color:var(--muted)]">
                    <span>{phaseLabel(job.current_phase)}</span>
                    <span>{job.overall_progress}%</span>
                  </div>
                  <ProgressBar aria-label={job.topic} value={job.overall_progress} />
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <Button asChild variant="secondary">
                    <Link href={`/research/jobs/${job.id}`}>打开</Link>
                  </Button>
                  {job.report_version_id && (
                    <Button asChild variant="ghost">
                      <Link href={`/research/jobs/${job.id}/report`}>
                        报告
                        <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
                      </Link>
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-[28px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.4)] px-4 py-12 text-center text-sm text-[color:var(--muted)]">
            还没有研究记录。先创建一条任务，后续这里会自动保留任务、报告和追问入口。
          </div>
        )}
      </div>

    </div>
  );
}

// ─── MetricCard ────────────────────────────────────────────────────────────
function MetricCard({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="card-lift rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.62)]">
      <p className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{value}</p>
      <p className="mt-1 text-xs text-[color:var(--muted)]">{helper}</p>
    </div>
  );
}
