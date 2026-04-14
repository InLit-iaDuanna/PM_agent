"use client";

import { useMemo, useState } from "react";

import type { ResearchAssetsRecord } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, Input, Select } from "@pm-agent/ui";

import { useResearchUiStore } from "../store/ui-store";
import { formatMarketStep, formatSourceType, sourceTierTone } from "./research-ui-utils";

function sourceTierRank(sourceTier?: string) {
  if (sourceTier === "t1") return 4;
  if (sourceTier === "t2") return 3;
  if (sourceTier === "t3") return 2;
  return 1;
}

function formatPercent(value?: number) {
  return `${Math.round((value || 0) * 100)}%`;
}

export function EvidenceExplorer({ assets }: { assets: ResearchAssetsRecord }) {
  const { selectedClaimId, setSelectedClaimId } = useResearchUiStore();
  const [marketStep, setMarketStep] = useState("all");
  const [sourceType, setSourceType] = useState("all");
  const [sourceTier, setSourceTier] = useState("all");
  const [competitorName, setCompetitorName] = useState("all");
  const [query, setQuery] = useState("");

  const evidenceClaimSupport = useMemo(() => {
    const supportMap = new Map<string, number>();
    assets.claims.forEach((claim) => {
      claim.evidence_ids.forEach((id) => {
        supportMap.set(id, (supportMap.get(id) ?? 0) + 1);
      });
    });
    return supportMap;
  }, [assets.claims]);

  const parseEvidenceDate = (value?: string | null) => {
    const parsed = Date.parse(value ?? "");
    return Number.isNaN(parsed) ? 0 : parsed;
  };

  const marketStepOptions = useMemo(() => {
    const normalized = new Set<string>();
    assets.evidence.forEach((item) => {
      if (item.market_step?.trim()) {
        normalized.add(item.market_step.trim());
      }
    });
    return Array.from(normalized).sort((left, right) => formatMarketStep(left).localeCompare(formatMarketStep(right), "zh-Hans-CN"));
  }, [assets.evidence]);

  const sourceTypeOptions = useMemo(() => {
    const normalized = new Set<string>();
    assets.evidence.forEach((item) => {
      if (item.source_type?.trim()) {
        normalized.add(item.source_type.trim());
      }
    });
    return Array.from(normalized).sort((left, right) => formatSourceType(left).localeCompare(formatSourceType(right), "zh-Hans-CN"));
  }, [assets.evidence]);

  const sourceTierLabels = useMemo(() => {
    const map = new Map<string, string>();
    assets.evidence.forEach((item) => {
      if (item.source_tier?.trim()) {
        map.set(item.source_tier, item.source_tier_label?.trim() || item.source_tier);
      }
    });
    return map;
  }, [assets.evidence]);

  const sourceTierOptions = useMemo(() => {
    return Array.from(sourceTierLabels.keys()).sort((left, right) => sourceTierRank(right) - sourceTierRank(left));
  }, [sourceTierLabels]);

  const competitorOptions = useMemo(() => {
    const normalized = new Set<string>();
    assets.evidence.forEach((item) => {
      if (item.competitor_name?.trim()) {
        normalized.add(item.competitor_name.trim());
      }
    });
    return Array.from(normalized).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
  }, [assets.evidence]);

  const competitorSummary = useMemo(() => {
    const counts = new Map<string, number>();
    assets.evidence.forEach((item) => {
      const name = item.competitor_name?.trim();
      if (!name) return;
      counts.set(name, (counts.get(name) ?? 0) + 1);
    });
    return Array.from(counts.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name, "zh-Hans-CN"))
      .slice(0, 6);
  }, [assets.evidence]);

  const linkedClaim = assets.claims.find((claim) => claim.id === selectedClaimId);
  const evidenceIds = linkedClaim ? new Set(linkedClaim.evidence_ids) : undefined;
  const hasActiveFilters = Boolean(
    linkedClaim || marketStep !== "all" || sourceType !== "all" || sourceTier !== "all" || competitorName !== "all" || query.trim(),
  );

  const filteredEvidence = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return assets.evidence
      .filter((item) => {
        const matchesClaim = evidenceIds ? evidenceIds.has(item.id) : true;
        const matchesStep = marketStep === "all" || item.market_step === marketStep;
        const matchesSourceType = sourceType === "all" || item.source_type === sourceType;
        const matchesSourceTier = sourceTier === "all" || item.source_tier === sourceTier;
        const matchesCompetitor = competitorName === "all" || item.competitor_name === competitorName;
        const haystack = [
          item.title,
          item.summary,
          item.quote,
          item.source_url,
          item.source_domain,
          item.citation_label,
          item.source_tier_label,
        ]
          .join(" ")
          .toLowerCase();
        const matchesQuery = !normalizedQuery || haystack.includes(normalizedQuery);
        return matchesClaim && matchesStep && matchesSourceType && matchesSourceTier && matchesCompetitor && matchesQuery;
      })
      .sort((left, right) => {
        const claimSupportGap = (evidenceClaimSupport.get(right.id) ?? 0) - (evidenceClaimSupport.get(left.id) ?? 0);
        if (claimSupportGap !== 0) return claimSupportGap;
        const tierGap = sourceTierRank(right.source_tier) - sourceTierRank(left.source_tier);
        if (tierGap !== 0) return tierGap;
        const rightTime = parseEvidenceDate(right.captured_at ?? right.published_at);
        const leftTime = parseEvidenceDate(left.captured_at ?? left.published_at);
        return rightTime - leftTime;
      });
  }, [assets.evidence, competitorName, evidenceClaimSupport, evidenceIds, marketStep, query, sourceTier, sourceType]);

  const resetFilters = () => {
    setMarketStep("all");
    setSourceType("all");
    setSourceTier("all");
    setCompetitorName("all");
    setQuery("");
    setSelectedClaimId(undefined);
  };

  return (
    <Card className="space-y-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <CardTitle>证据浏览器</CardTitle>
          <CardDescription>按步骤、来源类型、可信度层级和关键词过滤证据；选中 claim 时自动聚焦对应来源。</CardDescription>
        </div>
        <div className="space-y-3">
          <div className="flex flex-wrap justify-end gap-2">
            <Badge>{`当前结果 ${filteredEvidence.length}`}</Badge>
            {linkedClaim ? <Badge tone="warning">已按 claim 聚焦</Badge> : null}
            {hasActiveFilters ? (
              <Button onClick={resetFilters} type="button" variant="ghost">
                清空筛选
              </Button>
            ) : null}
          </div>
          <div className="grid gap-3 md:grid-cols-5">
            <Select value={marketStep} onChange={(event) => setMarketStep(event.target.value)}>
              <option value="all">全部步骤</option>
              {marketStepOptions.map((step) => (
                <option key={step} value={step}>
                  {formatMarketStep(step)}
                </option>
              ))}
            </Select>
            <Select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
              <option value="all">全部来源类型</option>
              {sourceTypeOptions.map((type) => (
                <option key={type} value={type}>
                  {formatSourceType(type)}
                </option>
              ))}
            </Select>
            <Select value={sourceTier} onChange={(event) => setSourceTier(event.target.value)}>
              <option value="all">全部可信层级</option>
              {sourceTierOptions.map((tier) => (
                <option key={tier} value={tier}>
                  {sourceTierLabels.get(tier) || tier}
                </option>
              ))}
            </Select>
            <Select value={competitorName} onChange={(event) => setCompetitorName(event.target.value)}>
              <option value="all">全部竞品</option>
              {competitorOptions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </Select>
            <Input placeholder="搜索标题或摘要" value={query} onChange={(event) => setQuery(event.target.value)} />
          </div>
        </div>
      </div>

      {competitorSummary.length ? (
        <div className="rounded-[24px] border border-slate-200 bg-[rgba(248,250,252,0.9)] px-4 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-sm font-medium text-slate-900">竞品证据摘要</p>
              <p className="mt-1 text-sm text-slate-500">点击某个竞品，可快速聚焦它目前已经沉淀的证据。</p>
            </div>
            {competitorName !== "all" ? (
              <Button onClick={() => setCompetitorName("all")} type="button" variant="ghost">
                查看全部竞品
              </Button>
            ) : null}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {competitorSummary.map((item) => (
              <button
                key={item.name}
                className={`rounded-full border px-3 py-2 text-sm transition ${
                  competitorName === item.name
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                }`}
                onClick={() => setCompetitorName((current) => (current === item.name ? "all" : item.name))}
                type="button"
              >
                {`${item.name} · ${item.count} 条`}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {linkedClaim ? (
        <div className="rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-900">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="font-medium">当前正在聚焦 claim</p>
              <p className="mt-1 leading-7">{linkedClaim.claim_text}</p>
            </div>
            <Button onClick={() => setSelectedClaimId(undefined)} type="button" variant="secondary">
              退出 claim 聚焦
            </Button>
          </div>
        </div>
      ) : null}

      <div className="grid gap-3">
        {filteredEvidence.map((item) => {
          const domainLabel = (item.source_domain || item.source_url || "未知来源").trim();
          return (
            <div
              key={item.id}
              className="rounded-[28px] border border-slate-200 bg-[linear-gradient(180deg,_rgba(255,255,255,0.98),_rgba(248,250,252,0.98))] p-5 shadow-sm shadow-slate-950/5"
            >
              <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{item.citation_label || item.id}</Badge>
                    {item.source_tier_label ? <Badge tone={sourceTierTone(item.source_tier)}>{item.source_tier_label}</Badge> : null}
                    <Badge>{formatSourceType(item.source_type)}</Badge>
                  </div>
                  <a
                    className="block text-sm font-semibold text-slate-950 transition hover:text-slate-700"
                    href={item.source_url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {item.title}
                  </a>
                  <p className="text-xs text-slate-500">{domainLabel}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={item.injection_risk > 0.18 ? "danger" : item.injection_risk > 0.08 ? "warning" : "success"}>
                    风险 {Math.round(item.injection_risk * 100)}%
                  </Badge>
                </div>
              </div>
            <p className="text-sm leading-7 text-slate-700">{item.summary}</p>
            {item.quote ? (
              <div className="mt-3 rounded-[20px] border border-slate-200 bg-white/90 px-4 py-3 text-sm leading-7 text-slate-600">
                <p className="text-xs uppercase tracking-[0.16em] text-slate-400">原文摘录</p>
                <p className="mt-2">“{item.quote}”</p>
              </div>
            ) : null}
            <div className="mt-3 rounded-[20px] bg-slate-50 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.16em] text-slate-400">研究提炼</p>
              <p className="mt-2 text-sm leading-7 text-slate-700">{item.extracted_fact || "当前仅保留来源摘要。"}</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-500">
              <span>{formatMarketStep(item.market_step)}</span>
              {item.competitor_name ? <span>{item.competitor_name}</span> : null}
              <span>{`置信度 ${formatPercent(item.confidence)}`}</span>
              <span>{`权威度 ${formatPercent(item.authority_score)}`}</span>
              <span>{`新鲜度 ${formatPercent(item.freshness_score)}`}</span>
            </div>
          </div>
        );
        })}
        {!filteredEvidence.length ? (
          <div className="rounded-[28px] border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-sm text-slate-500">
            当前筛选条件下没有匹配到证据，可以放宽可信度层级或关键词再看。
          </div>
        ) : null}
      </div>
    </Card>
  );
}
