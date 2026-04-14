import type { TextareaHTMLAttributes } from "react";

import { cn } from "../lib/cn";

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-28 w-full rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,252,247,0.86)] px-3.5 py-3 text-sm text-[color:var(--ink)] outline-none placeholder:text-[color:var(--muted)] focus:border-[color:var(--accent)] focus:bg-white focus:shadow-[0_0_0_4px_rgba(29,76,116,0.08)]",
        className,
      )}
      {...props}
    />
  );
}
