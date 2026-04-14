"use client";

import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from "lucide-react";
import { cn } from "../lib/cn";

// ─── Types ─────────────────────────────────────────────────────────────────
type ToastTone = "success" | "danger" | "warning" | "info";

interface ToastItem {
  id: string;
  message: string;
  tone?: ToastTone;
  duration?: number;
}

// ─── Context ───────────────────────────────────────────────────────────────
interface ToastContextValue {
  toast: (message: string, opts?: { tone?: ToastTone; duration?: number }) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  warn: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}

// ─── Single Toast Item ─────────────────────────────────────────────────────
function ToastItemView({ item, onDismiss }: { item: ToastItem; onDismiss: (id: string) => void }) {
  const tone = item.tone ?? "info";

  const icons: Record<ToastTone, ReactNode> = {
    success: <CheckCircle2 className="h-4 w-4 text-emerald-600" />,
    danger:  <XCircle className="h-4 w-4 text-rose-600" />,
    warning: <AlertTriangle className="h-4 w-4 text-amber-600" />,
    info:    <Info className="h-4 w-4 text-[color:var(--accent)]" />,
  };

  const toneClasses: Record<ToastTone, string> = {
    success: "border-emerald-200 bg-emerald-50/95",
    danger:  "border-rose-200 bg-rose-50/95",
    warning: "border-amber-200 bg-amber-50/95",
    info:    "border-[color:var(--border-soft)] bg-[color:var(--panel-strong)]",
  };

  const textClasses: Record<ToastTone, string> = {
    success: "text-emerald-900",
    danger:  "text-rose-900",
    warning: "text-amber-900",
    info:    "text-[color:var(--ink)]",
  };

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-[16px] border px-4 py-3 shadow-[var(--shadow-lg)]",
        "animate-fade-up backdrop-blur-xl",
        toneClasses[tone],
      )}
      role="alert"
    >
      <span className="mt-0.5 shrink-0">{icons[tone]}</span>
      <p className={cn("flex-1 text-sm leading-6", textClasses[tone])}>{item.message}</p>
      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        className="shrink-0 rounded-[8px] p-1 text-[color:var(--muted)] transition hover:bg-black/10"
        aria-label="关闭通知"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ─── Provider ──────────────────────────────────────────────────────────────
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, opts: { tone?: ToastTone; duration?: number } = {}) => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const duration = opts.duration ?? 4000;
      setItems((prev) => [...prev, { id, message, tone: opts.tone, duration }]);
      if (duration > 0) {
        setTimeout(() => dismiss(id), duration);
      }
    },
    [dismiss],
  );

  const success = useCallback((message: string) => toast(message, { tone: "success" }), [toast]);
  const error   = useCallback((message: string) => toast(message, { tone: "danger" }), [toast]);
  const warn    = useCallback((message: string) => toast(message, { tone: "warning" }), [toast]);

  return (
    <ToastContext.Provider value={{ toast, success, error, warn }}>
      {children}
      {/* Portal */}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-6 right-6 z-[9999] flex w-full max-w-sm flex-col gap-2"
      >
        {items.map((item) => (
          <div key={item.id} className="pointer-events-auto">
            <ToastItemView item={item} onDismiss={dismiss} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
