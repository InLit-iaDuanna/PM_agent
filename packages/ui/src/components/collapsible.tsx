"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../lib/cn";

interface CollapsibleProps {
  trigger: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  contentClassName?: string;
  /** 外部控制 open 状态 */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/**
 * Collapsible — 折叠面板
 *
 * 用法（非受控）：
 *   <Collapsible trigger="高级参数" defaultOpen={false}>
 *     内容...
 *   </Collapsible>
 *
 * 用法（受控）：
 *   <Collapsible trigger="详情" open={isOpen} onOpenChange={setIsOpen}>
 *     内容...
 *   </Collapsible>
 */
export function Collapsible({
  trigger,
  children,
  defaultOpen = false,
  className,
  contentClassName,
  open: controlledOpen,
  onOpenChange,
}: CollapsibleProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : internalOpen;

  const toggle = () => {
    if (isControlled) {
      onOpenChange?.(!isOpen);
    } else {
      setInternalOpen((prev) => !prev);
    }
  };

  return (
    <div className={cn("rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.48)]", className)}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={isOpen}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left text-sm font-medium text-[color:var(--ink)] transition hover:bg-[rgba(29,76,116,0.04)] rounded-[20px]"
      >
        <span className="flex-1">{trigger}</span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-[color:var(--muted)] transition-transform duration-200",
            isOpen && "rotate-180",
          )}
        />
      </button>

      {isOpen && (
        <div
          className={cn(
            "border-t border-[color:var(--border-soft)] px-5 pb-5 pt-4 animate-fade-in",
            contentClassName,
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

/** CollapsibleSection — 设置页用的大折叠区，带标题+描述 */
export function CollapsibleSection({
  title,
  description,
  children,
  defaultOpen = true,
  className,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={cn("glass-panel rounded-[30px] overflow-hidden", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start justify-between gap-4 p-5 text-left transition hover:bg-[rgba(29,76,116,0.03)] sm:p-6"
      >
        <div>
          <h3 className="text-base font-semibold tracking-[-0.03em] text-[color:var(--ink)]">{title}</h3>
          {description && (
            <p className="mt-1 text-sm leading-6 text-[color:var(--muted)]">{description}</p>
          )}
        </div>
        <ChevronDown
          className={cn(
            "mt-0.5 h-5 w-5 shrink-0 text-[color:var(--muted)] transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="border-t border-[color:var(--border-soft)] p-5 pt-5 sm:p-6 animate-fade-in">
          {children}
        </div>
      )}
    </div>
  );
}
