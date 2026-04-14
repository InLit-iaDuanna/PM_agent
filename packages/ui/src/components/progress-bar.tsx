import type { HTMLAttributes } from "react";

import { cn } from "../lib/cn";

export function ProgressBar({
  value,
  "aria-label": ariaLabel,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & { value: number }) {
  const normalizedValue = Math.max(0, Math.min(100, value));
  return (
    <div
      aria-label={ariaLabel ?? "Progress"}
      aria-valuemax={100}
      aria-valuemin={0}
      aria-valuenow={normalizedValue}
      className={cn("h-2.5 w-full overflow-hidden rounded-full bg-[rgba(23,32,51,0.08)]", className)}
      role="progressbar"
      {...props}
    >
      <div
        className="h-full rounded-full bg-[linear-gradient(90deg,_rgba(29,76,116,1),_rgba(197,129,32,0.86))] transition-all"
        style={{ width: `${normalizedValue}%` }}
      />
    </div>
  );
}
