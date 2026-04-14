import type { SelectHTMLAttributes } from "react";

import { cn } from "../lib/cn";

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "w-full rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,252,247,0.86)] px-3.5 py-2.5 text-sm text-[color:var(--ink)] outline-none focus:border-[color:var(--accent)] focus:bg-white focus:shadow-[0_0_0_4px_rgba(29,76,116,0.08)]",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
