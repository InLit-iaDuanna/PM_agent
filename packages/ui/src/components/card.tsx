import type { HTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../lib/cn";

export function Card({ children, className, ...props }: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div
      className={cn(
        "glass-panel rounded-[30px] p-5 shadow-[0_20px_45px_rgba(23,32,51,0.08)] sm:p-6",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children, className, ...props }: PropsWithChildren<HTMLAttributes<HTMLHeadingElement>>) {
  return (
    <h3 className={cn("text-base font-semibold tracking-[-0.03em] text-[color:var(--ink)]", className)} {...props}>
      {children}
    </h3>
  );
}

export function CardDescription({
  children,
  className,
  ...props
}: PropsWithChildren<HTMLAttributes<HTMLParagraphElement>>) {
  return (
    <p className={cn("text-sm leading-6 text-[color:var(--muted)]", className)} {...props}>
      {children}
    </p>
  );
}
