"use client";

import { FormEvent, useEffect, useState } from "react";

import { useQuery } from "@tanstack/react-query";
import { Badge, Button, Card, CardDescription, CardTitle, Input, Label } from "@pm-agent/ui";

import { fetchAuthPublicConfig, getApiErrorMessage } from "../../lib/api-client";
import { ApiSwitcher } from "../research/components/api-switcher";
import { useAuth } from "./auth-provider";

type AuthMode = "login" | "register";

export function LoginPage() {
  const auth = useAuth();
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [nextPath, setNextPath] = useState("/");
  const authConfigQuery = useQuery({
    queryKey: ["auth", "public-config"],
    queryFn: fetchAuthPublicConfig,
    staleTime: 30_000,
    retry: false,
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    setNextPath(new URLSearchParams(window.location.search).get("next") || "/");
  }, []);

  const registrationEnabled = authConfigQuery.data?.registration_enabled ?? true;
  const inviteCodeRequired = authConfigQuery.data?.invite_code_required ?? false;
  const firstUserWillBeAdmin = authConfigQuery.data?.first_user_will_be_admin ?? false;
  const registrationMode = authConfigQuery.data?.registration_mode ?? "open";
  const [inviteCode, setInviteCode] = useState("");

  useEffect(() => {
    if (!registrationEnabled && mode === "register") {
      setMode("login");
    }
  }, [mode, registrationEnabled]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedEmail = email.trim();
    if (!normalizedEmail) {
      setErrorMessage("请输入邮箱地址。");
      return;
    }
    if (password.length < 8) {
      setErrorMessage("密码至少需要 8 位。");
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    try {
      if (mode === "register") {
        await auth.signUp({
          email: normalizedEmail,
          password,
          display_name: displayName.trim() || undefined,
          invite_code: inviteCodeRequired ? inviteCode.trim() || undefined : undefined,
        });
      } else {
        await auth.signIn({
          email: normalizedEmail,
          password,
        });
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "登录失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto grid min-h-[calc(100vh-4rem)] max-w-5xl items-start gap-6 py-2 xl:min-h-[calc(100vh-5rem)] xl:grid-cols-[1fr_0.96fr] xl:items-center xl:gap-10">
      <div className="space-y-5">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="success">账号登录</Badge>
            {firstUserWillBeAdmin ? <Badge>首个账号将成为管理员</Badge> : null}
            {registrationMode === "invite_only" ? <Badge tone="warning">当前为邀请码注册</Badge> : null}
            {registrationMode === "closed" ? <Badge tone="warning">已关闭公开注册</Badge> : null}
          </div>
          <h1 className="max-w-2xl text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)] leading-[1.15] sm:text-[2rem] xl:text-[2.35rem]">
            把研究任务、报告和 PM 对话放进你自己的工作空间。
          </h1>
          <p className="max-w-xl text-sm leading-7 text-[color:var(--muted)] sm:text-[15px]">
            登录后，研究任务、聊天会话和模型配置会按账号隔离。部署到服务器后，也能直接用 Cookie 会话保持登录。
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <Card className="space-y-1.5 rounded-[26px] p-4 sm:p-5">
            <p className="text-sm font-semibold text-[color:var(--ink)]">研究记录隔离</p>
            <p className="text-sm leading-6 text-[color:var(--muted)]">每个账号只会看到自己的研究任务、报告版本和 PM Chat 记录。</p>
          </Card>
          <Card className="space-y-1.5 rounded-[26px] p-4 sm:p-5">
            <p className="text-sm font-semibold text-[color:var(--ink)]">运行时配置隔离</p>
            <p className="text-sm leading-6 text-[color:var(--muted)]">不同账号可以保存不同的模型地址、Key 和超时设置，互不覆盖。</p>
          </Card>
        </div>
      </div>

      <div className="max-w-xl space-y-3 xl:max-w-none">
        <Card className="space-y-4 rounded-[28px] p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{mode === "login" || !registrationEnabled ? "登录工作台" : "创建账号"}</CardTitle>
              <CardDescription>
                {mode === "login" || !registrationEnabled
                  ? "继续你之前的研究任务和 PM 对话。"
                  : "创建一个新账号，立刻进入自己的研究空间。"}
              </CardDescription>
            </div>
            <Badge>{nextPath === "/" ? "登录后进入首页" : "登录后返回原页面"}</Badge>
          </div>

          <div className="inline-flex rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.58)] p-1">
            <button
              className={`rounded-2xl px-3.5 py-2 text-xs transition sm:px-4 sm:text-sm ${
                mode === "login"
                  ? "bg-[color:var(--accent)] text-white shadow-[0_10px_24px_rgba(29,76,116,0.18)]"
                  : "text-[color:var(--muted)]"
              }`}
              onClick={() => {
                setMode("login");
                setErrorMessage(null);
              }}
              type="button"
            >
              登录
            </button>
            {registrationEnabled ? (
              <button
                className={`rounded-2xl px-3.5 py-2 text-xs transition sm:px-4 sm:text-sm ${
                  mode === "register"
                    ? "bg-[color:var(--accent)] text-white shadow-[0_10px_24px_rgba(29,76,116,0.18)]"
                    : "text-[color:var(--muted)]"
                }`}
                onClick={() => {
                  setMode("register");
                  setErrorMessage(null);
                }}
                type="button"
              >
                注册
              </button>
            ) : null}
          </div>

          <form className="space-y-3.5" onSubmit={onSubmit}>
            {mode === "register" && registrationEnabled ? (
              <div>
                <Label htmlFor="display-name">昵称</Label>
                <Input
                  id="display-name"
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="例如：产品研究组"
                  value={displayName}
                />
              </div>
            ) : null}

            {mode === "register" && inviteCodeRequired ? (
              <div className="space-y-1.5">
                <Label htmlFor="invite-code">邀请码</Label>
                <Input
                  id="invite-code"
                  onChange={(event) => setInviteCode(event.target.value)}
                  placeholder="请输入管理员发给你的邀请码"
                  value={inviteCode}
                />
                <p className="text-xs leading-5 text-[color:var(--muted)]">
                  当前站点仅支持邀请码注册。如果你现在已经登录了其他账号，请先退出登录，或改用无痕窗口测试注册。
                </p>
              </div>
            ) : null}

            <div>
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                onChange={(event) => setEmail(event.target.value)}
                placeholder="name@company.com"
                type="email"
                value={email}
              />
            </div>

            <div>
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                onChange={(event) => setPassword(event.target.value)}
                placeholder="至少 8 位"
                type="password"
                value={password}
              />
            </div>

            {authConfigQuery.error ? <p className="text-sm text-red-600">{getApiErrorMessage(authConfigQuery.error, "注册策略读取失败。")}</p> : null}
            {errorMessage ? <p className="text-sm text-red-600">{errorMessage}</p> : null}
            {!registrationEnabled ? <p className="text-sm text-[color:var(--muted)]">当前已关闭公开注册，如需新账号请联系管理员。</p> : null}

            <Button className="w-full sm:w-auto" disabled={submitting} type="submit">
              {submitting ? "提交中..." : mode === "login" || !registrationEnabled ? "登录" : "注册并进入"}
            </Button>
          </form>
        </Card>

        <ApiSwitcher />
      </div>
    </div>
  );
}
