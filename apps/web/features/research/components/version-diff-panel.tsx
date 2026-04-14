"use client";

import { useMemo } from "react";

import type { ResearchJobRecord } from "@pm-agent/types";
import { useQuery } from "@tanstack/react-query";
import { Badge, Card, CardDescription, CardTitle } from "@pm-agent/ui";

import { fetchReportVersionDiff, getApiErrorMessage } from "../../../lib/api-client";
import { MarkdownContent } from "./markdown-content";
import { getActiveReportVersionId, getStableReportVersionId } from "./report-version-utils";

type VersionDiffPanelProps = {
  job: ResearchJobRecord;
  enabled: boolean;
};

export function VersionDiffPanel({ job, enabled }: VersionDiffPanelProps) {
  const activeVersionId = getActiveReportVersionId(job);
  const stableVersionId = getStableReportVersionId(job);

  const diffQuery = useQuery({
    queryKey: ["report-version-diff", job.id, activeVersionId, stableVersionId],
    queryFn: () => fetchReportVersionDiff(job.id, activeVersionId!, stableVersionId!),
    enabled: enabled && Boolean(activeVersionId && stableVersionId),
  });

  const diff = diffQuery.data;
  const errorMessage = diffQuery.error ? getApiErrorMessage(diffQuery.error, "读取版本差异失败。") : null;

  type DiffBadge = { label: string; tone: "success" | "warning" };
  const actionBadges = useMemo((): DiffBadge[] => {
    if (!diff) {
      return [];
    }
    const rawBadges: Array<DiffBadge | null> = [
      diff.added_claim_ids?.length
        ? { label: `新增 ${diff.added_claim_ids.length} 条结论`, tone: "success" }
        : null,
      diff.removed_claim_ids?.length
        ? { label: `移除 ${diff.removed_claim_ids.length} 条结论`, tone: "warning" }
        : null,
      diff.added_evidence_ids?.length
        ? { label: `新增 ${diff.added_evidence_ids.length} 条证据`, tone: "success" }
        : null,
      diff.removed_evidence_ids?.length
        ? { label: `移除 ${diff.removed_evidence_ids.length} 条证据`, tone: "warning" }
        : null,
    ];
    return rawBadges.filter((badge): badge is DiffBadge => Boolean(badge));
  }, [diff]);

  if (!enabled) {
    return (
      <Card className="space-y-4">
        <div className="flex flex-col gap-1">
          <CardTitle>版本对比</CardTitle>
          <CardDescription>当前工作稿与稳定版暂未出现差异。</CardDescription>
        </div>
        <p className="text-sm text-[color:var(--muted)]">有新草稿时会自动生成差异摘要，方便快速复盘。</p>
      </Card>
    );
  }

  if (!activeVersionId || !stableVersionId) {
    return (
      <Card className="space-y-4">
        <div className="flex flex-col gap-1">
          <CardTitle>版本对比</CardTitle>
          <CardDescription>暂无可对比的版本。</CardDescription>
        </div>
        <p className="text-sm text-[color:var(--muted)]">
          当前还没有稳定版或工作稿。等系统生成或完成补充研究后会自动显示差异。
        </p>
      </Card>
    );
  }

  return (
    <Card className="space-y-4">
      <div className="flex flex-col gap-1">
        <CardTitle>版本对比</CardTitle>
        <CardDescription>对比稳定版与最新草稿的新增/移除内容，锁定需要重点审查的变更。</CardDescription>
        <div className="flex flex-wrap gap-2">
          <Badge>{`稳定版 ${stableVersionId}`}</Badge>
          <Badge tone="success">{`草稿 ${activeVersionId}`}</Badge>
        </div>
      </div>
      {diffQuery.isLoading ? (
        <p className="text-sm text-[color:var(--muted)]">正在抓取版本差异...</p>
      ) : errorMessage ? (
        <p className="text-sm text-red-600">{errorMessage}</p>
      ) : diff ? (
        <div className="space-y-3">
          {diff.summary ? <p className="text-sm text-[color:var(--muted)]">{diff.summary}</p> : null}
          <div className="flex flex-wrap gap-2">
            {actionBadges.map((badge) => (
              <Badge key={badge.label} tone={badge.tone}>
                {badge.label}
              </Badge>
            ))}
          </div>
          {diff.diff_markdown ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <MarkdownContent content={diff.diff_markdown} variant="research" />
            </div>
          ) : (
            <p className="text-sm text-[color:var(--muted)]">当前差异为结构或元数据变化，暂无 diff 内容。</p>
          )}
        </div>
      ) : (
        <p className="text-sm text-[color:var(--muted)]">尚未生成差异摘要。</p>
      )}
    </Card>
  );
}
