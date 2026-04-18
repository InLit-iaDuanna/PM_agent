"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FileText, Flag, LayoutDashboard, MessageSquareText, Search, Users } from "lucide-react";

import type { ChatSessionRecord, ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { Badge, Tabs, type TabItem } from "@pm-agent/ui";

import { EvidenceExplorer } from "../evidence-explorer";
import { PmChatPanelRefactored } from "../pm-chat-panel-refactored";
import { TaskDetailPanel } from "../task-detail-panel";
import { AgentSwarmBoardAnimated } from "../workbench/agent-swarm-board-animated";
import { useResearchUiStore } from "../../store/ui-store";
import { JobOverviewTab } from "./job-overview-tab";
import { JobCompetitorsTab } from "./job-competitors-tab";

type TabId = "overview" | "agents" | "evidence" | "report" | "chat" | "competitors";

const TABS: TabItem[] = [
  { id: "overview", label: "Overview", icon: <LayoutDashboard className="h-3.5 w-3.5" /> },
  { id: "agents", label: "Agents", icon: <Users className="h-3.5 w-3.5" /> },
  { id: "evidence", label: "Evidence", icon: <Search className="h-3.5 w-3.5" /> },
  { id: "report", label: "Report", icon: <FileText className="h-3.5 w-3.5" /> },
  { id: "chat", label: "Chat", icon: <MessageSquareText className="h-3.5 w-3.5" /> },
  { id: "competitors", label: "Competitors", icon: <Flag className="h-3.5 w-3.5" /> },
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
    scoping: "Plan",
    planning: "Plan",
    collecting: "Search",
    verifying: "Verify",
    synthesizing: "Synthesize",
    finalizing: "Done",
  };
  return map[phase ?? ""] ?? "Search";
}

function statusLabel(job: Pick<ResearchJobRecord, "status" | "completion_mode">) {
  if (job.status === "completed" && job.completion_mode === "diagnostic") return "Diagnostic";
  if (job.status === "completed") return "Complete";
  if (job.status === "failed") return "Failed";
  if (job.status === "cancelled") return "Cancelled";
  if (job.status === "planning") return "Planning";
  if (job.status === "verifying") return "Verifying";
  if (job.status === "synthesizing") return "Writing";
  return "In progress";
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
      <section className="minimal-panel px-5 py-5 sm:px-7">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-sm text-[color:var(--muted)]">
              <Link className="hover:text-[color:var(--ink)]" href="/">
                PM Research
              </Link>
              <span>·</span>
              <span>{job.topic}</span>
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)] sm:text-3xl">{job.topic}</h1>
              <p className="mt-2 max-w-3xl text-sm leading-7 text-[color:var(--muted)]">
                {job.orchestration_summary || "查看当前研究进度、证据、报告与后续追问。"}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={job.status === "completed" ? "success" : job.status === "failed" ? "danger" : "default"}>
                {statusLabel(job)}
              </Badge>
              <Badge>{phaseLabel(job.current_phase)}</Badge>
              {job.workflow_label ? <Badge>{job.workflow_label}</Badge> : null}
              {job.report_version_id ? <Badge tone="success">{job.report_version_id}</Badge> : null}
            </div>
          </div>

          <div className="grid min-w-[220px] gap-3 sm:grid-cols-3 lg:w-[320px] lg:grid-cols-1">
            <MiniSummary label="Progress" value={`${job.overall_progress}%`} />
            <MiniSummary label="Sources" value={`${job.source_count}`} />
            <MiniSummary label="Claims" value={`${job.claims_count}`} />
          </div>
        </div>
      </section>

      <div className="flex justify-center">
        <div className="rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(245,246,248,0.92)] p-2 shadow-[var(--shadow-sm)]">
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
                报告内容请在
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

function MiniSummary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] border border-[color:var(--border-soft)] bg-white/82 px-4 py-3 shadow-[var(--shadow-sm)]">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-1 text-lg font-semibold tracking-[-0.03em] text-[color:var(--ink)]">{value}</p>
    </div>
  );
}
