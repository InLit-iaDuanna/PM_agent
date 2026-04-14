"use client";

import Link from "next/link";

import { Activity, FileDiff, FileText, MessageSquareText, ScrollText, SearchCheck } from "lucide-react";

import type { ChatSessionRecord, ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { Badge, Button } from "@pm-agent/ui";

import { hasPendingDeltaReply } from "../../../lib/polling";
import { getActiveReportVersionId, getStableReportVersionId } from "./report-version-utils";
import { formatBrowserMode, formatValidationStatus } from "./research-ui-utils";
import { useResearchUiStore } from "../store/ui-store";

const tabs = [
  { id: "stable-report", label: "稳定版报告", prompt: "查看当前可分享版本与决策快照", icon: FileText },
  { id: "latest-draft", label: "最新草稿", prompt: "审阅当前待合入的草稿与扩展内容", icon: ScrollText },
  { id: "evidence", label: "证据来源", prompt: "筛选来源、层级与时间维度的依据", icon: SearchCheck },
  { id: "chat", label: "研究对话", prompt: "基于报告追问、补充或触发补充研究", icon: MessageSquareText },
  { id: "diff", label: "版本对比", prompt: "对比稳定版与工作稿的具体差异", icon: FileDiff },
] as const;

type StatusBadge = { label: string; tone: "success" | "warning" | "danger" | "default" };

function phaseLabel(phase: ResearchJobRecord["current_phase"]) {
  if (phase === "scoping") return "界定范围";
  if (phase === "planning") return "任务规划";
  if (phase === "collecting") return "证据采集";
  if (phase === "verifying") return "结论校验";
  if (phase === "synthesizing") return "报告整理";
  if (phase === "finalizing") return "收尾归档";
  return phase;
}

function nextActionHint(phase: ResearchJobRecord["current_phase"]) {
  if (phase === "scoping") return "正在收敛目标与边界";
  if (phase === "planning") return "正在拆分关键研究问题";
  if (phase === "collecting") return "正在补齐缺口证据";
  if (phase === "verifying") return "正在交叉验证关键结论";
  if (phase === "synthesizing") return "正在整理可决策结论";
  if (phase === "finalizing") return "正在生成最终交付";
  return "正在推进研究流程";
}

export function WorkbenchTabs({
  assets,
  job,
  realtimeConnected,
  session,
}: {
  assets: ResearchAssetsRecord;
  job: ResearchJobRecord;
  realtimeConnected: boolean;
  session: ChatSessionRecord;
}) {
  const { activeTab, setActiveTab } = useResearchUiStore();
  const activeVersionId = getActiveReportVersionId(job);
  const stableVersionId = getStableReportVersionId(job);
  const hasStableVersion = Boolean(stableVersionId);
  const activeLabel = activeVersionId || "待生成";
  const stableLabel = stableVersionId || "待生成";
  const hasVersionMismatch = Boolean(activeVersionId && stableVersionId && activeVersionId !== stableVersionId);
  const deltaPending = hasPendingDeltaReply(session);
  const runtimeSummary = job.runtime_summary;
  const degradeMode = runtimeSummary?.browser_mode?.includes("degraded") ?? false;
  const modelReady = Boolean(runtimeSummary?.llm_enabled && runtimeSummary.validation_status === "valid");
  const statusBadges = ([
    { label: realtimeConnected ? "流式连接" : "自动轮询", tone: realtimeConnected ? "success" : "warning" },
    degradeMode ? { label: "降级模式", tone: "warning" } : null,
    !modelReady ? { label: "模型未配置", tone: "danger" } : null,
    deltaPending ? { label: "补研中", tone: "warning" } : null,
    !hasStableVersion ? { label: "稳定版待生成", tone: "default" } : null,
    hasVersionMismatch ? { label: "新草稿待确认", tone: "warning" } : null,
  ] as Array<StatusBadge | null>).filter((badge): badge is StatusBadge => Boolean(badge));
  const tabMeta = {
    "stable-report": hasStableVersion ? `稳定 ${stableLabel}` : "未生成",
    "latest-draft": activeVersionId ? `草稿 ${activeLabel}` : "暂无草稿",
    evidence: `${assets.evidence.length} 条依据`,
    chat: session.messages.length ? `${session.messages.length} 条对话` : "尚未追问",
    diff: hasVersionMismatch ? "版本有差异" : hasStableVersion ? "版本一致" : "待生成稳定版",
  } as const;
  const summary = `${hasStableVersion ? `稳定 ${stableLabel}` : "稳定待生成"} · ${
    activeVersionId ? `草稿 ${activeLabel}` : "草稿待生成"
  } · ${phaseLabel(job.current_phase)} · ${nextActionHint(job.current_phase)}`;
  const detailRows = [
    `阶段：${phaseLabel(job.current_phase)}`,
    `连接：${realtimeConnected ? "流式" : "轮询"}`,
    `模型：${formatValidationStatus(runtimeSummary?.validation_status)}`,
    `浏览器：${formatBrowserMode(runtimeSummary?.browser_mode)}`,
    `稳定版：${stableLabel}`,
    `工作稿：${activeLabel}`,
  ];
  const diffAvailable = hasVersionMismatch;

  return (
    <div className="sticky top-4 z-20 rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,250,242,0.82)] p-4 shadow-[0_20px_42px_rgba(23,32,51,0.08)] backdrop-blur-xl">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm font-semibold text-[color:var(--ink)]">{summary}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {statusBadges.map((item) => (
                <Badge key={item.label} tone={item.tone}>
                  {item.label}
                </Badge>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              className="inline-flex items-center rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] px-3 py-2 text-sm text-[color:var(--ink)] transition hover:bg-white"
              href={`/research/jobs/${job.id}/report`}
              rel="noreferrer"
              target="_blank"
            >
              <FileText className="mr-2 h-4 w-4" />
              查看研究报告
            </Link>
            <Badge tone={realtimeConnected ? "success" : "warning"}>
              {realtimeConnected ? "SSE 流式连接" : "自动轮询中"}
            </Badge>
            <div className="inline-flex items-center gap-2 rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] px-3 py-2 text-xs text-[color:var(--muted)]">
              <Activity className="h-3.5 w-3.5 text-[color:var(--accent)]" />
              {`${job.running_task_count} 个任务正在执行 · ${assets.claims.length} 条判断`}
            </div>
          </div>
        </div>

        <div className="grid gap-3 xl:grid-cols-[1fr_auto] xl:items-center">
          <div className="flex flex-wrap gap-3">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <Button
                  key={tab.id}
                  className="min-w-[220px] justify-between gap-3"
                  onClick={() => setActiveTab(tab.id)}
                  type="button"
                  variant={activeTab === tab.id ? "primary" : "secondary"}
                >
                  <span className="min-w-0 text-left">
                    <span className="inline-flex items-center">
                      <Icon className="mr-2 h-4 w-4" />
                      {tab.label}
                    </span>
                    <span className={`mt-1 block text-xs ${activeTab === tab.id ? "text-white/80" : "text-[color:var(--muted)]"}`}>
                      {tab.prompt}
                    </span>
                  </span>
                  <span className={`text-xs ${activeTab === tab.id ? "text-white/80" : "text-[color:var(--muted)]"}`}>
                    {tabMeta[tab.id]}
                  </span>
                </Button>
              );
            })}
          </div>
          <div className="flex flex-col gap-3">
            <details className="rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] px-3 py-2 text-xs text-[color:var(--muted)]">
              <summary className="cursor-pointer text-xs font-semibold text-[color:var(--muted)]">系统快照</summary>
              <div className="mt-2 grid gap-1 text-[color:var(--muted)]">
                {detailRows.map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            </details>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={diffAvailable ? "success" : "default"}>{tabMeta.diff}</Badge>
              <Badge>{`证据 ${assets.evidence.length} 条`}</Badge>
              <Badge>{session.messages.length ? `${session.messages.length} 条对话` : "等待对话"}</Badge>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
