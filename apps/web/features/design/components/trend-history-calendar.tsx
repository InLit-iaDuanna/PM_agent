"use client";

import type { TrendRecord } from "../store/design-store";

interface TrendHistoryCalendarProps {
  records: Record<string, TrendRecord>;
  onSelectDate?: (date: string) => void;
}

export function TrendHistoryCalendar({ records, onSelectDate }: TrendHistoryCalendarProps) {
  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const days = Array.from({ length: 30 }, (_, index) => {
    const cursor = new Date(today);
    cursor.setDate(today.getDate() - (29 - index));
    const date = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}-${String(cursor.getDate()).padStart(2, "0")}`;
    return { date, record: records[date] };
  });

  return (
    <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-white/80 p-4 shadow-[var(--shadow-sm)]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold tracking-[-0.03em] text-[color:var(--ink)]">近 30 天趋势轨迹</h3>
          <p className="text-sm text-[color:var(--muted)]">点击任意日期，可快速回看当天的趋势结果。</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
        {days.map(({ date, record }) => {
          const isToday = date === todayKey;
          return (
            <button
              key={date}
              onClick={() => onSelectDate?.(date)}
              type="button"
              className="rounded-[20px] border p-3 text-left transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-sm)]"
              style={{
                borderColor: isToday ? "var(--accent)" : "var(--border-soft)",
                background: isToday ? "rgba(37,99,235,0.06)" : "rgba(255,255,255,0.7)",
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-[color:var(--ink)]">{date.slice(5)}</span>
                <span className="text-[11px] text-[color:var(--muted)]">{record?.category || "未记录"}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {(record?.trend.color_palette || ["#E2E8F0", "#CBD5E1", "#94A3B8", "#64748B", "#334155"]).map((color, index) => (
                  <span
                    key={`${date}-${color}-${index}`}
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                ))}
              </div>
              <p className="mt-3 line-clamp-2 text-xs leading-5 text-[color:var(--muted)]">
                {record?.trend.name || "还没有当天趋势记录"}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
