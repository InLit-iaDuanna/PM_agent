import type { LabelHTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../lib/cn";

export function Label({ children, className, ...props }: PropsWithChildren<LabelHTMLAttributes<HTMLLabelElement>>) {
  return (
    <label className={cn("mb-2 block text-sm font-medium text-slate-700", className)} {...props}>
      {children}
    </label>
  );
}

