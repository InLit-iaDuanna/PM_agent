import type {
  AdminResetUserPasswordDto,
  AuthPublicConfigRecord,
  AuthSessionRecord,
  AuthUserRecord,
  CancelResearchJobDto,
  ChatSessionRecord,
  ChangePasswordDto,
  CreateInviteDto,
  CreateResearchJobDto,
  DeleteAccountDto,
  HealthStatusRecord,
  InviteRecord,
  LoginUserDto,
  LogoutResultRecord,
  RegisterUserDto,
  ReportVersionDiffRecord,
  ResearchAssetsRecord,
  ResearchJobRecord,
  RuntimeConfigDto,
  RuntimeStatusRecord,
  RuntimeValidationResultRecord,
  SendChatMessageResultRecord,
  SystemUpdateJobRecord,
  SystemUpdateStatusRecord,
  TriggerSystemUpdateDto,
  UpdateRuntimeSettingsDto,
  UpdateRegistrationPolicyDto,
  UpdateUserRoleDto,
} from "@pm-agent/types";

import { getApiBaseUrl, getApiBaseUrlCandidates, setApiBaseUrl } from "./api-base-url";

export class ApiClientError extends Error {
  status: number;
  details?: string;

  constructor(message: string, status = 0, details?: string) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.details = details;
  }
}

export function getApiErrorMessage(error: unknown, fallback = "请求失败，请稍后再试。"): string {
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  if (error instanceof ApiClientError) {
    return error.message;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

async function readJson<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    return {} as T;
  }
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const activeBaseUrl = getApiBaseUrl();
  const candidateBaseUrls = getApiBaseUrlCandidates();
  const requestBaseUrls = candidateBaseUrls.length ? candidateBaseUrls : [activeBaseUrl];
  let response: Response | null = null;

  for (const baseUrl of requestBaseUrls) {
    try {
      response = await fetch(baseUrl ? `${baseUrl}${path}` : path, {
        cache: "no-store",
        credentials: "include",
        ...init,
      });
      if (response.ok && baseUrl !== activeBaseUrl) {
        setApiBaseUrl(baseUrl);
      }
      break;
    } catch {
      continue;
    }
  }

  if (!response) {
    const retryHint =
      requestBaseUrls.length > 1
        ? ` 已尝试 ${requestBaseUrls.length} 个本地候选地址：${requestBaseUrls.join("、")}`
        : "";
    throw new ApiClientError(`无法连接到 API。当前地址：${activeBaseUrl}。请确认后端已启动，或在运行时设置里切换 API 地址。${retryHint}`);
  }

  if (!response.ok) {
    const details = await response.text();
    let message = `API 请求失败（${response.status}）`;
    try {
      const parsed = JSON.parse(details) as { detail?: string };
      if (typeof parsed.detail === "string" && parsed.detail.trim()) {
        message = parsed.detail.trim();
      }
    } catch {
      if (details.trim()) {
        message = details.trim();
      }
    }
    if (response.status === 404) {
      throw new ApiClientError("目标资源不存在，请检查任务 ID、会话 ID 或 API 地址。", response.status, details);
    }
    throw new ApiClientError(message, response.status, details);
  }

  return readJson<T>(response);
}

export async function fetchResearchJob(jobId: string): Promise<ResearchJobRecord> {
  return apiRequest<ResearchJobRecord>(`/api/research-jobs/${jobId}`);
}

export async function fetchCurrentUser(): Promise<AuthUserRecord> {
  return apiRequest<AuthUserRecord>("/api/auth/me");
}

export async function fetchAuthPublicConfig(): Promise<AuthPublicConfigRecord> {
  return apiRequest<AuthPublicConfigRecord>("/api/auth/public-config");
}

export async function registerUser(payload: RegisterUserDto): Promise<AuthSessionRecord> {
  return apiRequest<AuthSessionRecord>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function loginUser(payload: LoginUserDto): Promise<AuthSessionRecord> {
  return apiRequest<AuthSessionRecord>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function logoutUser(): Promise<LogoutResultRecord> {
  return apiRequest<LogoutResultRecord>("/api/auth/logout", {
    method: "POST",
  });
}

export async function changePassword(payload: ChangePasswordDto): Promise<AuthSessionRecord> {
  return apiRequest<AuthSessionRecord>("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteCurrentAccount(payload: DeleteAccountDto): Promise<LogoutResultRecord> {
  return apiRequest<LogoutResultRecord>("/api/auth/delete-account", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchAdminUsers(): Promise<AuthUserRecord[]> {
  return apiRequest<AuthUserRecord[]>("/api/admin/users");
}

export async function fetchAdminInvites(): Promise<InviteRecord[]> {
  return apiRequest<InviteRecord[]>("/api/admin/invites");
}

export async function createAdminInvite(payload: CreateInviteDto): Promise<InviteRecord> {
  return apiRequest<InviteRecord>("/api/admin/invites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function disableAdminInvite(inviteId: string): Promise<InviteRecord> {
  return apiRequest<InviteRecord>(`/api/admin/invites/${inviteId}/disable`, {
    method: "POST",
  });
}

export async function updateAdminUserRole(userId: string, payload: UpdateUserRoleDto): Promise<AuthUserRecord> {
  return apiRequest<AuthUserRecord>(`/api/admin/users/${userId}/role`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function disableAdminUser(userId: string): Promise<AuthUserRecord> {
  return apiRequest<AuthUserRecord>(`/api/admin/users/${userId}/disable`, {
    method: "POST",
  });
}

export async function enableAdminUser(userId: string): Promise<AuthUserRecord> {
  return apiRequest<AuthUserRecord>(`/api/admin/users/${userId}/enable`, {
    method: "POST",
  });
}

export async function resetAdminUserPassword(userId: string, payload: AdminResetUserPasswordDto): Promise<AuthUserRecord> {
  return apiRequest<AuthUserRecord>(`/api/admin/users/${userId}/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateAdminRegistrationPolicy(payload: UpdateRegistrationPolicyDto): Promise<AuthPublicConfigRecord> {
  const mode = payload.registration_mode ?? payload.mode;
  return apiRequest<AuthPublicConfigRecord>("/api/admin/registration-policy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode,
      registration_mode: mode,
    }),
  });
}

export async function fetchAdminSystemUpdateStatus(): Promise<SystemUpdateStatusRecord> {
  return apiRequest<SystemUpdateStatusRecord>("/api/admin/system-update");
}

export async function triggerAdminSystemUpdate(payload: TriggerSystemUpdateDto): Promise<SystemUpdateJobRecord> {
  return apiRequest<SystemUpdateJobRecord>("/api/admin/system-update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchResearchJobs(): Promise<ResearchJobRecord[]> {
  return apiRequest<ResearchJobRecord[]>("/api/research-jobs");
}

export async function fetchHealthStatus(): Promise<HealthStatusRecord> {
  return apiRequest<HealthStatusRecord>("/api/health");
}

export async function fetchRuntimeStatus(): Promise<RuntimeStatusRecord> {
  return apiRequest<RuntimeStatusRecord>("/api/runtime");
}

export async function saveRuntimeSettings(payload: UpdateRuntimeSettingsDto): Promise<RuntimeStatusRecord> {
  return apiRequest<RuntimeStatusRecord>("/api/runtime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
}

export async function validateRuntimeSettings(runtimeConfig: RuntimeConfigDto): Promise<RuntimeValidationResultRecord> {
  return apiRequest<RuntimeValidationResultRecord>("/api/runtime/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ runtime_config: runtimeConfig }),
    });
}

export async function fetchResearchAssets(jobId: string): Promise<ResearchAssetsRecord> {
  return apiRequest<ResearchAssetsRecord>(`/api/research-jobs/${jobId}/assets`);
}

export async function cancelResearchJob(jobId: string, reason?: string): Promise<ResearchJobRecord> {
  const payload: CancelResearchJobDto = reason ? { reason } : {};
  return apiRequest<ResearchJobRecord>(`/api/research-jobs/${jobId}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
}

export async function finalizeResearchReport(jobId: string, sourceVersionId?: string): Promise<ResearchAssetsRecord> {
  return apiRequest<ResearchAssetsRecord>(`/api/research-jobs/${jobId}/finalize-report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sourceVersionId ? { source_version_id: sourceVersionId } : {}),
    });
}

export async function createResearchJob(payload: CreateResearchJobDto): Promise<ResearchJobRecord> {
  return apiRequest<ResearchJobRecord>("/api/research-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
}

export async function createChatSession(researchJobId: string, reuseExisting = true): Promise<ChatSessionRecord> {
  return apiRequest<ChatSessionRecord>("/api/chat/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ research_job_id: researchJobId, reuse_existing: reuseExisting }),
    });
}

export async function fetchChatSession(sessionId: string): Promise<ChatSessionRecord> {
  return apiRequest<ChatSessionRecord>(`/api/chat/sessions/${sessionId}/messages`);
}

export async function fetchChatSessions(researchJobId: string): Promise<ChatSessionRecord[]> {
  return apiRequest<ChatSessionRecord[]>(`/api/chat/sessions?research_job_id=${encodeURIComponent(researchJobId)}`);
}

export async function sendChatMessage(sessionId: string, content: string): Promise<SendChatMessageResultRecord> {
  return apiRequest<SendChatMessageResultRecord>(`/api/chat/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
}

export async function openTaskSource(jobId: string, taskId: string, url?: string): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>(`/api/research-jobs/${jobId}/tasks/${taskId}/open-source`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
}

export async function fetchReportVersionDiff(
  jobId: string,
  versionId: string,
  baseVersionId: string,
): Promise<ReportVersionDiffRecord> {
  return apiRequest<ReportVersionDiffRecord>(
    `/api/research-jobs/${jobId}/report-versions/${encodeURIComponent(versionId)}/diff/${encodeURIComponent(baseVersionId)}`,
  );
}
