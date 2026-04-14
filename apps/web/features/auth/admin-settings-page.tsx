"use client";

import { useEffect, useMemo, useState } from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuthPublicConfigRecord, RegistrationMode, RegistrationPolicyMode, SystemUpdateStatusRecord } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, Input, Label } from "@pm-agent/ui";

import {
  ApiClientError,
  createAdminInvite,
  disableAdminUser,
  disableAdminInvite,
  enableAdminUser,
  fetchAuthPublicConfig,
  fetchAdminInvites,
  fetchAdminSystemUpdateStatus,
  fetchAdminUsers,
  getApiErrorMessage,
  resetAdminUserPassword,
  triggerAdminSystemUpdate,
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

function getUpdateJobStatusTone(status?: string) {
  switch (status) {
    case "succeeded":
      return "success" as const;
    case "failed":
      return "warning" as const;
    case "running":
      return "default" as const;
    default:
      return "default" as const;
  }
}

function getUpdateJobStatusLabel(status?: string) {
  switch (status) {
    case "succeeded":
      return "成功";
    case "failed":
      return "失败";
    case "running":
      return "执行中";
    default:
      return "未知";
  }
}

function buildUpdateCommandPreview(
  status: SystemUpdateStatusRecord | undefined,
  ref: string,
  useProd: boolean,
  projectName: string,
) {
  if (!status) {
    return "";
  }
  const targetRef = (ref || status.default_ref || "main").trim();
  const parts = ["./scripts/server_update.sh", "--ref", targetRef];
  if (useProd) {
    parts.push("--prod");
  } else if (projectName.trim()) {
    parts.push("--project-name", projectName.trim());
  }
  return parts.join(" ");
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
  const [updateTargetRef, setUpdateTargetRef] = useState("main");
  const [updateUseProd, setUpdateUseProd] = useState(false);
  const [updateProjectName, setUpdateProjectName] = useState("pmagent101");
  const [triggeringSystemUpdate, setTriggeringSystemUpdate] = useState(false);
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

  const systemUpdateQuery = useQuery({
    queryKey: ["admin", "system-update"],
    queryFn: fetchAdminSystemUpdateStatus,
    enabled: isAdmin,
    staleTime: 10_000,
    refetchInterval: 10_000,
    retry: false,
  });

  useEffect(() => {
    if (!authConfigQuery.data) {
      return;
    }
    setRegistrationPolicyDraft(getEffectiveRegistrationPolicyMode(authConfigQuery.data));
  }, [authConfigQuery.data]);

  useEffect(() => {
    const status = systemUpdateQuery.data;
    if (!status) {
      return;
    }
    setUpdateTargetRef((current) => {
      if (current && status.options.some((option) => option.ref === current)) {
        return current;
      }
      return status.default_ref || status.current_ref || "main";
    });
    if (!updateProjectName.trim()) {
      setUpdateProjectName(status.compose_project_name || "pmagent101");
    }
  }, [systemUpdateQuery.data, updateProjectName]);

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
    if (systemUpdateQuery.error) {
      return getApiErrorMessage(systemUpdateQuery.error, "版本更新信息读取失败。");
    }
    return null;
  }, [authConfigQuery.error, invitesQuery.error, systemUpdateQuery.error, usersQuery.error]);

  const refreshAdminData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
      queryClient.invalidateQueries({ queryKey: ["admin", "invites"] }),
      queryClient.invalidateQueries({ queryKey: ["admin", "system-update"] }),
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

  const handleTriggerSystemUpdate = async () => {
    const status = systemUpdateQuery.data;
    if (!status) {
      setErrorMessage("还没拿到版本信息，请稍后再试。");
      setFeedback(null);
      return;
    }
    const targetRef = (updateTargetRef || status.default_ref || "main").trim();
    if (!targetRef) {
      setErrorMessage("请选择目标版本。");
      setFeedback(null);
      return;
    }
    setTriggeringSystemUpdate(true);
    setErrorMessage(null);
    setFeedback(null);
    try {
      const job = await triggerAdminSystemUpdate({
        ref: targetRef,
        use_prod: updateUseProd,
        project_name: updateUseProd ? undefined : updateProjectName.trim() || undefined,
      });
      setFeedback(`更新任务已启动：${job.job_id}（${job.ref}）。可在下方查看状态与日志路径。`);
      await queryClient.invalidateQueries({ queryKey: ["admin", "system-update"] });
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "更新任务启动失败。"));
    } finally {
      setTriggeringSystemUpdate(false);
    }
  };

  const handleCopyUpdateCommand = async () => {
    const command = buildUpdateCommandPreview(systemUpdateQuery.data, updateTargetRef, updateUseProd, updateProjectName);
    if (!command) {
      setErrorMessage("当前没有可复制的更新命令。");
      setFeedback(null);
      return;
    }
    try {
      await navigator.clipboard.writeText(command);
      setFeedback("更新命令已复制到剪贴板。");
      setErrorMessage(null);
    } catch {
      setErrorMessage("复制失败，请手动复制下方命令。");
      setFeedback(null);
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

  if (isForbidden(authConfigQuery.error) || isForbidden(usersQuery.error) || isForbidden(invitesQuery.error) || isForbidden(systemUpdateQuery.error)) {
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

  const systemUpdateStatus = systemUpdateQuery.data;
  const updateOptions = systemUpdateStatus?.options || [];
  const updateCommandPreview = buildUpdateCommandPreview(systemUpdateStatus, updateTargetRef, updateUseProd, updateProjectName);

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

        <div className="space-y-4 rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] p-5">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">系统版本与更新</p>
              {systemUpdateStatus?.current_tag ? <Badge tone="success">Tag {systemUpdateStatus.current_tag}</Badge> : null}
              {systemUpdateStatus?.current_branch ? <Badge>{systemUpdateStatus.current_branch}</Badge> : null}
              {systemUpdateStatus?.current_commit ? <Badge>{systemUpdateStatus.current_commit}</Badge> : null}
              {systemUpdateStatus?.active_job ? (
                <Badge tone={getUpdateJobStatusTone(systemUpdateStatus.active_job.status)}>
                  {`任务 ${getUpdateJobStatusLabel(systemUpdateStatus.active_job.status)}`}
                </Badge>
              ) : null}
            </div>
            <p className="text-sm leading-6 text-[color:var(--muted)]">
              在这里可以查看当前版本，并选择分支或 tag 触发更新。默认执行前会自动备份卷数据，便于回滚。
            </p>
            {systemUpdateStatus && !systemUpdateStatus.supported ? (
              <p className="text-sm text-amber-700">{systemUpdateStatus.reason || "当前环境不支持在 Web 执行更新。"}</p>
            ) : null}
            {systemUpdateStatus && systemUpdateStatus.supported && !systemUpdateStatus.can_execute ? (
              <p className="text-sm text-amber-700">{systemUpdateStatus.reason || "当前环境未开放 Web 更新执行。可先复制命令到服务器终端执行。"}</p>
            ) : null}
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <div className="md:col-span-1">
              <Label htmlFor="update-target-ref">目标版本</Label>
              <select
                className="mt-1 w-full rounded-2xl border border-[color:var(--border-soft)] bg-white/80 px-4 py-3 text-sm text-[color:var(--ink)] outline-none transition focus:border-[color:var(--accent)]"
                id="update-target-ref"
                onChange={(event) => setUpdateTargetRef(event.target.value)}
                value={updateTargetRef}
              >
                {updateOptions.length ? (
                  updateOptions.map((option) => (
                    <option key={`${option.kind}:${option.ref}`} value={option.ref}>
                      {option.kind === "tag" ? `tag: ${option.ref}` : `branch: ${option.ref}`}
                    </option>
                  ))
                ) : (
                  <option value={systemUpdateStatus?.default_ref || "main"}>{systemUpdateStatus?.default_ref || "main"}</option>
                )}
              </select>
            </div>
            <div className="md:col-span-1">
              <Label htmlFor="update-stack-mode">更新模式</Label>
              <select
                className="mt-1 w-full rounded-2xl border border-[color:var(--border-soft)] bg-white/80 px-4 py-3 text-sm text-[color:var(--ink)] outline-none transition focus:border-[color:var(--accent)]"
                id="update-stack-mode"
                onChange={(event) => setUpdateUseProd(event.target.value === "prod")}
                value={updateUseProd ? "prod" : "default"}
              >
                <option value="default">共享主机场景（gateway）</option>
                <option value="prod">公网 TLS 场景（caddy）</option>
              </select>
            </div>
            <div className="md:col-span-1">
              <Label htmlFor="update-project-name">Compose 项目标识</Label>
              <Input
                disabled={updateUseProd}
                id="update-project-name"
                onChange={(event) => setUpdateProjectName(event.target.value)}
                placeholder="pmagent101"
                value={updateUseProd ? "" : updateProjectName}
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              disabled={!systemUpdateStatus?.can_execute || triggeringSystemUpdate || systemUpdateQuery.isPending}
              onClick={() => void handleTriggerSystemUpdate()}
              type="button"
            >
              {triggeringSystemUpdate ? "启动中..." : "执行更新"}
            </Button>
            <Button disabled={!updateCommandPreview} onClick={() => void handleCopyUpdateCommand()} type="button" variant="secondary">
              复制更新命令
            </Button>
          </div>

          {updateCommandPreview ? (
            <div className="rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.7)] p-3">
              <p className="text-xs uppercase tracking-[0.14em] text-[color:var(--muted)]">命令预览</p>
              <p className="mt-2 break-all font-mono text-sm text-[color:var(--ink)]">{updateCommandPreview}</p>
            </div>
          ) : null}

          {systemUpdateStatus?.recent_jobs?.length ? (
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-[0.14em] text-[color:var(--muted)]">最近更新任务</p>
              {systemUpdateStatus.recent_jobs.slice(0, 5).map((job) => (
                <div
                  key={job.job_id}
                  className="rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.7)] px-3 py-2 text-sm"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={getUpdateJobStatusTone(job.status)}>{getUpdateJobStatusLabel(job.status)}</Badge>
                    <span className="font-medium text-[color:var(--ink)]">{job.ref}</span>
                    <span className="text-[color:var(--muted)]">{job.job_id}</span>
                  </div>
                  <p className="mt-1 text-xs text-[color:var(--muted)]">开始：{formatDateTime(job.started_at)}，结束：{formatDateTime(job.finished_at)}</p>
                  {job.log_path ? <p className="mt-1 break-all text-xs text-[color:var(--muted)]">日志：{job.log_path}</p> : null}
                </div>
              ))}
            </div>
          ) : null}
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
