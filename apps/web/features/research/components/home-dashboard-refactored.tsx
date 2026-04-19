"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import {
  ArrowRight,
  Clock3,
  FileText,
  Layers3,
  Radar,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { orchestrationPresetCatalog } from "@pm-agent/research-core";
import type { ResearchJobRecord, WorkflowCommandId } from "@pm-agent/types";
import {
  Badge,
  Button,
  Card,
  CardDescription,
  CardTitle,
  ProgressBar,
  SkeletonCard,
  Timeline,
  type TimelineEvent,
} from "@pm-agent/ui";

import { fetchHealthStatus, fetchResearchJobs, getApiErrorMessage } from "../../../lib/api-client";
import { isTerminalJobStatus } from "../../../lib/polling";
import { useDraftStore } from "../store/draft-store";
import { RequestStateCard } from "./request-state-card";
import { commandIcons } from "./research-ui-utils";

function statusLabel(status: ResearchJobRecord["status"]) {
  const map: Record<string, string> = {
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    planning: "规划中",
    verifying: "校验中",
    synthesizing: "成文中",
  };
  return map[status] ?? "进行中";
}

function statusTone(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode !== "diagnostic") return "success" as const;
  if (job.status === "failed") return "danger" as const;
  if (job.status === "cancelled") return "warning" as const;
  return "default" as const;
}

function phaseLabel(phase: ResearchJobRecord["current_phase"]) {
  const map: Record<string, string> = {
    scoping: "界定问题",
    planning: "拆解任务",
    collecting: "检索与采集",
    verifying: "校验结论",
    synthesizing: "整理成文",
    finalizing: "完成交付",
  };
  return map[phase ?? ""] ?? "检索与采集";
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

function workflowLabel(job: ResearchJobRecord) {
  return job.workflow_label || orchestrationPresetCatalog[(job.workflow_command || "deep_general_scan") as WorkflowCommandId]?.label || "研究任务";
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
      <section className="paper-panel relative overflow-hidden rounded-[36px] px-6 py-8 sm:px-8 xl:px-10 xl:py-10">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-[radial-gradient(circle_at_top_left,rgba(29,76,116,0.16),transparent_42%),radial-gradient(circle_at_top_right,rgba(197,129,32,0.14),transparent_36%)]" />
        <div className="relative grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              <span className="eyebrow-label">Research Command Deck</span>
              <Badge tone={healthQuery.error ? "warning" : "success"}>{healthQuery.error ? "连接待检查" : "系统在线"}</Badge>
              <Badge>{healthQuery.data?.runtime_configured ? "模型已就绪" : "模型待配置"}</Badge>
            </div>

            <div className="max-w-4xl space-y-3">
              <h1 className="section-title text-[2.4rem] leading-[1.05] text-[color:var(--ink)] sm:text-[3rem] xl:text-[3.6rem]">
                把模糊问题编排成
                <br />
                可追溯、可交付的研究
              </h1>
              <p className="max-w-2xl text-sm leading-7 text-[color:var(--muted)] sm:text-[15px]">
                这里不是普通的发起页，而是你的研究指挥台。先决定研究命令，再把主题送进任务编排、证据收集、报告成文与 PM 追问的完整闭环。
              </p>
            </div>

            <div className="paper-grid-bg rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.76)] p-3 shadow-[var(--shadow-sm)]">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <div className="min-w-0 flex-1 rounded-[22px] bg-[rgba(255,255,255,0.66)] px-4 py-3">
                  <p className="text-[11px] uppercase tracking-[0.22em] text-[color:var(--muted)]">研究主题</p>
                  <input
                    className="mt-2 h-8 w-full border-0 bg-transparent p-0 text-sm text-[color:var(--ink)] outline-none placeholder:text-[color:var(--muted)]"
                    onChange={(event) => setLaunchTopic(event.target.value)}
                    placeholder="例如：国内 AI 办公产品的商业化路径与定价空档"
                    value={launchTopic}
                  />
                </div>
                <Button className="h-[58px] rounded-[20px] px-6" onClick={handleLaunch} type="button">
                  进入研究编排
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[color:var(--muted)]">
                <span>当前命令</span>
                <Badge tone="success">
                  {draftCommand ? orchestrationPresetCatalog[draftCommand]?.label || draftCommand : "全景深度扫描"}
                </Badge>
                <span>可在下一步继续补充项目背景与预算。</span>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {featuredCommands.map(([commandId, preset]) => {
                const Icon = commandIcons[commandId];
                const isSelected = draftCommand === commandId;
                return (
                  <button
                    key={commandId}
                    type="button"
                    onClick={() => patchDraft({ workflow_command: commandId, research_mode: "deep" })}
                    className={`rounded-full border px-4 py-2 text-xs transition ${
                      isSelected
                        ? "border-[color:var(--accent)] bg-[rgba(29,76,116,0.08)] text-[color:var(--ink)]"
                        : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.66)] text-[color:var(--muted)] hover:border-[color:var(--border-strong)] hover:text-[color:var(--ink)]"
                    }`}
                  >
                    <span className="inline-flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5" />
                      {preset.label}
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <BoardMetric label="进行中研究" value={compactNumber(activeJobs.length)} helper="正在推进的研究主线" icon={<Radar className="h-4 w-4" />} />
              <BoardMetric label="运行中任务" value={compactNumber(activeTaskCount)} helper="后台并行中的子任务" icon={<Sparkles className="h-4 w-4" />} />
              <BoardMetric label="沉淀来源" value={compactNumber(totalSources)} helper="已经保留的依据页" icon={<Search className="h-4 w-4" />} />
              <BoardMetric label="报告版本" value={compactNumber(totalReportJobs)} helper="可回看的版本快照" icon={<FileText className="h-4 w-4" />} />
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,250,242,0.82)] p-6 shadow-[var(--shadow-md)]">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="eyebrow-label">Focus Dossier</p>
                  <p className="mt-1 text-sm text-[color:var(--muted)]">
                    {activeJobs.length ? "优先回到最值得继续推进的研究。" : "如果当前没有运行中的研究，就从最近一份交付继续。"}
                  </p>
                </div>
                {focusJob ? <Badge tone={statusTone(focusJob)}>{statusLabel(focusJob.status)}</Badge> : null}
              </div>

              {focusJob ? (
                <div className="mt-5 space-y-5">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{workflowLabel(focusJob)}</Badge>
                      <span className="inline-flex items-center gap-1 text-xs text-[color:var(--muted)]">
                        <Clock3 className="h-3.5 w-3.5" />
                        {relativeLabel(focusJob.updated_at || focusJob.completed_at || focusJob.created_at)}
                      </span>
                    </div>
                    <CardTitle className="mt-3 text-2xl leading-tight sm:text-[1.8rem]">{focusJob.topic}</CardTitle>
                    <p className="mt-2 text-sm leading-7 text-[color:var(--muted)]">
                      {focusJob.orchestration_summary || "继续查看证据、版本与对话补研，让研究真正落到决策上下文里。"}
                    </p>
                  </div>

                  <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] p-4">
                    <div className="mb-2 flex items-center justify-between text-sm text-[color:var(--muted)]">
                      <span>{phaseLabel(focusJob.current_phase)}</span>
                      <span>{focusJob.overall_progress}%</span>
                    </div>
                    <ProgressBar aria-label="当前研究进度" value={focusJob.overall_progress} />
                    <div className="mt-3 grid gap-2 sm:grid-cols-3">
                      <MiniFact label="任务" value={`${focusJob.completed_task_count}/${focusJob.tasks.length}`} />
                      <MiniFact label="来源" value={`${focusJob.source_count}`} />
                      <MiniFact label="结论" value={`${focusJob.claims_count}`} />
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button asChild>
                      <Link href={`/research/jobs/${focusJob.id}`}>
                        打开研究台
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </Link>
                    </Button>
                    {focusJob.report_version_id ? (
                      <Button asChild variant="secondary">
                        <Link href={`/research/jobs/${focusJob.id}/report`}>查看报告</Link>
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className="mt-5 rounded-[24px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] px-5 py-10 text-center text-sm text-[color:var(--muted)]">
                  还没有研究任务。先输入一个具体问题，我们就从这里开始搭第一条研究链路。
                </div>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <SignalCard
                label="系统状态"
                value={healthQuery.data?.runtime_configured ? "研究引擎已就绪" : "需要补充模型配置"}
                helper={healthQuery.data?.active_job_count ? `${healthQuery.data.active_job_count} 条研究正在推进` : "当前没有运行中的研究"}
              />
              <SignalCard
                label="知识沉淀"
                value={`${compactNumber(totalClaims)} 条判断`}
                helper={`${compactNumber(totalSources)} 条来源已进入可引用池`}
              />
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.18fr_0.82fr]">
        <Card className="space-y-5 rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,250,242,0.9)] p-6 shadow-[var(--shadow-md)]">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="eyebrow-label">Research Queue</p>
              <CardDescription className="mt-1">最近的研究任务按更新时间排序，方便直接接回上下文。</CardDescription>
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
              {allJobs.slice(0, 6).map((job, index) => (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => router.push(`/research/jobs/${job.id}`)}
                  className="card-lift stagger-item rounded-[26px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] p-5 text-left"
                  style={{ "--delay": `${index * 50}ms` } as React.CSSProperties}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge>{workflowLabel(job)}</Badge>
                        <span className="inline-flex items-center gap-1 text-[11px] text-[color:var(--muted)]">
                          <Clock3 className="h-3.5 w-3.5" />
                          {relativeLabel(job.updated_at || job.completed_at || job.created_at)}
                        </span>
                      </div>
                      <p className="mt-3 line-clamp-2 text-lg font-semibold tracking-[-0.03em] text-[color:var(--ink)]">{job.topic}</p>
                      <p className="mt-2 line-clamp-2 text-sm leading-6 text-[color:var(--muted)]">
                        {job.orchestration_summary || "查看当前任务拆解、证据保留和报告成文状态。"}
                      </p>
                    </div>
                    <Badge tone={statusTone(job)}>{statusLabel(job.status)}</Badge>
                  </div>

                  <div className="mt-4 space-y-2">
                    <div className="flex items-center justify-between text-xs text-[color:var(--muted)]">
                      <span>{phaseLabel(job.current_phase)}</span>
                      <span>{job.overall_progress}%</span>
                    </div>
                    <ProgressBar aria-label={job.topic} value={job.overall_progress} />
                  </div>

                  <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-[color:var(--muted)]">
                    <span className="inline-flex items-center gap-1 rounded-full bg-[rgba(29,76,116,0.08)] px-2.5 py-1 text-[color:var(--accent)]">
                      <Layers3 className="h-3.5 w-3.5" />
                      {job.completed_task_count}/{job.tasks.length} 任务
                    </span>
                    <span>{job.source_count} 来源</span>
                    <span>·</span>
                    <span>{job.claims_count} 结论</span>
                    {job.report_version_id ? (
                      <>
                        <span>·</span>
                        <span>{job.report_version_id}</span>
                      </>
                    ) : null}
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
          <Card className="space-y-5 rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,250,242,0.9)] p-6 shadow-[var(--shadow-md)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="eyebrow-label">Recent Activity</p>
                <CardDescription className="mt-1">保留最近的研究轨迹与状态变化，方便快速判断是否需要回到某条任务线上。</CardDescription>
              </div>
              <Button onClick={() => void jobsQuery.refetch()} type="button" variant="ghost">
                <RefreshCw className={`h-4 w-4 ${jobsQuery.isFetching ? "animate-spin" : ""}`} />
              </Button>
            </div>
            <Timeline events={timelineEvents} grouped />
          </Card>

          <Card className="space-y-4 rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,250,242,0.9)] p-6 shadow-[var(--shadow-md)]">
            <div>
              <p className="eyebrow-label">System Readiness</p>
              <CardDescription className="mt-1">确认环境是否适合启动下一轮研究，而不是把问题丢给一个状态不完整的工作台。</CardDescription>
            </div>
            <div className="grid gap-3">
              <SignalCard
                label="模型配置"
                value={healthQuery.data?.runtime_configured ? "已完成" : "待配置"}
                helper={healthQuery.data?.runtime_configured ? "可以直接发起研究与 PM 对话。" : "请先到服务设置里补齐模型参数。"}
              />
              <SignalCard
                label="后台活跃"
                value={`${healthQuery.data?.active_detached_worker_count ?? 0} 个进程`}
                helper={activeJobs.length ? "有研究正在持续推进。" : "当前适合启动新的任务。"}
              />
            </div>
          </Card>
        </div>
      </section>
    </div>
  );
}

function BoardMetric({
  label,
  value,
  helper,
  icon,
}: {
  label: string;
  value: string;
  helper: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-4 py-4 shadow-[var(--shadow-sm)]">
      <div className="flex items-center justify-between gap-3 text-[color:var(--muted)]">
        <p className="text-[11px] uppercase tracking-[0.2em]">{label}</p>
        {icon}
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{value}</p>
      <p className="mt-1 text-xs leading-5 text-[color:var(--muted)]">{helper}</p>
    </div>
  );
}

function MiniFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(252,247,241,0.92)] px-3 py-3">
      <p className="text-[10px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-1 text-base font-semibold text-[color:var(--ink)]">{value}</p>
    </div>
  );
}

function SignalCard({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-4 py-4">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-2 text-base font-semibold text-[color:var(--ink)]">{value}</p>
      <p className="mt-1 text-xs leading-5 text-[color:var(--muted)]">{helper}</p>
    </div>
  );
}
