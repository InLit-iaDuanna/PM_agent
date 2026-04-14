"use client";

import type { ChatSessionRecord, ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";

import { useResearchUiStore } from "../store/ui-store";
import { EvidenceExplorer } from "./evidence-explorer";
import { JobDashboard } from "./job-dashboard";
import { PmChatPanel } from "./pm-chat-panel";
import { RequestStateCard } from "./request-state-card";
import { ReportReader } from "./report-reader";
import { getActiveReportVersionId, getStableReportVersionId } from "./report-version-utils";
import { VersionDiffPanel } from "./version-diff-panel";
import { WorkbenchTabs } from "./workbench-tabs";

export function ResearchWorkbench({
  job,
  assets,
  chatDisabledReason,
  realtimeConnected = false,
  session,
}: {
  job: ResearchJobRecord;
  assets: ResearchAssetsRecord;
  chatDisabledReason?: string | null;
  realtimeConnected?: boolean;
  session: ChatSessionRecord;
}) {
  const { activeTab } = useResearchUiStore();
  const activeVersionId = getActiveReportVersionId(job);
  const stableVersionId = getStableReportVersionId(job);
  const stableJob = { ...job, report_version_id: stableVersionId ?? undefined };
  const draftJob = { ...job, report_version_id: activeVersionId ?? undefined };
  const showDiff = Boolean(activeVersionId && stableVersionId && activeVersionId !== stableVersionId);

  return (
    <div className="space-y-6">
      <JobDashboard job={job} assets={assets} />
      <WorkbenchTabs assets={assets} job={job} realtimeConnected={realtimeConnected} session={session} />
      {activeTab === "stable-report" ? (
        stableVersionId ? (
          <ReportReader
            assets={assets}
            job={stableJob}
            referenceJob={job}
            realtimeConnected={realtimeConnected}
            viewMode="stable"
          />
        ) : (
          <RequestStateCard
            title="稳定版尚未生成"
            description="当前只有工作稿。先在“最新草稿”中审阅补研结果，确认无误后再执行生成稳定版，系统才会产出可分享版本。"
          />
        )
      ) : null}
      {activeTab === "latest-draft" ? (
        <ReportReader
          assets={assets}
          job={draftJob}
          referenceJob={job}
          realtimeConnected={realtimeConnected}
          viewMode="draft"
        />
      ) : null}
      {activeTab === "evidence" ? <EvidenceExplorer assets={assets} /> : null}
      {activeTab === "chat" ? (
        <PmChatPanel
          assets={assets}
          chatDisabledReason={chatDisabledReason}
          job={job}
          realtimeConnected={realtimeConnected}
          session={session}
        />
      ) : null}
      {activeTab === "diff" ? (
        <VersionDiffPanel job={job} enabled={showDiff} />
      ) : null}
    </div>
  );
}
