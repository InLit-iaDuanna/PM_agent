"use client";

import Link from "next/link";
import { useState } from "react";
import { Database, Flag, Layers3, Activity, FileText, MessageSquareText } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useQueryClient } from "@tanstack/react-query";

import type { ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, ProgressBar, StatCard, StepIndicator } from "@pm-agent/ui";

import { cancelResearchJob, getApiErrorMessage } from "../../../../lib/api-client";
import { useResearchUiStore } from "../../store/ui-store";
import { getActiveReportVersionId, getReportVersions, getStableReportVersionId } from "../report-version-utils";
import { formatMarketStep } from "../research-ui-utils";

// ─── Phase steps ───────────────────────────────────────────────────────────
const PHASE_STEPS = [
  { id: "scoping",      label: "界定范围" },
  { id: "planning",     label: "任务规划" },
  { id: "collecting",   label: "证据采集" },
  { id: "verifying",    label: "结论校验" },
  { id: "synthesizing", label: "初稿成文" },
  { id: "finalizing",   label: "终稿整理" },
];

const SOURCE_COLORS = ["#1d4c74", "#355f88", "#8d9ab0", "#d7b786"];

// ─── Helpers (same as original job-dashboard) ──────────────────────────────
function phaseLabel(phase?: string) {
  const map: Record<string, string> = {
    scoping: "界定范围", planning: "任务规划", collecting: "证据采集",
    verifying: "结论校验", synthesizing: "初稿成文", finalizing: "终稿整理",
  };
  return map[phase ?? ""] ?? phase ?? "未知阶段";
}

function reportStageLabel(stage?: string) {
  if (stage === "final")           return "稳定版";
  if (stage === "feedback_pending") return "补研待合入";
  if (stage === "draft")           return "草稿";
  if (stage === "draft_pending")   return "生成中";
  return "待初稿";
}

function isDiagnosticJob(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  return job.status === "completed" && job.completion_mode === "diagnostic";
}

function jobStatusLabel(
  status: ResearchJobRecord["status"],
  workerActive = false,
  completionMode?: ResearchJobRecord["completion_mode"],
) {
  if (status === "completed" && completionMode === "diagnostic") return "诊断完成";
  if (status === "completed")  return "已完成";
  if (status === "failed")     return "已失败";
  if (status === "cancelled")  return workerActive ? "取消中" : "已取消";
  if (status === "planning")   return "规划中";
  if (status === "verifying")  return "校验中";
  if (status === "synthesizing") return "成文中";
  return "执行中";
}

// ─── Component ─────────────────────────────────────────────────────────────
interface JobOverviewTabProps {
  job: ResearchJobRecord;
  assets: ResearchAssetsRecord;
}

export function JobOverviewTab({ job, assets }: JobOverviewTabProps) {
  const queryClient = useQueryClient();
  const { setSelectedTaskId } = useResearchUiStore();
  const [cancelPending, setCancelPending] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  // Snapshot data
  const snapshot = assets.progress_snapshot as {
    source_growth: Array<{ label: string; value: number }>;
    source_mix: Array<{ name: string; value: number }>;
    competitor_coverage: Array<{ name: string; value: number }>;
  };
  const normalizedSnapshot = {
    source_growth: snapshot?.source_growth?.length ? snapshot.source_growth : [{ label: "采集", value: job.source_count }],
    source_mix:    snapshot?.source_mix?.length    ? snapshot.source_mix    : [{ name: "web", value: job.source_count }],
    competitor_coverage: snapshot?.competitor_coverage ?? [],
  };

  // Job state
  const diagnosticJob = isDiagnosticJob(job);
  const isCancellable = !["completed", "failed", "cancelled"].includes(job.status);
  const backgroundProcess = (job.background_process ?? {}) as Record<string, unknown>;
  const workerActive = Boolean(backgroundProcess.active);
  const stableVersionId = getStableReportVersionId(job);
  const activeVersionId  = getActiveReportVersionId(job);
  const hasStableVersion = Boolean(stableVersionId);
  const hasVersionMismatch = Boolean(stableVersionId && activeVersionId && stableVersionId !== activeVersionId);
  const reportVersions = getReportVersions(assets, job);
  const activeSnapshot = reportVersions.find((v) => v.version_id === activeVersionId);
  const stableSnapshot = reportVersions.find((v) => v.version_id === stableVersionId);
  const activeStage = activeSnapshot?.stage ?? assets.report?.stage;
  const stableStage = stableSnapshot?.stage ?? (stableVersionId ? assets.report?.stage : undefined);

  const jobTone = diagnosticJob ? "warning"
    : job.status === "completed" ? "success"
    : job.status === "failed"    ? "danger"
    : "warning";

  // Cancel handler
  const handleCancel = async () => {
    setCancelPending(true);
    try {
      const next = await cancelResearchJob(job.id, "已由用户从研究工作台取消。");
      queryClient.setQueryData(["research-job", job.id], next);
      queryClient.setQueryData<ResearchJobRecord[]>(["research-jobs"], (cur) =>
        (cur ?? []).map((j) => (j.id === next.id ? next : j)),
      );
      setActionFeedback(next.cancellation_reason || "研究任务已取消。");
    } catch (err) {
      setActionFeedback(getApiErrorMessage(err, "取消任务失败。"));
    } finally {
      setCancelPending(false);
    }
  };

  const focusTask =
    job.tasks.find((t) => (t.visited_sources?.length ?? 0) > 0 || (t.source_count ?? 0) > 0) ??
    job.tasks[0];

  const feedback = actionFeedback
    || (job.status === "cancelled" ? job.cancellation_reason : null)
    || (diagnosticJob ? job.latest_warning || job.latest_error : job.latest_error || job.latest_warning)
    || (job.cancel_requested ? "取消请求已发送，后台进程正在停止。" : null);

  return (
    <div className="space-y-6">
      {/* ── Hero Card ─────────────────────────────────────────────────── */}
      <Card className="data-grid-bg relative overflow-hidden">
        <div className="absolute inset-x-0 top-0 h-24 bg-[radial-gradient(circle_at_top_left,_rgba(29,76,116,0.16),_transparent_60%)]" />
        <div className="relative space-y-5">
          {/* Status badges */}
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={jobTone}>
              {jobStatusLabel(job.status, workerActive, job.completion_mode)}
            </Badge>
            {job.workflow_label && <Badge>{job.workflow_label}</Badge>}
            {job.report_version_id && <Badge>{job.report_version_id}</Badge>}
            {diagnosticJob && <Badge tone="warning">诊断结果</Badge>}
            {job.cancel_requested && job.status !== "cancelled" && <Badge tone="warning">取消中</Badge>}
          </div>

          {/* Title */}
          <div>
            <CardTitle className="text-3xl tracking-tight sm:text-[2.5rem]">{job.topic}</CardTitle>
            {job.orchestration_summary && (
              <CardDescription className="mt-2 max-w-3xl text-base leading-7">
                {job.orchestration_summary}
              </CardDescription>
            )}
            {job.project_memory && (
              <div className="mt-3 rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] px-4 py-3 text-sm leading-7 text-[color:var(--muted)]">
                <span className="font-medium text-[color:var(--ink)]">项目背景：</span>
                {job.project_memory}
              </div>
            )}
          </div>

          {/* Phase stepper */}
          <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.5)] px-5 py-4">
            <p className="mb-3 text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">研究阶段</p>
            <StepIndicator steps={PHASE_STEPS} activeId={job.current_phase ?? "scoping"} />
          </div>

          {/* Progress + actions */}
          <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm text-[color:var(--muted)]">
                <span>总体进度</span>
                <span>{job.overall_progress}%</span>
              </div>
              <ProgressBar aria-label="总体进度" value={job.overall_progress} />
              <div className="flex items-center justify-between text-xs text-[color:var(--muted)]">
                <span>{`当前：${phaseLabel(job.current_phase)}`}</span>
                <span>
                  {job.status === "failed" || job.status === "cancelled"
                    ? "已停止"
                    : job.eta_seconds === 0
                    ? "已完成"
                    : `预计 ${Math.round(job.eta_seconds / 60)} 分钟`}
                </span>
              </div>

              {/* Report version state */}
              <div className="flex flex-wrap gap-2">
                {stableVersionId
                  ? <Badge tone="success">{`稳定 ${stableVersionId}`}</Badge>
                  : <Badge>暂无稳定版</Badge>}
                {activeVersionId && (
                  <Badge tone={hasVersionMismatch ? "warning" : "default"}>
                    {`工作稿 ${activeVersionId}`}
                  </Badge>
                )}
                {hasVersionMismatch
                  ? <Badge tone="warning">草稿与稳定版存在差异</Badge>
                  : hasStableVersion
                  ? <Badge tone="success">版本同步</Badge>
                  : <Badge>等待稳定版</Badge>}
              </div>
            </div>

            {/* Actions */}
            <div className="flex flex-col gap-2">
              {stableVersionId && (
                <Button asChild>
                  <Link href={`/research/jobs/${job.id}/report`}>
                    <FileText className="mr-2 h-4 w-4" />
                    查看报告
                  </Link>
                </Button>
              )}
              <Button asChild variant="secondary">
                <Link href={`/research/jobs/${job.id}?tab=chat`}>
                  <MessageSquareText className="mr-2 h-4 w-4" />
                  PM 追问
                </Link>
              </Button>
              {isCancellable && (
                <button
                  type="button"
                  disabled={cancelPending}
                  onClick={() => void handleCancel()}
                  className="rounded-[14px] border border-rose-200 bg-rose-50/80 px-4 py-2.5 text-sm font-medium text-rose-700 transition hover:bg-rose-100 disabled:opacity-60"
                >
                  {cancelPending ? "取消中..." : "取消任务"}
                </button>
              )}
            </div>
          </div>

          {/* Feedback */}
          {feedback && (
            <div
              className={`rounded-[18px] border px-4 py-3 text-sm leading-7 ${
                job.status === "cancelled" || diagnosticJob
                  ? "border-amber-200 bg-amber-50/90 text-amber-900"
                  : job.status === "failed"
                  ? "border-rose-200 bg-rose-50/90 text-rose-800"
                  : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] text-[color:var(--ink)]"
              }`}
            >
              {feedback}
            </div>
          )}
        </div>
      </Card>

      {/* ── Stat Cards ────────────────────────────────────────────────── */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="可引用依据" value={`${job.source_count}`} helper="已整理成可引用依据的来源数" icon={<Database className="h-4 w-4 text-[color:var(--muted)]" />} />
        <StatCard label="竞品数量"   value={`${job.competitor_count}`} helper="已识别并对标的竞品样本" icon={<Flag className="h-4 w-4 text-[color:var(--muted)]" />} />
        <StatCard label="结论条目"   value={`${job.claims_count}`} helper="支持报告与对话双向追溯" icon={<Layers3 className="h-4 w-4 text-[color:var(--muted)]" />} />
        <StatCard label="子任务"     value={`${job.completed_task_count}/${job.tasks.length}`} helper={`${job.running_task_count} 运行中 · ${job.failed_task_count} 失败`} icon={<Activity className="h-4 w-4 text-[color:var(--muted)]" />} />
      </div>

      {/* ── Charts ────────────────────────────────────────────────────── */}
      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="space-y-4">
          <CardTitle>来源增长</CardTitle>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={normalizedSnapshot.source_growth}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d3dbe7" />
                <XAxis dataKey="label" stroke="#8090a5" tick={{ fontSize: 11 }} />
                <YAxis stroke="#8090a5" tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="value" stroke="#1d4c74" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="space-y-4">
          <CardTitle>来源类型分布</CardTitle>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={normalizedSnapshot.source_mix}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d3dbe7" />
                <XAxis dataKey="name" stroke="#8090a5" tick={{ fontSize: 11 }} />
                <YAxis stroke="#8090a5" tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" radius={[8, 8, 0, 0]}>
                  {normalizedSnapshot.source_mix.map((entry, i) => (
                    <Cell key={entry.name} fill={SOURCE_COLORS[i % SOURCE_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* ── Competitor coverage ────────────────────────────────────────── */}
      {normalizedSnapshot.competitor_coverage.length > 0 && (
        <Card className="space-y-4">
          <CardTitle>竞品覆盖度</CardTitle>
          <div className="space-y-3">
            {normalizedSnapshot.competitor_coverage.map((item) => (
              <div key={item.name}>
                <div className="mb-1.5 flex items-center justify-between text-sm text-[color:var(--muted)]">
                  <span>{item.name}</span>
                  <span>{item.value} / 10</span>
                </div>
                <ProgressBar aria-label={`${item.name}竞品覆盖`} value={item.value * 10} />
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
