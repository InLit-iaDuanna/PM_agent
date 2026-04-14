"use client";

import type { ResearchJobRecord, ResearchTaskRecord } from "@pm-agent/types";
import { Badge, Card, CardDescription, CardTitle, ProgressBar } from "@pm-agent/ui";
import { formatMarketStep, formatSkillPack, taskStatusLabel, taskStatusTone } from "../research-ui-utils";

function activitySummary(task: ResearchTaskRecord) {
  const leadCount = taskLeadCount(task);
  if (task.source_count === 0 && leadCount > 0) {
    return `已命中 ${leadCount} 条候选线索，正在核验与归档。`;
  }
  if (task.current_action) return task.current_action;
  if (task.search_queries?.length) return `最近查询：${task.search_queries[task.search_queries.length - 1]}`;
  if (task.logs?.length) return task.logs[task.logs.length - 1]?.message;
  return task.brief;
}

function statusDotClass(status: ResearchTaskRecord["status"]) {
  if (status === "completed") return "bg-emerald-500";
  if (status === "failed") return "bg-rose-500";
  if (status === "queued") return "bg-amber-500";
  if (status === "cancelled") return "bg-amber-500";
  return "bg-[color:var(--accent)]";
}

function questionDomain(task: ResearchTaskRecord) {
  const step = String(task.market_step || "").toLowerCase();
  const title = String(task.title || "").toLowerCase();
  const brief = String(task.brief || "").toLowerCase();
  const text = `${step} ${title} ${brief}`;
  if (text.includes("price") || text.includes("pricing") || text.includes("定价") || text.includes("报价")) {
    return "定价验证";
  }
  if (text.includes("compet") || text.includes("竞品") || text.includes("替代")) {
    return "竞品差异";
  }
  if (text.includes("review") || text.includes("community") || text.includes("reddit") || text.includes("用户") || text.includes("反馈")) {
    return "用户反馈";
  }
  if (text.includes("official") || text.includes("官网") || text.includes("文档") || text.includes("fact")) {
    return "官网事实";
  }
  return "市场判断";
}

function questionPrompt(domain: string) {
  if (domain === "官网事实") return "核心事实是否有可追溯来源？";
  if (domain === "用户反馈") return "真实用户反馈是否覆盖主要场景？";
  if (domain === "竞品差异") return "关键竞品差异是否足够清晰？";
  if (domain === "定价验证") return "价格区间与策略是否可被验证？";
  return "是否形成可用于决策的判断？";
}

function taskLeadCount(task: ResearchTaskRecord) {
  const visitedCount = (task.visited_sources ?? []).length;
  const queryHitCount = (task.research_rounds ?? []).flatMap((round) => round.query_summaries ?? []).filter((summary) => Number(summary.search_result_count || 0) > 0).length;
  return Math.max(visitedCount, queryHitCount);
}

export function AgentSwarmBoard({
  job,
  selectedTaskId,
  onSelectTask,
}: {
  job: ResearchJobRecord;
  selectedTaskId?: string;
  onSelectTask: (taskId: string) => void;
}) {
  const completedCount = job.tasks.filter((task) => task.status === "completed").length;
  const runningCount = job.tasks.filter((task) => task.status === "running").length;
  const queuedCount = job.tasks.filter((task) => task.status === "queued").length;
  const evidenceReadyCount = job.tasks.filter((task) => task.source_count > 0).length;
  const taskWithLeadsCount = job.tasks.filter((task) => taskLeadCount(task) > 0).length;
  const totalLeadCount = job.tasks.reduce((sum, task) => sum + taskLeadCount(task), 0);

  return (
    <Card className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>研究问题进展</CardTitle>
          <CardDescription>先看问题是否被回答，再按需展开查看执行细节。</CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone="success">{`已回答 ${completedCount}`}</Badge>
          <Badge>{`补证中 ${runningCount}`}</Badge>
          <Badge tone="warning">{`待开始 ${queuedCount}`}</Badge>
          <Badge>{`已有依据 ${evidenceReadyCount}/${job.tasks.length}`}</Badge>
          <Badge tone={totalLeadCount > 0 ? "success" : "default"}>{`已命中线索 ${taskWithLeadsCount}/${job.tasks.length}`}</Badge>
        </div>
      </div>

      <div className="space-y-3">
        {job.tasks.map((task, index) => {
          const isSelected = selectedTaskId === task.id || (!selectedTaskId && index === 0);
          const domain = questionDomain(task);
          const leadCount = taskLeadCount(task);
          return (
            <button
              key={task.id}
              className={`w-full rounded-[28px] border px-4 py-4 text-left transition ${
                isSelected
                  ? "border-[color:var(--accent)] bg-[linear-gradient(135deg,_rgba(29,76,116,0.08),_rgba(255,255,255,0.84))] shadow-[0_16px_34px_rgba(23,32,51,0.08)]"
                  : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] hover:border-[color:var(--border-strong)] hover:bg-white"
              }`}
              onClick={() => onSelectTask(task.id)}
              type="button"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <div className="mt-1 flex flex-col items-center">
                    <span className={`h-2.5 w-2.5 rounded-full ${statusDotClass(task.status)}`} />
                    <span className="mt-1 h-10 w-px bg-[rgba(29,76,116,0.16)]" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{domain}</Badge>
                      <Badge tone={taskStatusTone(task.status)}>{taskStatusLabel(task.status)}</Badge>
                    </div>
                    <p className="mt-2 text-sm font-semibold text-[color:var(--ink)]">{questionPrompt(domain)}</p>
                    <p className="mt-1 text-sm text-[color:var(--ink)]">{task.title}</p>
                    <p className="mt-1 text-sm text-[color:var(--muted)]">{activitySummary(task)}</p>
                    <details className="mt-3 rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.48)] px-3 py-2">
              <summary className="cursor-pointer text-xs font-semibold text-[color:var(--muted)]">查看执行细节</summary>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Badge>{`依据 ${task.source_count}`}</Badge>
                        {leadCount > 0 ? <Badge tone="success">{`线索 ${leadCount}`}</Badge> : null}
                        <Badge>{formatMarketStep(task.market_step)}</Badge>
                        {task.command_label ? <Badge>{task.command_label}</Badge> : null}
                        {task.agent_name ? <Badge>{`执行体 ${task.agent_name}`}</Badge> : null}
                        {(task.skill_packs ?? []).slice(0, 2).map((item) => (
                          <Badge key={item} tone="success">
                            {formatSkillPack(item)}
                          </Badge>
                        ))}
                      </div>
                    </details>
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">回答进度</p>
                  <p className="mt-1 text-lg font-semibold text-[color:var(--ink)]">{task.progress ?? 0}%</p>
                </div>
              </div>

              <div className="mt-4">
                <ProgressBar aria-label={`${task.title}进度`} value={task.progress ?? 0} />
              </div>
              {task.source_count === 0 && leadCount > 0 ? (
                <p className="mt-3 text-xs text-[color:var(--muted)]">当前还在核验候选线索，确认后会转成可引用依据。</p>
              ) : null}
            </button>
          );
        })}
      </div>
    </Card>
  );
}
