"use client";

import Link from "next/link";
import { SendHorizonal } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type {
  ChatAnswerMode,
  ChatMessageRecord,
  ChatSessionRecord,
  ReportQualityGateRecord,
  ResearchAssetsRecord,
  ResearchJobRecord,
} from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, Textarea } from "@pm-agent/ui";
import { finalizeResearchReport, getApiErrorMessage, sendChatMessage } from "../../../lib/api-client";
import { MarkdownContent } from "./markdown-content";
import { getActiveReportVersionId, getStableReportVersionId } from "./report-version-utils";
import { useResearchUiStore } from "../store/ui-store";

function reportLabel(stage?: string) {
  if (stage === "final") return "终稿";
  if (stage === "feedback_pending") return "待更新";
  if (stage === "draft") return "初稿";
  return "生成中";
}

const STARTER_PROMPTS = [
  "这份研究里最值得优先推进的 3 个动作是什么？",
  "这份研究最需要警惕的 3 个风险是什么？",
  "如果先面向 AI 产品团队，最适合优先验证哪些场景？",
];

const ANSWER_MODE_LABEL: Record<ChatAnswerMode, string> = {
  report_pending: "等待报告初稿",
  report_context: "参考当前报告",
  delta_requested: "正在补研",
  delta_draft: "补研草稿已生成",
  delta_failed: "补研失败",
};

export function PmChatPanel({
  session,
  assets,
  job,
  chatDisabledReason,
  realtimeConnected = false,
}: {
  session: ChatSessionRecord;
  assets: ResearchAssetsRecord;
  job: ResearchJobRecord;
  chatDisabledReason?: string | null;
  realtimeConnected?: boolean;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [composing, setComposing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [finalizeMessage, setFinalizeMessage] = useState<string | null>(null);
  const [finalizingDraft, setFinalizingDraft] = useState(false);
  const [pendingAssistantMessage, setPendingAssistantMessage] = useState<ChatMessageRecord | null>(null);
  const { chatDraft, setChatDraft, setActiveTab } = useResearchUiStore();
  const queryClient = useQueryClient();
  const lastAssistantMessage = [...session.messages].reverse().find((message) => message.role === "assistant");
  const assistantMeta = pendingAssistantMessage ?? lastAssistantMessage;
  const lastTriggeredDeltaId = assistantMeta?.triggered_delta_job_id;
  const hasDeltaFollowUp =
    Boolean(lastTriggeredDeltaId) &&
    session.messages.some(
      (message) =>
        message.role === "assistant" &&
        message.triggered_delta_job_id === lastTriggeredDeltaId &&
        message.id !== assistantMeta?.id,
    );
  const deltaPending = Boolean(lastTriggeredDeltaId) && !hasDeltaFollowUp;

  useEffect(() => {
    if (pendingAssistantMessage && lastAssistantMessage?.id === pendingAssistantMessage.id) {
      setPendingAssistantMessage(null);
    }
  }, [lastAssistantMessage?.id, pendingAssistantMessage]);

  const stableVersionId = getStableReportVersionId(job);
  const activeVersionId = getActiveReportVersionId(job);
  const hasStableVersion = Boolean(stableVersionId);
  const hasVersionMismatch = Boolean(stableVersionId && activeVersionId && stableVersionId !== activeVersionId);
  const reportReady = Boolean(assets.report?.markdown?.trim());
  const reportStage = assets.report?.stage;
  const qualityGate: ReportQualityGateRecord | undefined = assets.report?.quality_gate;
  const finalizeBlocked = !qualityGate?.pending && qualityGate?.passed === false;
  const trimmedDraft = chatDraft.trim();
  const chatEnabled = !chatDisabledReason;
  const canSend = reportReady && chatEnabled && !submitting && Boolean(trimmedDraft);
  const diffButtonLabel = hasVersionMismatch ? "查看版本差异" : hasStableVersion ? "版本差异暂不可用" : "等待稳定版";
  const finalizeSourceVersionId = assistantMeta?.draft_version_id ?? activeVersionId ?? job.report_version_id;

  const onSendMessage = async () => {
    if (!chatEnabled) return;
    if (!trimmedDraft) return;
    const createdAt = new Date().toISOString();
    const optimisticMessage: ChatMessageRecord = {
      id: `optimistic-${session.id}-${createdAt}`,
      role: "user",
      content: trimmedDraft,
      cited_claim_ids: [],
      created_at: createdAt,
    };
    const previousSession = queryClient.getQueryData<ChatSessionRecord>(["chat-session", session.id]);
    const previousSessionPage = queryClient.getQueryData<ChatSessionRecord>(["chat-session-page", session.id]);
    const appendOptimisticMessage = (currentSession?: ChatSessionRecord) =>
      currentSession
        ? {
            ...currentSession,
            messages: [...currentSession.messages, optimisticMessage],
            updated_at: createdAt,
          }
        : currentSession;

    setSubmitting(true);
    setErrorMessage(null);
    setChatDraft("");
    queryClient.setQueryData<ChatSessionRecord>(["chat-session", session.id], appendOptimisticMessage);
    queryClient.setQueryData<ChatSessionRecord>(["chat-session-page", session.id], appendOptimisticMessage);
    try {
      const result = await sendChatMessage(session.id, trimmedDraft);
      setPendingAssistantMessage(result.message);
      const replaceOptimisticMessage = (currentSession?: ChatSessionRecord) => {
        if (!currentSession) {
          return currentSession;
        }
        const hasAssistantMessage = currentSession.messages.some((message) => message.id === result.message.id);
        const messages = currentSession.messages.map((message) => {
          if (message.id === optimisticMessage.id) {
            return optimisticMessage;
          }
          return message;
        });
        if (!hasAssistantMessage) {
          messages.push(result.message);
        }
        return { ...currentSession, messages };
      };

      queryClient.setQueryData(["chat-session", session.id], replaceOptimisticMessage);
      queryClient.setQueryData(["chat-session-page", session.id], replaceOptimisticMessage);

      const refreshTasks: Promise<unknown>[] = [
        queryClient.invalidateQueries({ queryKey: ["chat-session", session.id] }),
        queryClient.invalidateQueries({ queryKey: ["chat-session-page", session.id] }),
      ];
      if (!realtimeConnected) {
        refreshTasks.push(
          queryClient.invalidateQueries({ queryKey: ["research-assets", session.research_job_id] }),
          queryClient.invalidateQueries({ queryKey: ["chat-session-assets", session.research_job_id] }),
          queryClient.invalidateQueries({ queryKey: ["research-job", session.research_job_id] }),
          queryClient.invalidateQueries({ queryKey: ["chat-session-job", session.research_job_id] }),
        );
      }
      if (realtimeConnected) {
        void Promise.all(refreshTasks);
      } else {
        await Promise.all(refreshTasks);
      }
    } catch (error) {
      setChatDraft(trimmedDraft);
      if (previousSession) {
        queryClient.setQueryData(["chat-session", session.id], previousSession);
      }
      if (previousSessionPage) {
        queryClient.setQueryData(["chat-session-page", session.id], previousSessionPage);
      }
      setErrorMessage(getApiErrorMessage(error, "发送消息失败。"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleComposerKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || composing || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    void onSendMessage();
  };

  const handleFinalizeDraft = async () => {
    if (!reportReady || !assistantMeta?.requires_finalize || !finalizeSourceVersionId || finalizingDraft || finalizeBlocked) {
      return;
    }
    setFinalizingDraft(true);
    setFinalizeMessage(null);
    try {
      const nextAssets = await finalizeResearchReport(job.id, finalizeSourceVersionId);
      queryClient.setQueryData(["research-assets", job.id], nextAssets);
      queryClient.setQueryData(["chat-session-assets", job.id], nextAssets);
      const nextQualityGate = nextAssets.report?.quality_gate;
      const nextGateBlocked = !nextQualityGate?.pending && nextQualityGate?.passed === false;
      setFinalizeMessage(
        nextGateBlocked
          ? nextQualityGate?.reasons?.[0] || "当前草稿还没达到终稿门槛，系统已继续保留为工作稿。"
          : `已基于 ${finalizeSourceVersionId} 生成新的可分享版本。`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["research-assets", job.id] }),
        queryClient.invalidateQueries({ queryKey: ["chat-session-assets", job.id] }),
        queryClient.invalidateQueries({ queryKey: ["research-job", session.research_job_id] }),
        queryClient.invalidateQueries({ queryKey: ["chat-session-job", session.research_job_id] }),
        queryClient.invalidateQueries({ queryKey: ["chat-session", session.id] }),
        queryClient.invalidateQueries({ queryKey: ["chat-session-page", session.id] }),
      ]);
    } catch (error) {
      setFinalizeMessage(getApiErrorMessage(error, "生成可分享版本失败。"));
    } finally {
      setFinalizingDraft(false);
    }
  };

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <CardTitle>研究对话</CardTitle>
          <CardDescription>基于当前报告继续追问，必要时补充修改意见。</CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone={reportReady ? "success" : "warning"}>{reportReady ? "报告已接入" : "等待报告"}</Badge>
          <Badge tone={reportStage === "final" ? "success" : "default"}>{reportLabel(reportStage)}</Badge>
          <Badge tone={realtimeConnected ? "success" : "warning"}>{realtimeConnected ? "实时更新" : "自动刷新"}</Badge>
          {stableVersionId ? <Badge tone="success">{`稳定 ${stableVersionId}`}</Badge> : <Badge tone="default">等待稳定版</Badge>}
          {activeVersionId ? (
            <Badge tone={hasVersionMismatch ? "warning" : "default"}>{`工作稿 ${activeVersionId}`}</Badge>
          ) : null}
          {assistantMeta?.answer_mode ? (
            <Badge tone="warning">{ANSWER_MODE_LABEL[assistantMeta.answer_mode]}</Badge>
          ) : null}
          {assistantMeta?.draft_version_id ? (
            <Badge tone="warning">{`补研草稿 ${assistantMeta.draft_version_id}`}</Badge>
          ) : null}
          {assistantMeta?.requires_finalize ? <Badge tone="danger">需生成稳定版</Badge> : null}
          {chatDisabledReason ? <Badge tone="warning">对话暂不可用</Badge> : null}
        </div>
      </div>

      {chatDisabledReason ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{chatDisabledReason}</div>
      ) : null}

      <div className="space-y-4">
        {session.messages.length ? (
          session.messages.map((message) => (
            <div key={message.id} className={`flex ${message.role === "assistant" ? "justify-start" : "justify-end"}`}>
              <div
                className={`w-full max-w-[56rem] rounded-[28px] border p-5 shadow-sm shadow-slate-950/5 ${
                  message.role === "assistant"
                    ? "border-slate-200 bg-gradient-to-br from-white via-slate-50 to-slate-100/80"
                    : "border-slate-200 bg-white"
                }`}
              >
                <div className="mb-3 flex items-center justify-between gap-3">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">
                    {message.role === "assistant" ? "助手" : "你"}
                  </span>
                  {message.triggered_delta_job_id ? <Badge tone="warning">{message.triggered_delta_job_id}</Badge> : null}
                </div>
                <MarkdownContent content={message.content} variant="chat" />
                {message.cited_claim_ids.length ? (
                  <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-200/80 pt-3">
                    {message.cited_claim_ids.map((claimId) => (
                      <Badge key={claimId}>{claimId}</Badge>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ))
        ) : (
          <div className="rounded-[28px] border border-dashed border-slate-200 bg-slate-50 px-5 py-8 text-sm text-slate-500">
            {reportReady
              ? "报告已经准备好，你还没有开始追问。可以直接点下面的快捷问题，或输入更具体的业务问题。"
              : "报告初稿生成前，这里会保持空白；等初稿准备好后，你可以围绕这份报告继续追问。"}
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-slate-100 bg-white p-3">
        <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
          <span>当前依据</span>
          <span>{reportReady ? `报告已接入 · ${reportLabel(reportStage)}` : "等待报告初稿"}</span>
        </div>
        {assistantMeta?.requires_finalize ? (
          <div className="mt-2 space-y-2">
            <p className="text-xs text-rose-600/90">
              本次回答引用了新的草稿，需要回到报告模块完成{" "}
              {assistantMeta.draft_version_id ? `草稿 ${assistantMeta.draft_version_id}` : "工作稿"} 的生成稳定版操作。
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                disabled={!finalizeSourceVersionId || finalizingDraft || finalizeBlocked}
                onClick={() => {
                  void handleFinalizeDraft();
                }}
              >
                {finalizingDraft ? "生成中..." : finalizeBlocked ? "先补充证据" : "直接生成可分享版"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setActiveTab("latest-draft")}
              >
                审阅最新草稿
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={!hasVersionMismatch}
                onClick={() => setActiveTab("diff")}
                title={hasVersionMismatch ? "查看此草稿与稳定版的差异" : "当前尚未生成版本差异"}
              >
                {diffButtonLabel}
              </Button>
            </div>
            {finalizeMessage ? <p className="text-xs text-slate-500">{finalizeMessage}</p> : null}
          </div>
        ) : null}
        <p className="text-sm text-slate-600">
          {!reportReady
            ? "当前还在生成报告初稿。可用后这里会自动切换为可对话状态。"
            : deltaPending
            ? "这个问题超出了当前报告范围，系统正在补充研究。"
            : reportStage === "feedback_pending"
            ? "回答会优先参考当前报告和已补充结论，正式版更新后会自动切换到最新版本。"
            : "回答会优先参考当前报告和已采集来源。若你提出修改意见，系统会先记录补充结果，再用于后续版本更新。"}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            className="inline-flex items-center justify-center rounded-xl bg-slate-100 px-3 py-2 text-sm font-medium text-slate-900 transition hover:bg-slate-200"
            href={`/research/jobs/${job.id}/report`}
          >
            查看完整报告
          </Link>
          {job.report_version_id ? (
            <Link
              className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              href={`/research/jobs/${job.id}/report?version=${encodeURIComponent(job.report_version_id)}`}
            >
              查看当前版本
            </Link>
          ) : null}
        </div>
      </div>

      <div className="rounded-2xl border border-slate-100 bg-white p-3">
        <Textarea
          disabled={!reportReady || !chatEnabled || submitting}
          onChange={(event) => setChatDraft(event.target.value)}
          onCompositionEnd={() => setComposing(false)}
          onCompositionStart={() => setComposing(true)}
          onKeyDown={handleComposerKeyDown}
          placeholder={
            reportReady ? "继续追问产品策略、竞品、用户问题，或直接补充修改意见..." : "等待报告初稿生成后再开始追问"
          }
          rows={4}
          value={chatDraft}
        />
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-slate-500">
            {chatDisabledReason
              ? "当前为只读状态，你仍然可以继续查看报告和来源。"
              : !reportReady
              ? "报告初稿可用后才能开始对话。"
              : realtimeConnected
              ? "实时连接已建立，Enter 发送，Shift+Enter 换行。"
              : "实时连接暂不可用，系统会稍后自动刷新；Enter 发送，Shift+Enter 换行。"}
          </p>
          <Button disabled={!canSend} onClick={onSendMessage} type="button">
            <SendHorizonal className="mr-2 h-4 w-4" />
            {submitting ? "发送中" : reportReady ? "发送" : "等待初稿"}
          </Button>
        </div>
        {reportReady ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {STARTER_PROMPTS.map((prompt) => (
              <Button key={prompt} disabled={submitting || !chatEnabled} onClick={() => setChatDraft(prompt)} type="button" variant="ghost">
                {prompt}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
      {errorMessage ? <p className="text-sm text-red-600">{errorMessage}</p> : null}
    </Card>
  );
}
