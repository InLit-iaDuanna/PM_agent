"use client";

import { useEffect, useMemo, useState } from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuthPublicConfigRecord, RegistrationMode, RegistrationPolicyMode } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, Input, Label } from "@pm-agent/ui";

import {
  ApiClientError,
  createAdminInvite,
  disableAdminUser,
  disableAdminInvite,
  enableAdminUser,
  fetchAuthPublicConfig,
  fetchAdminInvites,
  fetchAdminUsers,
  getApiErrorMessage,
  resetAdminUserPassword,
  updateAdminRegistrationPolicy,
  updateAdminUserRole,
} from "../../lib/api-client";
import { useAuth } from "./auth-provider";

function formatDateTime(value?: string) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function isForbidden(error: unknown) {
  return error instanceof ApiClientError && error.status === 403;
}

function isUserDisabled(user: { is_disabled?: boolean; disabled_at?: string }) {
  return user.is_disabled ?? Boolean(user.disabled_at);
}

const registrationPolicyOptions: Array<{
  mode: RegistrationPolicyMode;
  label: string;
  description: string;
}> = [
  {
    mode: "default",
    label: "跟随默认",
    description: "遵循部署默认值和当前邀请码规则；若系统还没有账号，首个注册者仍会成为管理员。",
  },
  {
    mode: "open",
    label: "公开注册",
    description: "任何人都可以直接注册，适合内测或公开试用阶段。",
  },
  {
    mode: "invite_only",
    label: "仅邀请码",
    description: "只有持有邀请码的新用户才能注册，适合受控放量。",
  },
  {
    mode: "closed",
    label: "完全关闭",
    description: "关闭所有新账号注册入口，只保留现有账号登录。",
  },
];

function getRegistrationPolicyLabel(mode: RegistrationPolicyMode) {
  return registrationPolicyOptions.find((option) => option.mode === mode)?.label ?? "跟随默认";
}

function getRegistrationPolicyDescription(mode: RegistrationPolicyMode) {
  return registrationPolicyOptions.find((option) => option.mode === mode)?.description ?? registrationPolicyOptions[0].description;
}

function getRegistrationModeLabel(mode?: RegistrationMode) {
  switch (mode) {
    case "bootstrap":
      return "首个管理员引导";
    case "invite_only":
      return "邀请码注册";
    case "closed":
      return "关闭注册";
    case "open":
    default:
      return "公开注册";
  }
}

function getRegistrationModeTone(mode?: RegistrationMode) {
  switch (mode) {
    case "bootstrap":
      return "warning" as const;
    case "invite_only":
      return "default" as const;
    case "closed":
      return "warning" as const;
    case "open":
    default:
      return "success" as const;
  }
}

function getEffectiveRegistrationPolicyMode(config?: AuthPublicConfigRecord | null): RegistrationPolicyMode {
  const configuredMode = config?.policy_mode ?? config?.configured_registration_mode;
  if (configuredMode === "default" || configuredMode === "open" || configuredMode === "invite_only" || configuredMode === "closed") {
    return configuredMode;
  }
  if (config?.registration_mode === "invite_only" || config?.registration_mode === "open" || config?.registration_mode === "closed") {
    return config.registration_mode;
  }
  return "default";
}

function getRegistrationModeDescription(config?: AuthPublicConfigRecord | null) {
  if (!config) {
    return "正在读取当前注册策略。";
  }
  switch (config.registration_mode) {
    case "bootstrap":
      return "当前仍处于首个管理员引导阶段。完成首个账号注册后，系统会按当前策略继续管理新注册入口。";
    case "invite_only":
      return "当前只有持有邀请码的新用户可以注册，适合小范围邀请和节奏控制。";
    case "closed":
      return "当前已关闭新账号注册，只允许现有成员继续登录和使用系统。";
    case "open":
    default:
      return "当前允许公开注册，任何访问登录页的人都可以直接创建新账号。";
  }
}

export function AdminSettingsPage() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [inviteNote, setInviteNote] = useState("");
  const [creatingInvite, setCreatingInvite] = useState(false);
  const [pendingInviteId, setPendingInviteId] = useState<string | null>(null);
  const [pendingUserActionId, setPendingUserActionId] = useState<string | null>(null);
  const [registrationPolicyDraft, setRegistrationPolicyDraft] = useState<RegistrationPolicyMode>("default");
  const [savingRegistrationPolicy, setSavingRegistrationPolicy] = useState(false);
  const [passwordDraftByUserId, setPasswordDraftByUserId] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const isAdmin = auth.user?.role === "admin";

  const authConfigQuery = useQuery({
    queryKey: ["auth", "public-config"],
    queryFn: fetchAuthPublicConfig,
    enabled: isAdmin,
    staleTime: 10_000,
    retry: false,
  });

  const usersQuery = useQuery({
    queryKey: ["admin", "users"],
    queryFn: fetchAdminUsers,
    enabled: isAdmin,
    staleTime: 10_000,
    retry: false,
  });

  const invitesQuery = useQuery({
    queryKey: ["admin", "invites"],
    queryFn: fetchAdminInvites,
    enabled: isAdmin,
    staleTime: 10_000,
    retry: false,
  });

  useEffect(() => {
    if (!authConfigQuery.data) {
      return;
    }
    setRegistrationPolicyDraft(getEffectiveRegistrationPolicyMode(authConfigQuery.data));
  }, [authConfigQuery.data]);

  const currentRegistrationPolicyMode = useMemo(
    () => getEffectiveRegistrationPolicyMode(authConfigQuery.data),
    [authConfigQuery.data],
  );

  const queryErrorMessage = useMemo(() => {
    if (authConfigQuery.error) {
      return getApiErrorMessage(authConfigQuery.error, "注册策略读取失败。");
    }
    if (usersQuery.error) {
      return getApiErrorMessage(usersQuery.error, "用户列表读取失败。");
    }
    if (invitesQuery.error) {
      return getApiErrorMessage(invitesQuery.error, "邀请码列表读取失败。");
    }
    return null;
  }, [authConfigQuery.error, invitesQuery.error, usersQuery.error]);

  const refreshAdminData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
      queryClient.invalidateQueries({ queryKey: ["admin", "invites"] }),
      queryClient.invalidateQueries({ queryKey: ["auth", "public-config"] }),
    ]);
  };

  const handleCreateInvite = async () => {
    setCreatingInvite(true);
    setFeedback(null);
    setErrorMessage(null);
    try {
      const invite = await createAdminInvite({ note: inviteNote.trim() || undefined });
      setInviteNote("");
      setFeedback(`已生成邀请码：${invite.code}。请让对方在未登录状态下打开 /login，切到“注册”并填入邀请码；如果你当前正登录管理员账号，请先退出或用无痕窗口测试。`);
      await refreshAdminData();
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "邀请码生成失败。"));
    } finally {
      setCreatingInvite(false);
    }
  };

  const handleDisableInvite = async (inviteId: string) => {
    setPendingInviteId(inviteId);
    setFeedback(null);
    setErrorMessage(null);
    try {
      await disableAdminInvite(inviteId);
      setFeedback("邀请码已停用。");
      await refreshAdminData();
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "邀请码停用失败。"));
    } finally {
      setPendingInviteId(null);
    }
  };

  const handleUpdateRegistrationPolicy = async () => {
    setSavingRegistrationPolicy(true);
    setFeedback(null);
    setErrorMessage(null);
    try {
      const updatedPolicy = await updateAdminRegistrationPolicy({ registration_mode: registrationPolicyDraft });
      const appliedMode = getEffectiveRegistrationPolicyMode(updatedPolicy);
      setRegistrationPolicyDraft(appliedMode);
      setFeedback(`注册策略已更新为“${getRegistrationPolicyLabel(appliedMode)}”，当前生效：${getRegistrationModeLabel(updatedPolicy.registration_mode)}。`);
      await refreshAdminData();
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "注册策略更新失败。"));
    } finally {
      setSavingRegistrationPolicy(false);
    }
  };

  const handleUpdateRole = async (userId: string, role: "admin" | "member") => {
    setPendingUserActionId(userId);
    setFeedback(null);
    setErrorMessage(null);
    try {
      const updatedUser = await updateAdminUserRole(userId, { role });
      setFeedback(`${updatedUser.email} 已更新为${updatedUser.role === "admin" ? "管理员" : "成员"}。`);
      await refreshAdminData();
      if (updatedUser.id === auth.user?.id) {
        await auth.refresh();
      }
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "角色更新失败。"));
    } finally {
      setPendingUserActionId(null);
    }
  };

  const handleDisableUser = async (userId: string) => {
    setPendingUserActionId(userId);
    setFeedback(null);
    setErrorMessage(null);
    try {
      const updatedUser = await disableAdminUser(userId);
      setFeedback(`${updatedUser.email} 已禁用。`);
      await refreshAdminData();
      if (updatedUser.id === auth.user?.id) {
        await auth.refresh();
      }
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "用户禁用失败。"));
    } finally {
      setPendingUserActionId(null);
    }
  };

  const handleEnableUser = async (userId: string) => {
    setPendingUserActionId(userId);
    setFeedback(null);
    setErrorMessage(null);
    try {
      const updatedUser = await enableAdminUser(userId);
      setFeedback(`${updatedUser.email} 已重新启用。`);
      await refreshAdminData();
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "用户启用失败。"));
    } finally {
      setPendingUserActionId(null);
    }
  };

  const handleResetUserPassword = async (userId: string) => {
    const newPassword = (passwordDraftByUserId[userId] || "").trim();
    if (!newPassword) {
      setErrorMessage("请先输入新密码。");
      setFeedback(null);
      return;
    }
    setPendingUserActionId(userId);
    setFeedback(null);
    setErrorMessage(null);
    try {
      const updatedUser = await resetAdminUserPassword(userId, { new_password: newPassword });
      setPasswordDraftByUserId((previous) => ({ ...previous, [userId]: "" }));
      setFeedback(`${updatedUser.email} 的密码已重置。`);
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "密码重置失败。"));
    } finally {
      setPendingUserActionId(null);
    }
  };

  if (!isAdmin) {
    return (
      <Card className="space-y-4">
        <div className="space-y-2">
          <Badge tone="warning">无权限</Badge>
          <CardTitle>管理员设置</CardTitle>
          <CardDescription>当前账号不是管理员，不能查看用户与邀请码管理。</CardDescription>
        </div>
      </Card>
    );
  }

  if (isForbidden(authConfigQuery.error) || isForbidden(usersQuery.error) || isForbidden(invitesQuery.error)) {
    return (
      <Card className="space-y-4">
        <div className="space-y-2">
          <Badge tone="warning">访问受限</Badge>
          <CardTitle>管理员设置</CardTitle>
          <CardDescription>服务端拒绝了管理员接口访问，请确认当前账号权限仍然有效。</CardDescription>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card className="space-y-5">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="success">管理员</Badge>
            <Badge>{auth.user?.email || "--"}</Badge>
          </div>
          <CardTitle>管理员设置</CardTitle>
          <CardDescription>在这里管理成员权限、邀请码发放与注册入口节奏。</CardDescription>
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">当前管理员</p>
            <p className="mt-2 text-lg font-semibold text-[color:var(--ink)]">{auth.user?.display_name || auth.user?.email || "--"}</p>
            <p className="mt-2 text-sm leading-6 text-[color:var(--muted)]">
              首个账号默认成为管理员。后续是否开放注册、仅限邀请码，或完全关闭入口，都可以在这里即时切换。
            </p>
          </div>
          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-5">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">注册策略</p>
              {authConfigQuery.data ? (
                <>
                  <Badge>{getRegistrationPolicyLabel(currentRegistrationPolicyMode)}</Badge>
                  <Badge tone={getRegistrationModeTone(authConfigQuery.data.registration_mode)}>
                    当前生效：{getRegistrationModeLabel(authConfigQuery.data.registration_mode)}
                  </Badge>
                </>
              ) : null}
            </div>
            <p className="mt-2 text-sm leading-6 text-[color:var(--muted)]">{getRegistrationModeDescription(authConfigQuery.data)}</p>
            <div className="mt-3 space-y-3">
              <div>
                <Label htmlFor="registration-policy">切换模式</Label>
                <select
                  className="mt-1 w-full rounded-2xl border border-[color:var(--border-soft)] bg-white/80 px-4 py-3 text-sm text-[color:var(--ink)] outline-none transition focus:border-[color:var(--accent)]"
                  disabled={authConfigQuery.isPending || savingRegistrationPolicy}
                  id="registration-policy"
                  onChange={(event) => setRegistrationPolicyDraft(event.target.value as RegistrationPolicyMode)}
                  value={registrationPolicyDraft}
                >
                  {registrationPolicyOptions.map((option) => (
                    <option key={option.mode} value={option.mode}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <p className="text-xs leading-6 text-[color:var(--muted)]">{getRegistrationPolicyDescription(registrationPolicyDraft)}</p>
              <Button
                disabled={authConfigQuery.isPending || savingRegistrationPolicy || registrationPolicyDraft === currentRegistrationPolicyMode}
                onClick={() => void handleUpdateRegistrationPolicy()}
                type="button"
              >
                {savingRegistrationPolicy ? "保存中..." : "保存注册策略"}
              </Button>
            </div>
          </div>
          <div className="rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">发放邀请码</p>
            <div className="mt-3 space-y-3">
              <p className="text-xs leading-6 text-[color:var(--muted)]">
                使用方式：让新用户在未登录状态下打开 <span className="font-mono text-[color:var(--ink)]">/login</span>，切到“注册”后填写邀请码。
                如果你当前浏览器已登录管理员，系统会自动跳回首页，无法在同一会话里测试注册。
                {authConfigQuery.data?.registration_mode === "closed"
                  ? " 当前生效策略是“关闭注册”，请先切到“仅邀请码”或“跟随默认”再发码。"
                  : ""}
              </p>
              <div>
                <Label htmlFor="invite-note">备注</Label>
                <Input
                  id="invite-note"
                  onChange={(event) => setInviteNote(event.target.value)}
                  placeholder="例如：外部顾问 / 运营同学"
                  value={inviteNote}
                />
              </div>
              <Button disabled={creatingInvite} onClick={() => void handleCreateInvite()} type="button">
                {creatingInvite ? "生成中..." : "生成邀请码"}
              </Button>
            </div>
          </div>
        </div>

        {queryErrorMessage ? <p className="text-sm text-red-600">{queryErrorMessage}</p> : null}
        {errorMessage ? <p className="text-sm text-red-600">{errorMessage}</p> : null}
        {feedback ? <p className="text-sm text-emerald-700">{feedback}</p> : null}
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <Card className="space-y-5">
          <div className="space-y-2">
            <CardTitle>成员与角色</CardTitle>
            <CardDescription>成员默认是普通用户。至少要保留一个管理员。</CardDescription>
          </div>

          <div className="space-y-3">
            {usersQuery.isPending ? <p className="text-sm text-[color:var(--muted)]">正在加载成员列表...</p> : null}
            {(usersQuery.data || []).map((user) => {
              const isPending = pendingUserActionId === user.id;
              const disabled = isUserDisabled(user);
              const isSelf = user.id === auth.user?.id;
              return (
                <div
                  key={user.id}
                  className="flex flex-col gap-3 rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold text-[color:var(--ink)]">{user.display_name || user.email}</p>
                        <Badge tone={user.role === "admin" ? "success" : "default"}>
                          {user.role === "admin" ? "管理员" : "成员"}
                        </Badge>
                        <Badge tone={disabled ? "warning" : "success"}>{disabled ? "已禁用" : "已启用"}</Badge>
                        {isSelf ? <Badge>当前账号</Badge> : null}
                      </div>
                      <p className="mt-1 text-sm text-[color:var(--muted)]">{user.email}</p>
                      <p className="mt-2 text-xs text-[color:var(--muted)]">
                        创建于 {formatDateTime(user.created_at)}，最近登录 {formatDateTime(user.last_login_at)}
                      </p>
                      {user.disabled_at ? <p className="mt-1 text-xs text-[color:var(--muted)]">禁用时间：{formatDateTime(user.disabled_at)}</p> : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        disabled={isPending || user.role === "admin"}
                        onClick={() => void handleUpdateRole(user.id, "admin")}
                        type="button"
                        variant="secondary"
                      >
                        设为管理员
                      </Button>
                      <Button
                        disabled={isPending || user.role === "member"}
                        onClick={() => void handleUpdateRole(user.id, "member")}
                        type="button"
                        variant="ghost"
                      >
                        设为成员
                      </Button>
                      <Button
                        disabled={isPending || isSelf || disabled}
                        onClick={() => void handleDisableUser(user.id)}
                        type="button"
                        variant="secondary"
                      >
                        禁用用户
                      </Button>
                      <Button
                        disabled={isPending || !disabled}
                        onClick={() => void handleEnableUser(user.id)}
                        type="button"
                        variant="ghost"
                      >
                        重新启用
                      </Button>
                    </div>
                  </div>
                  <div className="grid gap-2 md:grid-cols-[1fr_auto]">
                    <Input
                      disabled={isPending}
                      onChange={(event) =>
                        setPasswordDraftByUserId((previous) => ({
                          ...previous,
                          [user.id]: event.target.value,
                        }))
                      }
                      placeholder="管理员输入新密码"
                      type="password"
                      value={passwordDraftByUserId[user.id] || ""}
                    />
                    <Button
                      disabled={isPending || !(passwordDraftByUserId[user.id] || "").trim()}
                      onClick={() => void handleResetUserPassword(user.id)}
                      type="button"
                      variant="secondary"
                    >
                      重置密码
                    </Button>
                  </div>
                </div>
              );
            })}
            {!usersQuery.isPending && !usersQuery.data?.length ? <p className="text-sm text-[color:var(--muted)]">还没有成员数据。</p> : null}
          </div>
        </Card>

        <Card className="space-y-5">
          <div className="space-y-2">
            <CardTitle>邀请码</CardTitle>
            <CardDescription>邀请码使用一次后会自动失效，也可以提前手动停用。</CardDescription>
          </div>

          <div className="space-y-3">
            {invitesQuery.isPending ? <p className="text-sm text-[color:var(--muted)]">正在加载邀请码...</p> : null}
            {(invitesQuery.data || []).map((invite) => {
              const stateTone = invite.active ? "success" : invite.used_at ? "default" : "warning";
              const stateLabel = invite.active ? "可用" : invite.used_at ? "已使用" : "已停用";
              return (
                <div
                  key={invite.id}
                  className="space-y-3 rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.52)] p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={stateTone}>{stateLabel}</Badge>
                    {invite.note ? <Badge>{invite.note}</Badge> : null}
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.16em] text-[color:var(--muted)]">邀请码</p>
                    <p className="mt-1 break-all font-mono text-sm text-[color:var(--ink)]">{invite.code}</p>
                  </div>
                  <div className="text-xs leading-6 text-[color:var(--muted)]">
                    <p>创建时间：{formatDateTime(invite.created_at)}</p>
                    <p>发放人：{invite.issued_by_email || "--"}</p>
                    <p>使用情况：{invite.used_by_email ? `${invite.used_by_email} 于 ${formatDateTime(invite.used_at)}` : "未使用"}</p>
                  </div>
                  <Button
                    disabled={!invite.active || pendingInviteId === invite.id}
                    onClick={() => void handleDisableInvite(invite.id)}
                    type="button"
                    variant="secondary"
                  >
                    {pendingInviteId === invite.id ? "停用中..." : "停用邀请码"}
                  </Button>
                </div>
              );
            })}
            {!invitesQuery.isPending && !invitesQuery.data?.length ? <p className="text-sm text-[color:var(--muted)]">还没有邀请码记录。</p> : null}
          </div>
        </Card>
      </div>
    </div>
  );
}
