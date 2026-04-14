"use client";

import type { ResearchAssetsRecord, ResearchJobRecord, CompetitorRecord } from "@pm-agent/types";
import { Badge, Card, CardDescription, CardTitle, ProgressBar } from "@pm-agent/ui";

type CompetitorProfile = {
  name: string;
  category?: string;
  positioning?: string;
  pricing?: string;
  differentiation?: string;
  coverage_gap?: string;
  evidence_count?: number;
  source_count?: number;
  key_sources?: string[];
};

function normalizeCompetitorProfiles(
  competitors?: Array<CompetitorRecord | Record<string, unknown>>,
): CompetitorProfile[] {
  if (!Array.isArray(competitors)) return [];

  const toStr = (v: unknown) => {
    if (typeof v === "string") { const t = v.trim(); return t || undefined; }
    if (v == null) return undefined;
    const s = String(v).trim();
    return s || undefined;
  };
  const toNum = (v: unknown) => {
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string") { const n = Number(v.trim()); return Number.isFinite(n) ? n : undefined; }
    return undefined;
  };

  const profiles: CompetitorProfile[] = [];
  for (const entry of competitors) {
    if (!entry || typeof entry !== "object") continue;
    const r = entry as Record<string, unknown>;
    const name = toStr(r.name) || toStr(r.competitor_name);
    if (!name) continue;
    profiles.push({
      name,
      category: toStr(r.category),
      positioning: toStr(r.positioning),
      pricing: toStr(r.pricing),
      differentiation: toStr(r.differentiation),
      coverage_gap: toStr(r.coverage_gap),
      evidence_count: toNum(r.evidence_count),
      source_count: toNum(r.source_count),
      key_sources: Array.isArray(r.key_sources)
        ? (r.key_sources as unknown[]).map((s) => toStr(s)).filter(Boolean) as string[]
        : [],
    });
  }
  return profiles;
}

interface JobCompetitorsTabProps {
  job: ResearchJobRecord;
  assets: ResearchAssetsRecord;
}

export function JobCompetitorsTab({ job, assets }: JobCompetitorsTabProps) {
  const profiles = normalizeCompetitorProfiles(assets.competitors);
  const competitorCount = Number(job.competitor_count || 0);
  const hasData = profiles.length > 0;

  const snapshot = assets.progress_snapshot as {
    competitor_coverage?: Array<{ name: string; value: number }>;
  };
  const coverage = snapshot?.competitor_coverage ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-[-0.03em] text-[color:var(--ink)]">
            竞品结构化概览
          </h2>
          <p className="mt-1 text-sm text-[color:var(--muted)]">
            展示竞品角色、定价与差异线索，配合证据足迹帮助快速对标。
          </p>
        </div>
        <Badge tone={hasData ? "success" : "default"}>
          {hasData
            ? `${profiles.length} 个样本`
            : competitorCount
            ? `${competitorCount} 个竞品待补`
            : "暂无竞品数据"}
        </Badge>
      </div>

      {/* Coverage heatmap */}
      {coverage.length > 0 && (
        <Card className="space-y-4">
          <CardTitle>竞品覆盖度</CardTitle>
          <div className="space-y-3">
            {coverage.map((item) => (
              <div key={item.name}>
                <div className="mb-1.5 flex items-center justify-between text-sm text-[color:var(--muted)]">
                  <span>{item.name}</span>
                  <span>{item.value} / 10</span>
                </div>
                <ProgressBar aria-label={`${item.name}覆盖`} value={item.value * 10} />
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Profile cards */}
      {hasData ? (
        <div className="space-y-4">
          {profiles.map((item) => (
            <div
              key={item.name}
              className="card-lift rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.76)] p-5 shadow-[var(--shadow-md)]"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-base font-semibold text-[color:var(--ink)]">{item.name}</p>
                  {item.category && (
                    <p className="mt-0.5 text-xs text-[color:var(--muted)]">{item.category}</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  {typeof item.evidence_count === "number" && (
                    <Badge tone="success">{`证据 ${item.evidence_count}`}</Badge>
                  )}
                  {typeof item.source_count === "number" && (
                    <Badge>{`来源 ${item.source_count}`}</Badge>
                  )}
                </div>
              </div>

              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">定位 / 角色</p>
                  <p className="mt-1.5 text-sm leading-6 text-[color:var(--ink)]">
                    {item.positioning || "正在整理该竞品的定位描述。"}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">定价线索</p>
                  <p className="mt-1.5 text-sm leading-6 text-[color:var(--ink)]">
                    {item.pricing || "暂无定价线索"}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">核心差异</p>
                  <p className="mt-1.5 text-sm leading-6 text-[color:var(--ink)]">
                    {item.differentiation || item.coverage_gap || "尚待补齐差异化证据。"}
                  </p>
                </div>
              </div>

              {item.key_sources && item.key_sources.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {item.key_sources.map((src) => (
                    <Badge key={`${item.name}-${src}`}>{src}</Badge>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-[28px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.4)] px-4 py-10 text-center text-sm text-[color:var(--muted)]">
          {competitorCount > 0
            ? `已识别 ${competitorCount} 个竞品，正在整理结构化数据...`
            : "系统正在自动识别并整理竞品线索，待识别完成后会显示在这里。"}
        </div>
      )}
    </div>
  );
}
