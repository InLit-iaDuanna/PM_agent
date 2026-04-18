"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowRight, Clock3, RefreshCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { orchestrationPresetCatalog } from "@pm-agent/research-core";
import type { ResearchJobRecord, WorkflowCommandId } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, ProgressBar, SkeletonCard, Timeline, type TimelineEvent } from "@pm-agent/ui";

import { fetchHealthStatus, fetchResearchJobs, getApiErrorMessage } from "../../../lib/api-client";
import { isTerminalJobStatus } from "../../../lib/polling";
import { useDraftStore } from "../store/draft-store";
import { RequestStateCard } from "./request-state-card";
import { commandIcons } from "./research-ui-utils";

function statusLabel(status: ResearchJobRecord["status"]) {
  const map: Record<string, string> = {
    completed: "Complete",
    failed: "Failed",
    cancelled: "Cancelled",
    planning: "Planning",
    verifying: "Verifying",
    synthesizing: "Writing",
  };
  return map[status] ?? "In progress";
}

function statusTone(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode !== "diagnostic") return "success" as const;
  if (job.status === "failed") return "danger" as const;
  if (job.status === "cancelled") return "warning" as const;
  return "default" as const;
}

function phaseLabel(phase: ResearchJobRecord["current_phase"]) {
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

function compactNumber(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
}

function relativeLabel(value?: string) {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  const diff = Date.now() - date.getTime();
  const hour = 60 * 60 * 1000;
  const day = 24 * hour;
  if (diff < hour) return `${Math.max(1, Math.floor(diff / (60 * 1000)))} 分钟前`;
  if (diff < day) return `${Math.max(1, Math.floor(diff / hour))} 小时前`;
  return `${Math.max(1, Math.floor(diff / day))} 天前`;
}

export function HomeDashboardRefactored() {
  const router = useRouter();
  const draftCommand = useDraftStore((state) => state.newResearchForm.workflow_command);
  const patchDraft = useDraftStore((state) => state.patchNewResearchForm);
  const draftTopic = useDraftStore((state) => state.newResearchForm.topic);
  const [launchTopic, setLaunchTopic] = useState(draftTopic ?? "");

  const jobsQuery = useQuery({
    queryKey: ["research-jobs"],
    queryFn: fetchResearchJobs,
    refetchInterval: ({ state }) => {
      const jobs = Array.isArray(state.data) ? state.data : [];
      return jobs.some((job) => !isTerminalJobStatus(job.status)) ? 3000 : 10000;
    },
  });
  const healthQuery = useQuery({
    queryKey: ["api-health"],
    queryFn: fetchHealthStatus,
    refetchInterval: 5000,
  });

  const allJobs = useMemo(() => {
    const jobs = Array.isArray(jobsQuery.data) ? jobsQuery.data : [];
    return [...jobs].sort((left, right) => {
      const leftTimestamp = left.updated_at || left.completed_at || left.created_at || "";
      const rightTimestamp = right.updated_at || right.completed_at || right.created_at || "";
      return rightTimestamp.localeCompare(leftTimestamp);
    });
  }, [jobsQuery.data]);

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

  const activeJobs = allJobs.filter((job) => !isTerminalJobStatus(job.status));
  const completedJobs = allJobs.filter((job) => job.status === "completed");
  const focusJob = activeJobs[0] ?? completedJobs[0] ?? allJobs[0];
  const totalSources = allJobs.reduce((sum, job) => sum + job.source_count, 0);
  const totalClaims = allJobs.reduce((sum, job) => sum + job.claims_count, 0);
  const totalReportJobs = allJobs.filter((job) => job.report_version_id).length;
  const activeTaskCount = activeJobs.reduce((sum, job) => sum + job.tasks.filter((task) => task.status === "running").length, 0);

  const timelineEvents: TimelineEvent[] = allJobs
    .flatMap((job) =>
      (job.activity_log ?? []).map((log) => ({
        id: log.id,
        title: log.message,
        timestamp: log.timestamp,
        level: (log.level === "error" ? "error" : log.level === "warning" ? "warning" : "info") as TimelineEvent["level"],
        meta: job.topic,
      })),
    )
    .sort((left, right) => right.timestamp.localeCompare(left.timestamp))
    .slice(0, 8);

  const featuredCommands = (Object.entries(orchestrationPresetCatalog) as Array<
    [WorkflowCommandId, (typeof orchestrationPresetCatalog)[WorkflowCommandId]]
  >).slice(0, 4);

  const handleLaunch = () => {
    const topic = launchTopic.trim();
    patchDraft({
      topic,
      workflow_command: draftCommand || "deep_general_scan",
      research_mode: "deep",
    });
    router.push("/research/new");
  };

  const isLoading = jobsQuery.isLoading;

  return (
    <div className="space-y-8">
      <section className="minimal-panel px-6 py-10 sm:px-10 sm:py-14">
        <div className="mx-auto max-w-4xl text-center">
          <div className="mb-6 flex items-center justify-center gap-3 text-sm font-medium text-[color:var(--muted)]">
            <span className="h-3 w-3 rounded-full bg-[#2563eb]" />
            <span>PM Research</span>
            <Badge tone={healthQuery.error ? "warning" : "success"}>{healthQuery.error ? "连接待检查" : "在线"}</Badge>
          </div>

          <h1 className="text-4xl font-semibold tracking-[-0.05em] text-[color:var(--ink)] sm:text-5xl">
            Ready for your next research
          </h1>
          <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-[color:var(--muted)] sm:text-base">
            发起新研究，或回到你正在推进的任务。首页只保留最重要的入口和最近进展。
          </p>

          <div className="mx-auto mt-8 max-w-3xl rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(247,248,250,0.92)] p-2 shadow-[var(--shadow-sm)]">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <input
                className="h-12 flex-1 rounded-[16px] border-0 bg-transparent px-4 text-sm text-[color:var(--ink)] outline-none placeholder:text-[color:var(--muted)]"
                onChange={(event) => setLaunchTopic(event.target.value)}
                placeholder="Describe your research topic..."
                value={launchTopic}
              />
              <Button className="h-12 rounded-[16px] px-6" onClick={handleLaunch} type="button">
                Start research
              </Button>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap justify-center gap-2">
            {featuredCommands.map(([commandId, preset]) => {
              const isSelected = draftCommand === commandId;
              return (
                <button
                  key={commandId}
                  type="button"
                  onClick={() => patchDraft({ workflow_command: commandId, research_mode: "deep" })}
                  className={`rounded-full border px-4 py-2 text-xs transition ${
                    isSelected
                      ? "border-[color:var(--accent)] bg-[rgba(37,99,235,0.08)] text-[color:var(--ink)]"
                      : "border-[color:var(--border-soft)] bg-white text-[color:var(--muted)] hover:border-[color:var(--border-strong)] hover:text-[color:var(--ink)]"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>

          <div className="mt-8 grid gap-3 sm:grid-cols-4">
            <InlineMetric label="进行中研究" value={compactNumber(activeJobs.length)} />
            <InlineMetric label="运行中任务" value={compactNumber(activeTaskCount)} />
            <InlineMetric label="沉淀来源" value={compactNumber(totalSources)} />
            <InlineMetric label="报告版本" value={compactNumber(totalReportJobs)} />
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="space-y-5 rounded-[28px] border border-[color:var(--border-soft)] bg-white/88 p-6 shadow-[var(--shadow-sm)]">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[color:var(--muted)]">Recent research</p>
              <CardDescription className="mt-1">最近的研究任务和状态一目了然。</CardDescription>
            </div>
            <Button asChild variant="ghost">
              <Link href="/research/new">新建研究</Link>
            </Button>
          </div>

          {isLoading ? (
            <div className="grid gap-4 md:grid-cols-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <SkeletonCard key={index} lines={4} />
              ))}
            </div>
          ) : allJobs.length ? (
            <div className="grid gap-4 md:grid-cols-2">
              {allJobs.slice(0, 4).map((job) => (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => router.push(`/research/jobs/${job.id}`)}
                  className="card-lift rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(249,250,251,0.9)] p-5 text-left"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="line-clamp-2 text-base font-semibold tracking-[-0.02em] text-[color:var(--ink)]">{job.topic}</p>
                      <p className="mt-1 flex items-center gap-1 text-xs text-[color:var(--muted)]">
                        <Clock3 className="h-3.5 w-3.5" />
                        {relativeLabel(job.updated_at || job.completed_at || job.created_at)}
                      </p>
                    </div>
                    <Badge tone={statusTone(job)}>{statusLabel(job.status)}</Badge>
                  </div>

                  <div className="mt-4 flex items-center gap-2 text-xs text-[color:var(--muted)]">
                    {job.status === "completed" ? (
                      <>
                        <span>{job.source_count} sources</span>
                        <span>·</span>
                        <span>{job.claims_count} claims</span>
                      </>
                    ) : (
                      <>
                        <div className="flex-1">
                          <ProgressBar aria-label={job.topic} value={job.overall_progress} />
                        </div>
                        <span>{job.overall_progress}%</span>
                      </>
                    )}
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="rounded-[24px] border border-dashed border-[color:var(--border-soft)] px-5 py-10 text-center text-sm text-[color:var(--muted)]">
              还没有研究记录。输入主题后即可开始第一条研究。
            </div>
          )}
        </Card>

        <div className="space-y-6">
          <Card className="space-y-5 rounded-[28px] border border-[color:var(--border-soft)] bg-white/88 p-6 shadow-[var(--shadow-sm)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[color:var(--muted)]">
                  {activeJobs.length ? "Current research" : "Latest completed"}
                </p>
                <CardDescription className="mt-1">优先回到最值得继续的任务。</CardDescription>
              </div>
              {focusJob ? <Badge tone={statusTone(focusJob)}>{statusLabel(focusJob.status)}</Badge> : null}
            </div>

            {focusJob ? (
              <>
                <div>
                  <CardTitle className="text-xl tracking-[-0.03em]">{focusJob.topic}</CardTitle>
                  <p className="mt-2 text-sm leading-6 text-[color:var(--muted)]">
                    {focusJob.orchestration_summary || "继续查看证据、报告版本，或基于当前结果发起追问。"}
                  </p>
                </div>

                <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(249,250,251,0.88)] p-4">
                  <div className="mb-2 flex items-center justify-between text-sm text-[color:var(--muted)]">
                    <span>{phaseLabel(focusJob.current_phase)}</span>
                    <span>{focusJob.overall_progress}%</span>
                  </div>
                  <ProgressBar aria-label="当前研究进度" value={focusJob.overall_progress} />
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-[color:var(--muted)]">
                    <span>{focusJob.completed_task_count}/{focusJob.tasks.length} tasks</span>
                    <span>·</span>
                    <span>{focusJob.source_count} sources</span>
                    <span>·</span>
                    <span>{focusJob.claims_count} claims</span>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button asChild variant="secondary">
                    <Link href={`/research/jobs/${focusJob.id}`}>Open research</Link>
                  </Button>
                  {focusJob.report_version_id ? (
                    <Button asChild variant="ghost">
                      <Link href={`/research/jobs/${focusJob.id}/report`}>View report</Link>
                    </Button>
                  ) : null}
                </div>
              </>
            ) : (
              <p className="text-sm text-[color:var(--muted)]">还没有研究任务，先从上方输入主题开始。</p>
            )}
          </Card>

          <Card className="space-y-5 rounded-[28px] border border-[color:var(--border-soft)] bg-white/88 p-6 shadow-[var(--shadow-sm)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[color:var(--muted)]">Recent activity</p>
                <CardDescription className="mt-1">保留最近的研究轨迹与运行状态。</CardDescription>
              </div>
              <Button onClick={() => void jobsQuery.refetch()} type="button" variant="ghost">
                <RefreshCw className={`h-4 w-4 ${jobsQuery.isFetching ? "animate-spin" : ""}`} />
              </Button>
            </div>
            <Timeline events={timelineEvents} grouped />
          </Card>

          <Card className="rounded-[28px] border border-[color:var(--border-soft)] bg-white/88 p-6 shadow-[var(--shadow-sm)]">
            <div className="grid gap-3 sm:grid-cols-2">
              <InlineStatus label="模型配置" value={healthQuery.data?.runtime_configured ? "已就绪" : "需配置"} />
              <InlineStatus label="判断条目" value={compactNumber(totalClaims)} />
            </div>
          </Card>
        </div>
      </section>
    </div>
  );
}

function InlineMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-white/70 px-4 py-3 text-left shadow-[var(--shadow-sm)]">
      <p className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{value}</p>
    </div>
  );
}

function InlineStatus({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(249,250,251,0.9)] px-4 py-3">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-1 text-sm font-medium text-[color:var(--ink)]">{value}</p>
    </div>
  );
}
