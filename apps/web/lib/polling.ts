import type { ChatSessionRecord, ResearchJobRecord } from "@pm-agent/types";

const TERMINAL_JOB_STATUSES: Set<ResearchJobRecord["status"]> = new Set(["completed", "failed", "cancelled"]);

export function isTerminalJobStatus(status?: ResearchJobRecord["status"] | string): status is ResearchJobRecord["status"] {
  return Boolean(status && TERMINAL_JOB_STATUSES.has(status as ResearchJobRecord["status"]));
}

export function hasPendingDeltaReply(session?: Pick<ChatSessionRecord, "messages"> | null): boolean {
  if (!session?.messages?.length) {
    return false;
  }

  const lastAssistantMessage = [...session.messages].reverse().find((message) => message.role === "assistant");
  const lastTriggeredDeltaId = lastAssistantMessage?.triggered_delta_job_id;
  if (!lastTriggeredDeltaId) {
    return false;
  }

  return !session.messages.some(
    (message) => message.role === "assistant" && message.triggered_delta_job_id === lastTriggeredDeltaId && message.id !== lastAssistantMessage?.id,
  );
}

export function getPollingInterval(
  status?: ResearchJobRecord["status"] | string,
  options?: {
    keepHot?: boolean;
    activeMs?: number;
    idleMs?: number;
  },
): number {
  const { keepHot = false, activeMs = 1500, idleMs = 10000 } = options ?? {};
  return keepHot || !isTerminalJobStatus(status) ? activeMs : idleMs;
}
