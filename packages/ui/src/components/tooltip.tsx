"use client";

import {
  useState,
  useRef,
  useEffect,
  type ReactNode,
  type CSSProperties,
} from "react";
import { cn } from "../lib/cn";

type TooltipPlacement = "top" | "bottom" | "left" | "right";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  placement?: TooltipPlacement;
  delay?: number;
  className?: string;
  disabled?: boolean;
}

/**
 * Tooltip — 悬停提示组件
 *
 * 用法：
 *   <Tooltip content="可引用的外部来源数量">
 *     <Badge>42 来源</Badge>
 *   </Tooltip>
 *
 * 纯 CSS + React state，无 Radix 依赖。
 */
export function Tooltip({
  content,
  children,
  placement = "top",
  delay = 300,
  className,
  disabled = false,
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapRef = useRef<HTMLSpanElement>(null);

  const show = () => {
    if (disabled) return;
    timerRef.current = setTimeout(() => setVisible(true), delay);
  };

  const hide = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setVisible(false);
  };

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  const positionStyle: CSSProperties = (() => {
    switch (placement) {
      case "bottom": return { top: "calc(100% + 8px)", left: "50%", transform: "translateX(-50%)" };
      case "left":   return { right: "calc(100% + 8px)", top: "50%",  transform: "translateY(-50%)" };
      case "right":  return { left: "calc(100% + 8px)",  top: "50%",  transform: "translateY(-50%)" };
      default:       return { bottom: "calc(100% + 8px)", left: "50%", transform: "translateX(-50%)" };
    }
  })();

  return (
    <span
      ref={wrapRef}
      className="relative inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}

      {visible && !disabled && (
        <span
          role="tooltip"
          style={positionStyle}
          className={cn(
            "pointer-events-none absolute z-50 w-max max-w-[220px] animate-fade-in",
            "rounded-[12px] border border-[color:var(--border-soft)]",
            "bg-[rgba(23,32,51,0.92)] px-3 py-2 text-xs leading-5 text-white",
            "shadow-[0_8px_24px_rgba(23,32,51,0.18)] backdrop-blur-sm",
            className,
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}
