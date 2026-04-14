import type {
  EvidenceRecord,
  ReportAssetRecord,
  ReportVersionRecord,
  ResearchAssetsRecord,
  ResearchJobRecord,
} from "@pm-agent/types";

type ReportBadgeTone = "default" | "success" | "warning";
export type ReportContentViewId = "brief" | "memo" | "report" | "conflicts" | "appendix";

export interface ReportContentView {
  id: ReportContentViewId;
  label: string;
  description: string;
  content: string;
  emptyMessage: string;
}

const SECTION_HEADING_ALIASES: Record<string, string[]> = {
  "核心结论摘要": ["Executive Summary"],
  "决策快照": ["Decision Snapshot"],
  "研究范围与方法": ["Research Scope & Configuration"],
  "竞争格局": ["Competitive Landscape"],
  "建议动作": ["Recommended Actions"],
  "待验证问题": ["Open Questions"],
  "证据冲突与使用边界": ["Evidence Conflicts & Validation Boundary"],
  "关键证据摘录": ["Evidence Highlights"],
  "PM 反馈整合": ["PM Feedback Integration"],
};

function headingAliases(heading: string) {
  const normalized = heading.trim().replace(/^#+\s*/, "");
  const aliases = new Set<string>([normalized]);
  if (SECTION_HEADING_ALIASES[normalized]) {
    for (const alias of SECTION_HEADING_ALIASES[normalized]) {
      aliases.add(alias);
    }
  }
  for (const [canonical, legacyAliases] of Object.entries(SECTION_HEADING_ALIASES)) {
    if (normalized === canonical || legacyAliases.includes(normalized)) {
      aliases.add(canonical);
      for (const alias of legacyAliases) {
        aliases.add(alias);
      }
    }
  }
  return Array.from(aliases);
}

function headingMatches(line: string, heading: string) {
  const normalizedLine = line.trim().replace(/^#+\s*/, "");
  return headingAliases(heading).includes(normalizedLine);
}

export function buildHeadingAnchor(value: string) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[`*_~]/g, "")
    .replace(/[^\w\u4e00-\u9fff\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export function reportTone(stage?: string): ReportBadgeTone {
  if (stage === "final") return "success";
  if (stage === "feedback_pending") return "warning";
  if (stage === "draft") return "warning";
  return "default";
}

export function reportLabel(stage?: string) {
  if (stage === "final") return "可分享版";
  if (stage === "feedback_pending") return "待更新";
  if (stage === "draft") return "草稿";
  return "整理中";
}

export function getActiveReportVersionId(
  job?: Pick<ResearchJobRecord, "active_report_version_id" | "report_version_id"> | null,
) {
  const versionId = String(job?.active_report_version_id || job?.report_version_id || "").trim();
  return versionId || null;
}

export function getStableReportVersionId(
  job?: Pick<ResearchJobRecord, "stable_report_version_id"> | null,
) {
  const versionId = String(job?.stable_report_version_id || "").trim();
  return versionId || null;
}

function parseReportVersionNumber(versionId?: string) {
  const match = String(versionId || "").match(/-report-v(\d+)$/);
  return match ? Number.parseInt(match[1] || "0", 10) : 0;
}

function normalizeStringList(values?: string[]) {
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const item of values || []) {
    const value = String(item || "").trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    normalized.push(value);
  }
  return normalized;
}

function normalizeOptionalStringList(values?: string[]) {
  return values == null ? undefined : normalizeStringList(values);
}

function hasSupportSnapshot(report: Pick<ReportAssetRecord | ReportVersionRecord, "claim_ids" | "evidence_ids" | "source_domains">) {
  return Array.isArray(report.claim_ids) || Array.isArray(report.evidence_ids) || Array.isArray(report.source_domains);
}

function normalizeVersion(version: ReportVersionRecord): ReportVersionRecord | null {
  const versionId = String(version.version_id || "").trim();
  const markdown = String(version.markdown || "");
  if (!versionId || !markdown.trim()) {
    return null;
  }

  const claimIds = normalizeOptionalStringList(version.claim_ids);
  const evidenceIds = normalizeOptionalStringList(version.evidence_ids);
  const sourceDomains = normalizeOptionalStringList(version.source_domains);

  return {
    ...version,
    version_id: versionId,
    markdown,
    version_number: version.version_number ?? parseReportVersionNumber(versionId),
    label: version.label || reportLabel(version.stage),
    claim_ids: claimIds,
    evidence_ids: evidenceIds,
    source_domains: sourceDomains,
    evidence_count: typeof version.evidence_count === "number" ? version.evidence_count : evidenceIds?.length,
  };
}

function buildCurrentVersion(
  report: ReportAssetRecord,
  versionId?: string,
  fallbackVersion?: ReportVersionRecord | null,
): ReportVersionRecord | null {
  const resolvedVersionId = String(versionId || "current-report").trim();
  const markdown = String(report.markdown || "");
  if (!markdown.trim()) {
    return null;
  }

  const currentVersion = normalizeVersion({
    version_id: resolvedVersionId,
    version_number: parseReportVersionNumber(resolvedVersionId),
    label: reportLabel(report.stage),
    stage: report.stage,
    markdown,
    board_brief_markdown: report.board_brief_markdown,
    executive_memo_markdown: report.executive_memo_markdown,
    appendix_markdown: report.appendix_markdown,
    conflict_summary_markdown: report.conflict_summary_markdown,
    claim_ids: report.claim_ids,
    evidence_ids: report.evidence_ids,
    source_domains: report.source_domains,
    decision_snapshot: report.decision_snapshot,
    generated_at: report.generated_at,
    updated_at: report.updated_at,
    section_count: report.section_count,
    evidence_count: report.evidence_count,
    feedback_count: report.feedback_count,
    revision_count: report.revision_count,
    long_report_ready: report.long_report_ready,
  });

  if (!currentVersion || !fallbackVersion || fallbackVersion.version_id !== currentVersion.version_id) {
    return currentVersion;
  }

  return normalizeVersion({
    ...fallbackVersion,
    ...currentVersion,
    claim_ids: currentVersion.claim_ids !== undefined ? currentVersion.claim_ids : fallbackVersion.claim_ids,
    evidence_ids: currentVersion.evidence_ids !== undefined ? currentVersion.evidence_ids : fallbackVersion.evidence_ids,
    source_domains: currentVersion.source_domains !== undefined ? currentVersion.source_domains : fallbackVersion.source_domains,
    evidence_count: typeof currentVersion.evidence_count === "number" ? currentVersion.evidence_count : fallbackVersion.evidence_count,
  });
}

export function getReportVersions(assets: ResearchAssetsRecord, job?: ResearchJobRecord): ReportVersionRecord[] {
  const deduped = new Map<string, ReportVersionRecord>();

  for (const item of assets.report_versions || []) {
    const normalized = normalizeVersion(item);
    if (normalized) {
      deduped.set(normalized.version_id, normalized);
    }
  }

  const currentVersion = buildCurrentVersion(
    assets.report,
    job?.report_version_id,
    job?.report_version_id ? deduped.get(job.report_version_id) : null,
  );
  if (currentVersion) {
    deduped.set(currentVersion.version_id, currentVersion);
  }

  return Array.from(deduped.values()).sort((left, right) => {
    const versionDelta = (right.version_number || 0) - (left.version_number || 0);
    if (versionDelta !== 0) {
      return versionDelta;
    }
    return String(right.updated_at || right.generated_at || "").localeCompare(String(left.updated_at || left.generated_at || ""));
  });
}

export function buildReportPreview(markdown: string, maxLength = 110) {
  for (const line of markdown.split("\n")) {
    const cleaned = line
      .replace(/^#{1,6}\s*/, "")
      .replace(/^[-*+]\s*/, "")
      .replace(/^\d+\.\s*/, "")
      .replace(/`/g, "")
      .trim();
    if (cleaned) {
      return cleaned.length > maxLength ? `${cleaned.slice(0, maxLength)}...` : cleaned;
    }
  }
  return "当前版本暂无摘要。";
}

export function extractMarkdownSection(markdown: string, heading: string) {
  const normalizedHeading = heading.trim().replace(/^#+\s*/, "");
  if (!normalizedHeading) {
    return "";
  }

  const lines = markdown.split("\n");
  const startIndex = lines.findIndex((line) => headingMatches(line, normalizedHeading));
  if (startIndex < 0) {
    return "";
  }

  let endIndex = lines.length;
  for (let index = startIndex + 1; index < lines.length; index += 1) {
    if (lines[index]?.startsWith("## ")) {
      endIndex = index;
      break;
    }
  }

  return lines.slice(startIndex, endIndex).join("\n").trim();
}

function buildMemoFallback(markdown: string) {
  const blocks = [
    extractMarkdownSection(markdown, "核心结论摘要"),
    extractMarkdownSection(markdown, "决策快照"),
    extractMarkdownSection(markdown, "建议动作"),
  ].filter(Boolean);
  return blocks.join("\n\n").trim();
}

function buildConflictFallback(markdown: string) {
  return extractMarkdownSection(markdown, "证据冲突与使用边界");
}

function buildAppendixFallback(markdown: string) {
  const blocks = [
    extractMarkdownSection(markdown, "研究范围与方法"),
    extractMarkdownSection(markdown, "关键证据摘录"),
    extractMarkdownSection(markdown, "PM 反馈整合"),
  ].filter(Boolean);
  return blocks.join("\n\n").trim();
}

function sourceTierRank(sourceTier?: string) {
  if (sourceTier === "t1") return 4;
  if (sourceTier === "t2") return 3;
  if (sourceTier === "t3") return 2;
  return 1;
}

function sortEvidenceByWeight(left: EvidenceRecord, right: EvidenceRecord) {
  const tierGap = sourceTierRank(right.source_tier) - sourceTierRank(left.source_tier);
  if (tierGap !== 0) return tierGap;
  const confidenceGap = (right.confidence || 0) - (left.confidence || 0);
  if (confidenceGap !== 0) return confidenceGap;
  return (right.authority_score || 0) - (left.authority_score || 0);
}

function normalizeSourceDomain(sourceDomain?: string, sourceUrl?: string) {
  const domain = String(sourceDomain || "").trim().toLowerCase();
  if (domain) {
    return domain.replace(/^www\./, "");
  }

  try {
    return new URL(String(sourceUrl || "")).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function hasVersionScopedSources(version: ReportVersionRecord) {
  return hasSupportSnapshot(version);
}

export function getVersionEvidence(assets: ResearchAssetsRecord, version: ReportVersionRecord, limit?: number) {
  const evidenceIds = new Set(normalizeStringList(version.evidence_ids));
  const scopedEvidence = hasSupportSnapshot(version)
    ? assets.evidence.filter((item) => evidenceIds.has(String(item.id || "").trim()))
    : assets.evidence;
  const sortedEvidence = [...scopedEvidence].sort(sortEvidenceByWeight);
  return typeof limit === "number" ? sortedEvidence.slice(0, limit) : sortedEvidence;
}

export function getVersionClaims(assets: ResearchAssetsRecord, version: ReportVersionRecord) {
  const claimIds = new Set(normalizeStringList(version.claim_ids));
  if (!hasSupportSnapshot(version)) {
    return assets.claims;
  }
  return assets.claims.filter((item) => claimIds.has(String(item.id || "").trim()));
}

export function getVersionSourceDomains(version: ReportVersionRecord, evidence: EvidenceRecord[]) {
  if (version.source_domains !== undefined) {
    const snapshotDomains = normalizeStringList(version.source_domains);
    return snapshotDomains;
  }

  const domains: string[] = [];
  const seen = new Set<string>();
  for (const item of evidence) {
    const domain = normalizeSourceDomain(item.source_domain, item.source_url);
    if (!domain || seen.has(domain)) {
      continue;
    }
    seen.add(domain);
    domains.push(domain);
  }
  return domains;
}

export function buildReportContentViews(report: ReportAssetRecord | ReportVersionRecord): ReportContentView[] {
  const markdown = String(report.markdown || "");
  const briefContent = String(report.board_brief_markdown || "").trim();
  const memoContent = String(report.executive_memo_markdown || "").trim() || buildMemoFallback(markdown);
  const conflictContent = String(report.conflict_summary_markdown || "").trim() || buildConflictFallback(markdown);
  const appendixContent = String(report.appendix_markdown || "").trim() || buildAppendixFallback(markdown);

  return [
    {
      id: "brief",
      label: "先看结论",
      description: "用 1 页看完结论、建议动作和适用范围。",
      content: briefContent || memoContent,
      emptyMessage: "当前版本还没有单独整理这页结论。",
    },
    {
      id: "memo",
      label: "摘要",
      description: "快速浏览核心判断、判断依据和下一步动作。",
      content: memoContent,
      emptyMessage: "当前版本还没有单独整理摘要。",
    },
    {
      id: "report",
      label: "完整内容",
      description: "阅读当前版本的完整研究正文。",
      content: markdown,
      emptyMessage: "当前版本还没有完整报告正文。",
    },
    {
      id: "conflicts",
      label: "风险与待确认",
      description: "聚焦有争议项、弱信号和仍待验证的问题。",
      content: conflictContent,
      emptyMessage: "当前版本还没有单独整理风险与待确认项。",
    },
    {
      id: "appendix",
      label: "方法与来源",
      description: "查看方法、覆盖范围、关键证据和反馈整合记录。",
      content: appendixContent,
      emptyMessage: "当前版本还没有单独整理方法与来源。",
    },
  ];
}

export function extractReportOutline(markdown: string, limit = 12) {
  const outline: string[] = [];
  for (const line of markdown.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("#")) {
      continue;
    }
    outline.push(trimmed.replace(/^#+\s*/, ""));
    if (outline.length >= limit) {
      break;
    }
  }
  return outline;
}

export function formatReportVersionTag(version: ReportVersionRecord) {
  if (version.version_number && version.version_number > 0) {
    return `V${version.version_number}`;
  }
  return version.version_id;
}

export function formatReportTimestamp(value?: string) {
  if (!value) {
    return "时间未知";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}
