"use client";

import { BookmarkPlus, ExternalLink, Network, Share2 } from "lucide-react";
import { AnimatedCard, Badge, Button } from "@pm-agent/ui";

import type { DesignTrend, TrendCategory } from "../data/trend-types";
import { TREND_CATEGORY_ACCENTS } from "../data/trend-types";

interface TrendCardProps {
  trend: DesignTrend;
  category: TrendCategory;
  onSave: () => void;
  isSaved: boolean;
  onShare?: () => void;
  onViewRelations?: () => void;
}

export function TrendCard({ trend, category, onSave, isSaved, onShare, onViewRelations }: TrendCardProps) {
  const sourceLabels =
    trend.source_labels?.filter(Boolean).slice(0, 3) ??
    trend.source_urls
      .map((url) => {
        try {
          return new URL(url).hostname.replace(/^www\./, "");
        } catch {
          return "";
        }
      })
      .filter(Boolean)
      .slice(0, 3);

  return (
    <AnimatedCard
      className="overflow-hidden border border-[color:var(--border-soft)]"
      style={{
        background: `linear-gradient(180deg, ${trend.color_palette[0] || "#FFFFFF"}14, rgba(255,255,255,0.94))`,
      }}
    >
      <div className="space-y-5">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-3">
            <Badge
              className="border-transparent text-[color:var(--ink)]"
              style={{ backgroundColor: `${TREND_CATEGORY_ACCENTS[category]}1A` }}
            >
              {category}
            </Badge>
            <div>
              <h2 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{trend.name}</h2>
              {trend.name_en ? (
                <p className="mt-1 text-sm font-medium tracking-[0.02em] text-[color:var(--muted)]">{trend.name_en}</p>
              ) : null}
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            {[1, 2, 3].map((level) => (
              <span
                key={level}
                className="h-2.5 w-2.5 rounded-full"
                style={{
                  background: level <= trend.difficulty ? "var(--accent)" : "rgba(148,163,184,0.25)",
                }}
                title={`难度 ${trend.difficulty}/3`}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {trend.color_palette.map((color) => (
            <span
              key={color}
              className="h-7 w-12 rounded-xl border border-white/50 shadow-sm"
              style={{ backgroundColor: color }}
              title={color}
            />
          ))}
        </div>

        <p className="text-sm leading-7 text-[color:var(--muted)]">{trend.description}</p>

        <div className="flex flex-wrap gap-2">
          {trend.keywords.map((keyword) => (
            <Badge key={keyword} className="normal-case tracking-[0.02em]">
              {keyword}
            </Badge>
          ))}
          {trend.mood_keywords.map((keyword) => (
            <Badge key={keyword} tone="success" className="normal-case tracking-[0.02em]">
              {keyword}
            </Badge>
          ))}
        </div>

        <div className="rounded-[24px] border border-dashed border-[color:var(--border-soft)] bg-white/65 p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--muted)]">练习提示</p>
          <p className="mt-2 text-sm leading-7 text-[color:var(--ink)]">{trend.example_prompt}</p>
        </div>

        <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={trend.summary_mode === "llm" ? "success" : "default"} className="normal-case tracking-[0.02em]">
              {trend.summary_mode === "llm" ? "模型提炼" : "站外实时摘要"}
            </Badge>
            <Badge className="normal-case tracking-[0.02em]">{`${trend.source_count ?? trend.source_urls.length} 条来源`}</Badge>
            {trend.published_at ? (
              <span className="text-xs text-[color:var(--muted)]">发布于 {new Date(trend.published_at).toLocaleDateString("zh-CN")}</span>
            ) : null}
            {trend.fetched_at ? (
              <span className="text-xs text-[color:var(--muted)]">
                抓取时间 {new Date(trend.fetched_at).toLocaleString("zh-CN")}
              </span>
            ) : null}
          </div>
          {sourceLabels.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {sourceLabels.map((label) => (
                <Badge key={label} className="normal-case tracking-[0.02em]">
                  {label}
                </Badge>
              ))}
            </div>
          ) : null}
          {trend.source_urls.length > 0 ? (
            <div className="mt-3 space-y-2">
              {trend.source_urls.slice(0, 3).map((url, index) => (
                <a
                  key={`${url}-${index}`}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-2 rounded-[14px] border border-[color:var(--border-soft)] bg-white/80 px-3 py-2 text-xs text-[color:var(--muted)] transition hover:border-[color:var(--accent)] hover:text-[color:var(--ink)]"
                >
                  <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{sourceLabels[index] ?? url}</span>
                </a>
              ))}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-3">
          <Button onClick={onSave} type="button">
            <BookmarkPlus className="mr-2 h-4 w-4" />
            {isSaved ? "已收藏到素材库" : "收藏到素材库"}
          </Button>
          <Button onClick={onShare} type="button" variant="secondary">
            <Share2 className="mr-2 h-4 w-4" />
            分享
          </Button>
          <Button onClick={onViewRelations} type="button" variant="ghost">
            <Network className="mr-2 h-4 w-4" />
            查看关联网络
          </Button>
        </div>
      </div>
    </AnimatedCard>
  );
}
