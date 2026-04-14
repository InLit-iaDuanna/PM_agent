"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { ChatSessionRecord, ResearchAssetsRecord, ResearchJobRecord } from "@pm-agent/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { createChatSession, fetchChatSession, fetchResearchAssets, fetchResearchJob, getApiErrorMessage } from "../../../lib/api-client";
import { buildDemoAssets, buildDemoChatSession, buildDemoJob } from "../../../lib/demo-data";
import { getPollingInterval, hasPendingDeltaReply } from "../../../lib/polling";
import { useResearchJobStream } from "../hooks/use-research-job-stream";
import { useResearchUiStore } from "../store/ui-store";
import { RequestStateCard } from "./request-state-card";
import { ResearchWorkbench } from "./research-workbench";

export function ResearchJobLivePage({
  jobId,
  initialJob,
  initialAssets,
}: {
  jobId: string;
  initialJob?: ResearchJobRecord;
  initialAssets?: ResearchAssetsRecord;
}) {
  const { selectedClaimId, selectedTaskId, setCurrentJobId, setSelectedClaimId, setSelectedTaskId } = useResearchUiStore();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionBootstrapError, setSessionBootstrapError] = useState<string | null>(null);
  const isDemoJob = jobId === "demo-job";
  const queryClient = useQueryClient();
  const jobStatusRef = useRef<ResearchJobRecord["status"] | undefined>(undefined);
  const deltaPendingRef = useRef(false);
  const jobStream = useResearchJobStream({ enabled: !isDemoJob, jobId, sessionId });

  const jobQuery = useQuery({
    queryKey: ["research-job", jobId],
    queryFn: () => (isDemoJob ? Promise.resolve(buildDemoJob(jobId)) : fetchResearchJob(jobId)),
    initialData: isDemoJob ? buildDemoJob(jobId) : initialJob,
    refetchInterval: ({ state }) => (jobStream.shouldPoll ? getPollingInterval(state.data?.status, { activeMs: 1000 }) : false),
  });

  const assetsQuery = useQuery({
    queryKey: ["research-assets", jobId],
    queryFn: () => (isDemoJob ? Promise.resolve(buildDemoAssets(jobId)) : fetchResearchAssets(jobId)),
    initialData: isDemoJob ? buildDemoAssets(jobId) : initialAssets,
    refetchInterval: () => (jobStream.shouldPoll ? getPollingInterval(jobStatusRef.current, { keepHot: deltaPendingRef.current }) : false),
  });

  useEffect(() => {
    jobStatusRef.current = jobQuery.data?.status;
  }, [jobQuery.data?.status]);

  useEffect(() => {
    setCurrentJobId(jobId);
  }, [jobId, setCurrentJobId]);

  useEffect(() => {
    let cancelled = false;
    if (isDemoJob) {
      setSessionId("demo-session");
      setSessionBootstrapError(null);
      return () => {
        cancelled = true;
      };
    }

    if (!sessionId) {
      createChatSession(jobId)
        .then((session) => {
          if (!cancelled) {
            queryClient.setQueryData(["chat-session", session.id], session);
            queryClient.setQueryData(["chat-session-page", session.id], session);
            setSessionId(session.id);
            setSessionBootstrapError(null);
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setSessionBootstrapError(getApiErrorMessage(error, "实时对话暂未连上，你仍可先查看已保存的研究内容。"));
          }
        });
    }
    return () => {
      cancelled = true;
    };
  }, [isDemoJob, jobId, queryClient, sessionId]);

  const chatQuery = useQuery<ChatSessionRecord>({
    queryKey: ["chat-session", sessionId],
    queryFn: () =>
      sessionId === "demo-session" ? Promise.resolve(buildDemoChatSession(sessionId, jobId)) : fetchChatSession(sessionId || ""),
    initialData: sessionId === "demo-session" ? buildDemoChatSession(sessionId, jobId) : undefined,
    enabled: Boolean(sessionId),
    refetchInterval: ({ state }) =>
      jobStream.shouldPoll ? getPollingInterval(jobStatusRef.current, { keepHot: hasPendingDeltaReply(state.data) }) : false,
  });

  useEffect(() => {
    deltaPendingRef.current = hasPendingDeltaReply(chatQuery.data);
  }, [chatQuery.data]);

  useEffect(() => {
    if (!jobStream.isStreaming) {
      return;
    }
    if (sessionId) {
      void Promise.all([jobQuery.refetch(), assetsQuery.refetch(), chatQuery.refetch()]);
      return;
    }
    void Promise.all([jobQuery.refetch(), assetsQuery.refetch()]);
  }, [assetsQuery.refetch, chatQuery.refetch, jobQuery.refetch, jobStream.isStreaming, sessionId]);

  useEffect(() => {
    const tasks = jobQuery.data?.tasks ?? [];
    if (!tasks.length) {
      return;
    }
    const selectedTaskExists = tasks.some((task) => task.id === selectedTaskId);
    if (!selectedTaskId || !selectedTaskExists) {
      setSelectedTaskId(tasks[0].id);
    }
  }, [jobQuery.data?.tasks, selectedTaskId, setSelectedTaskId]);

  useEffect(() => {
    const hasSelectedClaim = Boolean(assetsQuery.data?.claims?.some((claim) => claim.id === selectedClaimId));
    if (selectedClaimId && !hasSelectedClaim) {
      setSelectedClaimId(undefined);
    }
  }, [assetsQuery.data?.claims, selectedClaimId, setSelectedClaimId]);

  const chatSession = useMemo(
    () =>
      sessionId === "demo-session"
        ? buildDemoChatSession(sessionId, jobId)
        : chatQuery.data || {
            id: sessionId || `chat-unavailable-${jobId}`,
            research_job_id: jobId,
            messages: [],
          },
    [chatQuery.data, jobId, sessionId],
  );

  const errorMessage = [jobQuery.error, assetsQuery.error].find(Boolean);
  const chatDisabledReason =
    sessionBootstrapError || (chatQuery.error ? getApiErrorMessage(chatQuery.error, "对话连接暂未就绪，你仍可先查看报告和证据。") : null);

  if (errorMessage) {
    return (
      <RequestStateCard
        actionLabel="重新加载"
        description={getApiErrorMessage(errorMessage, "恢复研究现场时遇到中断。重新连接后，会继续展示已保存的研究内容。")}
        onAction={() => {
          setSessionId(isDemoJob ? "demo-session" : null);
          setSessionBootstrapError(null);
          void Promise.all([jobQuery.refetch(), assetsQuery.refetch(), chatQuery.refetch()]);
        }}
        title="恢复研究现场失败"
      />
    );
  }

  if (!jobQuery.data || !assetsQuery.data || !chatSession) {
    return <RequestStateCard description="正在连接实时进展；连接完成前会先恢复已保存内容。" loading title="正在恢复研究现场" />;
  }

  return (
    <ResearchWorkbench
      assets={assetsQuery.data}
      chatDisabledReason={chatDisabledReason}
      job={jobQuery.data}
      realtimeConnected={jobStream.isStreaming}
      session={chatSession}
    />
  );
}
