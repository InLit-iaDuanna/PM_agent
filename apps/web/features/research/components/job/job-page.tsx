"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FileText, Flag, LayoutDashboard, MessageSquareText, Search, Users } from "lucide-react";

import type { ChatSessionRecord, ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { Tabs, type TabItem } from "@pm-agent/ui";

import { EvidenceExplorer } from "../evidence-explorer";
import { PmChatPanelRefactored } from "../pm-chat-panel-refactored";
import { TaskDetailPanel } from "../task-detail-panel";
import { AgentSwarmBoardAnimated } from "../workbench/agent-swarm-board-animated";
import { useResearchUiStore } from "../../store/ui-store";
import { JobOverviewTab } from "./job-overview-tab";
import { JobCompetitorsTab } from "./job-competitors-tab";

type TabId = "overview" | "agents" | "evidence" | "report" | "chat" | "competitors";

const TABS: TabItem[] = [
  { id: "overview",     label: "概览",   icon: <LayoutDashboard className="h-3.5 w-3.5" /> },
  { id: "agents",       label: "研究组",  icon: <Users className="h-3.5 w-3.5" /> },
  { id: "evidence",     label: "证据库",  icon: <Search className="h-3.5 w-3.5" /> },
  { id: "report",       label: "报告",   icon: <FileText className="h-3.5 w-3.5" /> },
  { id: "chat",         label: "PM 追问", icon: <MessageSquareText className="h-3.5 w-3.5" /> },
  { id: "competitors",  label: "竞品",   icon: <Flag className="h-3.5 w-3.5" /> },
];

interface JobPageProps {
  job: ResearchJobRecord;
  assets: ResearchAssetsRecord;
  session: ChatSessionRecord;
  chatDisabledReason?: string | null;
  realtimeConnected?: boolean;
}

/**
 * JobPage — 重构后的研究任务页
 *
 * 将原来单页 932 行的 job-dashboard 拆成 6 个 Tab：
 *   概览 | 研究组 | 证据库 | 报告 | PM 追问 | 竞品
 *
 * URL 参数 ?tab=xxx 支持直接跳转到指定 tab
 */
export function JobPage({ job, assets, session, chatDisabledReason, realtimeConnected = false }: JobPageProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { selectedTaskId, setSelectedTaskId } = useResearchUiStore();
  const initialTab = (searchParams.get("tab") as TabId) ?? "overview";
  const [activeTab, setActiveTab] = useState<TabId>(
    TABS.some((t) => t.id === initialTab) ? initialTab : "overview",
  );

  useEffect(() => {
    if (!job.tasks.length) {
      return;
    }
    const exists = job.tasks.some((task) => task.id === selectedTaskId);
    if (!selectedTaskId || !exists) {
      setSelectedTaskId(job.tasks[0].id);
    }
  }, [job.tasks, selectedTaskId, setSelectedTaskId]);

  // Sync tab → URL (replace, no history push)
  const handleTabChange = (id: string) => {
    const tab = id as TabId;
    setActiveTab(tab);
    const params = new URLSearchParams(searchParams.toString());
    if (tab === "overview") {
      params.delete("tab");
    } else {
      params.set("tab", tab);
    }
    const qs = params.toString();
    router.replace(`/research/jobs/${job.id}${qs ? `?${qs}` : ""}`, { scroll: false });
  };

  // Derive badge counts for tabs
  const agentCount    = job.tasks.length;
  const runningCount  = job.tasks.filter((t) => t.status === "running").length;
  const evidenceCount = job.source_count;
  const hasReport     = Boolean(job.report_version_id || assets.report?.markdown?.trim());
  const competitorCount = Number(job.competitor_count || 0);

  const tabs: TabItem[] = TABS.map((t) => {
    if (t.id === "agents")      return { ...t, badge: runningCount > 0 ? runningCount : agentCount };
    if (t.id === "evidence")    return { ...t, badge: evidenceCount || undefined };
    if (t.id === "competitors") return { ...t, badge: competitorCount || undefined };
    if (t.id === "report")      return { ...t, disabled: !hasReport };
    return t;
  });

  return (
    <div className="space-y-5">
      {/* Tab bar */}
      <Tabs
        items={tabs}
        activeId={activeTab}
        onChange={handleTabChange}
        variant="underline"
      />

      {/* Tab content */}
      <div>
        {activeTab === "overview" && (
          <JobOverviewTab job={job} assets={assets} />
        )}

        {activeTab === "agents" && (
          <div className="space-y-4">
            <AgentSwarmBoardAnimated
              job={job}
              onSelectTask={setSelectedTaskId}
              selectedTaskId={selectedTaskId}
            />
            <TaskDetailPanel job={job} />
          </div>
        )}

        {activeTab === "evidence" && (
          <EvidenceExplorer assets={assets} />
        )}

        {activeTab === "report" && (
          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-6 text-sm text-[color:var(--muted)]">
            {hasReport
              ? (
                <span>
                  报告内容请在
                  <Link className="mx-1 underline text-[color:var(--ink)]" href={`/research/jobs/${job.id}/report`}>
                    报告阅读页
                  </Link>
                  查看完整版本。
                </span>
              )
              : "报告尚未生成，等待研究任务完成后会自动创建。"}
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

        {activeTab === "competitors" && (
          <JobCompetitorsTab job={job} assets={assets} />
        )}
      </div>
    </div>
  );
}
