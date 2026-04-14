import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export interface TimelineEvent {
  id: string;
  title: string;
  description?: string;
  timestamp: string;
  /** "info" | "success" | "warning" | "error" */
  level?: "info" | "success" | "warning" | "error";
  icon?: ReactNode;
  meta?: string;
}

interface TimelineProps {
  events: TimelineEvent[];
  className?: string;
  /** 是否分组（今天/昨天/更早） */
  grouped?: boolean;
  /** 点击事件 */
  onEventClick?: (event: TimelineEvent) => void;
}

function getDayGroup(isoString: string): string {
  const date = new Date(isoString);
  const now  = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "今天";
  if (diffDays === 1) return "昨天";
  return `${diffDays} 天前`;
}

const levelDotClass: Record<string, string> = {
  info:    "bg-[color:var(--accent)]",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error:   "bg-rose-500",
};

const levelTextClass: Record<string, string> = {
  info:    "text-[color:var(--accent)]",
  success: "text-emerald-700",
  warning: "text-amber-700",
  error:   "text-rose-700",
};

/**
 * Timeline — 纵向时间线
 *
 * 用法：
 *   <Timeline events={activityFeed} grouped onEventClick={(e) => router.push(...)} />
 */
export function Timeline({ events, className, grouped = false, onEventClick }: TimelineProps) {
  if (!events.length) {
    return (
      <div className="rounded-[24px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.4)] px-4 py-8 text-center text-sm text-[color:var(--muted)]">
        还没有活动记录
      </div>
    );
  }

  if (!grouped) {
    return (
      <ol className={cn("space-y-0", className)}>
        {events.map((event, i) => (
          <TimelineItem
            key={event.id}
            event={event}
            isLast={i === events.length - 1}
            onClick={onEventClick}
          />
        ))}
      </ol>
    );
  }

  // Grouped by day
  const groups: { label: string; items: TimelineEvent[] }[] = [];
  for (const event of events) {
    const label = getDayGroup(event.timestamp);
    const existing = groups.find((g) => g.label === label);
    if (existing) {
      existing.items.push(event);
    } else {
      groups.push({ label, items: [event] });
    }
  }

  return (
    <div className={cn("space-y-5", className)}>
      {groups.map((group) => (
        <div key={group.label}>
          <p className="mb-3 text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
            {group.label}
          </p>
          <ol className="space-y-0">
            {group.items.map((event, i) => (
              <TimelineItem
                key={event.id}
                event={event}
                isLast={i === group.items.length - 1}
                onClick={onEventClick}
              />
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

function TimelineItem({
  event,
  isLast,
  onClick,
}: {
  event: TimelineEvent;
  isLast: boolean;
  onClick?: (event: TimelineEvent) => void;
}) {
  const level = event.level ?? "info";
  const Wrapper = onClick ? "button" : "div";

  return (
    <li className="flex gap-3">
      {/* Left: dot + line */}
      <div className="flex flex-col items-center">
        <span
          className={cn(
            "mt-1.5 h-2 w-2 shrink-0 rounded-full",
            levelDotClass[level],
          )}
        />
        {!isLast && (
          <span className="mt-1 w-px flex-1 bg-[color:var(--border-soft)]" />
        )}
      </div>

      {/* Right: content */}
      <Wrapper
        className={cn(
          "mb-4 min-w-0 flex-1 rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-3",
          onClick && "cursor-pointer text-left transition hover:border-[color:var(--border-strong)] hover:bg-white",
        )}
        onClick={onClick ? () => onClick(event) : undefined}
        type={onClick ? "button" : undefined}
      >
        <div className="flex items-start justify-between gap-3">
          <p className={cn("text-sm font-medium", levelTextClass[level])}>{event.title}</p>
          <time className="shrink-0 text-[11px] text-[color:var(--muted)]">
            {new Date(event.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
          </time>
        </div>
        {event.description && (
          <p className="mt-1.5 text-sm leading-6 text-[color:var(--muted)]">{event.description}</p>
        )}
        {event.meta && (
          <p className="mt-1 text-xs text-[color:var(--muted)]">{event.meta}</p>
        )}
      </Wrapper>
    </li>
  );
}
