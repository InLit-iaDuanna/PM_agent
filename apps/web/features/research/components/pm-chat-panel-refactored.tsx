"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { FileText, SendHorizonal, Sparkles } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import type {
  ChatAnswerMode,
  ChatMessageRecord,
  ChatSessionRecord,
  ReportQualityGateRecord,
  ResearchAssetsRecord,
  ResearchJobRecord,
} from "@pm-agent/types";
import { Badge, Button, Tooltip } from "@pm-agent/ui";

import { finalizeResearchReport, getApiErrorMessage, sendChatMessage } from "../../../lib/api-client";
import { useResearchUiStore } from "../store/ui-store";
import { MarkdownContent } from "./markdown-content";
import { getActiveReportVersionId, getStableReportVersionId } from "./report-version-utils";

type ChatSourceRef = {
  id: string;
  source_url: string;
  title?: string;
  citation_label?: string;
};

function parseSourceRefs(message: ChatMessageRecord): ChatSourceRef[] {
  const rawRefs = (message as ChatMessageRecord & { source_refs?: unknown }).source_refs;
  if (!Array.isArray(rawRefs)) return [];

  const normalized: ChatSourceRef[] = [];
  for (const item of rawRefs) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const id = String(record.id || "").trim();
    const sourceUrl = String(record.source_url || "").trim();
    if (!id || !sourceUrl) continue;
    normalized.push({
      id,
      source_url: sourceUrl,
      title: String(record.title || "").trim() || undefined,
      citation_label: String(record.citation_label || "").trim() || undefined,
    });
  }
  return normalized;
}

const STARTER_PROMPTS = [
  "What are the key risks in this market?",
  "What should we validate first?",
  "Which findings matter most for product decisions?",
];

const ANSWER_MODE_LABEL: Record<ChatAnswerMode, string> = {
  report_pending: "等待报告初稿",
  report_context: "参考当前报告",
  delta_requested: "正在补研",
  delta_draft: "补研草稿已生成",
  delta_failed: "补研失败",
};

const ANSWER_MODE_TONE: Record<ChatAnswerMode, "default" | "success" | "warning" | "danger"> = {
  report_pending: "warning",
  report_context: "success",
  delta_requested: "warning",
  delta_draft: "success",
  delta_failed: "danger",
};

function reportLabel(stage?: string) {
  if (stage === "final") return "终稿";
  if (stage === "feedback_pending") return "待更新";
  if (stage === "draft") return "初稿";
  return "生成中";
}

function MessageBubble({
  message,
  isPending = false,
}: {
  message: ChatMessageRecord;
  isPending?: boolean;
}) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const sourceRefs = parseSourceRefs(message);
  const hasSourceRefs = isAssistant && sourceRefs.length > 0;

  return (
    <div className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={[
          "max-w-[82%] rounded-[24px] border px-4 py-3 shadow-[var(--shadow-sm)] transition-opacity sm:px-5 sm:py-4",
          isPending ? "opacity-60" : "opacity-100",
          isUser
            ? "border-[#dbeafe] bg-[#eff6ff] text-[color:var(--ink)]"
            : "border-[color:var(--border-soft)] bg-white/92 text-[color:var(--ink)]",
        ].join(" ")}
      >
        <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px]">
          <span className="font-medium uppercase tracking-[0.18em] text-[color:var(--muted)]">{isUser ? "You" : "PM Agent"}</span>
          {isAssistant && message.answer_mode ? <Badge tone={ANSWER_MODE_TONE[message.answer_mode]}>{ANSWER_MODE_LABEL[message.answer_mode]}</Badge> : null}
          {isAssistant && message.triggered_delta_job_id ? (
            <Tooltip content="点击跳转到该补研任务">
              <Link
                href={`/research/jobs/${message.triggered_delta_job_id}`}
                className="inline-flex items-center gap-1 rounded-full border border-[color:var(--border-soft)] bg-[rgba(37,99,235,0.08)] px-2 py-1 text-[10px] font-medium text-[#2563eb]"
              >
                <Sparkles className="h-3 w-3" />
                查看补研任务
              </Link>
            </Tooltip>
          ) : null}
          <span className="ml-auto text-[10px] text-[color:var(--muted)]">
            {message.created_at ? new Date(message.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : ""}
          </span>
        </div>

        <div className={isUser ? "text-sm leading-7" : ""}>
          {isUser ? <p className="text-sm leading-7">{message.content}</p> : <MarkdownContent content={message.content} variant="chat" />}
        </div>

        {hasSourceRefs ? (
          <div className="mt-3 border-t border-[color:var(--border-soft)] pt-3">
            <button
              type="button"
              onClick={() => setSourcesOpen((value) => !value)}
              className="flex items-center gap-1.5 text-xs text-[color:var(--muted)] hover:text-[color:var(--ink)]"
            >
              <FileText className="h-3.5 w-3.5" />
              {sourcesOpen ? "收起来源引用" : `展开 ${sourceRefs.length} 条来源引用`}
            </button>
            {sourcesOpen ? (
              <div className="mt-3 space-y-2">
                {sourceRefs.map((ref) => (
                  <a
                    key={ref.id}
                    href={ref.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded-[14px] border border-[color:var(--border-soft)] bg-[rgba(249,250,251,0.95)] px-3 py-3 text-xs text-[color:var(--muted)] hover:text-[color:var(--ink)]"
                  >
                    <div className="flex items-start gap-2">
                      <span className="rounded-[6px] bg-[rgba(37,99,235,0.08)] px-2 py-1 text-[10px] font-semibold text-[#2563eb]">
                        {ref.citation_label || ref.id}
                      </span>
                      <span className="line-clamp-2">{ref.title || ref.source_url}</span>
                    </div>
                  </a>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function DeltaProgressIndicator() {
  return (
    <div className="rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(249,250,251,0.95)] px-4 py-3 text-sm text-[color:var(--muted)]">
      Running targeted research and updating the report context…
    </div>
  );
}

export function PmChatPanelRefactored({
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
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [finalizeMessage, setFinalizeMessage] = useState<string | null>(null);
  const [finalizingDraft, setFinalizingDraft] = useState(false);
  const [pendingMsg, setPendingMsg] = useState<ChatMessageRecord | null>(null);
  const { chatDraft, setChatDraft } = useResearchUiStore();
  const queryClient = useQueryClient();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const lastAssistant = [...session.messages].reverse().find((message) => message.role === "assistant");
  const assistantMeta = pendingMsg ?? lastAssistant;
  const deltaPending =
    Boolean(assistantMeta?.triggered_delta_job_id) &&
    !session.messages.some(
      (message) =>
        message.role === "assistant" &&
        message.triggered_delta_job_id === assistantMeta?.triggered_delta_job_id &&
        message.id !== assistantMeta?.id,
    );

  const stableVersionId = getStableReportVersionId(job);
  const activeVersionId = getActiveReportVersionId(job);
  const hasStableVersion = Boolean(stableVersionId);
  const reportReady = Boolean(assets.report?.markdown?.trim());
  const qualityGate: ReportQualityGateRecord | undefined = assets.report?.quality_gate;
  const finalizeBlocked = !qualityGate?.pending && qualityGate?.passed === false;
  const chatEnabled = !chatDisabledReason;
  const trimmedDraft = chatDraft.trim();
  const canSend = reportReady && chatEnabled && !submitting && Boolean(trimmedDraft);

  useEffect(() => {
    if (pendingMsg && lastAssistant?.id === pendingMsg.id) {
      setPendingMsg(null);
    }
  }, [lastAssistant?.id, pendingMsg]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session.messages.length, pendingMsg]);

  const onSend = async () => {
    if (!chatEnabled || !trimmedDraft) return;
    const createdAt = new Date().toISOString();
    const optimistic: ChatMessageRecord = {
      id: `optimistic-${Date.now()}`,
      role: "user",
      content: trimmedDraft,
      cited_claim_ids: [],
      created_at: createdAt,
    };

    const currentDraft = trimmedDraft;
    setChatDraft("");
    setErrorMessage(null);
    setSubmitting(true);

    try {
      const result = await sendChatMessage(session.id, currentDraft);
      const appendMessages = (old: ChatSessionRecord | undefined) => {
        if (!old) return old;
        const withUser = { ...old, messages: [...old.messages, optimistic] };
        const hasAssistant = withUser.messages.some((item) => item.id === result.message.id);
        if (hasAssistant) return withUser;
        return { ...withUser, messages: [...withUser.messages, result.message] };
      };
      setPendingMsg(result.message);
      queryClient.setQueryData(["chat-session", session.id], appendMessages);
      queryClient.setQueryData(["chat-session-page", session.id], appendMessages);
    } catch (error) {
      setChatDraft(currentDraft);
      setErrorMessage(getApiErrorMessage(error, "发送失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      if (canSend) void onSend();
    }
  };

  const handleFinalizeDraft = async () => {
    const draftVersionId = assistantMeta?.draft_version_id ?? activeVersionId ?? job.report_version_id;
    if (!draftVersionId) return;
    setFinalizingDraft(true);
    setFinalizeMessage(null);
    try {
      const nextAssets = await finalizeResearchReport(job.id, draftVersionId);
      queryClient.setQueryData(["research-assets", job.id], nextAssets);
      queryClient.setQueryData(["chat-session-assets", job.id], nextAssets);
      setFinalizeMessage("已更新报告，上一版已自动保留。");
    } catch (error) {
      setFinalizeMessage(getApiErrorMessage(error, "更新报告失败。"));
    } finally {
      setFinalizingDraft(false);
    }
  };

  const allMessages = [...session.messages, ...(pendingMsg ? [pendingMsg] : [])];

  return (
    <div className="minimal-panel flex h-[72vh] min-h-[520px] flex-col overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-4 border-b border-[color:var(--border-soft)] px-5 py-4 sm:px-6">
        <div>
          <p className="text-sm font-semibold text-[color:var(--ink)]">Chat</p>
          <p className="mt-1 text-xs text-[color:var(--muted)]">
            {reportReady ? `Based on ${reportLabel(assets.report?.stage)} · ${stableVersionId ?? "工作草稿"}` : "等待报告生成后可追问"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {hasStableVersion ? (
            <Button asChild variant="ghost">
              <Link href={`/research/jobs/${job.id}/report`}>
                <FileText className="mr-1.5 h-3.5 w-3.5" />
                查看报告
              </Link>
            </Button>
          ) : null}
          <Badge tone={realtimeConnected ? "success" : "default"}>{realtimeConnected ? "实时" : "轮询"}</Badge>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto bg-[rgba(247,248,250,0.72)] px-5 py-5 sm:px-6">
        <div className="mx-auto flex max-w-4xl flex-col gap-4">
          {session.messages.length === 0 ? (
            <div className="flex flex-col items-center gap-4 rounded-[24px] border border-[color:var(--border-soft)] bg-white/88 px-6 py-10 text-center shadow-[var(--shadow-sm)]">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[rgba(37,99,235,0.1)] text-[#2563eb]">
                <Sparkles className="h-5 w-5" />
              </div>
              <div>
                <p className="text-base font-medium text-[color:var(--ink)]">{reportReady ? "Ask a follow-up question" : "报告生成后即可追问"}</p>
                <p className="mt-1 text-sm text-[color:var(--muted)]">当前对话会锚定在研究报告和证据之上，必要时自动触发补研。</p>
              </div>
              {reportReady ? (
                <div className="flex flex-wrap justify-center gap-2">
                  {STARTER_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => setChatDraft(prompt)}
                      className="rounded-full border border-[color:var(--border-soft)] bg-[rgba(249,250,251,0.95)] px-4 py-2 text-xs text-[color:var(--muted)] transition hover:border-[color:var(--border-strong)] hover:text-[color:var(--ink)]"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {allMessages.map((message) => (
            <MessageBubble key={message.id} message={message} isPending={message.id === pendingMsg?.id} />
          ))}

          {deltaPending ? <DeltaProgressIndicator /> : null}

          {assistantMeta?.answer_mode === "delta_draft" && !finalizeBlocked ? (
            <div className="rounded-[18px] border border-emerald-200 bg-emerald-50/90 px-4 py-3 text-sm text-emerald-900">
              <div className="flex flex-wrap items-center gap-3">
                <p className="flex-1">补研草稿已生成，确认后可更新报告。</p>
                <Button disabled={finalizingDraft} onClick={() => void handleFinalizeDraft()} type="button">
                  {finalizingDraft ? "更新中..." : "更新报告"}
                </Button>
              </div>
              {finalizeMessage ? <p className="mt-2 text-xs text-emerald-700">{finalizeMessage}</p> : null}
            </div>
          ) : null}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {chatDisabledReason ? (
        <div className="shrink-0 border-t border-amber-200 bg-amber-50/90 px-5 py-3 text-sm text-amber-900 sm:px-6">{chatDisabledReason}</div>
      ) : null}

      <div className="shrink-0 border-t border-[color:var(--border-soft)] bg-white/92 px-5 py-4 sm:px-6">
        <div className="mx-auto max-w-4xl">
          {errorMessage ? <p className="mb-2 text-xs text-rose-600">{errorMessage}</p> : null}
          <div className="rounded-[22px] border border-[color:var(--border-soft)] bg-[rgba(247,248,250,0.96)] p-2 shadow-[var(--shadow-sm)]">
            <div className="flex items-end gap-3">
              <textarea
                ref={textareaRef}
                value={chatDraft}
                onChange={(event) => setChatDraft(event.target.value)}
                onKeyDown={onKeyDown}
                disabled={!chatEnabled || submitting}
                placeholder={reportReady ? "Ask a follow-up question..." : "等待报告生成后即可追问…"}
                rows={2}
                className="min-h-[52px] flex-1 resize-none rounded-[16px] border-0 bg-transparent px-3 py-2 text-sm text-[color:var(--ink)] outline-none placeholder:text-[color:var(--muted)] disabled:opacity-60"
              />
              <Button type="button" disabled={!canSend} onClick={() => void onSend()} className="h-11 w-11 rounded-full p-0">
                {submitting ? (
                  <span className="h-4 w-4 animate-spin-slow rounded-full border-2 border-white border-t-transparent" />
                ) : (
                  <SendHorizonal className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
          <p className="mt-2 text-[10px] text-[color:var(--muted)]">⌘↵ 发送 · 输入 /delta 触发补研 · /report 跳到报告页</p>
        </div>
      </div>
    </div>
  );
}
