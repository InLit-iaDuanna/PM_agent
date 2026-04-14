"use client";

import Link from "next/link";
import { PropsWithChildren, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { Badge, Button, Card } from "@pm-agent/ui";

import { ApiSwitcher } from "../research/components/api-switcher";
import { AppShellNav } from "../research/components/app-shell-nav";
import { useAuth } from "./auth-provider";

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
  if (typeof window === "undefined") {
    return "";
  }
  return window.location.search.replace(/^\?/, "");
}

function currentNextPath() {
  if (typeof window === "undefined") {
    return "/";
  }
  return sanitizeNextPath(new URLSearchParams(window.location.search).get("next"));
}

function buildNextPath(pathname: string, query: string) {
  return query ? `${pathname}?${query}` : pathname;
}

function sanitizeNextPath(nextPath: string | null | undefined) {
  const normalized = String(nextPath || "").trim();
  if (!normalized.startsWith("/") || normalized.startsWith("//")) {
    return "/";
  }
  try {
    const parsed = new URL(normalized, "http://pm-agent.local");
    const safePath = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    return safePath.startsWith("/") ? safePath : "/";
  } catch {
    return "/";
  }
}

export function AppChrome({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const router = useRouter();
  const auth = useAuth();
  const isLoginRoute = pathname === "/login";

  useEffect(() => {
    if (auth.status === "loading") {
      return;
    }
    if (auth.status === "authenticated" && isLoginRoute) {
      router.replace(currentNextPath());
      return;
    }
    if (auth.status === "anonymous" && !isLoginRoute) {
      router.replace(`/login?next=${encodeURIComponent(buildNextPath(pathname, currentSearchString()))}`);
    }
  }, [auth.status, isLoginRoute, pathname, router]);

  if (auth.status === "loading") {
    return <LoadingScreen />;
  }

  if (isLoginRoute) {
    if (auth.status === "authenticated") {
      return <LoadingScreen label="正在进入工作台..." />;
    }
    return <main className="min-h-screen px-4 py-6 sm:px-6 sm:py-8">{children}</main>;
  }

  if (auth.status === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-xl space-y-4">
          <div className="space-y-2">
            <Badge tone="warning">连接异常</Badge>
            <h1 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">暂时无法确认登录状态</h1>
            <p className="text-sm leading-6 text-[color:var(--muted)]">{auth.errorMessage || "请检查 API 是否已启动。"}</p>
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

  if (auth.status !== "authenticated" || !auth.user) {
    return <LoadingScreen label="正在跳转到登录页..." />;
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-[color:var(--border-soft)] bg-[rgba(246,241,232,0.84)] backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-5 px-4 py-5 sm:px-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-4">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-full border border-[color:var(--border-strong)] bg-[rgba(255,250,242,0.74)] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.3em] text-[color:var(--muted-strong)]">
                  研究总览
                </span>
                <span className="inline-flex items-center rounded-full border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] px-3 py-1 text-xs text-[color:var(--muted)]">
                  任务 · 证据 · 报告 · 对话
                </span>
              </div>
              <div>
                <h1 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)] sm:text-3xl">
                  <Link href="/">PM 研究工作台</Link>
                </h1>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-[color:var(--muted)] sm:text-[15px]">
                  在同一套界面里管理研究任务、执行进度、证据、报告版本和后续追问，减少在多个页面之间来回切换。
                </p>
              </div>
            </div>
            <AppShellNav />
          </div>
          <div className="grid w-full gap-3 lg:max-w-[420px]">
            <div className="rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.62)] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.64)]">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">当前账号</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-base font-semibold text-[color:var(--ink)]">
                      {auth.user.display_name || auth.user.email}
                    </p>
                    <Badge tone={auth.user.role === "admin" ? "success" : "default"}>
                      {auth.user.role === "admin" ? "管理员" : "成员"}
                    </Badge>
                  </div>
                  <p className="truncate text-sm text-[color:var(--muted)]">{auth.user.email}</p>
                </div>
                <div className="flex flex-col gap-2">
                  <Button asChild type="button" variant="ghost">
                    <Link href="/settings/account">账号设置</Link>
                  </Button>
                  <Button onClick={() => void auth.signOut()} type="button" variant="secondary">
                    退出
                  </Button>
                </div>
              </div>
            </div>
            <ApiSwitcher />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:py-10">{children}</main>
    </div>
  );
}
