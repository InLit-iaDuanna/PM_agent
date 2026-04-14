"use client";

import { type ReactNode, useId } from "react";
import { cn } from "../lib/cn";

export interface TabItem {
  id: string;
  label: string;
  icon?: ReactNode;
  badge?: string | number;
  disabled?: boolean;
}

interface TabsProps {
  items: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
  /** "underline" (默认) | "pill" */
  variant?: "underline" | "pill";
  className?: string;
}

/**
 * Tabs — 带动画的 Tab 组件
 *
 * variant="underline" → 下划线式（报告页、job dashboard 切换）
 * variant="pill"      → 胶囊式（小面板内）
 */
export function Tabs({ items, activeId, onChange, variant = "underline", className }: TabsProps) {
  const uid = useId();

  if (variant === "pill") {
    return (
      <div
        role="tablist"
        className={cn(
          "inline-flex flex-wrap gap-1 rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,252,246,0.6)] p-1.5",
          className,
        )}
      >
        {items.map((item) => (
          <button
            key={item.id}
            role="tab"
            type="button"
            id={`${uid}-tab-${item.id}`}
            aria-controls={`${uid}-panel-${item.id}`}
            aria-selected={activeId === item.id}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-[14px] px-3.5 py-2 text-sm transition-all duration-150",
              "disabled:cursor-not-allowed disabled:opacity-50",
              activeId === item.id
                ? "border border-[color:var(--accent)] bg-[linear-gradient(135deg,rgba(29,76,116,1),rgba(23,32,51,0.98))] text-white shadow-[0_8px_20px_rgba(29,76,116,0.18)]"
                : "border border-transparent text-[color:var(--muted)] hover:border-[color:var(--border-soft)] hover:bg-[rgba(255,255,255,0.56)] hover:text-[color:var(--ink)]",
            )}
          >
            {item.icon}
            {item.label}
            {item.badge !== undefined && (
              <span
                className={cn(
                  "inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full px-1 text-[10px] font-semibold",
                  activeId === item.id
                    ? "bg-white/20 text-white"
                    : "bg-[rgba(29,76,116,0.12)] text-[color:var(--accent)]",
                )}
              >
                {item.badge}
              </span>
            )}
          </button>
        ))}
      </div>
    );
  }

  // underline variant
  return (
    <div
      role="tablist"
      className={cn(
        "flex items-end gap-0 border-b border-[color:var(--border-soft)]",
        className,
      )}
    >
      {items.map((item) => {
        const isActive = activeId === item.id;
        return (
          <button
            key={item.id}
            role="tab"
            type="button"
            id={`${uid}-tab-${item.id}`}
            aria-controls={`${uid}-panel-${item.id}`}
            aria-selected={isActive}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            className={cn(
              "group relative inline-flex items-center gap-2 px-4 pb-3 pt-2.5 text-sm transition-all duration-150",
              "disabled:cursor-not-allowed disabled:opacity-50",
              isActive
                ? "text-[color:var(--ink)] font-semibold"
                : "text-[color:var(--muted)] hover:text-[color:var(--muted-strong)]",
            )}
          >
            {item.icon && (
              <span className={cn("shrink-0", isActive ? "text-[color:var(--accent)]" : "text-[color:var(--muted)] group-hover:text-[color:var(--muted-strong)]")}>
                {item.icon}
              </span>
            )}
            {item.label}
            {item.badge !== undefined && (
              <span className={cn(
                "inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full px-1 text-[10px] font-semibold",
                isActive
                  ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)]"
                  : "bg-[rgba(0,0,0,0.06)] text-[color:var(--muted)]",
              )}>
                {item.badge}
              </span>
            )}
            {/* 下划线 */}
            <span
              className={cn(
                "absolute bottom-0 left-0 h-0.5 w-full rounded-full transition-all duration-200",
                isActive
                  ? "bg-[color:var(--accent)] opacity-100 scale-x-100"
                  : "bg-transparent opacity-0 scale-x-0",
              )}
            />
          </button>
        );
      })}
    </div>
  );
}

/** TabPanel — 配合 Tabs 使用的内容面板 */
export function TabPanel({
  id,
  activeId,
  uid,
  children,
  className,
}: {
  id: string;
  activeId: string;
  uid: string;
  children: ReactNode;
  className?: string;
}) {
  if (activeId !== id) return null;
  return (
    <div
      role="tabpanel"
      id={`${uid}-panel-${id}`}
      aria-labelledby={`${uid}-tab-${id}`}
      className={cn("animate-fade-up", className)}
    >
      {children}
    </div>
  );
}
