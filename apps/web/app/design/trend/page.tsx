"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, ChevronUp, ExternalLink, RefreshCw } from "lucide-react";
import { Badge, Button, Card, useToast } from "@pm-agent/ui";

import { TrendCard } from "../../../features/design/components/trend-card";
import { TrendDice } from "../../../features/design/components/trend-dice";
import { TrendHistoryCalendar } from "../../../features/design/components/trend-history-calendar";
import type { DesignTrend } from "../../../features/design/data/trend-types";
import { TREND_CATEGORY_ORDER } from "../../../features/design/data/trend-types";
import { useRefreshTrendPool, useSaveTrendToLibrary, useTodayTrend, useTrendHistory } from "../../../features/design/hooks/use-trend";
import { buildTrendRecordFromRoll, useDesignStore } from "../../../features/design/store/design-store";

type TrendFilter = "all" | (typeof TREND_CATEGORY_ORDER)[number];

function hostFromUrl(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function sourceLabelsFromTrend(trend: DesignTrend): string[] {
  if (trend.source_labels?.length) {
    return trend.source_labels.filter(Boolean);
  }
  return trend.source_urls.map((url) => hostFromUrl(url)).filter(Boolean);
}

function extractionModeLabel(trend: DesignTrend) {
  return trend.summary_mode === "llm" ? "模型提炼" : "站外摘要";
}

function extractionModeTone(trend: DesignTrend) {
  return trend.summary_mode === "llm" ? "success" : "default";
}

export default function DesignTrendPage() {
  const router = useRouter();
  const toast = useToast();
  const todayTrendQuery = useTodayTrend();
  const historyQuery = useTrendHistory(30);
  const refreshMutation = useRefreshTrendPool();
  const saveTrendMutation = useSaveTrendToLibrary();
  const {
    trend_history,
    saved_trends,
    has_rolled_today,
    hydrateTrendHistory,
    recordTrendRoll,
    toggleSaveTrend,
    markTrendSavedForDate,
    setHasRolledToday,
  } = useDesignStore();

  const [showHistory, setShowHistory] = useState(false);
  const [diceRolling, setDiceRolling] = useState(false);
  const [showTrendCard, setShowTrendCard] = useState(false);
  const [activeDate, setActiveDate] = useState<string | null>(null);
  const [selectedPoolTrendId, setSelectedPoolTrendId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<TrendFilter>("all");

  useEffect(() => {
    if (!historyQuery.data?.length) {
      return;
    }
    hydrateTrendHistory(
      historyQuery.data.map((record) => ({
        date: record.date,
        trend: record.trend,
        category: record.dice_category,
        dice_face: record.dice_face,
        saved_to_library: saved_trends.includes(record.trend.id),
      })),
    );
  }, [historyQuery.data, hydrateTrendHistory, saved_trends]);

  useEffect(() => {
    if (!todayTrendQuery.data) {
      return;
    }
    const hasTodayRecord = Boolean(trend_history[todayTrendQuery.data.date]);
    setActiveDate((current) => current ?? todayTrendQuery.data.date);
    setHasRolledToday(hasTodayRecord);
    if (hasTodayRecord) {
      setShowTrendCard(true);
    }
  }, [setHasRolledToday, todayTrendQuery.data, trend_history]);

  useEffect(() => {
    if (!todayTrendQuery.data || !selectedPoolTrendId) {
      return;
    }
    const stillExists = todayTrendQuery.data.pool.some((item) => item.id === selectedPoolTrendId);
    if (!stillExists) {
      setSelectedPoolTrendId(null);
    }
  }, [selectedPoolTrendId, todayTrendQuery.data]);

  const livePool = todayTrendQuery.data?.pool ?? [];
  const filteredPool = livePool.filter((trend) => activeFilter === "all" || trend.category === activeFilter);
  const liveCategoryCount = new Set(livePool.map((item) => item.category)).size;
  const liveSourceHosts = new Set(
    livePool.flatMap((item) => sourceLabelsFromTrend(item)),
  );
  const summaryModes = new Set(livePool.map((item) => item.summary_mode || "heuristic"));

  const activeRecord = useMemo(() => {
    if (selectedPoolTrendId && todayTrendQuery.data) {
      const selectedTrend = todayTrendQuery.data.pool.find((item) => item.id === selectedPoolTrendId);
      if (selectedTrend) {
        return {
          date: todayTrendQuery.data.date,
          trend: selectedTrend,
          category: selectedTrend.category,
          dice_face: TREND_CATEGORY_ORDER.indexOf(selectedTrend.category) + 1,
          saved_to_library: saved_trends.includes(selectedTrend.id),
        };
      }
    }
    if (activeDate && trend_history[activeDate]) {
      return trend_history[activeDate];
    }
    if (showTrendCard && todayTrendQuery.data) {
      return buildTrendRecordFromRoll(todayTrendQuery.data);
    }
    return null;
  }, [activeDate, saved_trends, selectedPoolTrendId, showTrendCard, todayTrendQuery.data, trend_history]);

  const previewTrend = todayTrendQuery.data?.trend ?? null;
  const currentRecord = activeRecord ?? (todayTrendQuery.data ? buildTrendRecordFromRoll(todayTrendQuery.data) : null);
  const currentIsSaved = Boolean(currentRecord && saved_trends.includes(currentRecord.trend.id));

  const startRoll = () => {
    if (!todayTrendQuery.data) {
      return;
    }
    setSelectedPoolTrendId(null);
    setActiveDate(todayTrendQuery.data.date);
    setShowTrendCard(false);
    setDiceRolling(false);
    window.setTimeout(() => setDiceRolling(true), 30);
  };

  const handleRollComplete = () => {
    if (!todayTrendQuery.data) {
      return;
    }
    recordTrendRoll(buildTrendRecordFromRoll(todayTrendQuery.data));
    setSelectedPoolTrendId(todayTrendQuery.data.trend.id);
    setHasRolledToday(true);
    setShowTrendCard(true);
  };

  const handleSave = async () => {
    if (!currentRecord) {
      return;
    }
    try {
      await saveTrendMutation.mutateAsync(currentRecord.trend);
      if (!currentIsSaved) {
        toggleSaveTrend(currentRecord.trend.id);
      }
      markTrendSavedForDate(currentRecord.date, true);
      toast.success("趋势已收藏到素材库。");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "收藏失败。");
    }
  };

  const handleShare = async () => {
    if (!activeRecord) {
      return;
    }
    try {
      await navigator.clipboard.writeText(
        `今日设计趋势：${activeRecord.trend.name}\n类别：${activeRecord.category}\n练习提示：${activeRecord.trend.example_prompt}`,
      );
      toast.success("趋势文案已复制到剪贴板。");
    } catch {
      toast.error("复制失败，请稍后重试。");
    }
  };

  const handleRefresh = async () => {
    try {
      const result = await refreshMutation.mutateAsync();
      setSelectedPoolTrendId(null);
      setShowTrendCard(false);
      setHasRolledToday(false);
      toast.success(
        result.trend_count
          ? `${result.message} 已抓到 ${result.trend_count} 条趋势，覆盖 ${result.available_category_count ?? 0} 个类别。`
          : result.message,
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "刷新失败。");
    }
  };

  return (
    <div className="space-y-6">
      <section className="paper-panel rounded-[34px] px-6 py-6 sm:px-7">
        <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="success">Live Design Trend</Badge>
              <Badge>{livePool.length ? `${livePool.length} 条信号` : "等待抓取"}</Badge>
              <Badge>{liveCategoryCount ? `${liveCategoryCount} 个类别` : "类别待生成"}</Badge>
              <Badge>{`${liveSourceHosts.size} 个站点`}</Badge>
              {todayTrendQuery.data?.pool_fetched_at ? (
                <Badge>{`抓取于 ${new Date(todayTrendQuery.data.pool_fetched_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`}</Badge>
              ) : null}
            </div>

            <div>
              <h1 className="section-title text-[clamp(2rem,4vw,3.2rem)] leading-[1.05] text-[color:var(--ink)]">每日设计趋势</h1>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-[color:var(--muted)]">
                页面会先从站外网站抓当天最新趋势信号，再给出可浏览的趋势池和一个今日推荐。没有结果时会明确报错，不再回退到系统内置卡片。
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <StatusMetric label="结果来源" value={summaryModes.has("llm") ? "模型 + 站外" : "站外实时摘要"} />
              <StatusMetric label="推荐机制" value="按类别投骰推荐" />
              <StatusMetric label="保留方式" value="可直接收藏到素材库" />
            </div>
          </div>

          <div className="flex flex-wrap justify-start gap-3 xl:justify-end">
            <Button onClick={handleRefresh} type="button" variant="secondary" disabled={refreshMutation.isPending}>
              <RefreshCw className={`mr-2 h-4 w-4 ${refreshMutation.isPending ? "animate-spin" : ""}`} />
              {refreshMutation.isPending ? "正在刷新站外趋势..." : "刷新站外趋势"}
            </Button>
            <Button asChild type="button" variant="ghost">
              <Link href="/design/materials">打开素材库</Link>
            </Button>
          </div>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[420px_minmax(0,1fr)]">
        <Card className="flex flex-col items-center justify-center gap-6 p-8 text-center">
          <TrendDice targetFace={todayTrendQuery.data?.dice_face ?? 1} isRolled={diceRolling} onRollComplete={handleRollComplete} />

          {todayTrendQuery.isLoading ? (
            <div className="space-y-3">
              <Badge>正在建立趋势池</Badge>
              <p className="text-sm leading-7 text-[color:var(--muted)]">正在抓取今天的站外最新趋势，首次搜索可能需要 15 到 30 秒。</p>
            </div>
          ) : todayTrendQuery.error ? (
            <div className="space-y-3">
              <Badge tone="warning">暂无可揭晓结果</Badge>
              <p className="text-sm leading-7 text-[color:var(--muted)]">
                当前还没有拿到今天可用的站外趋势池。可以直接刷新重试。
              </p>
              <Button onClick={handleRefresh} type="button" disabled={refreshMutation.isPending}>
                {refreshMutation.isPending ? "刷新中..." : "重新抓取"}
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <Badge tone="success">{has_rolled_today ? "今日推荐已揭晓" : "今日推荐已准备好"}</Badge>
              <p className="text-sm leading-7 text-[color:var(--muted)]">
                {has_rolled_today
                  ? "今天已经投过一次，可以重播动画，结果仍然来自今天这批实时趋势。"
                  : "点击按钮揭晓今天的推荐方向。你也可以直接从下方趋势池里手动挑选。"}
              </p>
              <Button onClick={startRoll} type="button" disabled={refreshMutation.isPending || !todayTrendQuery.data}>
                {has_rolled_today ? "重播今日揭晓" : "揭晓今日趋势"}
              </Button>
            </div>
          )}
        </Card>

        <div>
          {todayTrendQuery.isLoading ? (
            <Card className="space-y-4">
              <div className="skeleton h-8 w-36 rounded-[14px]" />
              <div className="skeleton h-12 rounded-[18px]" />
              <div className="skeleton h-40 rounded-[24px]" />
              <p className="text-sm text-[color:var(--muted)]">正在分析站外搜索结果并组织为可浏览的趋势卡片。</p>
            </Card>
          ) : todayTrendQuery.error ? (
            <Card className="space-y-4">
              <div className="space-y-2">
                <h2 className="text-lg font-semibold text-[color:var(--ink)]">实时趋势加载失败</h2>
                <p className="text-sm leading-7 text-[color:var(--muted)]">
                  {todayTrendQuery.error instanceof Error ? todayTrendQuery.error.message : "请稍后重试。"}
                </p>
                <p className="text-xs leading-6 text-[color:var(--muted)]">
                  当前页不会回退到系统内置趋势；拿不到当天站外结果时会直接报错。
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button onClick={handleRefresh} type="button" disabled={refreshMutation.isPending}>
                  {refreshMutation.isPending ? "刷新中..." : "重新抓取"}
                </Button>
                <Button asChild type="button" variant="secondary">
                  <Link href="/settings/runtime">检查服务设置</Link>
                </Button>
              </div>
            </Card>
          ) : activeRecord ? (
            <TrendCard
              trend={activeRecord.trend}
              category={activeRecord.category}
              onSave={handleSave}
              isSaved={currentIsSaved || Boolean(trend_history[activeRecord.date]?.saved_to_library)}
              onShare={handleShare}
              onViewRelations={() => router.push("/design/network")}
            />
          ) : previewTrend ? (
            <Card className="space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={extractionModeTone(previewTrend)}>{extractionModeLabel(previewTrend)}</Badge>
                <Badge>{previewTrend.category}</Badge>
                <Badge>{`${previewTrend.source_count ?? previewTrend.source_urls.length} 条来源`}</Badge>
              </div>
              <div>
                <h2 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">{previewTrend.name}</h2>
                <p className="mt-2 text-sm leading-7 text-[color:var(--muted)]">{previewTrend.description}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {previewTrend.keywords.slice(0, 4).map((keyword) => (
                  <Badge key={keyword} className="normal-case tracking-[0.02em]">
                    {keyword}
                  </Badge>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-[color:var(--muted)]">
                {previewTrend.published_at ? <span>{`发布于 ${new Date(previewTrend.published_at).toLocaleDateString("zh-CN")}`}</span> : null}
                {sourceLabelsFromTrend(previewTrend).slice(0, 3).map((label) => (
                  <Badge key={label} className="normal-case tracking-[0.02em]">
                    {label}
                  </Badge>
                ))}
              </div>
              <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] p-4 text-sm leading-7 text-[color:var(--muted)]">
                左侧点击“揭晓今日趋势”会播放投骰动画；如果你不想等，也可以直接从下方趋势池选择任意一条站外趋势信号。
              </div>
            </Card>
          ) : (
            <Card className="flex min-h-[320px] items-center justify-center text-center">
              <div className="space-y-3">
                <h2 className="text-xl font-semibold text-[color:var(--ink)]">等待今日趋势就绪</h2>
                <p className="text-sm leading-7 text-[color:var(--muted)]">站外趋势池准备完成后，这里会先显示推荐概览，再由左侧骰子揭晓。</p>
              </div>
            </Card>
          )}
        </div>
      </div>

      {livePool.length > 0 ? (
        <Card className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-[color:var(--ink)]">今日站外趋势池</h2>
              <p className="text-sm leading-7 text-[color:var(--muted)]">这里列出今天实际抓到的全部趋势信号。推荐结果只是从这批实时信号里挑出的一条入口。</p>
            </div>
            <Badge tone="success">live only</Badge>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveFilter("all")}
              className={`rounded-full border px-4 py-2 text-xs transition ${
                activeFilter === "all"
                  ? "border-[color:var(--accent)] bg-[rgba(29,76,116,0.08)] text-[color:var(--ink)]"
                  : "border-[color:var(--border-soft)] bg-white/70 text-[color:var(--muted)]"
              }`}
            >
              全部
            </button>
            {TREND_CATEGORY_ORDER.filter((category) => livePool.some((trend) => trend.category === category)).map((category) => (
              <button
                key={category}
                type="button"
                onClick={() => setActiveFilter(category)}
                className={`rounded-full border px-4 py-2 text-xs transition ${
                  activeFilter === category
                    ? "border-[color:var(--accent)] bg-[rgba(29,76,116,0.08)] text-[color:var(--ink)]"
                    : "border-[color:var(--border-soft)] bg-white/70 text-[color:var(--muted)]"
                }`}
              >
                {category}
              </button>
            ))}
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filteredPool.map((trend) => {
              const sourceLabels = Array.from(new Set(sourceLabelsFromTrend(trend))).slice(0, 2);
              const isActive = currentRecord?.trend.id === trend.id;
              return (
                <button
                  key={trend.id}
                  type="button"
                  onClick={() => {
                    setSelectedPoolTrendId(trend.id);
                    setActiveDate(todayTrendQuery.data?.date ?? null);
                    setShowTrendCard(true);
                  }}
                  className={`rounded-[22px] border p-4 text-left transition ${
                    isActive
                      ? "border-[color:var(--accent)] bg-[rgba(29,76,116,0.08)]"
                      : "border-[color:var(--border-soft)] bg-white/70 hover:border-[color:var(--accent)] hover:bg-white"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{trend.category}</Badge>
                    <Badge tone={extractionModeTone(trend)}>{extractionModeLabel(trend)}</Badge>
                    <span className="text-[11px] text-[color:var(--muted)]">{`${trend.source_count ?? trend.source_urls.length} 条来源`}</span>
                    {trend.published_at ? <span className="text-[11px] text-[color:var(--muted)]">{new Date(trend.published_at).toLocaleDateString("zh-CN")}</span> : null}
                  </div>
                  <p className="mt-3 text-base font-semibold text-[color:var(--ink)]">{trend.name}</p>
                  <p className="mt-2 line-clamp-3 text-sm leading-6 text-[color:var(--muted)]">{trend.description}</p>
                  {sourceLabels.length > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {sourceLabels.map((label) => (
                        <span
                          key={label}
                          className="inline-flex items-center gap-1 rounded-full border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.76)] px-2.5 py-1 text-[11px] text-[color:var(--muted)]"
                        >
                          <ExternalLink className="h-3 w-3" />
                          {label}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </button>
              );
            })}
          </div>
        </Card>
      ) : null}

      <div className="space-y-3">
        <button
          onClick={() => setShowHistory((value) => !value)}
          type="button"
          className="inline-flex items-center gap-2 rounded-full border border-[color:var(--border-soft)] bg-white/72 px-4 py-2 text-sm text-[color:var(--ink)] transition hover:border-[color:var(--accent)]"
        >
          {showHistory ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          {showHistory ? "收起历史日历" : "查看历史日历"}
        </button>

        {showHistory ? (
          <TrendHistoryCalendar
            records={trend_history}
            onSelectDate={(date) => {
              setSelectedPoolTrendId(null);
              setActiveDate(date);
              setShowTrendCard(true);
            }}
          />
        ) : null}
      </div>
    </div>
  );
}

function StatusMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-4 py-4">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-2 text-sm font-medium text-[color:var(--ink)]">{value}</p>
    </div>
  );
}
