"use client";

import { useState, useEffect, useRef, type KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { Search, ArrowRight, FileText, Settings, Plus, Home } from "lucide-react";

import { orchestrationPresetCatalog } from "@pm-agent/research-core";
import type { ResearchJobRecord, WorkflowCommandId } from "@pm-agent/types";
import { Badge } from "@pm-agent/ui";

import { commandIcons } from "../research/components/research-ui-utils";

interface QuickSearchPanelProps {
  jobs: ResearchJobRecord[];
  onClose: () => void;
}

type ResultItem =
  | { type: "job"; id: string; label: string; sub: string; status: ResearchJobRecord["status"] }
  | { type: "template"; id: WorkflowCommandId; label: string; sub: string }
  | { type: "nav"; href: string; label: string; sub: string };

const staticNavItems: ResultItem[] = [
  { type: "nav", href: "/",                  label: "研究首页",   sub: "回到首页概览" },
  { type: "nav", href: "/research/new",      label: "新建研究",   sub: "创建新的研究任务" },
  { type: "nav", href: "/settings/runtime",  label: "服务设置",   sub: "API、模型、搜索配置" },
  { type: "nav", href: "/settings/account",  label: "账号设置",   sub: "密码、账号管理" },
];

const navIcons: Record<string, React.ReactNode> = {
  "/":                  <Home className="h-4 w-4" />,
  "/research/new":      <Plus className="h-4 w-4" />,
  "/settings/runtime":  <Settings className="h-4 w-4" />,
  "/settings/account":  <Settings className="h-4 w-4" />,
};

function statusLabel(s: ResearchJobRecord["status"]) {
  if (s === "completed") return "已完成";
  if (s === "failed")    return "已失败";
  if (s === "cancelled") return "已取消";
  if (s === "planning")  return "规划中";
  return "进行中";
}

function statusTone(s: ResearchJobRecord["status"]): "success" | "danger" | "warning" | "default" {
  if (s === "completed") return "success";
  if (s === "failed")    return "danger";
  if (s === "cancelled") return "warning";
  return "default";
}

function match(text: string | undefined, q: string) {
  return text?.toLowerCase().includes(q) ?? false;
}

export function QuickSearchPanel({ jobs, onClose }: QuickSearchPanelProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus
  useEffect(() => { inputRef.current?.focus(); }, []);

  // Cmd+K / Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent | Event) => {
      const ke = e as KeyboardEvent;
      if (ke.key === "Escape") onClose();
      if ((ke.metaKey || ke.ctrlKey) && ke.key === "k") {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", handler as EventListener);
    return () => document.removeEventListener("keydown", handler as EventListener);
  }, [onClose]);

  const q = query.trim().toLowerCase();

  // Build results
  const results: ResultItem[] = [];

  // Nav items (always shown when no query, or if they match)
  staticNavItems
    .filter((item) => !q || match(item.label, q) || match(item.sub, q))
    .forEach((item) => results.push(item));

  // Templates
  if (q || results.length < 6) {
    (Object.entries(orchestrationPresetCatalog) as Array<[WorkflowCommandId, typeof orchestrationPresetCatalog[WorkflowCommandId]]>)
      .filter(([id, p]) =>
        !q || match(p.label, q) || match(p.summary, q) || match(id, q),
      )
      .slice(0, 4)
      .forEach(([id, p]) =>
        results.push({ type: "template", id, label: p.label, sub: p.summary }),
      );
  }

  // Jobs
  const matchedJobs = jobs
    .filter((j) => !q || match(j.topic, q) || match(j.workflow_label, q))
    .slice(0, q ? 8 : 4);

  matchedJobs.forEach((j) =>
    results.push({ type: "job", id: j.id, label: j.topic, sub: `${j.source_count} 来源 · ${j.claims_count} 判断`, status: j.status }),
  );

  // Reset active when results change
  useEffect(() => { setActiveIndex(0); }, [query]);

  const navigate = (item: ResultItem) => {
    if (item.type === "nav")      { router.push(item.href); onClose(); return; }
    if (item.type === "job")      { router.push(`/research/jobs/${item.id}`); onClose(); return; }
    if (item.type === "template") { router.push(`/research/new?command=${item.id}`); onClose(); return; }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveIndex((i) => Math.min(i + 1, results.length - 1)); }
    if (e.key === "ArrowUp")   { e.preventDefault(); setActiveIndex((i) => Math.max(i - 1, 0)); }
    if (e.key === "Enter" && results[activeIndex]) navigate(results[activeIndex]);
  };

  return (
    <div className="cmdk-overlay fixed inset-0 z-50 flex items-start justify-center px-4 pt-[15vh]">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-[rgba(23,32,51,0.32)] backdrop-blur-[3px]"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div
        role="dialog"
        aria-label="快速搜索"
        aria-modal
        className="animate-fade-up relative w-full max-w-lg rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(250,246,240,0.98)] shadow-[0_32px_96px_rgba(23,32,51,0.18)] backdrop-blur-xl"
      >
        {/* Input */}
        <div className="flex items-center gap-3 border-b border-[color:var(--border-soft)] px-4 py-3.5">
          <Search className="h-4 w-4 shrink-0 text-[color:var(--muted)]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="搜索研究、任务、模板、设置..."
            className="flex-1 bg-transparent text-sm text-[color:var(--ink)] placeholder:text-[color:var(--muted)] outline-none"
            aria-label="搜索"
          />
          <kbd className="rounded-[6px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.6)] px-1.5 py-0.5 text-[10px] text-[color:var(--muted)]">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[360px] overflow-y-auto p-2">
          {results.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-[color:var(--muted)]">
              没有找到匹配结果
            </div>
          )}

          {results.map((item, i) => {
            const isActive = i === activeIndex;
            const key = item.type === "job" ? `job-${item.id}` : item.type === "template" ? `tpl-${item.id}` : `nav-${item.href}`;

            let icon: React.ReactNode = <ArrowRight className="h-4 w-4" />;
            if (item.type === "nav")      icon = navIcons[(item as Extract<ResultItem, { type: "nav" }>).href] ?? icon;
            if (item.type === "job")      icon = <FileText className="h-4 w-4" />;
            if (item.type === "template") {
              const tplItem = item as Extract<ResultItem, { type: "template" }>;
              const Icon = commandIcons[tplItem.id];
              if (Icon) icon = <Icon className="h-4 w-4" />;
            }

            return (
              <button
                key={key}
                type="button"
                onClick={() => navigate(item)}
                onMouseEnter={() => setActiveIndex(i)}
                className={`flex w-full items-center gap-3 rounded-[14px] px-3 py-2.5 text-left transition-colors ${
                  isActive ? "bg-[rgba(29,76,116,0.1)]" : "hover:bg-[rgba(29,76,116,0.06)]"
                }`}
              >
                <span className="shrink-0 text-[color:var(--muted)]">{icon}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-[color:var(--ink)]">{item.label}</p>
                  <p className="truncate text-xs text-[color:var(--muted)]">{item.sub}</p>
                </div>
                {item.type === "job" && (
                  <Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
                )}
                {item.type === "template" && (
                  <span className="shrink-0 text-xs text-[color:var(--muted)]">模板</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Footer hint */}
        <div className="flex items-center gap-3 border-t border-[color:var(--border-soft)] px-4 py-2.5 text-[11px] text-[color:var(--muted)]">
          <span><kbd className="rounded border border-[color:var(--border-soft)] px-1">↑↓</kbd> 选择</span>
          <span><kbd className="rounded border border-[color:var(--border-soft)] px-1">↵</kbd> 跳转</span>
          <span><kbd className="rounded border border-[color:var(--border-soft)] px-1">ESC</kbd> 关闭</span>
        </div>
      </div>
    </div>
  );
}
