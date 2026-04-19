"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FileText, Flag, LayoutDashboard, MessageSquareText, Search, Users } from "lucide-react";

import type { ChatSessionRecord, ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { Badge, Button, ProgressBar, Tabs, type TabItem } from "@pm-agent/ui";

import { EvidenceExplorer } from "../evidence-explorer";
import { PmChatPanelRefactored } from "../pm-chat-panel-refactored";
import { TaskDetailPanel } from "../task-detail-panel";
import { AgentSwarmBoardAnimated } from "../workbench/agent-swarm-board-animated";
import { useResearchUiStore } from "../../store/ui-store";
import { JobCompetitorsTab } from "./job-competitors-tab";
import { JobOverviewTab } from "./job-overview-tab";

type TabId = "overview" | "agents" | "evidence" | "report" | "chat" | "competitors";

const TABS: TabItem[] = [
  { id: "overview", label: "总览", icon: <LayoutDashboard className="h-3.5 w-3.5" /> },
  { id: "agents", label: "任务群", icon: <Users className="h-3.5 w-3.5" /> },
  { id: "evidence", label: "证据库", icon: <Search className="h-3.5 w-3.5" /> },
  { id: "report", label: "报告", icon: <FileText className="h-3.5 w-3.5" /> },
  { id: "chat", label: "PM 对话", icon: <MessageSquareText className="h-3.5 w-3.5" /> },
  { id: "competitors", label: "竞品", icon: <Flag className="h-3.5 w-3.5" /> },
];

interface JobPageProps {
  job: ResearchJobRecord;
  assets: ResearchAssetsRecord;
  session: ChatSessionRecord;
  chatDisabledReason?: string | null;
  realtimeConnected?: boolean;
}

function phaseLabel(phase?: string) {
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

function statusLabel(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode === "diagnostic") return "诊断完成";
  if (job.status === "completed") return "已完成";
  if (job.status === "failed") return "失败";
  if (job.status === "cancelled") return "已取消";
  if (job.status === "planning") return "规划中";
  if (job.status === "verifying") return "校验中";
  if (job.status === "synthesizing") return "成文中";
  return "进行中";
}

function statusTone(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode !== "diagnostic") return "success" as const;
  if (job.status === "failed") return "danger" as const;
  if (job.status === "cancelled") return "warning" as const;
  return "default" as const;
}

function workflowLabel(job: ResearchJobRecord) {
  return job.workflow_label || "研究任务";
}

export function JobPage({ job, assets, session, chatDisabledReason, realtimeConnected = false }: JobPageProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { selectedTaskId, setSelectedTaskId } = useResearchUiStore();
  const initialTab = (searchParams.get("tab") as TabId) ?? "overview";
  const [activeTab, setActiveTab] = useState<TabId>(TABS.some((tab) => tab.id === initialTab) ? initialTab : "overview");

  useEffect(() => {
    if (!job.tasks.length) return;
    const exists = job.tasks.some((task) => task.id === selectedTaskId);
    if (!selectedTaskId || !exists) {
      setSelectedTaskId(job.tasks[0].id);
    }
  }, [job.tasks, selectedTaskId, setSelectedTaskId]);

  const handleTabChange = (id: string) => {
    const tab = id as TabId;
    setActiveTab(tab);
    const params = new URLSearchParams(searchParams.toString());
    if (tab === "overview") {
      params.delete("tab");
    } else {
      params.set("tab", tab);
    }
    const queryString = params.toString();
    router.replace(`/research/jobs/${job.id}${queryString ? `?${queryString}` : ""}`, { scroll: false });
  };

  const agentCount = job.tasks.length;
  const runningCount = job.tasks.filter((task) => task.status === "running").length;
  const evidenceCount = job.source_count;
  const hasReport = Boolean(job.report_version_id || assets.report?.markdown?.trim());
  const competitorCount = Number(job.competitor_count || 0);

  const tabs: TabItem[] = TABS.map((tab) => {
    if (tab.id === "agents") return { ...tab, badge: runningCount > 0 ? runningCount : agentCount };
    if (tab.id === "evidence") return { ...tab, badge: evidenceCount || undefined };
    if (tab.id === "competitors") return { ...tab, badge: competitorCount || undefined };
    if (tab.id === "report") return { ...tab, disabled: !hasReport };
    return tab;
  });

  return (
    <div className="space-y-6">
      <section className="paper-panel relative overflow-hidden rounded-[34px] px-6 py-6 sm:px-7 xl:px-8">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-[radial-gradient(circle_at_top_left,rgba(29,76,116,0.18),transparent_40%),radial-gradient(circle_at_top_right,rgba(197,129,32,0.12),transparent_34%)]" />
        <div className="relative space-y-6">
          <div className="flex flex-wrap items-center gap-2 text-sm text-[color:var(--muted)]">
            <Link className="hover:text-[color:var(--ink)]" href="/">
              研究指挥台
            </Link>
            <span>·</span>
            <span>{workflowLabel(job)}</span>
            <span>·</span>
            <span>{phaseLabel(job.current_phase)}</span>
          </div>

          <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr] xl:items-start">
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={statusTone(job)}>{statusLabel(job)}</Badge>
                <Badge>{phaseLabel(job.current_phase)}</Badge>
                {job.workflow_label ? <Badge>{job.workflow_label}</Badge> : null}
                {job.report_version_id ? <Badge tone="success">{job.report_version_id}</Badge> : null}
                <Badge tone={realtimeConnected ? "success" : "default"}>{realtimeConnected ? "实时同步" : "轮询更新"}</Badge>
              </div>

              <div className="space-y-3">
                <h1 className="section-title text-[2.3rem] leading-[1.06] text-[color:var(--ink)] sm:text-[3rem]">
                  {job.topic}
                </h1>
                <p className="max-w-3xl text-sm leading-7 text-[color:var(--muted)] sm:text-[15px]">
                  {job.orchestration_summary || "查看任务拆解、证据保留、报告演化以及 PM 对话补研的完整上下文。"}
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                {hasReport ? (
                  <Button asChild>
                    <Link href={`/research/jobs/${job.id}/report`}>
                      <FileText className="mr-2 h-4 w-4" />
                      打开报告阅读页
                    </Link>
                  </Button>
                ) : null}
                <Button asChild variant="secondary">
                  <Link href={`/research/jobs/${job.id}?tab=chat`}>
                    <MessageSquareText className="mr-2 h-4 w-4" />
                    进入 PM 对话
                  </Link>
                </Button>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-2">
              <QuickMetric label="总体进度" value={`${job.overall_progress}%`} helper={phaseLabel(job.current_phase)} />
              <QuickMetric label="运行任务" value={`${runningCount}/${agentCount}`} helper="活跃 agent / 全部子任务" />
              <QuickMetric label="可引用来源" value={`${job.source_count}`} helper="已沉淀进入依据池" />
              <QuickMetric label="结论条目" value={`${job.claims_count}`} helper="支持报告与对话复核" />
            </div>
          </div>

          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.68)] px-5 py-5">
            <div className="mb-2 flex items-center justify-between text-sm text-[color:var(--muted)]">
              <span>研究推进度</span>
              <span>{job.overall_progress}%</span>
            </div>
            <ProgressBar aria-label="总体进度" value={job.overall_progress} />
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-[color:var(--muted)]">
              <span>{job.completed_task_count}/{job.tasks.length} 个任务已完成</span>
              <span>·</span>
              <span>{job.failed_task_count} 个失败</span>
              <span>·</span>
              <span>{job.source_count} 条来源</span>
              <span>·</span>
              <span>{job.claims_count} 条结论</span>
            </div>
          </div>
        </div>
      </section>

      <div className="flex justify-center">
        <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,250,242,0.82)] p-2 shadow-[var(--shadow-sm)]">
          <Tabs items={tabs} activeId={activeTab} onChange={handleTabChange} variant="underline" />
        </div>
      </div>

      <div>
        {activeTab === "overview" && <JobOverviewTab job={job} assets={assets} />}

        {activeTab === "agents" && (
          <div className="space-y-4">
            <AgentSwarmBoardAnimated job={job} onSelectTask={setSelectedTaskId} selectedTaskId={selectedTaskId} />
            <TaskDetailPanel job={job} />
          </div>
        )}

        {activeTab === "evidence" && <EvidenceExplorer assets={assets} />}

        {activeTab === "report" && (
          <div className="minimal-panel px-6 py-6 text-sm text-[color:var(--muted)]">
            {hasReport ? (
              <span>
                报告内容请前往
                <Link className="mx-1 text-[color:var(--ink)] underline" href={`/research/jobs/${job.id}/report`}>
                  报告阅读页
                </Link>
                查看完整版本。
              </span>
            ) : (
              "报告尚未生成，等待研究任务完成后会自动创建。"
            )}
          </div>
        )}

        {activeTab === "chat" && (
          <PmChatPanelRefactored
            assets={assets}
            chatDisabledReason={chatDisabledReason}
            job={job}
            realtimeConnected={realtimeConnected}
            session={session}
          />
        )}

        {activeTab === "competitors" && <JobCompetitorsTab job={job} assets={assets} />}
      </div>
    </div>
  );
}

function QuickMetric({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-4 py-4 shadow-[var(--shadow-sm)]">
      <p className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{value}</p>
      <p className="mt-1 text-xs leading-5 text-[color:var(--muted)]">{helper}</p>
    </div>
  );
}
