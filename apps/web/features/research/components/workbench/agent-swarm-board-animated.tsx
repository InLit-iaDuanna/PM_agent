"use client";

import type { ResearchJobRecord, ResearchTaskRecord } from "@pm-agent/types";
import { Badge, Card, CardTitle, ProgressBar, Tooltip } from "@pm-agent/ui";
import { formatMarketStep, formatSkillPack, taskStatusLabel, taskStatusTone } from "../research-ui-utils";

// ─── Helpers (same as original) ────────────────────────────────────────────
function taskLeadCount(task: ResearchTaskRecord) {
  const visitedCount = (task.visited_sources ?? []).length;
  const queryHitCount = (task.research_rounds ?? [])
    .flatMap((r) => r.query_summaries ?? [])
    .filter((s) => Number(s.search_result_count || 0) > 0).length;
  return Math.max(visitedCount, queryHitCount);
}

function activitySummary(task: ResearchTaskRecord) {
  const leadCount = taskLeadCount(task);
  if (task.source_count === 0 && leadCount > 0)
    return `已命中 ${leadCount} 条候选线索，正在核验与归档。`;
  if (task.current_action) return task.current_action;
  if (task.search_queries?.length)
    return `最近查询：${task.search_queries[task.search_queries.length - 1]}`;
  if (task.logs?.length) return task.logs[task.logs.length - 1]?.message;
  return task.brief;
}

function questionDomain(task: ResearchTaskRecord) {
  const text = `${task.market_step ?? ""} ${task.title ?? ""} ${task.brief ?? ""}`.toLowerCase();
  if (text.includes("price") || text.includes("pricing") || text.includes("定价")) return "定价验证";
  if (text.includes("compet") || text.includes("竞品")) return "竞品差异";
  if (text.includes("review") || text.includes("用户") || text.includes("反馈")) return "用户反馈";
  if (text.includes("official") || text.includes("官网") || text.includes("文档")) return "官网事实";
  return "市场判断";
}

// ─── Animated status dot ───────────────────────────────────────────────────
function AgentStatusDot({ status }: { status: ResearchTaskRecord["status"] }) {
  const isRunning = status === "running";
  const isQueued  = status === "queued";
  const isDone    = status === "completed";
  const isFailed  = status === "failed";

  if (isRunning) {
    return (
      <span className="relative flex h-2.5 w-2.5 shrink-0">
        {/* 外圈脉冲 */}
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[color:var(--accent)] opacity-50" />
        {/* 内核 */}
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[color:var(--accent)]" />
      </span>
    );
  }
  if (isQueued) {
    return <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-amber-400" />;
  }
  if (isDone) {
    return <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-500" />;
  }
  if (isFailed) {
    return <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-rose-500" />;
  }
  return <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-[color:var(--border-strong)]" />;
}

// ─── Single agent card ─────────────────────────────────────────────────────
function AgentCard({
  task,
  isSelected,
  onClick,
  delay,
}: {
  task: ResearchTaskRecord;
  isSelected: boolean;
  onClick: () => void;
  delay: number;
}) {
  const isRunning  = task.status === "running";
  const leadCount  = taskLeadCount(task);
  const domain     = questionDomain(task);
  const activity   = activitySummary(task);

  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "stagger-item w-full rounded-[24px] border p-4 text-left transition-all duration-200",
        isSelected
          ? "border-[color:var(--accent)] bg-[linear-gradient(135deg,rgba(29,76,116,0.10),rgba(255,255,255,0.9))] shadow-[0_0_0_3px_rgba(29,76,116,0.08)]"
          : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] hover:border-[color:var(--border-strong)] hover:bg-white hover:-translate-y-0.5 hover:shadow-[var(--shadow-md)]",
        isRunning && !isSelected && "animate-agent-pulse",
      ].join(" ")}
      style={{ "--delay": `${delay}ms` } as React.CSSProperties}
    >
      {/* Header row */}
      <div className="flex items-start gap-3">
        <AgentStatusDot status={task.status} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-sm font-semibold text-[color:var(--ink)]">
              {task.agent_name || task.title}
            </p>
            <Badge tone={taskStatusTone(task.status)}>
              {taskStatusLabel(task.status)}
            </Badge>
          </div>
          {task.title && task.agent_name && (
            <p className="mt-0.5 truncate text-xs text-[color:var(--muted)]">{task.title}</p>
          )}
        </div>
      </div>

      {/* Activity summary */}
      {activity && (
        <p className={[
          "mt-2.5 text-xs leading-5",
          isRunning ? "text-[color:var(--ink)]" : "text-[color:var(--muted)]",
        ].join(" ")}>
          {isRunning && (
            <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-spin-slow rounded-full border border-[color:var(--accent)] border-t-transparent" />
          )}
          {activity}
        </p>
      )}

      {/* Progress bar */}
      {typeof task.progress === "number" && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between text-[10px] text-[color:var(--muted)]">
            <span>{formatMarketStep(task.market_step)}</span>
            <span>{task.progress}%</span>
          </div>
          <ProgressBar aria-label={task.title} value={task.progress} />
        </div>
      )}

      {/* Tags */}
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Tooltip content="该任务已沉淀的可引用来源数">
          <Badge tone={task.source_count > 0 ? "success" : "default"}>
            {leadCount > task.source_count
              ? `线索 ${leadCount}`
              : `来源 ${task.source_count}`}
          </Badge>
        </Tooltip>
        <Tooltip content="该任务的研究维度分类">
          <Badge>{domain}</Badge>
        </Tooltip>
        {(task.skill_packs ?? []).slice(0, 1).map((sp) => (
          <Badge key={sp}>{formatSkillPack(sp)}</Badge>
        ))}
        {task.command_label && <Badge>{task.command_label}</Badge>}
      </div>
    </button>
  );
}

// ─── Coverage heatmap ──────────────────────────────────────────────────────
function CoverageHeatmap({ tasks }: { tasks: ResearchTaskRecord[] }) {
  const domains = ["定价验证", "竞品差异", "用户反馈", "官网事实", "市场判断"];

  const domainStatus = domains.map((domain) => {
    const domainTasks = tasks.filter((t) => questionDomain(t) === domain);
    if (!domainTasks.length) return { domain, status: "absent" as const };
    const hasRunning   = domainTasks.some((t) => t.status === "running");
    const hasCompleted = domainTasks.some((t) => t.source_count > 0);
    if (hasRunning)   return { domain, status: "active"  as const };
    if (hasCompleted) return { domain, status: "covered" as const };
    return { domain, status: "pending" as const };
  });

  const dotClass = {
    covered: "bg-emerald-500",
    active:  "bg-[color:var(--accent)] animate-ping",
    pending: "bg-amber-400",
    absent:  "bg-[color:var(--border-strong)]",
  };

  const labelClass = {
    covered: "text-emerald-700",
    active:  "text-[color:var(--accent)]",
    pending: "text-amber-700",
    absent:  "text-[color:var(--muted)]",
  };

  return (
    <div className="flex flex-wrap gap-3">
      {domainStatus.map(({ domain, status }) => (
        <Tooltip
          key={domain}
          content={
            status === "covered" ? `${domain}：已有可引用来源` :
            status === "active"  ? `${domain}：正在采集` :
            status === "pending" ? `${domain}：已分配，待推进` :
            `${domain}：当前无对应任务`
          }
        >
          <div className="flex items-center gap-1.5 rounded-full border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.6)] px-3 py-1">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass[status]}`} />
            <span className={`text-[11px] font-medium ${labelClass[status]}`}>{domain}</span>
          </div>
        </Tooltip>
      ))}
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────
export function AgentSwarmBoardAnimated({
  job,
  selectedTaskId,
  onSelectTask,
}: {
  job: ResearchJobRecord;
  selectedTaskId?: string;
  onSelectTask: (taskId: string) => void;
}) {
  const completedCount = job.tasks.filter((t) => t.status === "completed").length;
  const runningCount   = job.tasks.filter((t) => t.status === "running").length;
  const queuedCount    = job.tasks.filter((t) => t.status === "queued").length;

  // Sort: running first, then queued, then completed, then failed
  const sortedTasks = [...job.tasks].sort((a, b) => {
    const rank = { running: 0, queued: 1, failed: 2, completed: 3, cancelled: 4 };
    const ar = rank[a.status as keyof typeof rank] ?? 5;
    const br = rank[b.status as keyof typeof rank] ?? 5;
    if (ar !== br) return ar - br;
    return (b.progress ?? 0) - (a.progress ?? 0);
  });

  return (
    <Card className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>研究组进展</CardTitle>
          <p className="mt-1 text-sm text-[color:var(--muted)]">
            {runningCount > 0
              ? `当前 ${runningCount} 个 Agent 正在执行，点击卡片查看详情。`
              : completedCount === job.tasks.length
              ? "全部子任务已完成，可进入证据或报告查看。"
              : `${queuedCount} 个任务等待分配，${completedCount} 个已完成。`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone={runningCount > 0 ? "success" : "default"}>
            {`${runningCount} 运行中`}
          </Badge>
          <Badge>{`${completedCount}/${job.tasks.length} 完成`}</Badge>
        </div>
      </div>

      {/* Coverage heatmap */}
      <div>
        <p className="mb-2 text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
          知识维度覆盖
        </p>
        <CoverageHeatmap tasks={job.tasks} />
      </div>

      {/* Agent cards grid */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {sortedTasks.map((task, i) => (
          <AgentCard
            key={task.id}
            task={task}
            isSelected={selectedTaskId === task.id}
            onClick={() => onSelectTask(task.id)}
            delay={i * 40}
          />
        ))}
      </div>
    </Card>
  );
}
