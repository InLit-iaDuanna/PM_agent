"use client";

import { Wifi, WifiOff, Activity, Clock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { fetchHealthStatus } from "../../lib/api-client";
import { getApiBaseUrl } from "../../lib/api-base-url";

function shortHost(url: string) {
  try {
    const p = new URL(url);
    return `${p.hostname}${p.port ? `:${p.port}` : ""}`;
  } catch {
    return url;
  }
}

/**
 * StatusBar — 底部状态栏
 * 固定在 shell 底部，显示 API 连接、活跃任务数、后台进程数
 */
export function StatusBar() {
  const healthQuery = useQuery({
    queryKey: ["api-health"],
    queryFn: fetchHealthStatus,
    refetchInterval: 8000,
    staleTime: 5000,
  });

  const isOnline = !healthQuery.error && !!healthQuery.data;
  const host = shortHost(getApiBaseUrl());
  const data = healthQuery.data;

  return (
    <footer className="flex h-[26px] shrink-0 items-center gap-4 border-t border-[color:var(--border-soft)] bg-[rgba(243,237,226,0.7)] px-4 backdrop-blur-sm">
      {/* 连接状态 */}
      <div className="flex items-center gap-1.5">
        {isOnline ? (
          <Wifi className="h-3 w-3 text-emerald-600" />
        ) : (
          <WifiOff className="h-3 w-3 text-rose-500" />
        )}
        <span className="text-[11px] text-[color:var(--muted)]">
          {isOnline ? host : "连接断开"}
        </span>
      </div>

      {/* 活跃任务 */}
      {data && data.active_job_count > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
          </span>
          <span className="text-[11px] text-[color:var(--muted)]">
            {`${data.active_job_count} 个研究运行中`}
          </span>
        </div>
      )}

      {/* 后台进程 */}
      {data && data.active_detached_worker_count > 0 && (
        <div className="flex items-center gap-1.5">
          <Activity className="h-3 w-3 text-[color:var(--muted)]" />
          <span className="text-[11px] text-[color:var(--muted)]">
            {`${data.active_detached_worker_count} 后台`}
          </span>
        </div>
      )}

      {/* 右侧：模型状态 */}
      <div className="ml-auto flex items-center gap-1.5">
        {data?.runtime_configured === false && (
          <span className="text-[11px] text-amber-600">⚠ 模型未配置</span>
        )}
        {data?.runtime_configured && (
          <span className="text-[11px] text-[color:var(--muted)]">模型已就绪</span>
        )}
      </div>
    </footer>
  );
}
