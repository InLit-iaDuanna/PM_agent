"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft, BookOpenText, Clock3, Copy,
  FileText, History, ListTree, Sparkles, ExternalLink,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type { ReportDecisionSnapshotRecord, ReportQualityGateRecord } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, ReadProgressBar, Sheet, Skeleton, Tabs, Tooltip } from "@pm-agent/ui";

import { buildDemoAssets, buildDemoJob } from "../../../lib/demo-data";
import {
  fetchResearchAssets, fetchResearchJob,
  finalizeResearchReport, getApiErrorMessage,
} from "../../../lib/api-client";
import { getPollingInterval } from "../../../lib/polling";
import { useResearchJobStream } from "../hooks/use-research-job-stream";
import { MarkdownContent } from "./markdown-content";
import { RequestStateCard } from "./request-state-card";
import { sourceTierTone } from "./research-ui-utils";
import {
  buildReportContentViews, buildHeadingAnchor, buildReportPreview,
  extractReportOutline, formatReportTimestamp, formatReportVersionTag,
  getReportVersions, getVersionEvidence, getVersionSourceDomains,
  hasVersionScopedSources, reportLabel, reportTone,
  type ReportContentViewId,
} from "./report-version-utils";

// ─── View tabs ────────────────────────────────────────────────────────────
const VIEW_TABS = [
  { id: "brief",   label: "决策摘要" },
  { id: "full",    label: "完整报告" },
  { id: "memo",    label: "执行备忘" },
  { id: "appendix",label: "附录" },
];

export function ResearchReportPageRefactored({ jobId }: { jobId: string }) {
  const isDemoJob = jobId === "demo-job";
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requestedVersionId = searchParams.get("version");
  const queryClient = useQueryClient();

  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(requestedVersionId);
  const [finalizing, setFinalizing]     = useState(false);
  const [composeMessage, setComposeMessage] = useState<string | null>(null);
  const [copyMessage, setCopyMessage]   = useState<string | null>(null);
  const [selectedView, setSelectedView] = useState<ReportContentViewId>("brief");
  const [sourceSheetOpen, setSourceSheetOpen] = useState(false);

  const jobStream = useResearchJobStream({ enabled: !isDemoJob, jobId });

  const jobQuery = useQuery({
    queryKey: ["research-job", jobId],
    queryFn: () => (isDemoJob ? Promise.resolve(buildDemoJob(jobId)) : fetchResearchJob(jobId)),
    initialData: isDemoJob ? buildDemoJob(jobId) : undefined,
    refetchInterval: ({ state }) =>
      jobStream.shouldPoll ? getPollingInterval(state.data?.status, { activeMs: 1000 }) : false,
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

  // Sync selectedVersionId with available versions
  useEffect(() => {
    if (requestedVersionId && reportVersions.some((v) => v.version_id === requestedVersionId)) {
      setSelectedVersionId(requestedVersionId);
      return;
    }
    const fallback = jobQuery.data?.report_version_id || reportVersions[0]?.version_id || null;
    if (!fallback) return;
    setSelectedVersionId((cur) => {
      if (cur && reportVersions.some((v) => v.version_id === cur)) return cur;
      return fallback;
    });
  }, [jobQuery.data?.report_version_id, reportVersions, requestedVersionId]);

  useEffect(() => {
    if (!jobStream.isStreaming) return;
    void Promise.all([jobQuery.refetch(), assetsQuery.refetch()]);
  }, [assetsQuery.refetch, jobQuery.refetch, jobStream.isStreaming]);

  useEffect(() => { setCopyMessage(null); }, [selectedVersionId, selectedView]);

  const errorMessage = [jobQuery.error, assetsQuery.error].find(Boolean);
  if (errorMessage) {
    return (
      <RequestStateCard
        actionLabel="重新加载"
        description={getApiErrorMessage(errorMessage, "报告暂时无法加载，请稍后重试。")}
        onAction={() => void Promise.all([jobQuery.refetch(), assetsQuery.refetch()])}
        title="暂时无法加载报告"
      />
    );
  }

  // Loading skeleton
  if (!jobQuery.data || !assetsQuery.data) {
    return (
      <div className="space-y-6">
        <Skeleton h="2rem" w="60%" />
        <Skeleton h="1rem" w="40%" />
        <div className="grid gap-6 xl:grid-cols-[300px_1fr]">
          <div className="space-y-4">
            <Skeleton h="200px" />
            <Skeleton h="160px" />
          </div>
          <Skeleton h="500px" />
        </div>
      </div>
    );
  }

  const selectedVersion =
    reportVersions.find((v) => v.version_id === selectedVersionId) ||
    reportVersions.find((v) => v.version_id === jobQuery.data.report_version_id) ||
    reportVersions[0];

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

  // Computed values (same logic as original)
  const versionHasScopedSources = selectedVersion ? hasVersionScopedSources(selectedVersion) : false;
  const versionEvidencePool = useMemo(
    () => selectedVersion && assetsQuery.data ? getVersionEvidence(assetsQuery.data, selectedVersion) : [],
    [assetsQuery.data, selectedVersion],
  );
  const citationRegistry  = useMemo(() => versionEvidencePool.slice(0, 8), [versionEvidencePool]);
  const versionSourceDomains = selectedVersion ? getVersionSourceDomains(selectedVersion, versionEvidencePool) : [];

  const reportReady     = Boolean(assetsQuery.data.report.markdown?.trim());
  const qualityGate: ReportQualityGateRecord | undefined = assetsQuery.data.report.quality_gate;
  const qualityGateReasons = (qualityGate?.reasons || []).filter((r): r is string => Boolean(r));
  const qualityGateMetrics = qualityGate?.metrics || {};
  const finalizeBlocked = !qualityGate?.pending && qualityGate?.passed === false;
  const outline         = extractReportOutline(selectedVersion.markdown);
  const reportViews     = buildReportContentViews(selectedVersion);
  const activeReportView = reportViews.find((v) => v.id === selectedView) || reportViews[0];
  const decisionSnapshot: Partial<ReportDecisionSnapshotRecord> =
    selectedVersion.decision_snapshot || assetsQuery.data.report.decision_snapshot || {};
  const isCurrentVersion = selectedVersion.version_id === jobQuery.data.report_version_id;
  const selectedVersionTag = formatReportVersionTag(selectedVersion);
  const versionEvidenceCount = versionHasScopedSources
    ? (selectedVersion.evidence_ids?.length ?? versionEvidencePool.length)
    : typeof selectedVersion.evidence_count === "number"
    ? selectedVersion.evidence_count
    : versionEvidencePool.length;

  const handleSelectVersion = (versionId: string) => {
    setSelectedVersionId(versionId);
    router.replace(`${pathname}?version=${encodeURIComponent(versionId)}`, { scroll: false });
  };

  const handleScrollToHeading = (heading: string) => {
    const anchor = buildHeadingAnchor(heading);
    if (!anchor) return;
    const target = document.getElementById(anchor);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const handleCopy = async () => {
    if (!activeReportView?.content?.trim()) return;
    try {
      await navigator.clipboard.writeText(activeReportView.content);
      setCopyMessage(`已复制${activeReportView.label}。`);
    } catch (err) {
      setCopyMessage(getApiErrorMessage(err, "复制失败。"));
    }
  };

  const handleFinalize = async () => {
    if (!reportReady || finalizeBlocked) return;
    setFinalizing(true);
    setComposeMessage(null);
    try {
      const nextAssets = await finalizeResearchReport(jobId, selectedVersion.version_id);
      queryClient.setQueryData(["research-assets", jobId], nextAssets);
      queryClient.setQueryData(["chat-session-assets", jobId], nextAssets);
      const nextGate = nextAssets.report.quality_gate;
      const nextBlocked = !nextGate?.pending && nextGate?.passed === false;
      if (nextBlocked) {
        setComposeMessage(nextGate?.reasons?.length ? `这版内容还不够完整：${nextGate.reasons[0]}` : "这版内容还不够完整。");
      } else {
        setSelectedVersionId(null);
        setComposeMessage("已更新当前报告，上一版已自动保留。");
      }
      router.replace(pathname, { scroll: false });
    } catch (err) {
      setComposeMessage(getApiErrorMessage(err, "更新报告失败，请稍后重试。"));
    } finally {
      setFinalizing(false);
    }
  };

  // ── View tabs from reportViews ──────────────────────────────────────────
  const viewTabItems = reportViews.map((v) => ({ id: v.id, label: v.label }));

  return (
    <div className="space-y-6 pb-12">
      {/* Reading progress bar */}
      <ReadProgressBar />

      {/* ── Hero ────────────────────────────────────────────────────── */}
      <section className="animate-fade-up rounded-[32px] border border-[color:var(--border-soft)] bg-[radial-gradient(circle_at_top_left,rgba(29,76,116,0.10),transparent_40%),linear-gradient(135deg,rgba(255,255,255,0.9),rgba(249,244,235,0.85))] p-6 shadow-[var(--shadow-md)] xl:p-8">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            <Link
              className="inline-flex items-center gap-2 text-sm font-medium text-[color:var(--muted)] transition hover:text-[color:var(--ink)]"
              href={`/research/jobs/${jobId}`}
            >
              <ArrowLeft className="h-4 w-4" />
              返回研究页
            </Link>

            <div className="flex items-center gap-3">
              <div className="rounded-[18px] bg-[color:var(--accent)] p-2.5 text-white shadow-[var(--shadow-md)]">
                <FileText className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">研究报告</p>
                <h1 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)] xl:text-[1.9rem]">
                  {jobQuery.data.topic}
                </h1>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Badge tone={reportTone(assetsQuery.data.report.stage)}>
                {reportLabel(assetsQuery.data.report.stage)}
              </Badge>
              {jobQuery.data.report_version_id && <Badge>{jobQuery.data.report_version_id}</Badge>}
              <Badge>{`历史 ${reportVersions.length} 版`}</Badge>
              <Tooltip content={jobStream.isStreaming ? "SSE 实时推送中" : "定期轮询更新"}>
                <Badge tone={jobStream.isStreaming ? "success" : "default"}>
                  {jobStream.isStreaming ? "实时更新" : "轮询更新"}
                </Badge>
              </Tooltip>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button
              disabled={!reportReady || finalizing || finalizeBlocked}
              onClick={() => void handleFinalize()}
              type="button"
            >
              {finalizing ? "更新中..." : finalizeBlocked ? "先补充再更新" : "更新报告"}
            </Button>
            {!isCurrentVersion && (
              <Button
                onClick={() => handleSelectVersion(jobQuery.data.report_version_id!)}
                type="button"
                variant="secondary"
              >
                切回当前版本
              </Button>
            )}
            <Button asChild variant="secondary">
              <Link href={`/research/jobs/${jobId}`}>回到研究页</Link>
            </Button>
          </div>
        </div>

        {composeMessage && (
          <p className="mt-4 text-sm text-[color:var(--muted)]">{composeMessage}</p>
        )}

        {/* Quality gate alert */}
        {finalizeBlocked && (
          <div className="mt-4 animate-fade-in rounded-[22px] border border-amber-200 bg-amber-50/90 px-5 py-4 text-sm text-amber-950">
            <p className="font-semibold">这版内容还不够完整。</p>
            <p className="mt-1.5 leading-7">补齐以下信息后再更新会更稳。</p>
            {qualityGateReasons.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {qualityGateReasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
            )}
            <p className="mt-3 text-xs text-amber-800">
              {`正式来源 ${qualityGateMetrics.formal_evidence_count ?? 0} 条 · 结论 ${qualityGateMetrics.formal_claim_count ?? 0} 条 · 独立域名 ${qualityGateMetrics.formal_domain_count ?? 0} 个`}
            </p>
          </div>
        )}
      </section>

      {/* ── Main: TOC sidebar + content ─────────────────────────────── */}
      <div className="grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)]">

        {/* Sticky left sidebar */}
        <aside className="space-y-4 xl:sticky xl:top-[60px] xl:self-start">

          {/* Version history - now as dropdown-style list */}
          <Card className="space-y-4">
            <div className="flex items-center gap-2">
              <History className="h-4 w-4 text-[color:var(--muted)]" />
              <CardTitle>历史版本</CardTitle>
            </div>
            <div className="space-y-2">
              {reportVersions.map((version) => {
                const isSelected = version.version_id === selectedVersion.version_id;
                const isCurrent  = version.version_id === jobQuery.data.report_version_id;
                return (
                  <button
                    key={version.version_id}
                    type="button"
                    onClick={() => handleSelectVersion(version.version_id)}
                    className={[
                      "w-full rounded-[18px] border px-4 py-3 text-left transition-all duration-150",
                      isSelected
                        ? "border-[color:var(--accent)] bg-[rgba(29,76,116,0.06)] shadow-[0_0_0_2px_rgba(29,76,116,0.08)]"
                        : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] hover:bg-white hover:border-[color:var(--border-strong)]",
                    ].join(" ")}
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge>{formatReportVersionTag(version)}</Badge>
                      <Badge tone={reportTone(version.stage)}>
                        {version.label || reportLabel(version.stage)}
                      </Badge>
                      {isCurrent && <Badge tone="success">当前</Badge>}
                    </div>
                    <p className="mt-2 text-xs font-medium text-[color:var(--ink)] line-clamp-2">
                      {buildReportPreview(version.markdown, 72)}
                    </p>
                    <p className="mt-1.5 flex items-center gap-1 text-[11px] text-[color:var(--muted)]">
                      <Clock3 className="h-3 w-3" />
                      {formatReportTimestamp(version.updated_at || version.generated_at)}
                    </p>
                  </button>
                );
              })}
            </div>
          </Card>

          {/* Table of contents */}
          <Card className="space-y-3">
            <div className="flex items-center gap-2">
              <ListTree className="h-4 w-4 text-[color:var(--muted)]" />
              <CardTitle>目录</CardTitle>
            </div>
            <nav>
              {outline.length > 0 ? (
                <div className="space-y-1">
                  {outline.map((heading, i) => (
                    <button
                      key={`${heading}-${i}`}
                      type="button"
                      onClick={() => handleScrollToHeading(heading)}
                      className="stagger-item block w-full rounded-[12px] px-3 py-2 text-left text-xs text-[color:var(--muted-strong)] transition hover:bg-[rgba(29,76,116,0.07)] hover:text-[color:var(--ink)]"
                      style={{ "--delay": `${i * 20}ms` } as React.CSSProperties}
                    >
                      {heading}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-[color:var(--muted)]">当前版本暂无章节标题。</p>
              )}
            </nav>
          </Card>

          {/* Source index trigger */}
          <button
            type="button"
            onClick={() => setSourceSheetOpen(true)}
            className="card-lift w-full rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-4 text-left"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <BookOpenText className="h-4 w-4 text-[color:var(--accent)]" />
                <span className="text-sm font-semibold text-[color:var(--ink)]">来源索引</span>
              </div>
              <Badge tone={citationRegistry.length > 0 ? "success" : "default"}>
                {citationRegistry.length > 0 ? `${citationRegistry.length} 条` : "暂无"}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-[color:var(--muted)]">
              点击展开当前版本的全部引用来源。
            </p>
          </button>
        </aside>

        {/* ── Report content area ─────────────────────────────────── */}
        <section className="space-y-5">

          {/* Non-current version warning */}
          {!isCurrentVersion && (
            <div className="animate-fade-in rounded-[20px] border border-amber-200 bg-amber-50/90 px-4 py-3 text-sm text-amber-900">
              当前查看历史版本 <span className="font-semibold">{selectedVersionTag}</span>。
              研究对话仍默认使用{" "}
              <span className="font-semibold">{jobQuery.data.report_version_id || "当前版本"}</span>。
            </div>
          )}

          {/* Metrics row */}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: "当前版本", value: selectedVersionTag, helper: selectedVersion.label || reportLabel(selectedVersion.stage) },
              { label: "来源记录", value: String(versionEvidenceCount), helper: "该版本关联的可引用来源" },
              { label: "独立域名", value: String(versionSourceDomains.length || decisionSnapshot.unique_domains || "--"), helper: "来源多样性指标" },
              { label: "决策成熟度", value: String(decisionSnapshot.readiness || "待判断"), helper: String(decisionSnapshot.readiness_reason || "成文后显示") },
            ].map(({ label, value, helper }, i) => (
              <div
                key={label}
                className="stagger-item rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] px-4 py-4"
                style={{ "--delay": `${i * 40}ms` } as React.CSSProperties}
              >
                <p className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">{label}</p>
                <p className="mt-2 text-lg font-semibold tracking-tight text-[color:var(--ink)]">{value}</p>
                <p className="mt-0.5 text-xs text-[color:var(--muted)]">{helper}</p>
              </div>
            ))}
          </div>

          {/* View switcher + copy */}
          <div className="flex flex-col gap-3 rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.7)] p-4 sm:flex-row sm:items-center sm:justify-between">
            <Tabs
              items={viewTabItems}
              activeId={selectedView}
              onChange={(id) => setSelectedView(id as ReportContentViewId)}
              variant="pill"
            />
            <div className="flex items-center gap-2">
              {copyMessage && (
                <span className="animate-fade-in text-xs text-[color:var(--muted)]">{copyMessage}</span>
              )}
              <Button onClick={() => void handleCopy()} type="button" variant="ghost">
                <Copy className="mr-2 h-3.5 w-3.5" />
                复制
              </Button>
            </div>
          </div>

          {/* Report body */}
          <div className="report-sheet rounded-[32px] border border-[color:var(--border-soft)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(249,244,235,0.94))] p-3 shadow-[var(--shadow-xl)] xl:p-5">
            <article className="rounded-[26px] border border-[rgba(0,0,0,0.06)] bg-white px-5 py-7 shadow-inner xl:px-12 xl:py-10">
              <div className="mb-7 border-b border-[color:var(--border-soft)] pb-5">
                <p className="text-[10px] uppercase tracking-[0.24em] text-[color:var(--muted)]">
                  {activeReportView?.label || "完整内容"}
                </p>
                <div className="mt-2 flex flex-col gap-2 xl:flex-row xl:items-end xl:justify-between">
                  <p className="text-sm leading-7 text-[color:var(--muted)]">
                    {activeReportView?.description || buildReportPreview(selectedVersion.markdown, 160)}
                  </p>
                  <div className="flex shrink-0 flex-wrap gap-2 text-[11px] text-[color:var(--muted)]">
                    <span className="rounded-[10px] bg-[rgba(0,0,0,0.04)] px-2.5 py-1">
                      {selectedVersionTag}
                    </span>
                    <span className="rounded-[10px] bg-[rgba(0,0,0,0.04)] px-2.5 py-1">
                      {formatReportTimestamp(selectedVersion.updated_at || selectedVersion.generated_at)}
                    </span>
                  </div>
                </div>
              </div>

              {activeReportView?.content?.trim() ? (
                <MarkdownContent content={activeReportView.content} variant="report" />
              ) : (
                <div className="rounded-[20px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(0,0,0,0.02)] px-4 py-8 text-center text-sm text-[color:var(--muted)]">
                  {activeReportView?.emptyMessage || "当前视图还没有内容。"}
                </div>
              )}
            </article>
          </div>
        </section>
      </div>

      {/* ── Source index Sheet ──────────────────────────────────────── */}
      <Sheet
        open={sourceSheetOpen}
        onClose={() => setSourceSheetOpen(false)}
        title={versionHasScopedSources ? "当前版本来源索引" : "研究来源池样本"}
        description={
          versionHasScopedSources
            ? "这些页面与当前阅读版本直接绑定，可据此复核正文判断。"
            : "当前版本还没回填逐条来源索引，先展示研究来源池里的高权重页面。"
        }
        width="480px"
      >
        <div className="space-y-3">
          {citationRegistry.length > 0 ? (
            citationRegistry.map((item) => (
              <a
                key={item.id}
                href={item.source_url}
                target="_blank"
                rel="noreferrer"
                className="card-lift flex items-start gap-3 rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.7)] p-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge>{item.citation_label || item.id}</Badge>
                    {item.source_tier_label && (
                      <Badge tone={sourceTierTone(item.source_tier)}>
                        {item.source_tier_label}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-2 text-sm font-medium text-[color:var(--ink)] line-clamp-2">
                    {item.title}
                  </p>
                  <p className="mt-1 text-xs text-[color:var(--muted)]">
                    {item.source_domain || item.source_url}
                  </p>
                </div>
                <ExternalLink className="h-3.5 w-3.5 shrink-0 text-[color:var(--muted)]" />
              </a>
            ))
          ) : (
            <div className="rounded-[18px] border border-dashed border-[color:var(--border-soft)] px-4 py-8 text-center text-sm text-[color:var(--muted)]">
              当前还没有可展示的来源。等证据沉淀后，这里会展示来源池里的代表页面。
            </div>
          )}
        </div>
      </Sheet>
    </div>
  );
}
