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
import type {
  DailyTrendRoll,
  DesignTrend,
  MaterialItem,
  MaterialList,
  NetworkData,
  TrendHistoryRecord,
  UpdateMaterialTagsPayload,
} from "../features/design/data/trend-types";

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

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function ensureObjectResponse<T>(payload: unknown, endpoint: string): T {
  if (isPlainObject(payload)) {
    return payload as T;
  }
  throw new ApiClientError(`接口返回格式异常：${endpoint} 应返回对象。`);
}

function ensureArrayResponse<T>(payload: unknown): T[] {
  return Array.isArray(payload) ? (payload as T[]) : [];
}

function resolveApiAssetUrl(path?: string | null): string {
  const cleaned = String(path || "").trim();
  if (!cleaned) {
    return "";
  }
  if (/^(?:https?:)?\/\//i.test(cleaned) || cleaned.startsWith("data:") || cleaned.startsWith("blob:")) {
    return cleaned;
  }
  const baseUrl = getApiBaseUrl();
  if (!baseUrl) {
    return cleaned;
  }
  try {
    return new URL(cleaned, `${baseUrl}/`).toString();
  } catch {
    return cleaned;
  }
}

function normalizeMaterialItemUrls(item: MaterialItem): MaterialItem {
  return {
    ...item,
    thumbnail_url: resolveApiAssetUrl(item.thumbnail_url),
    full_url: resolveApiAssetUrl(item.full_url),
  };
}

function normalizeMaterialListUrls(payload: MaterialList): MaterialList {
  return {
    ...payload,
    items: (payload.items || []).map(normalizeMaterialItemUrls),
  };
}

function normalizeNetworkDataUrls(payload: NetworkData): NetworkData {
  return {
    ...payload,
    nodes: (payload.nodes || []).map((node) => ({
      ...node,
      thumbnail: resolveApiAssetUrl(node.thumbnail),
    })),
  };
}

async function readJson<T>(response: Response): Promise<T> {
  const responseText = await response.text();
  if (!responseText.trim()) {
    if (response.status === 204 || response.status === 205) {
      return {} as T;
    }
    throw new ApiClientError("API 返回了空响应，无法解析数据。", response.status);
  }

  try {
    return JSON.parse(responseText) as T;
  } catch {
    throw new ApiClientError("API 返回格式异常（非 JSON），请检查后端日志。", response.status, responseText.slice(0, 600));
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
  const payload = await apiRequest<unknown>(`/api/research-jobs/${jobId}`);
  return ensureObjectResponse<ResearchJobRecord>(payload, "/api/research-jobs/:jobId");
}

export async function fetchCurrentUser(): Promise<AuthUserRecord> {
  const payload = await apiRequest<unknown>("/api/auth/me");
  return ensureObjectResponse<AuthUserRecord>(payload, "/api/auth/me");
}

export async function fetchAuthPublicConfig(): Promise<AuthPublicConfigRecord> {
  const payload = await apiRequest<unknown>("/api/auth/public-config");
  return ensureObjectResponse<AuthPublicConfigRecord>(payload, "/api/auth/public-config");
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
  const payload = await apiRequest<unknown>("/api/admin/users");
  return ensureArrayResponse<AuthUserRecord>(payload);
}

export async function fetchAdminInvites(): Promise<InviteRecord[]> {
  const payload = await apiRequest<unknown>("/api/admin/invites");
  return ensureArrayResponse<InviteRecord>(payload);
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

export async function syncAdminSystemUpdateStatus(): Promise<SystemUpdateStatusRecord> {
  return apiRequest<SystemUpdateStatusRecord>("/api/admin/system-update/sync", {
    method: "POST",
  });
}

export async function triggerAdminSystemUpdate(payload: TriggerSystemUpdateDto): Promise<SystemUpdateJobRecord> {
  return apiRequest<SystemUpdateJobRecord>("/api/admin/system-update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchResearchJobs(): Promise<ResearchJobRecord[]> {
  const payload = await apiRequest<unknown>("/api/research-jobs");
  return ensureArrayResponse<ResearchJobRecord>(payload);
}

export async function fetchHealthStatus(): Promise<HealthStatusRecord> {
  const payload = await apiRequest<unknown>("/api/health");
  return ensureObjectResponse<HealthStatusRecord>(payload, "/api/health");
}

export async function fetchRuntimeStatus(): Promise<RuntimeStatusRecord> {
  const payload = await apiRequest<unknown>("/api/runtime");
  return ensureObjectResponse<RuntimeStatusRecord>(payload, "/api/runtime");
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
  const payload = await apiRequest<unknown>(`/api/research-jobs/${jobId}/assets`);
  return ensureObjectResponse<ResearchAssetsRecord>(payload, "/api/research-jobs/:jobId/assets");
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
  const payload = await apiRequest<unknown>(`/api/chat/sessions/${sessionId}/messages`);
  return ensureObjectResponse<ChatSessionRecord>(payload, "/api/chat/sessions/:sessionId/messages");
}

export async function fetchChatSessions(researchJobId: string): Promise<ChatSessionRecord[]> {
  const payload = await apiRequest<unknown>(`/api/chat/sessions?research_job_id=${encodeURIComponent(researchJobId)}`);
  return ensureArrayResponse<ChatSessionRecord>(payload);
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

export async function fetchTodayTrend(): Promise<DailyTrendRoll> {
  const payload = await apiRequest<unknown>("/api/design/trends/today");
  return ensureObjectResponse<DailyTrendRoll>(payload, "/api/design/trends/today");
}

export async function refreshTrendPool(): Promise<{
  ok: boolean;
  message: string;
  trend_count?: number;
  available_category_count?: number;
  pool_fetched_at?: string | null;
}> {
  const payload = await apiRequest<unknown>("/api/design/trends/refresh", {
    method: "POST",
  });
  return ensureObjectResponse<{
    ok: boolean;
    message: string;
    trend_count?: number;
    available_category_count?: number;
    pool_fetched_at?: string | null;
  }>(payload, "/api/design/trends/refresh");
}

export async function fetchTrendHistory(days = 30): Promise<TrendHistoryRecord[]> {
  const payload = await apiRequest<unknown>(`/api/design/trends/history?days=${days}`);
  return ensureArrayResponse<TrendHistoryRecord>(payload);
}

export async function uploadMaterial(file: File): Promise<MaterialItem> {
  const formData = new FormData();
  formData.append("file", file);
  const payload = await apiRequest<unknown>("/api/design/materials/upload", {
    method: "POST",
    body: formData,
  });
  return normalizeMaterialItemUrls(ensureObjectResponse<MaterialItem>(payload, "/api/design/materials/upload"));
}

export async function uploadMaterialFromUrl(url: string, tags: string[] = []): Promise<MaterialItem> {
  const payload = await apiRequest<unknown>("/api/design/materials/upload-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, tags }),
  });
  return normalizeMaterialItemUrls(ensureObjectResponse<MaterialItem>(payload, "/api/design/materials/upload-url"));
}

export async function saveTrendAsMaterial(trend: DesignTrend): Promise<MaterialItem> {
  const payload = await apiRequest<unknown>("/api/design/materials/from-trend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trend }),
  });
  return normalizeMaterialItemUrls(ensureObjectResponse<MaterialItem>(payload, "/api/design/materials/from-trend"));
}

export async function fetchMaterials(params?: {
  tag?: string;
  category?: string;
  color?: string;
  page?: number;
  page_size?: number;
}): Promise<MaterialList> {
  const search = new URLSearchParams();
  if (params?.tag) search.set("tag", params.tag);
  if (params?.category) search.set("category", params.category);
  if (params?.color) search.set("color", params.color);
  search.set("page", String(params?.page ?? 1));
  search.set("page_size", String(params?.page_size ?? 30));
  const query = search.toString();
  const payload = await apiRequest<unknown>(`/api/design/materials${query ? `?${query}` : ""}`);
  return normalizeMaterialListUrls(ensureObjectResponse<MaterialList>(payload, "/api/design/materials"));
}

export async function fetchMaterial(materialId: string): Promise<MaterialItem> {
  const payload = await apiRequest<unknown>(`/api/design/materials/${encodeURIComponent(materialId)}`);
  return normalizeMaterialItemUrls(ensureObjectResponse<MaterialItem>(payload, "/api/design/materials/:materialId"));
}

export async function deleteMaterial(materialId: string): Promise<{ ok: boolean }> {
  const payload = await apiRequest<unknown>(`/api/design/materials/${encodeURIComponent(materialId)}`, {
    method: "DELETE",
  });
  return ensureObjectResponse<{ ok: boolean }>(payload, "/api/design/materials/:materialId");
}

export async function updateMaterialTags(materialId: string, payload: UpdateMaterialTagsPayload): Promise<MaterialItem> {
  const response = await apiRequest<unknown>(`/api/design/materials/${encodeURIComponent(materialId)}/tags`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return normalizeMaterialItemUrls(ensureObjectResponse<MaterialItem>(response, "/api/design/materials/:materialId/tags"));
}

export async function fetchAllMaterialTags(): Promise<string[]> {
  const payload = await apiRequest<unknown>("/api/design/materials/tags/all");
  return ensureArrayResponse<string>(payload);
}

export async function fetchMaterialNetwork(): Promise<NetworkData> {
  const payload = await apiRequest<unknown>("/api/design/materials/network");
  return normalizeNetworkDataUrls(ensureObjectResponse<NetworkData>(payload, "/api/design/materials/network"));
}
