"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, createContext, useContext, type ReactNode } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Home,
  Plus,
  Settings,
  User,
  Shield,
  Circle,
  CheckCircle2,
  XCircle,
  Clock,
  Dices,
  FolderOpen,
} from "lucide-react";
import { cn } from "../lib/cn";

// ─── Context ───────────────────────────────────────────────────────────────
interface SidebarContextValue {
  collapsed: boolean;
  toggle: () => void;
}
const SidebarContext = createContext<SidebarContextValue>({ collapsed: false, toggle: () => {} });
export function useSidebar() { return useContext(SidebarContext); }

// ─── Types ─────────────────────────────────────────────────────────────────
export interface NavJob {
  id: string;
  topic: string;
  status: "running" | "planning" | "verifying" | "synthesizing" | "completed" | "failed" | "cancelled";
}

interface SidebarProps {
  recentJobs?: NavJob[];
  isAdmin?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
}

// ─── Status dot ────────────────────────────────────────────────────────────
function StatusDot({ status }: { status: NavJob["status"] }) {
  const isActive = ["running", "planning", "verifying", "synthesizing"].includes(status);
  const isFailed = status === "failed";
  const isCompleted = status === "completed";

  if (isActive) {
    return (
      <span className="relative inline-flex h-2 w-2 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
    );
  }
  if (isFailed) return <XCircle className="h-3 w-3 shrink-0 text-rose-500" />;
  if (isCompleted) return <CheckCircle2 className="h-3 w-3 shrink-0 text-[color:var(--accent)]" />;
  return <Circle className="h-3 w-3 shrink-0 text-[color:var(--muted)]" />;
}

// ─── Nav Item ──────────────────────────────────────────────────────────────
interface NavItemProps {
  href: string;
  icon: ReactNode;
  label: string;
  collapsed: boolean;
  exact?: boolean;
}
function NavItem({ href, icon, label, collapsed, exact }: NavItemProps) {
  const pathname = usePathname();
  const isActive = exact ? pathname === href : (pathname === href || pathname.startsWith(`${href}/`));

  return (
    <Link
      href={href}
      title={collapsed ? label : undefined}
      className={cn(
        "group relative flex items-center gap-3 rounded-[14px] px-3 py-2.5 text-sm transition-all duration-150",
        "hover:bg-[rgba(29,76,116,0.08)] hover:text-[color:var(--ink)]",
        isActive
          ? "border-l-[3px] border-[color:var(--accent)] bg-[linear-gradient(135deg,rgba(29,76,116,0.12),rgba(29,76,116,0.04))] pl-[calc(0.75rem-3px)] font-semibold text-[color:var(--ink)]"
          : "border-l-[3px] border-transparent text-[color:var(--muted-strong)]",
        collapsed && "justify-center px-0 pl-0 border-l-0",
      )}
    >
      <span className={cn("shrink-0", isActive ? "text-[color:var(--accent)]" : "text-[color:var(--muted)]")}>
        {icon}
      </span>
      {!collapsed && <span className="truncate">{label}</span>}
      {/* Tooltip when collapsed */}
      {collapsed && (
        <span className="pointer-events-none absolute left-full ml-3 hidden whitespace-nowrap rounded-[10px] border border-[color:var(--border-soft)] bg-[color:var(--panel-strong)] px-2.5 py-1.5 text-xs text-[color:var(--ink)] shadow-[var(--shadow-md)] group-hover:block">
          {label}
        </span>
      )}
    </Link>
  );
}

// ─── Sidebar Root ──────────────────────────────────────────────────────────
export function Sidebar({ recentJobs = [], isAdmin = false, onCollapsedChange }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    onCollapsedChange?.(next);
  };

  const pathname = usePathname();

  return (
    <SidebarContext.Provider value={{ collapsed, toggle }}>
      <aside
        className={cn(
          "relative flex h-full flex-col border-r border-[color:var(--border-soft)] bg-[rgba(249,244,235,0.9)] backdrop-blur-xl transition-[width] duration-200",
          collapsed ? "w-[var(--sidebar-collapsed-w)]" : "w-[var(--sidebar-w)]",
        )}
        style={{ "--sidebar-collapsed-w": "64px", "--sidebar-w": "228px" } as React.CSSProperties}
      >
        {/* Logo区 */}
        <div className={cn(
          "flex h-[var(--topbar-h)] shrink-0 items-center border-b border-[color:var(--border-soft)] px-4",
          collapsed && "justify-center px-0",
        )}
          style={{ "--topbar-h": "52px" } as React.CSSProperties}
        >
          {!collapsed && (
            <Link href="/" className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[10px] bg-[linear-gradient(135deg,rgba(29,76,116,1),rgba(23,32,51,0.92))]">
                <span className="text-xs font-bold text-white">PM</span>
              </div>
              <span className="text-sm font-semibold tracking-[-0.03em] text-[color:var(--ink)]">研究工作台</span>
            </Link>
          )}
          {collapsed && (
            <div className="flex h-7 w-7 items-center justify-center rounded-[10px] bg-[linear-gradient(135deg,rgba(29,76,116,1),rgba(23,32,51,0.92))]">
              <span className="text-xs font-bold text-white">PM</span>
            </div>
          )}
        </div>

        {/* 主导航 */}
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          <div className="space-y-0.5">
            <NavItem href="/" icon={<Home className="h-4 w-4" />} label="研究首页" collapsed={collapsed} exact />
            <NavItem href="/research/new" icon={<Plus className="h-4 w-4" />} label="新建研究" collapsed={collapsed} />
          </div>

          <div className="mt-4">
            {!collapsed && (
              <p className="mb-1.5 px-3 text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
                设计工具
              </p>
            )}
            {collapsed && <div className="mb-1.5 h-px bg-[color:var(--border-soft)]" />}
            <div className="space-y-0.5">
              <NavItem href="/design/trend" icon={<Dices className="h-4 w-4" />} label="设计趋势" collapsed={collapsed} />
              <NavItem href="/design/materials" icon={<FolderOpen className="h-4 w-4" />} label="素材库" collapsed={collapsed} />
            </div>
          </div>

          {/* 最近研究 */}
          {recentJobs.length > 0 && (
            <div className="mt-4">
              {!collapsed && (
                <p className="mb-1.5 px-3 text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
                  最近研究
                </p>
              )}
              {collapsed && <div className="mb-1.5 h-px bg-[color:var(--border-soft)]" />}
              <div className="space-y-0.5">
                {recentJobs.slice(0, 5).map((job) => {
                  const isActive = pathname.startsWith(`/research/jobs/${job.id}`);
                  return (
                    <Link
                      key={job.id}
                      href={`/research/jobs/${job.id}`}
                      title={collapsed ? job.topic : undefined}
                      className={cn(
                        "group relative flex items-center gap-2.5 rounded-[12px] px-3 py-2 text-xs transition-all duration-150",
                        "hover:bg-[rgba(29,76,116,0.08)]",
                        isActive
                          ? "border-l-[3px] border-[color:var(--accent)] bg-[rgba(29,76,116,0.08)] pl-[calc(0.75rem-3px)] font-medium text-[color:var(--ink)]"
                          : "border-l-[3px] border-transparent text-[color:var(--muted)]",
                        collapsed && "justify-center border-l-0 px-0 pl-0",
                      )}
                    >
                      <StatusDot status={job.status} />
                      {!collapsed && <span className="truncate">{job.topic}</span>}
                      {collapsed && (
                        <span className="pointer-events-none absolute left-full ml-3 hidden max-w-[180px] whitespace-normal rounded-[10px] border border-[color:var(--border-soft)] bg-[color:var(--panel-strong)] px-2.5 py-1.5 text-xs leading-5 text-[color:var(--ink)] shadow-[var(--shadow-md)] group-hover:block">
                          {job.topic}
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          )}

          {/* 设置区 */}
          <div className={cn("mt-4", !collapsed && "border-t border-[color:var(--border-soft)] pt-4")}>
            {!collapsed && (
              <p className="mb-1.5 px-3 text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
                设置
              </p>
            )}
            {collapsed && <div className="mb-1.5 h-px bg-[color:var(--border-soft)]" />}
            <div className="space-y-0.5">
              <NavItem href="/settings/runtime" icon={<Settings className="h-4 w-4" />} label="服务设置" collapsed={collapsed} />
              <NavItem href="/settings/account" icon={<User className="h-4 w-4" />} label="账号设置" collapsed={collapsed} />
              {isAdmin && (
                <NavItem href="/settings/admin" icon={<Shield className="h-4 w-4" />} label="管理设置" collapsed={collapsed} />
              )}
            </div>
          </div>
        </nav>

        {/* 折叠按钮 */}
        <div className="shrink-0 border-t border-[color:var(--border-soft)] p-2">
          <button
            onClick={toggle}
            type="button"
            className={cn(
              "flex w-full items-center gap-2 rounded-[12px] px-3 py-2 text-xs text-[color:var(--muted)] transition hover:bg-[rgba(29,76,116,0.08)] hover:text-[color:var(--ink)]",
              collapsed && "justify-center px-0",
            )}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : (
              <>
                <ChevronLeft className="h-4 w-4" />
                <span>收起</span>
              </>
            )}
          </button>
        </div>
      </aside>
    </SidebarContext.Provider>
  );
}
