"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Activity, Database, FileText, Flag, Layers3, MessageSquareText } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useQueryClient } from "@tanstack/react-query";

import type { ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, ProgressBar, StepIndicator } from "@pm-agent/ui";

import { cancelResearchJob, getApiErrorMessage } from "../../../../lib/api-client";
import { getActiveReportVersionId, getReportVersions, getStableReportVersionId } from "../report-version-utils";

const PHASE_STEPS = [
  { id: "scoping", label: "Plan" },
  { id: "planning", label: "Plan" },
  { id: "collecting", label: "Search" },
  { id: "verifying", label: "Verify" },
  { id: "synthesizing", label: "Synthesize" },
  { id: "finalizing", label: "Done" },
];

const SOURCE_COLORS = ["#2563eb", "#60a5fa", "#94a3b8", "#dbeafe"];

function phaseLabel(phase?: string) {
  const map: Record<string, string> = {
    scoping: "Plan",
    planning: "Plan",
    collecting: "Search",
    verifying: "Verify",
    synthesizing: "Synthesize",
    finalizing: "Done",
  };
  return map[phase ?? ""] ?? "Search";
}

function reportStageLabel(stage?: string) {
  if (stage === "final") return "Stable";
  if (stage === "feedback_pending") return "Pending merge";
  if (stage === "draft") return "Draft";
  if (stage === "draft_pending") return "Generating";
  return "Pending";
}

function isDiagnosticJob(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  return job.status === "completed" && job.completion_mode === "diagnostic";
}

function jobStatusLabel(
  status: ResearchJobRecord["status"],
  workerActive = false,
  completionMode?: ResearchJobRecord["completion_mode"],
) {
  if (status === "completed" && completionMode === "diagnostic") return "Diagnostic";
  if (status === "completed") return "Complete";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return workerActive ? "Cancelling" : "Cancelled";
  if (status === "planning") return "Planning";
  if (status === "verifying") return "Verifying";
  if (status === "synthesizing") return "Writing";
  return "In progress";
}

interface JobOverviewTabProps {
  job: ResearchJobRecord;
  assets: ResearchAssetsRecord;
}

export function JobOverviewTab({ job, assets }: JobOverviewTabProps) {
  const queryClient = useQueryClient();
  const [cancelPending, setCancelPending] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  const snapshot = assets.progress_snapshot as {
    source_growth: Array<{ label: string; value: number }>;
    source_mix: Array<{ name: string; value: number }>;
    competitor_coverage: Array<{ name: string; value: number }>;
  };
  const normalizedSnapshot = {
    source_growth: snapshot?.source_growth?.length ? snapshot.source_growth : [{ label: "Search", value: job.source_count }],
    source_mix: snapshot?.source_mix?.length ? snapshot.source_mix : [{ name: "web", value: job.source_count }],
    competitor_coverage: snapshot?.competitor_coverage ?? [],
  };

  const diagnosticJob = isDiagnosticJob(job);
  const isCancellable = !["completed", "failed", "cancelled"].includes(job.status);
  const backgroundProcess = (job.background_process ?? {}) as Record<string, unknown>;
  const workerActive = Boolean(backgroundProcess.active);
  const stableVersionId = getStableReportVersionId(job);
  const activeVersionId = getActiveReportVersionId(job);
  const hasStableVersion = Boolean(stableVersionId);
  const hasVersionMismatch = Boolean(stableVersionId && activeVersionId && stableVersionId !== activeVersionId);
  const reportVersions = getReportVersions(assets, job);
  const activeSnapshot = reportVersions.find((version) => version.version_id === activeVersionId);
  const stableSnapshot = reportVersions.find((version) => version.version_id === stableVersionId);
  const activeStage = activeSnapshot?.stage ?? assets.report?.stage;
  const stableStage = stableSnapshot?.stage ?? (stableVersionId ? assets.report?.stage : undefined);

  const handleCancel = async () => {
    setCancelPending(true);
    try {
      const next = await cancelResearchJob(job.id, "已由用户从研究工作台取消。");
      queryClient.setQueryData(["research-job", job.id], next);
      queryClient.setQueryData<ResearchJobRecord[]>(["research-jobs"], (current) =>
        (current ?? []).map((item) => (item.id === next.id ? next : item)),
      );
      setActionFeedback(next.cancellation_reason || "研究任务已取消。");
    } catch (error) {
      setActionFeedback(getApiErrorMessage(error, "取消任务失败。"));
    } finally {
      setCancelPending(false);
    }
  };

  const feedback =
    actionFeedback ||
    (job.status === "cancelled" ? job.cancellation_reason : null) ||
    (diagnosticJob ? job.latest_warning || job.latest_error : job.latest_error || job.latest_warning) ||
    (job.cancel_requested ? "取消请求已发送，后台进程正在停止。" : null);

  return (
    <div className="space-y-6">
      <section className="minimal-panel px-6 py-6 sm:px-8">
        <div className="space-y-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-4xl space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={job.status === "completed" ? "success" : job.status === "failed" ? "danger" : "default"}>
                  {jobStatusLabel(job.status, workerActive, job.completion_mode)}
                </Badge>
                {job.workflow_label ? <Badge>{job.workflow_label}</Badge> : null}
                {job.report_version_id ? <Badge tone="success">{job.report_version_id}</Badge> : null}
                {diagnosticJob ? <Badge tone="warning">诊断结果</Badge> : null}
                {job.cancel_requested && job.status !== "cancelled" ? <Badge tone="warning">取消中</Badge> : null}
              </div>

              <div>
                <CardTitle className="text-3xl tracking-[-0.05em] sm:text-[2.7rem]">{job.topic}</CardTitle>
                {job.orchestration_summary ? (
                  <CardDescription className="mt-3 max-w-3xl text-sm leading-7 sm:text-base">{job.orchestration_summary}</CardDescription>
                ) : null}
                {job.project_memory ? (
                  <div className="mt-4 rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(247,248,250,0.92)] px-4 py-4 text-sm leading-7 text-[color:var(--muted)]">
                    <span className="font-medium text-[color:var(--ink)]">项目背景：</span>
                    {job.project_memory}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:w-[320px] lg:grid-cols-1">
              <MetricBox label="Sources" value={`${job.source_count}`} />
              <MetricBox label="Claims" value={`${job.claims_count}`} />
              <MetricBox label="Tasks" value={`${job.completed_task_count}/${job.tasks.length}`} />
            </div>
          </div>

          <div className="rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(249,250,251,0.9)] px-5 py-5">
            <div className="mb-3 flex items-center justify-between text-sm text-[color:var(--muted)]">
              <span>{phaseLabel(job.current_phase)}</span>
              <span>{job.overall_progress}%</span>
            </div>
            <ProgressBar aria-label="总体进度" value={job.overall_progress} />
            <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_280px]">
              <div className="space-y-4">
                <StepIndicator steps={PHASE_STEPS} activeId={job.current_phase ?? "scoping"} />
                <div className="flex flex-wrap gap-2 text-xs text-[color:var(--muted)]">
                  <span>{job.running_task_count} running</span>
                  <span>·</span>
                  <span>{job.failed_task_count} failed</span>
                  <span>·</span>
                  <span>
                    {job.status === "failed" || job.status === "cancelled"
                      ? "已停止"
                      : job.eta_seconds === 0
                      ? "已完成"
                      : `预计 ${Math.round(job.eta_seconds / 60)} 分钟`}
                  </span>
                </div>
              </div>

              <div className="space-y-2 rounded-[18px] border border-[color:var(--border-soft)] bg-white/90 p-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[color:var(--muted)]">Stable</span>
                  <span className="font-medium text-[color:var(--ink)]">{stableVersionId ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[color:var(--muted)]">Working</span>
                  <span className="font-medium text-[color:var(--ink)]">{activeVersionId ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[color:var(--muted)]">Stage</span>
                  <span className="font-medium text-[color:var(--ink)]">{reportStageLabel(activeStage || stableStage)}</span>
                </div>
                <div className="pt-1 text-xs text-[color:var(--muted)]">
                  {hasVersionMismatch ? "草稿与稳定版存在差异" : hasStableVersion ? "稳定版与工作稿已同步" : "等待首个稳定版"}
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            {stableVersionId ? (
              <Button asChild>
                <Link href={`/research/jobs/${job.id}/report`}>
                  <FileText className="mr-2 h-4 w-4" />
                  查看报告
                </Link>
              </Button>
            ) : null}
            <Button asChild variant="secondary">
              <Link href={`/research/jobs/${job.id}?tab=chat`}>
                <MessageSquareText className="mr-2 h-4 w-4" />
                PM 追问
              </Link>
            </Button>
            {isCancellable ? (
              <button
                type="button"
                disabled={cancelPending}
                onClick={() => void handleCancel()}
                className="rounded-[14px] border border-rose-200 bg-rose-50/80 px-4 py-2.5 text-sm font-medium text-rose-700 transition hover:bg-rose-100 disabled:opacity-60"
              >
                {cancelPending ? "取消中..." : "取消任务"}
              </button>
            ) : null}
          </div>

          {feedback ? (
            <div
              className={`rounded-[18px] border px-4 py-3 text-sm leading-7 ${
                job.status === "cancelled" || diagnosticJob
                  ? "border-amber-200 bg-amber-50/90 text-amber-900"
                  : job.status === "failed"
                  ? "border-rose-200 bg-rose-50/90 text-rose-800"
                  : "border-[color:var(--border-soft)] bg-[rgba(249,250,251,0.92)] text-[color:var(--ink)]"
              }`}
            >
              {feedback}
            </div>
          ) : null}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SimpleStatCard icon={<Database className="h-4 w-4" />} label="可引用依据" value={`${job.source_count}`} helper="已整理成可引用依据的来源数" />
        <SimpleStatCard icon={<Flag className="h-4 w-4" />} label="竞品数量" value={`${job.competitor_count}`} helper="已识别并对标的竞品样本" />
        <SimpleStatCard icon={<Layers3 className="h-4 w-4" />} label="结论条目" value={`${job.claims_count}`} helper="支持报告与对话双向追溯" />
        <SimpleStatCard icon={<Activity className="h-4 w-4" />} label="子任务" value={`${job.completed_task_count}/${job.tasks.length}`} helper={`${job.running_task_count} 运行中 · ${job.failed_task_count} 失败`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="minimal-panel space-y-4 px-5 py-5">
          <CardTitle>来源增长</CardTitle>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={normalizedSnapshot.source_growth}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="value" stroke="#2563eb" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="minimal-panel space-y-4 px-5 py-5">
          <CardTitle>来源类型分布</CardTitle>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={normalizedSnapshot.source_mix}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="name" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" radius={[8, 8, 0, 0]}>
                  {normalizedSnapshot.source_mix.map((entry, index) => (
                    <Cell key={entry.name} fill={SOURCE_COLORS[index % SOURCE_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {normalizedSnapshot.competitor_coverage.length > 0 ? (
        <Card className="minimal-panel space-y-4 px-5 py-5">
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
      ) : null}
    </div>
  );
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] border border-[color:var(--border-soft)] bg-white/82 px-4 py-3 shadow-[var(--shadow-sm)]">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-1 text-lg font-semibold tracking-[-0.03em] text-[color:var(--ink)]">{value}</p>
    </div>
  );
}

function SimpleStatCard({
  icon,
  label,
  value,
  helper,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="rounded-[22px] border border-[color:var(--border-soft)] bg-white/88 p-5 shadow-[var(--shadow-sm)]">
      <div className="flex items-center justify-between text-[color:var(--muted)]">
        <span className="text-[11px] uppercase tracking-[0.18em]">{label}</span>
        {icon}
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{value}</p>
      <p className="mt-1 text-xs leading-5 text-[color:var(--muted)]">{helper}</p>
    </div>
  );
}
