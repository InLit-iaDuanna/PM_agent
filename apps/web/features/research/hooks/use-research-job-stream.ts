"use client";

import { useEffect, useRef, useState } from "react";

import type { ChatSessionRecord, ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { useQueryClient } from "@tanstack/react-query";

import { getApiBaseUrl, getApiBaseUrlCandidates, setApiBaseUrl, subscribeApiBaseUrl } from "../../../lib/api-base-url";

const STREAM_EVENT_NAMES = [
  "chat.session.updated",
  "job.progress",
  "job.failed",
  "job.cancelled",
  "task.started",
  "task.progress",
  "task.completed",
  "task.failed",
  "claim.generated",
  "report.section.completed",
  "report.finalized",
  "report.finalize_blocked",
  "delta_research.started",
  "delta_research.completed",
  "delta_research.failed",
] as const;

type StreamConnectionState = "idle" | "connecting" | "open" | "fallback";

type ResearchJobStreamPayload = {
  assets?: ResearchAssetsRecord;
  job?: ResearchJobRecord;
  session?: ChatSessionRecord;
  session_id?: string;
};

function sortJobs(jobs: ResearchJobRecord[]): ResearchJobRecord[] {
  return [...jobs].sort((left, right) => {
    const leftTimestamp = left.updated_at || left.completed_at || left.created_at || "";
    const rightTimestamp = right.updated_at || right.completed_at || right.created_at || "";
    return rightTimestamp.localeCompare(leftTimestamp);
  });
}

function upsertJob(jobs: ResearchJobRecord[] | undefined, nextJob: ResearchJobRecord): ResearchJobRecord[] {
  const currentJobs = jobs ?? [];
  const nextJobs = currentJobs.some((job) => job.id === nextJob.id)
    ? currentJobs.map((job) => (job.id === nextJob.id ? nextJob : job))
    : [nextJob, ...currentJobs];
  return sortJobs(nextJobs);
}

function buildStreamUrl(baseUrl: string, jobId: string): string {
  return `${baseUrl}/api/stream/jobs/${encodeURIComponent(jobId)}`;
}

export function useResearchJobStream({
  enabled = true,
  jobId,
  sessionId,
}: {
  enabled?: boolean;
  jobId?: string | null;
  sessionId?: string | null;
}) {
  const queryClient = useQueryClient();
  const [connectionState, setConnectionState] = useState<StreamConnectionState>("idle");
  const [activeBaseUrl, setActiveBaseUrl] = useState(() => getApiBaseUrl());
  const activeJobIdRef = useRef<string | null | undefined>(jobId);
  const activeSessionIdRef = useRef<string | null | undefined>(sessionId);

  useEffect(() => {
    activeJobIdRef.current = jobId;
  }, [jobId]);

  useEffect(() => {
    activeSessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => subscribeApiBaseUrl(setActiveBaseUrl), []);

  useEffect(() => {
    if (!enabled || !jobId || typeof window === "undefined" || typeof window.EventSource === "undefined") {
      setConnectionState("idle");
      return;
    }

    let closed = false;
    let eventSource: EventSource | null = null;
    let retryTimer: number | null = null;
    let connectTimer: number | null = null;

    const clearTimers = () => {
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
        retryTimer = null;
      }
      if (connectTimer !== null) {
        window.clearTimeout(connectTimer);
        connectTimer = null;
      }
    };

    const closeSource = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      clearTimers();
    };

    const applyPayload = (payload: ResearchJobStreamPayload) => {
      const activeJobId = activeJobIdRef.current;
      if (!activeJobId) {
        return;
      }

      if (payload.job) {
        queryClient.setQueryData<ResearchJobRecord>(["research-job", activeJobId], payload.job);
        queryClient.setQueryData<ResearchJobRecord>(["chat-session-job", activeJobId], payload.job);
        queryClient.setQueryData<ResearchJobRecord[]>(["research-jobs"], (currentJobs) => upsertJob(currentJobs, payload.job as ResearchJobRecord));
      }

      if (payload.assets) {
        queryClient.setQueryData<ResearchAssetsRecord>(["research-assets", activeJobId], payload.assets);
        queryClient.setQueryData<ResearchAssetsRecord>(["chat-session-assets", activeJobId], payload.assets);
      }

      if (payload.session) {
        queryClient.setQueryData<ChatSessionRecord>(["chat-session", payload.session.id], payload.session);
        queryClient.setQueryData<ChatSessionRecord>(["chat-session-page", payload.session.id], payload.session);
        return;
      }

      const nextSessionId = payload.session_id || activeSessionIdRef.current;
      if (!nextSessionId) {
        return;
      }

      void queryClient.invalidateQueries({ queryKey: ["chat-session", nextSessionId], exact: true });
      void queryClient.invalidateQueries({ queryKey: ["chat-session-page", nextSessionId], exact: true });
    };

    const scheduleReconnect = (attemptIndex: number, delayMs: number) => {
      if (closed) {
        return;
      }
      setConnectionState("fallback");
      clearTimers();
      retryTimer = window.setTimeout(() => {
        connect(attemptIndex);
      }, delayMs);
    };

    const connect = (attemptIndex: number) => {
      if (closed) {
        return;
      }

      const candidates = getApiBaseUrlCandidates();
      if (!candidates.length) {
        setConnectionState("fallback");
        return;
      }

      closeSource();
      setConnectionState("connecting");

      const candidateIndex = candidates.indexOf(activeBaseUrl);
      const startIndex = candidateIndex >= 0 ? candidateIndex : 0;
      const baseUrl = candidates[(startIndex + attemptIndex) % candidates.length];
      const nextSource = new window.EventSource(buildStreamUrl(baseUrl, jobId), { withCredentials: true });
      let opened = false;

      eventSource = nextSource;
      connectTimer = window.setTimeout(() => {
        if (opened || closed || eventSource !== nextSource) {
          return;
        }
        nextSource.close();
        if (eventSource === nextSource) {
          eventSource = null;
        }
        scheduleReconnect(attemptIndex + 1, 250);
      }, 2500);

      nextSource.onopen = () => {
        if (closed || eventSource !== nextSource) {
          return;
        }
        opened = true;
        clearTimers();
        setApiBaseUrl(baseUrl);
        setConnectionState("open");
      };

      nextSource.onerror = () => {
        if (closed || eventSource !== nextSource) {
          return;
        }
        nextSource.close();
        if (eventSource === nextSource) {
          eventSource = null;
        }
        scheduleReconnect(attemptIndex + 1, opened ? 1200 : 250);
      };

      for (const eventName of STREAM_EVENT_NAMES) {
        nextSource.addEventListener(eventName, (event) => {
          if (closed || eventSource !== nextSource) {
            return;
          }

          const messageEvent = event as MessageEvent<string>;
          try {
            const payload = messageEvent.data ? (JSON.parse(messageEvent.data) as ResearchJobStreamPayload) : {};
            applyPayload(payload);
          } catch {
            return;
          }
        });
      }
    };

    connect(0);

    return () => {
      closed = true;
      closeSource();
      setConnectionState("idle");
    };
  }, [activeBaseUrl, enabled, jobId, queryClient]);

  return {
    connectionState,
    isStreaming: connectionState === "open",
    shouldPoll: !enabled || connectionState !== "open",
  };
}
