import type { HTMLAttributes } from "react";
import { cn } from "../lib/cn";

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** 高度，默认 "1rem" */
  h?: string;
  /** 宽度，默认 "100%" */
  w?: string;
  /** 是否圆形（头像用） */
  circle?: boolean;
}

/**
 * Skeleton — 内容加载占位组件
 *
 * 用法：
 *   <Skeleton h="1.2rem" w="60%" />
 *   <Skeleton h="80px" w="80px" circle />
 */
export function Skeleton({ h = "1rem", w = "100%", circle = false, className, style, ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        "skeleton",
        circle ? "rounded-full" : "rounded-[10px]",
        className,
      )}
      style={{ height: h, width: w, ...style }}
      aria-hidden="true"
      {...props}
    />
  );
}

/** SkeletonCard — 卡片占位 */
export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="glass-panel rounded-[30px] p-5 space-y-3 sm:p-6">
      <Skeleton h="1rem" w="40%" />
      <Skeleton h="0.75rem" w="70%" />
      {Array.from({ length: lines - 2 }).map((_, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <Skeleton key={i} h="0.75rem" w={`${60 + Math.random() * 30}%`} />
      ))}
    </div>
  );
}

/** SkeletonJobRow — 研究任务行占位 */
export function SkeletonJobRow() {
  return (
    <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-4 py-4 space-y-2.5">
      <div className="flex items-center justify-between gap-3">
        <Skeleton h="0.875rem" w="55%" />
        <Skeleton h="1.4rem" w="60px" />
      </div>
      <Skeleton h="0.75rem" w="40%" />
      <Skeleton h="6px" w="100%" />
    </div>
  );
}

/** SkeletonText — 多行文本占位 */
export function SkeletonText({ lines = 4 }: { lines?: number }) {
  const widths = ["100%", "92%", "96%", "78%", "88%", "84%"];
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }).map((_, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <Skeleton key={i} h="0.875rem" w={widths[i % widths.length]} />
      ))}
    </div>
  );
}
