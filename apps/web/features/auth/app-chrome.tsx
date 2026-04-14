"use client";

import { PropsWithChildren, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { Badge, Button, Card } from "@pm-agent/ui";

import { useAuth } from "./auth-provider";
import { ShellLayout } from "../shell/shell-layout";

function LoadingScreen({ label = "正在校验登录状态..." }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="space-y-3 text-center">
        <p className="text-xs uppercase tracking-[0.28em] text-[color:var(--muted)]">PM Research Agent</p>
        <p className="text-base text-[color:var(--ink)]">{label}</p>
      </div>
    </div>
  );
}

function currentSearchString() {
  if (typeof window === "undefined") return "";
  return window.location.search.replace(/^\?/, "");
}

function currentNextPath() {
  if (typeof window === "undefined") return "/";
  return sanitizeNextPath(new URLSearchParams(window.location.search).get("next"));
}

function buildNextPath(pathname: string, query: string) {
  return query ? `${pathname}?${query}` : pathname;
}

function sanitizeNextPath(nextPath: string | null | undefined) {
  const normalized = String(nextPath || "").trim();
  if (!normalized.startsWith("/") || normalized.startsWith("//")) return "/";
  try {
    const parsed = new URL(normalized, "http://pm-agent.local");
    const safePath = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    return safePath.startsWith("/") ? safePath : "/";
  } catch {
    return "/";
  }
}

/**
 * AppChrome — 重构后的应用外壳
 *
 * 变化：
 * - 原来的巨型 sticky header（品牌名+描述+nav pills+账号信息）已移除
 * - 改为 ShellLayout（侧边栏 + TopBar + StatusBar 的三栏工作台）
 * - 登录态、错误态、加载态逻辑保持不变
 */
export function AppChrome({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const router = useRouter();
  const auth = useAuth();
  const isLoginRoute = pathname === "/login";

  useEffect(() => {
    if (auth.status === "loading") return;
    if (auth.status === "authenticated" && isLoginRoute) {
      router.replace(currentNextPath());
      return;
    }
    if (auth.status === "anonymous" && !isLoginRoute) {
      router.replace(`/login?next=${encodeURIComponent(buildNextPath(pathname, currentSearchString()))}`);
    }
  }, [auth.status, isLoginRoute, pathname, router]);

  // ── 加载中 ──
  if (auth.status === "loading") {
    return <LoadingScreen />;
  }

  // ── 登录页 ──
  if (isLoginRoute) {
    if (auth.status === "authenticated") {
      return <LoadingScreen label="正在进入工作台..." />;
    }
    return (
      <main className="min-h-screen px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    );
  }

  // ── 连接错误 ──
  if (auth.status === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-xl space-y-4">
          <div className="space-y-2">
            <Badge tone="warning">连接异常</Badge>
            <h1 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">
              暂时无法确认登录状态
            </h1>
            <p className="text-sm leading-6 text-[color:var(--muted)]">
              {auth.errorMessage || "请检查 API 是否已启动。"}
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => void auth.refresh()} type="button">
              重新检查
            </Button>
            <Button onClick={() => router.replace("/login")} type="button" variant="secondary">
              前往登录页
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  // ── 未登录（跳转中）──
  if (auth.status !== "authenticated" || !auth.user) {
    return <LoadingScreen label="正在跳转到登录页..." />;
  }

  // ── 已登录：三栏工作台 ──
  return <ShellLayout>{children}</ShellLayout>;
}
