"use client";

import { useEffect, useMemo, useState } from "react";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ArrowLeft, BookOpenText, Clock3, Copy, FileText, History, ListTree, Sparkles } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type { ReportDecisionSnapshotRecord, ReportQualityGateRecord } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle } from "@pm-agent/ui";

import { buildDemoAssets, buildDemoJob } from "../../../lib/demo-data";
import { fetchResearchAssets, fetchResearchJob, finalizeResearchReport, getApiErrorMessage } from "../../../lib/api-client";
import { getPollingInterval } from "../../../lib/polling";
import { useResearchJobStream } from "../hooks/use-research-job-stream";
import { MarkdownContent } from "./markdown-content";
import { RequestStateCard } from "./request-state-card";
import { sourceTierTone } from "./research-ui-utils";
import {
  buildReportContentViews,
  buildHeadingAnchor,
  buildReportPreview,
  extractReportOutline,
  formatReportTimestamp,
  formatReportVersionTag,
  getReportVersions,
  getVersionEvidence,
  getVersionSourceDomains,
  hasVersionScopedSources,
  reportLabel,
  reportTone,
  type ReportContentViewId,
} from "./report-version-utils";

export function ResearchReportPage({ jobId }: { jobId: string }) {
  const isDemoJob = jobId === "demo-job";
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requestedVersionId = searchParams.get("version");
  const queryClient = useQueryClient();
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(requestedVersionId);
  const [finalizing, setFinalizing] = useState(false);
  const [composeMessage, setComposeMessage] = useState<string | null>(null);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const [selectedView, setSelectedView] = useState<ReportContentViewId>("brief");
  const jobStream = useResearchJobStream({ enabled: !isDemoJob, jobId });

  const jobQuery = useQuery({
    queryKey: ["research-job", jobId],
    queryFn: () => (isDemoJob ? Promise.resolve(buildDemoJob(jobId)) : fetchResearchJob(jobId)),
    initialData: isDemoJob ? buildDemoJob(jobId) : undefined,
    refetchInterval: ({ state }) => (jobStream.shouldPoll ? getPollingInterval(state.data?.status, { activeMs: 1000 }) : false),
  });

  const assetsQuery = useQuery({
    queryKey: ["research-assets", jobId],
    queryFn: () => (isDemoJob ? Promise.resolve(buildDemoAssets(jobId)) : fetchResearchAssets(jobId)),
    initialData: isDemoJob ? buildDemoAssets(jobId) : undefined,
    refetchInterval: () => (jobStream.shouldPoll ? getPollingInterval(jobQuery.data?.status) : false),
  });

  const reportVersions = useMemo(
    () => (jobQuery.data && assetsQuery.data ? getReportVersions(assetsQuery.data, jobQuery.data) : []),
    [assetsQuery.data, jobQuery.data],
  );

  useEffect(() => {
    if (requestedVersionId && reportVersions.some((version) => version.version_id === requestedVersionId)) {
      setSelectedVersionId(requestedVersionId);
      return;
    }

    const fallbackVersionId = jobQuery.data?.report_version_id || reportVersions[0]?.version_id || null;
    if (!fallbackVersionId) {
      return;
    }

    setSelectedVersionId((currentValue) => {
      if (currentValue && reportVersions.some((version) => version.version_id === currentValue)) {
        return currentValue;
      }
      return fallbackVersionId;
    });
  }, [jobQuery.data?.report_version_id, reportVersions, requestedVersionId]);

  useEffect(() => {
    if (!requestedVersionId || !reportVersions.length) {
      return;
    }
    if (reportVersions.some((version) => version.version_id === requestedVersionId)) {
      return;
    }
    const fallbackVersionId = jobQuery.data?.report_version_id || reportVersions[0]?.version_id;
    if (!fallbackVersionId) {
      return;
    }
    const nextUrl =
      fallbackVersionId === jobQuery.data?.report_version_id ? pathname : `${pathname}?version=${encodeURIComponent(fallbackVersionId)}`;
    router.replace(nextUrl, { scroll: false });
  }, [jobQuery.data?.report_version_id, pathname, reportVersions, requestedVersionId, router]);

  const selectedVersion =
    reportVersions.find((version) => version.version_id === selectedVersionId) ||
    reportVersions.find((version) => version.version_id === jobQuery.data?.report_version_id) ||
    reportVersions[0];
  const versionHasScopedSources = selectedVersion ? hasVersionScopedSources(selectedVersion) : false;
  const versionEvidencePool = useMemo(
    () => (selectedVersion && assetsQuery.data ? getVersionEvidence(assetsQuery.data, selectedVersion) : []),
    [assetsQuery.data, selectedVersion],
  );
  const citationRegistry = useMemo(() => versionEvidencePool.slice(0, 6), [versionEvidencePool]);
  const versionSourceDomains = selectedVersion ? getVersionSourceDomains(selectedVersion, versionEvidencePool) : [];

  useEffect(() => {
    setCopyMessage(null);
  }, [selectedVersion?.version_id, selectedView]);

  useEffect(() => {
    if (!jobStream.isStreaming) {
      return;
    }
    void Promise.all([jobQuery.refetch(), assetsQuery.refetch()]);
  }, [assetsQuery.refetch, jobQuery.refetch, jobStream.isStreaming]);

  const errorMessage = [jobQuery.error, assetsQuery.error].find(Boolean);

  if (errorMessage) {
    return (
      <RequestStateCard
        actionLabel="重新加载"
        description={getApiErrorMessage(errorMessage, "报告暂时无法加载，请稍后重试。若问题持续，再检查服务连接或任务状态。")}
        onAction={() => {
          setComposeMessage(null);
          void Promise.all([jobQuery.refetch(), assetsQuery.refetch()]);
        }}
        title="暂时无法加载报告"
      />
    );
  }

  if (!jobQuery.data || !assetsQuery.data) {
    return <RequestStateCard description="正在加载报告内容和版本历史。" loading title="正在打开研究报告" />;
  }

  if (!selectedVersion) {
    return (
      <RequestStateCard
        actionLabel="回到研究页"
        description="当前任务的报告正文还在整理中。准备好后，这里会自动展示全文和历史版本。"
        onAction={() => router.push(`/research/jobs/${jobId}`)}
        title="报告尚未生成"
      />
    );
  }

  const reportReady = Boolean(assetsQuery.data.report.markdown?.trim());
  const qualityGate: ReportQualityGateRecord | undefined = assetsQuery.data.report.quality_gate;
  const qualityGateReasons = (qualityGate?.reasons || []).filter((item): item is string => Boolean(item));
  const qualityGateMetrics = qualityGate?.metrics || {};
  const finalizeBlocked = !qualityGate?.pending && qualityGate?.passed === false;
  const finalizeLabel = finalizeBlocked ? "先补充再更新" : "更新报告";
  const outline = extractReportOutline(selectedVersion.markdown);
  const reportViews = buildReportContentViews(selectedVersion);
  const activeReportView = reportViews.find((item) => item.id === selectedView) || reportViews[0];
  const decisionSnapshot: Partial<ReportDecisionSnapshotRecord> =
    selectedVersion.decision_snapshot || assetsQuery.data.report.decision_snapshot || {};
  const isCurrentVersion = selectedVersion.version_id === jobQuery.data.report_version_id;
  const selectedVersionTag = formatReportVersionTag(selectedVersion);
  const defaultReferenceVersionTag = jobQuery.data.report_version_id || selectedVersion.version_id;
  const sourceTierSummary = (() => {
    const counts = new Map<string, number>();
    for (const item of versionEvidencePool) {
      const label = item.source_tier_label || item.source_tier || "待分层";
      counts.set(label, (counts.get(label) || 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((left, right) => right[1] - left[1])
      .slice(0, 3)
      .map(([label, count]) => `${label} ${count}`)
      .join(" / ");
  })();
  const sourceDomainCount =
    versionHasScopedSources ? versionSourceDomains.length : (decisionSnapshot.unique_domains ?? (versionSourceDomains.length || "--"));
  const openQuestionCount = decisionSnapshot.open_questions ?? "--";
  const versionEvidenceCount =
    versionHasScopedSources
      ? (selectedVersion.evidence_ids?.length ?? versionEvidencePool.length)
      : typeof selectedVersion.evidence_count === "number"
        ? selectedVersion.evidence_count
        : versionEvidencePool.length;
  const versionEvidenceHelper =
    versionHasScopedSources
      ? "这版正文关联的来源数"
      : typeof selectedVersion.evidence_count === "number"
        ? "该版本只记录了来源数量，暂未回填逐条来源索引"
        : "当前缺少版本级来源快照，先展示研究来源池总量";
  const sourcePanelTitle = versionHasScopedSources ? "当前版本来源索引" : "研究来源池样本";
  const sourcePanelDescription = versionHasScopedSources
    ? "这些页面与当前阅读版本直接绑定，可据此复核正文判断。"
    : "当前版本还没回填逐条来源索引，先展示本次研究来源池里的高权重页面。";
  const sourcePanelEmptyMessage = versionHasScopedSources
    ? versionEvidenceCount > 0
      ? "这版已记录来源索引，但来源明细暂未完全回填。"
      : "这一版正文还没有绑定外部来源。继续补充研究后，这里会展示实际引用页面。"
    : "当前还没有可展示的来源样本。等证据沉淀后，这里会展示来源池里的代表页面。";

  const handleSelectVersion = (versionId: string) => {
    setSelectedVersionId(versionId);
    router.replace(`${pathname}?version=${encodeURIComponent(versionId)}`, { scroll: false });
  };

  const handleJumpToCurrentVersion = () => {
    const currentVersionId = jobQuery.data?.report_version_id;
    if (!currentVersionId) return;
    handleSelectVersion(currentVersionId);
  };

  const handleScrollToHeading = (heading: string) => {
    const anchor = buildHeadingAnchor(heading);
    if (!anchor) return;
    const target = document.getElementById(anchor);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.replaceState(null, "", `${pathname}?version=${encodeURIComponent(selectedVersion.version_id)}#${anchor}`);
  };

  const handleCopyCurrentView = async () => {
    if (!activeReportView?.content?.trim()) return;
    try {
      await navigator.clipboard.writeText(activeReportView.content);
      setCopyMessage(`已复制${activeReportView.label}。`);
    } catch (error) {
      setCopyMessage(getApiErrorMessage(error, "复制当前视图失败。"));
    }
  };

  const handleFinalizeReport = async () => {
    if (!reportReady || finalizeBlocked) return;
    setFinalizing(true);
    setComposeMessage(null);
    try {
      const nextAssets = await finalizeResearchReport(jobId, selectedVersion.version_id);
      queryClient.setQueryData(["research-assets", jobId], nextAssets);
      queryClient.setQueryData(["chat-session-assets", jobId], nextAssets);
      const nextQualityGate = nextAssets.report.quality_gate;
      const nextGateBlocked = !nextQualityGate?.pending && nextQualityGate?.passed === false;
      if (nextGateBlocked) {
        setComposeMessage(
          nextQualityGate?.reasons?.length
            ? `这版内容还不够完整：${nextQualityGate.reasons[0]}`
            : "这版内容还不够完整，已先保留为当前草稿。",
        );
      } else {
        setSelectedVersionId(null);
        setComposeMessage(assetsQuery.data.report.stage === "final" ? "已更新当前报告，上一版已自动保留。" : "已更新当前报告，并保留了上一版快照。");
      }
      router.replace(pathname, { scroll: false });
      if (jobStream.shouldPoll) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["research-job", jobId] }),
          queryClient.invalidateQueries({ queryKey: ["chat-session-job", jobId] }),
        ]);
      }
    } catch (error) {
      setComposeMessage(getApiErrorMessage(error, "更新报告失败，请稍后重试。"));
    } finally {
      setFinalizing(false);
    }
  };

  return (
    <div className="space-y-6 pb-8">
      <section className="rounded-[36px] border border-slate-200 bg-[radial-gradient(circle_at_top_left,_rgba(148,163,184,0.22),_transparent_38%),radial-gradient(circle_at_bottom_right,_rgba(251,191,36,0.12),_transparent_32%),linear-gradient(135deg,_#ffffff,_#f8fafc)] p-6 shadow-sm shadow-slate-950/5 xl:p-8">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            <Link
              className="inline-flex items-center gap-2 text-sm font-medium text-slate-600 transition hover:text-slate-900"
              href={`/research/jobs/${jobId}`}
            >
              <ArrowLeft className="h-4 w-4" />
              返回研究页
            </Link>
            <div className="flex items-center gap-3">
              <div className="rounded-[22px] bg-slate-900 px-3 py-2 text-white shadow-lg shadow-slate-950/10">
                <FileText className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-medium text-slate-500">研究报告</p>
                <h1 className="text-2xl font-semibold tracking-tight text-slate-950 xl:text-[2rem]">{jobQuery.data.topic}</h1>
              </div>
            </div>
            <div className="max-w-4xl space-y-3">
              <p className="text-sm leading-7 text-slate-600">
                这里汇总每一版研究结论，建议先看摘要判断，再按需展开正文、当前版本引用来源和历史版本。
              </p>
              <div className="rounded-[24px] border border-white/80 bg-white/80 px-4 py-4 shadow-sm shadow-slate-950/5 backdrop-blur">
                <div className="flex flex-wrap items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
                  <Sparkles className="h-3.5 w-3.5" />
                  默认参考版本
                </div>
                <p className="mt-2 text-sm leading-7 text-slate-700">
                  你当前正在阅读 <span className="font-semibold text-slate-950">{selectedVersionTag}</span>。
                  {isCurrentVersion
                    ? " 该版本也是当前默认参考版本，会用于研究对话与导出。"
                    : ` 研究对话与导出默认参考 ${defaultReferenceVersionTag}。切换历史版本只影响当前阅读视图。`}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone={reportTone(assetsQuery.data.report.stage)}>{reportLabel(assetsQuery.data.report.stage)}</Badge>
              {jobQuery.data.report_version_id ? <Badge>{jobQuery.data.report_version_id}</Badge> : null}
              <Badge>{`历史 ${reportVersions.length} 版`}</Badge>
              <Badge tone={jobStream.isStreaming ? "success" : "warning"}>{jobStream.isStreaming ? "流式更新" : "自动轮询更新"}</Badge>
              {typeof assetsQuery.data.report.revision_count === "number" ? <Badge>{`修订 ${assetsQuery.data.report.revision_count} 次`}</Badge> : null}
              {typeof assetsQuery.data.report.feedback_count === "number" ? <Badge>{`反馈 ${assetsQuery.data.report.feedback_count} 条`}</Badge> : null}
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button disabled={!reportReady || finalizing || finalizeBlocked} onClick={() => void handleFinalizeReport()} type="button">
              {finalizing ? "更新中..." : finalizeLabel}
            </Button>
            {!isCurrentVersion ? (
              <Button onClick={handleJumpToCurrentVersion} type="button" variant="secondary">
                切回当前版本
              </Button>
            ) : null}
            <Link
              className="inline-flex items-center justify-center rounded-xl bg-slate-100 px-4 py-2 text-sm font-medium text-slate-900 transition hover:bg-slate-200"
              href={`/research/jobs/${jobId}`}
            >
              回到研究页
            </Link>
          </div>
        </div>
        {composeMessage ? <p className="mt-4 text-sm text-slate-500">{composeMessage}</p> : null}
        {finalizeBlocked ? (
          <div className="mt-4 rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-950">
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
      </section>

      <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="self-start space-y-4 xl:sticky xl:top-6">
          <Card className="space-y-4 rounded-[28px] border-slate-200/90 bg-white/95 shadow-sm shadow-slate-950/5">
            <div className="flex items-center gap-2">
              <History className="h-4 w-4 text-slate-400" />
              <div>
                <CardTitle>历史版本</CardTitle>
                <CardDescription>当前版本继续用于追问，历史版本用于回看和比较。</CardDescription>
              </div>
            </div>
            <div className="space-y-2">
              {reportVersions.map((version) => {
                const isSelected = version.version_id === selectedVersion.version_id;
                const isCurrent = version.version_id === jobQuery.data.report_version_id;
                return (
                  <button
                    key={version.version_id}
                    className={`w-full rounded-[22px] border px-4 py-3 text-left transition ${
                      isSelected ? "border-slate-900 bg-slate-50 shadow-sm shadow-slate-950/5" : "border-slate-200 bg-white hover:bg-slate-50"
                    }`}
                    onClick={() => handleSelectVersion(version.version_id)}
                    type="button"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{formatReportVersionTag(version)}</Badge>
                      <Badge tone={reportTone(version.stage)}>{version.label || reportLabel(version.stage)}</Badge>
                      {isCurrent ? <Badge tone="success">当前</Badge> : null}
                    </div>
                    <p className="mt-2 text-sm font-medium text-slate-900">{buildReportPreview(version.markdown, 88)}</p>
                    <p className="mt-2 flex items-center gap-1 text-xs text-slate-500">
                      <Clock3 className="h-3.5 w-3.5" />
                      {formatReportTimestamp(version.updated_at || version.generated_at)}
                    </p>
                  </button>
                );
              })}
            </div>
          </Card>

          <Card className="space-y-4 rounded-[28px] border-slate-200/90 bg-white/95 shadow-sm shadow-slate-950/5">
            <div className="flex items-center gap-2">
              <ListTree className="h-4 w-4 text-slate-400" />
              <div>
                <CardTitle>目录</CardTitle>
                <CardDescription>点击可跳到正文对应位置，方便快速定位重点章节。</CardDescription>
              </div>
            </div>
            <div className="space-y-2">
              {outline.length ? (
                outline.map((item, index) => (
                  <button
                    key={`${item}-${index}`}
                    className="block w-full rounded-[18px] bg-slate-50 px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-100"
                    onClick={() => handleScrollToHeading(item)}
                    type="button"
                  >
                    {item}
                  </button>
                ))
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-3 py-4 text-sm text-slate-500">
                  当前版本还没有可提取的章节标题。
                </div>
              )}
            </div>
          </Card>

          <Card className="space-y-4 rounded-[28px] border-slate-200/90 bg-[linear-gradient(180deg,_#ffffff,_#f8fafc)] shadow-sm shadow-slate-950/5">
            <div className="flex items-center gap-2">
              <BookOpenText className="h-4 w-4 text-slate-400" />
              <div>
                <CardTitle>先看什么</CardTitle>
                <CardDescription>先看摘要判断，再决定是否继续展开正文和版本来源。</CardDescription>
              </div>
            </div>
            <div className="space-y-3 text-sm leading-7 text-slate-600">
              <p>先确认最重要的判断和边界，再根据需要展开完整报告、来源索引与版本差异。</p>
            </div>
          </Card>

          <Card className="space-y-4 rounded-[28px] border-slate-200/90 bg-white/95 shadow-sm shadow-slate-950/5">
            <div>
              <CardTitle>{sourcePanelTitle}</CardTitle>
              <CardDescription>{sourcePanelDescription}</CardDescription>
            </div>
            <div className="rounded-[18px] bg-slate-50 px-3 py-3 text-sm text-slate-600">{sourceTierSummary || "当前还没有可展示的来源分层信息。"}</div>
            <div className="space-y-2">
              {citationRegistry.length ? (
                citationRegistry.map((item) => (
                  <a
                    key={item.id}
                    className="block rounded-[20px] border border-slate-200 bg-white px-3 py-3 transition hover:border-slate-300 hover:bg-slate-50"
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
                <div className="rounded-[20px] border border-dashed border-slate-200 bg-white px-3 py-5 text-sm text-slate-500">{sourcePanelEmptyMessage}</div>
              )}
            </div>
          </Card>
        </aside>

        <section className="space-y-4">
          {!isCurrentVersion ? (
            <div className="rounded-[24px] border border-amber-200 bg-[linear-gradient(135deg,_rgba(254,243,199,0.85),_rgba(255,251,235,0.95))] px-4 py-4 text-sm text-amber-950">
              你当前查看的是历史版本 <span className="font-semibold">{formatReportVersionTag(selectedVersion)}</span>。
              研究对话仍默认使用 <span className="font-semibold">{jobQuery.data.report_version_id || "当前版本"}</span> 作为参考版本。
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">当前版本</p>
              <p className="mt-2 text-lg font-semibold text-slate-950">{formatReportVersionTag(selectedVersion)}</p>
              <p className="mt-1 text-sm text-slate-500">{selectedVersion.label || reportLabel(selectedVersion.stage)}</p>
            </div>
            <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">来源记录</p>
              <p className="mt-2 text-lg font-semibold text-slate-950">{versionEvidenceCount}</p>
              <p className="mt-1 text-sm text-slate-500">{versionEvidenceHelper}</p>
            </div>
            <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">独立域名</p>
              <p className="mt-2 text-lg font-semibold text-slate-950">{sourceDomainCount}</p>
              <p className="mt-1 text-sm text-slate-500">帮助判断这份结论是不是只依赖单一路径</p>
            </div>
            <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">决策成熟度</p>
              <p className="mt-2 text-lg font-semibold text-slate-950">{String(decisionSnapshot.readiness || "待判断")}</p>
              <p className="mt-1 text-sm text-slate-500">{String(decisionSnapshot.readiness_reason || "成文后会在这里展示当前可用于决策的边界。")}</p>
            </div>
            <div className="rounded-[24px] border border-slate-200 bg-white px-4 py-4 shadow-sm shadow-slate-950/5">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">待验证问题</p>
              <p className="mt-2 text-lg font-semibold text-slate-950">{openQuestionCount}</p>
              <p className="mt-1 text-sm text-slate-500">{`更新 ${formatReportTimestamp(selectedVersion.updated_at || selectedVersion.generated_at)}`}</p>
            </div>
          </div>

          <div className="rounded-[28px] border border-slate-200 bg-white/90 p-4 shadow-sm shadow-slate-950/5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{formatReportVersionTag(selectedVersion)}</Badge>
                  <Badge tone={reportTone(selectedVersion.stage)}>{selectedVersion.label || reportLabel(selectedVersion.stage)}</Badge>
                  {isCurrentVersion ? <Badge tone="success">当前版本</Badge> : <Badge tone="warning">历史版本</Badge>}
                  <Badge>{activeReportView?.label || "完整内容"}</Badge>
                </div>
                <p className="text-sm leading-7 text-slate-600">
                  {activeReportView?.description || buildReportPreview(selectedVersion.markdown, 180)}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {reportViews.map((view) => (
                  <button
                    key={view.id}
                    className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
                      activeReportView?.id === view.id ? "border-slate-900 bg-slate-900 text-white shadow-sm shadow-slate-950/10" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                    onClick={() => setSelectedView(view.id)}
                    type="button"
                  >
                    {view.label}
                  </button>
                ))}
                <Button onClick={() => void handleCopyCurrentView()} type="button" variant="secondary">
                  <Copy className="mr-2 h-4 w-4" />
                  复制当前内容
                </Button>
              </div>
            </div>
            {copyMessage ? <p className="mt-3 text-sm text-slate-500">{copyMessage}</p> : null}
          </div>

          <div className="report-sheet rounded-[34px] border border-slate-200 bg-[linear-gradient(180deg,_rgba(255,255,255,0.98),_rgba(248,250,252,0.95))] p-3 shadow-[0_18px_50px_rgba(15,23,42,0.06)] xl:p-5">
            <article className="rounded-[28px] border border-slate-200/80 bg-white px-5 py-6 shadow-inner shadow-slate-950/5 xl:px-12 xl:py-10">
              <div className="mb-8 border-b border-slate-200 pb-6">
                <p className="text-xs font-medium uppercase tracking-[0.22em] text-slate-400">报告正文</p>
                <div className="mt-3 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
                  <div>
                    <h2 className="text-2xl font-semibold tracking-tight text-slate-950 xl:text-[2rem]">
                      {activeReportView?.label || "完整内容"}
                    </h2>
                    <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-600">
                      {activeReportView?.description || "阅读当前选中版本的报告内容。"}
                    </p>
                  </div>
                  <div className="grid gap-3 text-sm text-slate-500 sm:grid-cols-3">
                    <div className="rounded-[18px] bg-slate-50 px-4 py-3">
                      <p className="text-xs uppercase tracking-[0.16em] text-slate-400">版本</p>
                      <p className="mt-1 font-medium text-slate-900">{formatReportVersionTag(selectedVersion)}</p>
                    </div>
                    <div className="rounded-[18px] bg-slate-50 px-4 py-3">
                      <p className="text-xs uppercase tracking-[0.16em] text-slate-400">章节</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedVersion.section_count ?? "--"}</p>
                    </div>
                    <div className="rounded-[18px] bg-slate-50 px-4 py-3">
                      <p className="text-xs uppercase tracking-[0.16em] text-slate-400">更新时间</p>
                      <p className="mt-1 font-medium text-slate-900">{formatReportTimestamp(selectedVersion.updated_at || selectedVersion.generated_at)}</p>
                    </div>
                  </div>
                </div>
              </div>
              {activeReportView?.content?.trim() ? (
                <MarkdownContent content={activeReportView.content} variant="report" />
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                  {activeReportView?.emptyMessage || "当前视图还没有内容。"}
                </div>
              )}
            </article>
          </div>
        </section>
      </div>
    </div>
  );
}
