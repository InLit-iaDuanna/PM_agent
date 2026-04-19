"use client";

import { useMemo, useState } from "react";

import Link from "next/link";

import { Clock3, FileText, History } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import type { ClaimRecord, ReportDecisionSnapshotRecord, ReportQualityGateRecord, ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle } from "@pm-agent/ui";
import { finalizeResearchReport, getApiErrorMessage } from "../../../lib/api-client";
import { MarkdownContent } from "./markdown-content";
import {
  buildReportContentViews,
  buildReportPreview,
  formatReportTimestamp,
  formatReportVersionTag,
  getActiveReportVersionId,
  getReportVersions,
  getStableReportVersionId,
  getVersionClaims,
  getVersionEvidence,
  hasVersionScopedSources,
  reportLabel,
  reportTone,
  type ReportContentViewId,
} from "./report-version-utils";

import { useResearchUiStore } from "../store/ui-store";
import { formatMarketStep, sourceTierTone } from "./research-ui-utils";

function claimTone(status: ClaimRecord["status"]) {
  if (status === "confirmed") return "success";
  if (status === "verified") return "success";
  if (status === "disputed") return "warning";
  return "default";
}

function claimStatusLabel(status: ClaimRecord["status"]) {
  if (status === "confirmed") return "高置信确认";
  if (status === "verified") return "已验证";
  if (status === "directional") return "方向性参考";
  if (status === "disputed") return "有争议";
  return "待确认";
}

export function ReportReader({
  assets,
  job,
  referenceJob,
  realtimeConnected = false,
  viewMode = "stable",
}: {
  assets: ResearchAssetsRecord;
  job: ResearchJobRecord;
  referenceJob: ResearchJobRecord;
  realtimeConnected?: boolean;
  viewMode?: "stable" | "draft";
}) {
  const { selectedClaimId, setActiveTab, setSelectedClaimId } = useResearchUiStore();
  const [finalizing, setFinalizing] = useState(false);
  const [composeMessage, setComposeMessage] = useState<string | null>(null);
  const [selectedView, setSelectedView] = useState<ReportContentViewId>("brief");
  const queryClient = useQueryClient();
  const reportVersions = getReportVersions(assets, job);
  const recentVersions = reportVersions.slice(0, 4);
  const currentVersion = reportVersions.find((item) => item.version_id === job.report_version_id) || reportVersions[0];
  const resolvedReport = currentVersion
    ? {
        ...assets.report,
        ...currentVersion,
        quality_gate: currentVersion.quality_gate ?? assets.report.quality_gate,
        decision_snapshot: currentVersion.decision_snapshot ?? assets.report.decision_snapshot,
      }
    : assets.report;
  const reportStage = resolvedReport.stage;
  const reportReady = Boolean(resolvedReport.markdown?.trim());
  const qualityGate: ReportQualityGateRecord | undefined = resolvedReport.quality_gate;
  const qualityGateReasons = (qualityGate?.reasons || []).filter((item): item is string => Boolean(item));
  const qualityGateMetrics = qualityGate?.metrics || {};
  const finalizeBlocked = !qualityGate?.pending && qualityGate?.passed === false;
  const finalizeEnabled = viewMode === "draft";
  const finalizeLabel = finalizeBlocked ? "先补充再更新" : "更新报告";
  const reportViews = buildReportContentViews(resolvedReport);
  const activeReportView = reportViews.find((item) => item.id === selectedView) || reportViews[0];
  const decisionSnapshot: Partial<ReportDecisionSnapshotRecord> = resolvedReport.decision_snapshot || {};
  const currentVersionClaims = useMemo(
    () => (currentVersion ? getVersionClaims(assets, currentVersion) : assets.claims),
    [assets, currentVersion],
  );
  const citationRegistry = useMemo(
    () => (currentVersion ? getVersionEvidence(assets, currentVersion, 5) : assets.evidence.slice(0, 5)),
    [assets, currentVersion],
  );
  const currentVersionHasScopedSources = currentVersion ? hasVersionScopedSources(currentVersion) : false;
  const sourcePanelTitle = currentVersionHasScopedSources ? "当前版本来源索引" : "研究来源池样本";
  const sourcePanelDescription = currentVersionHasScopedSources
    ? "这些页面与当前默认版本直接绑定，适合继续回溯正文判断。"
    : "当前版本还没回填逐条来源索引，先展示本次研究来源池里的代表页面。";
  const sourcePanelEmptyMessage = currentVersionHasScopedSources
    ? "当前默认版本还没有绑定外部来源。继续补充研究并更新正文后，这里会自动补齐。"
    : "当前还没有可展示的来源样本。等证据沉淀后，这里会展示来源池里的代表页面。";
  const stableVersionId = getStableReportVersionId(referenceJob);
  const activeVersionId = getActiveReportVersionId(referenceJob);
  const hasStableVersion = Boolean(stableVersionId);
  const hasVersionMismatch = Boolean(stableVersionId && activeVersionId && stableVersionId !== activeVersionId);
  const viewModeBadgeTone: "success" | "warning" = viewMode === "stable" ? "success" : "warning";
  const viewModeLabel = viewMode === "stable" ? "稳定版视图" : "草稿视图";

  const handleFinalizeReport = async () => {
    if (!finalizeEnabled || !reportReady || finalizeBlocked) return;
    setFinalizing(true);
    setComposeMessage(null);
    try {
      const nextAssets = await finalizeResearchReport(job.id, job.report_version_id);
      queryClient.setQueryData(["research-assets", job.id], nextAssets);
      queryClient.setQueryData(["chat-session-assets", job.id], nextAssets);
      const nextQualityGate = nextAssets.report.quality_gate;
      const nextGateBlocked = !nextQualityGate?.pending && nextQualityGate?.passed === false;
      setComposeMessage(
        nextGateBlocked
          ? nextQualityGate?.reasons?.length
            ? `这版内容还不够完整：${nextQualityGate.reasons[0]}`
            : "这版内容还不够完整，已先保留为当前草稿。"
          : reportStage === "final"
            ? "已更新当前报告，上一版已自动保留。"
            : "已更新当前报告，并保留了上一版快照。",
      );
      if (!realtimeConnected) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["research-job", job.id] }),
          queryClient.invalidateQueries({ queryKey: ["chat-session-job", job.id] }),
        ]);
      }
    } catch (error) {
      setComposeMessage(getApiErrorMessage(error, "更新报告失败。"));
    } finally {
      setFinalizing(false);
    }
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[0.75fr_1.25fr]">
      <Card className="space-y-4">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-slate-400" />
          <div>
            <CardTitle>关键结论</CardTitle>
            <CardDescription>点击结论可查看相关证据，并继续追问。</CardDescription>
          </div>
        </div>
        <div className="space-y-3">
          {currentVersionClaims.length ? (
            currentVersionClaims.map((claim) => (
              <button
                key={claim.id}
                className={`w-full rounded-2xl border p-4 text-left transition ${
                  selectedClaimId === claim.id ? "border-slate-900 bg-slate-50" : "border-slate-100 bg-white"
                }`}
                onClick={() => {
                  setSelectedClaimId(claim.id);
                  setActiveTab("evidence");
                }}
                type="button"
              >
                <div className="mb-2 flex items-center justify-between gap-3">
                  <Badge tone={claimTone(claim.status)}>{claimStatusLabel(claim.status)}</Badge>
                  <span className="text-xs text-slate-400">{formatMarketStep(claim.market_step)}</span>
                </div>
                <p className="text-sm font-medium text-slate-900">{claim.claim_text}</p>
              </button>
            ))
          ) : (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              当前版本还没有可浏览的关键结论。等这版正文完成更新后，这里会成为报告和来源之间的导航入口。
            </div>
          )}
        </div>
      </Card>

      <Card className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>当前报告</CardTitle>
            <CardDescription>在这里阅读这版结论，并决定是否继续补充来源或更新正文。</CardDescription>
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge tone={viewModeBadgeTone}>{viewModeLabel}</Badge>
              <Badge tone={reportTone(reportStage)}>{reportLabel(reportStage)}</Badge>
              {stableVersionId ? <Badge tone="success">{`稳定 ${stableVersionId}`}</Badge> : <Badge tone="default">未生成稳定版</Badge>}
              {activeVersionId && hasVersionMismatch ? (
                <Badge tone="warning">{`草稿 ${activeVersionId}`}</Badge>
              ) : null}
              {hasVersionMismatch ? (
                <Badge tone="warning">草稿待合入</Badge>
              ) : hasStableVersion ? (
                <Badge tone="success">版本同步</Badge>
              ) : (
                <Badge tone="default">等待生成稳定版</Badge>
              )}
              {reportVersions.length ? <Badge>{`历史 ${reportVersions.length} 版`}</Badge> : null}
              {typeof resolvedReport.revision_count === "number" ? <Badge>{`修订 ${resolvedReport.revision_count} 次`}</Badge> : null}
              {typeof resolvedReport.feedback_count === "number" ? <Badge>{`反馈 ${resolvedReport.feedback_count} 条`}</Badge> : null}
            </div>
          </div>
          <div className="flex flex-wrap justify-end gap-3">
            {finalizeEnabled ? (
              <Button disabled={!reportReady || finalizing || finalizeBlocked} onClick={handleFinalizeReport} type="button">
                {finalizing ? "更新中..." : finalizeLabel}
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => setActiveTab("chat")}>
              继续追问
            </Button>
            <Link
              className="inline-flex items-center justify-center rounded-xl bg-slate-100 px-4 py-2 text-sm font-medium text-slate-900 transition hover:bg-slate-200"
              href={`/research/jobs/${job.id}/report`}
              rel="noreferrer"
              target="_blank"
            >
              打开完整报告
            </Link>
          </div>
        </div>
        {reportStage === "feedback_pending" ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            有新的反馈和补充结论还没合并进正文。更新报告后，这些内容会并入当前版本。
          </div>
        ) : null}
        {finalizeBlocked ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-950">
            <p className="font-medium">这版内容还不够完整。</p>
            <p className="mt-2 leading-7">关键结论还缺少足够的可追溯来源。补齐以下信息后，再更新正文会更稳。</p>
            {qualityGateReasons.length ? (
              <ul className="mt-3 list-disc space-y-1 pl-5">
                {qualityGateReasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
            <p className="mt-3 text-xs text-amber-900/80">
              {`目前可直接引用的正式来源 ${qualityGateMetrics.formal_evidence_count ?? 0} 条，关键结论 ${qualityGateMetrics.formal_claim_count ?? 0} 条，独立域名 ${qualityGateMetrics.formal_domain_count ?? 0} 个。`}
            </p>
          </div>
        ) : null}
        {!finalizeEnabled && hasVersionMismatch ? (
          <div className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
            当前正在查看稳定版。新的补研结果已经进入工作稿，请切到“最新草稿”后再执行生成稳定版。
          </div>
        ) : null}
        {resolvedReport.markdown?.trim() ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">决策成熟度</p>
                <p className="mt-2 text-lg font-semibold text-slate-950">{String(decisionSnapshot.readiness || "待判断")}</p>
                <p className="mt-1 text-sm text-slate-500">{String(decisionSnapshot.readiness_reason || "成文后会在这里展示当前可用于决策的边界。")}</p>
              </div>
              <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">高置信判断</p>
                <p className="mt-2 text-lg font-semibold text-slate-950">{decisionSnapshot.high_confidence_claims ?? "--"}</p>
                <p className="mt-1 text-sm text-slate-500">适合直接进入评审会讨论的核心结论数量</p>
              </div>
              <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">争议 / 推断</p>
                <p className="mt-2 text-lg font-semibold text-slate-950">{`${decisionSnapshot.disputed_claims ?? 0} / ${decisionSnapshot.inferred_claims ?? 0}`}</p>
                <p className="mt-1 text-sm text-slate-500">帮助 PM 区分已验证结论与仍需谨慎的弱信号</p>
              </div>
              <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">待验证问题</p>
                <p className="mt-2 text-lg font-semibold text-slate-950">{decisionSnapshot.open_questions ?? "--"}</p>
                <p className="mt-1 text-sm text-slate-500">{`来源域名 ${decisionSnapshot.unique_domains ?? "--"} 个`}</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {reportViews.map((view) => (
                <button
                  key={view.id}
                  className={`rounded-2xl border px-4 py-2 text-sm font-medium transition ${
                    activeReportView?.id === view.id ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                  }`}
                  onClick={() => setSelectedView(view.id)}
                  type="button"
                >
                  {view.label}
                </button>
              ))}
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
              <article className="rounded-[28px] border border-slate-200 bg-gradient-to-b from-white via-white to-slate-50/80 p-6 shadow-sm shadow-slate-950/5">
                <div className="mb-6 border-b border-slate-200 pb-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{activeReportView?.label || "完整报告"}</Badge>
                    <Badge tone={reportTone(reportStage)}>{reportLabel(reportStage)}</Badge>
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">
                    {activeReportView?.description || "阅读当前版本的报告内容。"}
                  </p>
                </div>
                {activeReportView?.content?.trim() ? (
                  <MarkdownContent content={activeReportView.content} variant="report" />
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                    {activeReportView?.emptyMessage || "当前视图还没有内容。"}
                  </div>
                )}
              </article>

              <div className="space-y-3">
                <div className="rounded-[28px] border border-slate-200 bg-slate-50/80 p-4">
                  <p className="text-sm font-semibold text-slate-900">决策快照</p>
                  <p className="mt-1 text-xs text-slate-500">快速确认这份成文现在适合支撑什么程度的 PM 决策。</p>
                  <div className="mt-4 space-y-3 text-sm">
                    <div className="rounded-2xl bg-white px-3 py-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">当前判断</p>
                      <p className="mt-1 font-medium text-slate-900">{String(decisionSnapshot.readiness || "待判断")}</p>
                    </div>
                    <div className="rounded-2xl bg-white px-3 py-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">建议下一步</p>
                      <p className="mt-1 text-slate-700">{String(decisionSnapshot.next_step || "成文后会在这里展示优先动作。")}</p>
                    </div>
                    <div className="rounded-2xl bg-white px-3 py-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">使用边界</p>
                      <p className="mt-1 text-slate-700">{String(decisionSnapshot.readiness_reason || "结合冲突与边界视图一起判断是否还需要补研。")}</p>
                    </div>
                  </div>
                </div>

                <div className="rounded-[28px] border border-slate-200 bg-slate-50/80 p-4">
                  <p className="text-sm font-semibold text-slate-900">{sourcePanelTitle}</p>
                  <p className="mt-1 text-xs text-slate-500">{sourcePanelDescription}</p>
                  <div className="mt-4 space-y-2">
                    {citationRegistry.length ? (
                      citationRegistry.map((item) => (
                        <a
                          key={item.id}
                          className="block rounded-2xl border border-slate-200 bg-white px-3 py-3 transition hover:border-slate-300"
                          href={item.source_url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge>{item.citation_label || item.id}</Badge>
                            {item.source_tier_label ? <Badge tone={sourceTierTone(item.source_tier)}>{item.source_tier_label}</Badge> : null}
                          </div>
                          <p className="mt-2 text-sm font-medium text-slate-900">{item.title}</p>
                          <p className="mt-1 text-xs text-slate-500">{item.source_domain || item.source_url}</p>
                        </a>
                      ))
                    ) : (
                      <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-3 py-5 text-sm text-slate-500">{sourcePanelEmptyMessage}</div>
                    )}
                  </div>
                </div>

                <div className="rounded-[28px] border border-slate-200 bg-slate-50/80 p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <History className="h-4 w-4 text-slate-400" />
                    <div>
                      <p className="text-sm font-semibold text-slate-900">历史版本</p>
                      <p className="text-xs text-slate-500">每次更新都会保留一个可回看的版本。</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    {recentVersions.map((version) => {
                      const isCurrentVersion = version.version_id === job.report_version_id;
                      return (
                        <div
                          key={version.version_id}
                          className={`rounded-2xl border px-3 py-3 ${
                            isCurrentVersion ? "border-slate-900 bg-white" : "border-slate-200 bg-white/70"
                          }`}
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge>{formatReportVersionTag(version)}</Badge>
                            <Badge tone={reportTone(version.stage)}>{version.label || reportLabel(version.stage)}</Badge>
                            {isCurrentVersion ? <Badge tone="success">当前</Badge> : null}
                          </div>
                          <p className="mt-2 text-sm font-medium text-slate-900">{buildReportPreview(version.markdown, 72)}</p>
                          <p className="mt-2 flex items-center gap-1 text-xs text-slate-500">
                            <Clock3 className="h-3.5 w-3.5" />
                            {formatReportTimestamp(version.updated_at || version.generated_at)}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                  {reportVersions.length > recentVersions.length ? (
                    <p className="mt-3 text-xs text-slate-500">{`另有 ${reportVersions.length - recentVersions.length} 个历史版本可在完整报告中查看。`}</p>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            报告正文还在整理中。准备好后，你可以继续追问，并把新增反馈合并进下一版。
          </div>
        )}
        {composeMessage ? <p className="text-sm text-slate-500">{composeMessage}</p> : null}
      </Card>
    </div>
  );
}
