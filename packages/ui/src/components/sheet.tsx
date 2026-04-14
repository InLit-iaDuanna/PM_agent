"use client";

import { useEffect, useRef, type ReactNode, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import { cn } from "../lib/cn";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  description?: string;
  children: ReactNode;
  /** Width of the panel, default "520px" */
  width?: string;
  /** Extra className for the panel */
  className?: string;
}

/**
 * Sheet — 从右侧滑入的面板
 * 用于 task-detail、evidence 详情、来源索引等场景
 */
export function Sheet({ open, onClose, title, description, children, width = "520px", className }: SheetProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Escape 关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent | Event) => {
      if ((e as KeyboardEvent).key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler as EventListener);
    return () => document.removeEventListener("keydown", handler as EventListener);
  }, [open, onClose]);

  // 锁定 body 滚动
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Overlay */}
      <div
        className="sheet-overlay absolute inset-0 bg-[rgba(23,32,51,0.24)] backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "sheet-panel absolute right-0 top-0 flex h-full flex-col",
          "border-l border-[color:var(--border-soft)] bg-[rgba(250,246,240,0.98)] backdrop-blur-xl",
          "shadow-[-24px_0_80px_rgba(23,32,51,0.12)]",
          className,
        )}
        style={{ width }}
      >
        {/* Header */}
        {(title || description) && (
          <div className="flex shrink-0 items-start justify-between gap-4 border-b border-[color:var(--border-soft)] px-6 py-5">
            <div className="min-w-0">
              {title && (
                <h2 className="text-base font-semibold tracking-[-0.03em] text-[color:var(--ink)]">{title}</h2>
              )}
              {description && (
                <p className="mt-1 text-sm text-[color:var(--muted)]">{description}</p>
              )}
            </div>
            <button
              onClick={onClose}
              type="button"
              aria-label="关闭"
              className="shrink-0 rounded-[10px] p-1.5 text-[color:var(--muted)] transition hover:bg-[rgba(29,76,116,0.1)] hover:text-[color:var(--ink)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {children}
        </div>
      </div>
    </div>
  );
}

/** useSheet — 管理 Sheet 开关状态的便捷 hook */
export function useSheet<T = undefined>() {
  const { useState } = require("react") as typeof import("react");
  const [state, setState] = useState<{ open: boolean; data: T | undefined }>({
    open: false,
    data: undefined,
  });
  return {
    isOpen: state.open,
    data: state.data,
    open: (data?: T) => setState({ open: true, data }),
    close: () => setState({ open: false, data: undefined }),
  };
}
