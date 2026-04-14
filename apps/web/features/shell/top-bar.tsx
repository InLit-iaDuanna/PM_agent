"use client";

import Link from "next/link";
import { useState } from "react";
import { Search, Wifi, WifiOff, LogOut, User, Settings, ChevronDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@pm-agent/ui";
import { useAuth } from "../auth/auth-provider";
import { fetchHealthStatus } from "../../lib/api-client";
import { getApiBaseUrl } from "../../lib/api-base-url";

interface TopBarProps {
  onSearchOpen?: () => void;
}

function shortHost(url: string) {
  try {
    const p = new URL(url);
    return `${p.hostname}${p.port ? `:${p.port}` : ""}`;
  } catch {
    return url;
  }
}

export function TopBar({ onSearchOpen }: TopBarProps) {
  const auth = useAuth();
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const healthQuery = useQuery({
    queryKey: ["api-health"],
    queryFn: fetchHealthStatus,
    refetchInterval: 8000,
    staleTime: 5000,
  });

  const isOnline = !healthQuery.error && !!healthQuery.data;
  const currentUrl = getApiBaseUrl();

  return (
    <header
      className="sticky top-0 z-40 flex h-[52px] shrink-0 items-center gap-3 border-b border-[color:var(--border-soft)] bg-[rgba(246,241,232,0.88)] px-4 backdrop-blur-xl"
    >
      {/* Search trigger */}
      <button
        type="button"
        onClick={onSearchOpen}
        className="flex flex-1 max-w-xs items-center gap-2 rounded-[12px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-3 py-1.5 text-sm text-[color:var(--muted)] transition hover:border-[color:var(--border-strong)] hover:bg-white"
        aria-label="搜索研究、任务、报告"
      >
        <Search className="h-3.5 w-3.5 shrink-0" />
        <span className="flex-1 text-left text-xs">搜索研究、任务...</span>
        <kbd className="hidden rounded-[6px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.7)] px-1.5 py-0.5 text-[10px] text-[color:var(--muted)] sm:inline">
          ⌘K
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-3">
        {/* API 连接状态 */}
        <div className="hidden items-center gap-2 sm:flex">
          {isOnline ? (
            <Wifi className="h-3.5 w-3.5 text-emerald-600" />
          ) : (
            <WifiOff className="h-3.5 w-3.5 text-rose-500" />
          )}
          <span className="text-xs text-[color:var(--muted)]">{shortHost(currentUrl)}</span>
        </div>

        {/* 活跃任务数 */}
        {healthQuery.data && healthQuery.data.active_job_count > 0 && (
          <Badge tone="success" className="hidden sm:inline-flex">
            {`${healthQuery.data.active_job_count} 研究中`}
          </Badge>
        )}

        {/* 用户菜单 */}
        {auth.user && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setUserMenuOpen((v) => !v)}
              className="flex items-center gap-2 rounded-[12px] border border-transparent px-2.5 py-1.5 text-sm text-[color:var(--muted-strong)] transition hover:border-[color:var(--border-soft)] hover:bg-[rgba(255,255,255,0.56)] hover:text-[color:var(--ink)]"
            >
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[rgba(29,76,116,0.15)] text-[10px] font-bold uppercase text-[color:var(--accent)]">
                {(auth.user.display_name || auth.user.email).slice(0, 1)}
              </div>
              <span className="hidden max-w-[120px] truncate text-xs sm:block">
                {auth.user.display_name || auth.user.email}
              </span>
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${userMenuOpen ? "rotate-180" : ""}`} />
            </button>

            {userMenuOpen && (
              <>
                {/* 点击外部关闭 */}
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setUserMenuOpen(false)}
                  aria-hidden
                />
                <div className="absolute right-0 top-full z-20 mt-2 w-48 rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(250,246,240,0.98)] p-1.5 shadow-[var(--shadow-xl)] backdrop-blur-xl">
                  <div className="border-b border-[color:var(--border-soft)] px-3 pb-2 pt-1.5">
                    <p className="truncate text-xs font-semibold text-[color:var(--ink)]">
                      {auth.user.display_name || auth.user.email}
                    </p>
                    <p className="text-[11px] text-[color:var(--muted)]">
                      {auth.user.role === "admin" ? "管理员" : "成员"}
                    </p>
                  </div>
                  <Link
                    href="/settings/account"
                    onClick={() => setUserMenuOpen(false)}
                    className="flex items-center gap-2 rounded-[10px] px-3 py-2 text-sm text-[color:var(--muted-strong)] transition hover:bg-[rgba(29,76,116,0.08)] hover:text-[color:var(--ink)]"
                  >
                    <User className="h-3.5 w-3.5" />
                    账号设置
                  </Link>
                  <Link
                    href="/settings/runtime"
                    onClick={() => setUserMenuOpen(false)}
                    className="flex items-center gap-2 rounded-[10px] px-3 py-2 text-sm text-[color:var(--muted-strong)] transition hover:bg-[rgba(29,76,116,0.08)] hover:text-[color:var(--ink)]"
                  >
                    <Settings className="h-3.5 w-3.5" />
                    服务设置
                  </Link>
                  <div className="mt-1 border-t border-[color:var(--border-soft)] pt-1">
                    <button
                      type="button"
                      onClick={() => { setUserMenuOpen(false); void auth.signOut(); }}
                      className="flex w-full items-center gap-2 rounded-[10px] px-3 py-2 text-sm text-rose-600 transition hover:bg-rose-50"
                    >
                      <LogOut className="h-3.5 w-3.5" />
                      退出登录
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
