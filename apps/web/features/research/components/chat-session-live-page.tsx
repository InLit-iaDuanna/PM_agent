"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useQuery } from "@tanstack/react-query";
import type { ResearchJobRecord } from "@pm-agent/types";

import { fetchChatSession, fetchResearchAssets, fetchResearchJob, getApiErrorMessage } from "../../../lib/api-client";
import { buildDemoAssets, buildDemoChatSession, buildDemoJob } from "../../../lib/demo-data";
import { getPollingInterval, hasPendingDeltaReply } from "../../../lib/polling";
import { useResearchJobStream } from "../hooks/use-research-job-stream";
import { useResearchUiStore } from "../store/ui-store";
import { PmChatPanel } from "./pm-chat-panel";
import { RequestStateCard } from "./request-state-card";

export function ChatSessionLivePage({ sessionId }: { sessionId: string }) {
  const isDemoSession = sessionId === "demo-session";
  const { setCurrentJobId } = useResearchUiStore();
  const jobStatusRef = useRef<ResearchJobRecord["status"]>();
  const [streamJobId, setStreamJobId] = useState<string | undefined>(isDemoSession ? "demo-job" : undefined);
  const jobStream = useResearchJobStream({
    enabled: !isDemoSession && Boolean(streamJobId),
    jobId: streamJobId,
    sessionId,
  });

  const sessionQuery = useQuery({
    queryKey: ["chat-session-page", sessionId],
    queryFn: () => (isDemoSession ? Promise.resolve(buildDemoChatSession(sessionId)) : fetchChatSession(sessionId)),
    initialData: isDemoSession ? buildDemoChatSession(sessionId) : undefined,
    refetchInterval: ({ state }) =>
      jobStream.shouldPoll ? getPollingInterval(jobStatusRef.current, { keepHot: hasPendingDeltaReply(state.data) }) : false,
  });
  const researchJobId = sessionQuery.data?.research_job_id;

  const assetsQuery = useQuery({
    queryKey: ["chat-session-assets", sessionQuery.data?.research_job_id],
    queryFn: () =>
      isDemoSession
        ? Promise.resolve(buildDemoAssets("demo-job"))
        : fetchResearchAssets(sessionQuery.data?.research_job_id || ""),
    enabled: Boolean(sessionQuery.data?.research_job_id),
    initialData: isDemoSession ? buildDemoAssets("demo-job") : undefined,
    refetchInterval: () =>
      jobStream.shouldPoll ? getPollingInterval(jobStatusRef.current, { keepHot: hasPendingDeltaReply(sessionQuery.data) }) : false,
  });

  const jobQuery = useQuery({
    queryKey: ["chat-session-job", sessionQuery.data?.research_job_id],
    queryFn: () =>
      isDemoSession
        ? Promise.resolve(buildDemoJob("demo-job"))
        : fetchResearchJob(sessionQuery.data?.research_job_id || ""),
    enabled: Boolean(sessionQuery.data?.research_job_id),
    initialData: isDemoSession ? buildDemoJob("demo-job") : undefined,
    refetchInterval: ({ state }) =>
      jobStream.shouldPoll
        ? getPollingInterval(state.data?.status, { keepHot: hasPendingDeltaReply(sessionQuery.data), activeMs: 1000 })
        : false,
  });

  useEffect(() => {
    jobStatusRef.current = jobQuery.data?.status;
  }, [jobQuery.data?.status]);

  useEffect(() => {
    if (researchJobId) {
      setStreamJobId(researchJobId);
    }
  }, [researchJobId]);

  useEffect(() => {
    if (!jobStream.isStreaming || !researchJobId) {
      return;
    }
    void Promise.all([sessionQuery.refetch(), assetsQuery.refetch(), jobQuery.refetch()]);
  }, [assetsQuery.refetch, jobQuery.refetch, jobStream.isStreaming, researchJobId, sessionQuery.refetch]);

  const errorMessage = [sessionQuery.error, assetsQuery.error, jobQuery.error].find(Boolean);
  const session = useMemo(() => (isDemoSession ? buildDemoChatSession(sessionId) : sessionQuery.data), [isDemoSession, sessionId, sessionQuery.data]);
  const assets = useMemo(() => (isDemoSession ? buildDemoAssets("demo-job") : assetsQuery.data), [assetsQuery.data, isDemoSession]);
  const job = useMemo(() => (isDemoSession ? buildDemoJob("demo-job") : jobQuery.data), [isDemoSession, jobQuery.data]);

  useEffect(() => {
    if (researchJobId) {
      setCurrentJobId(researchJobId);
    }
  }, [researchJobId, setCurrentJobId]);

  if (errorMessage) {
    return (
      <RequestStateCard
        actionLabel="重新加载"
        description={getApiErrorMessage(errorMessage, "无法加载对话记录，请检查当前服务配置。")}
        onAction={() => {
          void Promise.all([sessionQuery.refetch(), assetsQuery.refetch(), jobQuery.refetch()]);
        }}
        title="对话记录加载失败"
      />
    );
  }

  if (!session || !assets || !job) {
    return <RequestStateCard description="正在加载对话记录与研究结果。" loading title="正在打开研究对话" />;
  }

  return <PmChatPanel assets={assets} job={job} realtimeConnected={jobStream.isStreaming} session={session} />;
}
