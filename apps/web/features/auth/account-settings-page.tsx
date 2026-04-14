"use client";

import { useState } from "react";

import { useQuery } from "@tanstack/react-query";
import { Badge, Button, Card, CardDescription, CardTitle, Input, Label } from "@pm-agent/ui";

import { fetchAuthPublicConfig, getApiErrorMessage } from "../../lib/api-client";
import { useAuth } from "./auth-provider";

export function AccountSettingsPage() {
  const auth = useAuth();
  const authConfigQuery = useQuery({
    queryKey: ["auth", "public-config"],
    queryFn: fetchAuthPublicConfig,
    staleTime: 30_000,
    retry: false,
  });
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirmEmail, setDeleteConfirmEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [deleteErrorMessage, setDeleteErrorMessage] = useState<string | null>(null);

  const handleChangePassword = async () => {
    if (newPassword.length < 8) {
      setErrorMessage("新密码至少需要 8 位。");
      return;
    }
    if (newPassword !== confirmPassword) {
      setErrorMessage("两次输入的新密码不一致。");
      return;
    }

    setSaving(true);
    setFeedback(null);
    setErrorMessage(null);
    try {
      await auth.updatePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setFeedback("密码已更新，其他旧会话也已失效。");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "密码更新失败。");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (deletePassword.length < 8) {
      setDeleteErrorMessage("请输入当前密码后再删除账号。");
      return;
    }
    if (deleteConfirmEmail.trim().toLowerCase() !== (auth.user?.email || "").trim().toLowerCase()) {
      setDeleteErrorMessage("请输入当前账号邮箱以确认删除。");
      return;
    }

    setDeleting(true);
    setDeleteErrorMessage(null);
    try {
      await auth.deleteAccount({
        current_password: deletePassword,
      });
    } catch (error) {
      setDeleteErrorMessage(error instanceof Error ? error.message : "账号删除失败。");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card className="space-y-5">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={auth.user?.role === "admin" ? "success" : "default"}>
                {auth.user?.role === "admin" ? "管理员" : "成员"}
              </Badge>
              <Badge>{auth.user?.email || "--"}</Badge>
            </div>
            <CardTitle>账号设置</CardTitle>
            <CardDescription>管理你的登录账号和密码。当前研究数据与运行时 API 配置都会按账号隔离保存。</CardDescription>
          </div>

          <div className="space-y-4 rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-5">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">显示名称</p>
              <p className="mt-2 text-lg font-semibold text-[color:var(--ink)]">{auth.user?.display_name || "未设置昵称"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">邮箱</p>
              <p className="mt-2 text-base text-[color:var(--ink)]">{auth.user?.email || "--"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">注册策略</p>
              <p className="mt-2 text-sm leading-6 text-[color:var(--muted)]">
                {authConfigQuery.data
                  ? authConfigQuery.data.registration_mode === "bootstrap"
                    ? "当前仍处于首个管理员引导阶段。"
                    : authConfigQuery.data.registration_mode === "invite_only"
                    ? "当前新账号需要邀请码。"
                    : authConfigQuery.data.registration_mode === "closed"
                    ? "当前已关闭公开注册。"
                    : "当前允许公开注册。"
                  : authConfigQuery.error
                  ? getApiErrorMessage(authConfigQuery.error, "注册策略读取失败。")
                  : "正在读取注册策略。"}
              </p>
            </div>
          </div>
        </Card>

        <Card className="space-y-5">
          <div>
            <CardTitle>修改密码</CardTitle>
            <CardDescription>修改后会刷新当前登录态，并使旧密码登录的会话失效。</CardDescription>
          </div>

          <div className="space-y-4">
            <div>
              <Label htmlFor="current-password">当前密码</Label>
              <Input
                id="current-password"
                onChange={(event) => setCurrentPassword(event.target.value)}
                type="password"
                value={currentPassword}
              />
            </div>
            <div>
              <Label htmlFor="new-password">新密码</Label>
              <Input
                id="new-password"
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder="至少 8 位"
                type="password"
                value={newPassword}
              />
            </div>
            <div>
              <Label htmlFor="confirm-password">确认新密码</Label>
              <Input
                id="confirm-password"
                onChange={(event) => setConfirmPassword(event.target.value)}
                type="password"
                value={confirmPassword}
              />
            </div>

            {errorMessage ? <p className="text-sm text-red-600">{errorMessage}</p> : null}
            {feedback ? <p className="text-sm text-emerald-700">{feedback}</p> : null}

            <Button disabled={saving} onClick={() => void handleChangePassword()} type="button">
              {saving ? "保存中..." : "更新密码"}
            </Button>
          </div>
        </Card>
      </div>

      <Card className="space-y-5">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="danger">危险操作</Badge>
            {auth.user?.role === "admin" ? <Badge tone="warning">管理员账号受额外保护</Badge> : null}
          </div>
          <CardTitle>删除账号</CardTitle>
          <CardDescription>验证当前密码后，会永久删除当前账号自己的研究任务、报告资产、PM 对话、运行时配置与登录会话。</CardDescription>
        </div>

        <div className="space-y-4 rounded-[24px] border border-rose-200 bg-rose-50/70 p-5">
          <p className="text-sm leading-6 text-rose-900">
            这个操作不可恢复。为了避免误删，请先输入当前账号邮箱 <span className="font-mono">{auth.user?.email || "--"}</span>，再输入当前密码确认。
          </p>
          <p className="text-sm leading-6 text-rose-900">
            如果你是当前系统里最后一个可用管理员，而系统中还存在其他账号，系统会阻止删除，避免后台彻底失管。
          </p>

          <div>
            <Label htmlFor="delete-confirm-email">确认邮箱</Label>
            <Input
              id="delete-confirm-email"
              onChange={(event) => setDeleteConfirmEmail(event.target.value)}
              placeholder={auth.user?.email || "请输入当前账号邮箱"}
              value={deleteConfirmEmail}
            />
          </div>
          <div>
            <Label htmlFor="delete-password">当前密码</Label>
            <Input
              id="delete-password"
              onChange={(event) => setDeletePassword(event.target.value)}
              type="password"
              value={deletePassword}
            />
          </div>

          {deleteErrorMessage ? <p className="text-sm text-rose-700">{deleteErrorMessage}</p> : null}

          <Button
            className="border-rose-700 bg-rose-700 text-white shadow-none hover:border-rose-800 hover:bg-rose-800"
            disabled={deleting}
            onClick={() => void handleDeleteAccount()}
            type="button"
          >
            {deleting ? "删除中..." : "永久删除账号"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
