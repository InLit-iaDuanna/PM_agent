import type { HTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../lib/cn";

type BadgeTone = "default" | "success" | "warning" | "danger";

export function Badge({
  children,
  className,
  tone = "default",
  ...props
}: PropsWithChildren<HTMLAttributes<HTMLSpanElement>> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em]",
        tone === "default" && "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.46)] text-[color:var(--muted-strong)]",
        tone === "success" && "border-emerald-200 bg-emerald-50/80 text-emerald-800",
        tone === "warning" && "border-amber-200 bg-amber-50/80 text-amber-800",
        tone === "danger" && "border-rose-200 bg-rose-50/80 text-rose-800",
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}
