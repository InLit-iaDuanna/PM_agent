"use client";

import Link from "next/link";
import { FileText, SendHorizonal, Sparkles } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

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
  if (!Array.isArray(rawRefs)) {
    return [];
  }
  const normalized: ChatSourceRef[] = [];
  for (const item of rawRefs) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const record = item as Record<string, unknown>;
    const id = String(record.id || "").trim();
    const sourceUrl = String(record.source_url || "").trim();
    if (!id || !sourceUrl) {
      continue;
    }
    normalized.push({
      id,
      source_url: sourceUrl,
      title: String(record.title || "").trim() || undefined,
      citation_label: String(record.citation_label || "").trim() || undefined,
    });
  }
  return normalized;
}

// ─── Constants ─────────────────────────────────────────────────────────────
const STARTER_PROMPTS = [
  "这份研究里最值得优先推进的 3 个动作是什么？",
  "这份研究最需要警惕的 3 个风险是什么？",
  "如果先面向 AI 产品团队，最适合优先验证哪些场景？",
];

const ANSWER_MODE_LABEL: Record<ChatAnswerMode, string> = {
  report_pending:   "等待报告初稿",
  report_context:   "参考当前报告",
  delta_requested:  "正在补研",
  delta_draft:      "补研草稿已生成",
  delta_failed:     "补研失败",
};

const ANSWER_MODE_TONE: Record<ChatAnswerMode, "default" | "success" | "warning" | "danger"> = {
  report_pending:  "warning",
  report_context:  "success",
  delta_requested: "warning",
  delta_draft:     "success",
  delta_failed:    "danger",
};

function reportLabel(stage?: string) {
  if (stage === "final")            return "终稿";
  if (stage === "feedback_pending") return "待更新";
  if (stage === "draft")            return "初稿";
  return "生成中";
}

// ─── Message bubble ─────────────────────────────────────────────────────────
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
    <div
      className={[
        "flex w-full stagger-item",
        isUser ? "justify-end" : "justify-start",
      ].join(" ")}
    >
      <div
        className={[
          "max-w-[85%] rounded-[22px] border p-4 shadow-[var(--shadow-sm)] transition-opacity",
          isPending && "opacity-60",
          isUser
            ? "border-[color:var(--accent)] bg-[linear-gradient(135deg,rgba(29,76,116,0.92),rgba(23,32,51,0.96))] text-white"
            : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.9)]",
        ].join(" ")}
      >
        {/* Meta row */}
        <div className="mb-2.5 flex flex-wrap items-center gap-2">
          <span className={[
            "text-[10px] font-semibold uppercase tracking-[0.2em]",
            isUser ? "text-white/70" : "text-[color:var(--muted)]",
          ].join(" ")}>
            {isUser ? "你" : "PM Agent"}
          </span>
          {isAssistant && message.answer_mode && (
            <Badge tone={ANSWER_MODE_TONE[message.answer_mode]}>
              {ANSWER_MODE_LABEL[message.answer_mode]}
            </Badge>
          )}
          {isAssistant && message.triggered_delta_job_id && (
            <Tooltip content="点击跳转到该补研任务">
              <Link
                href={`/research/jobs/${message.triggered_delta_job_id}`}
                className="inline-flex items-center gap-1 rounded-full border border-[color:var(--accent)] bg-[color:var(--accent-soft)] px-2 py-0.5 text-[10px] font-medium text-[color:var(--accent)]"
              >
                <Sparkles className="h-2.5 w-2.5" />
                查看补研任务
              </Link>
            </Tooltip>
          )}
          <span className={[
            "ml-auto text-[10px]",
            isUser ? "text-white/50" : "text-[color:var(--muted)]",
          ].join(" ")}>
            {message.created_at
              ? new Date(message.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
              : ""}
          </span>
        </div>

        {/* Content */}
        <div className={isUser ? "text-sm leading-7 text-white" : ""}>
          {isUser ? (
            <p className="text-sm leading-7">{message.content}</p>
          ) : (
            <MarkdownContent content={message.content} variant="chat" />
          )}
        </div>

        {/* Source refs toggle */}
        {hasSourceRefs && (
          <div className="mt-3 border-t border-[color:var(--border-soft)] pt-3">
            <button
              type="button"
              onClick={() => setSourcesOpen((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-[color:var(--muted)] hover:text-[color:var(--ink)]"
            >
              <FileText className="h-3 w-3" />
              {sourcesOpen ? "收起来源引用" : `展开 ${sourceRefs.length} 条来源引用`}
            </button>
            {sourcesOpen && (
              <div className="mt-2 animate-fade-in space-y-1.5">
                {sourceRefs.map((ref) => (
                  <a
                    key={ref.id}
                    href={ref.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-start gap-2 rounded-[10px] border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.7)] px-3 py-2 text-xs text-[color:var(--muted-strong)] hover:text-[color:var(--ink)]"
                  >
                    <span className="mt-0.5 shrink-0 rounded-[4px] bg-[color:var(--accent-soft)] px-1.5 py-0.5 text-[10px] font-semibold text-[color:var(--accent)]">
                      {ref.citation_label || ref.id}
                    </span>
                    <span className="line-clamp-2">{ref.title || ref.source_url}</span>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Delta progress inline indicator ───────────────────────────────────────
function DeltaProgressIndicator() {
  return (
    <div className="flex items-center gap-3 rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.7)] px-4 py-3 animate-fade-in">
      <span className="relative flex h-2.5 w-2.5 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[color:var(--accent)] opacity-60" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[color:var(--accent)]" />
      </span>
      <p className="text-sm text-[color:var(--muted)]">
        正在进行补研，完成后会自动更新这条对话…
      </p>
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────
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
  const [submitting, setSubmitting]               = useState(false);
  const [errorMessage, setErrorMessage]           = useState<string | null>(null);
  const [finalizeMessage, setFinalizeMessage]     = useState<string | null>(null);
  const [finalizingDraft, setFinalizingDraft]     = useState(false);
  const [pendingMsg, setPendingMsg]               = useState<ChatMessageRecord | null>(null);
  const { chatDraft, setChatDraft }               = useResearchUiStore();
  const queryClient                               = useQueryClient();
  const messagesEndRef                            = useRef<HTMLDivElement>(null);
  const textareaRef                               = useRef<HTMLTextAreaElement>(null);

  // Derived state
  const lastAssistant = [...session.messages].reverse().find((m) => m.role === "assistant");
  const assistantMeta = pendingMsg ?? lastAssistant;
  const deltaPending  = Boolean(assistantMeta?.triggered_delta_job_id) &&
    !session.messages.some(
      (m) => m.role === "assistant" &&
             m.triggered_delta_job_id === assistantMeta?.triggered_delta_job_id &&
             m.id !== assistantMeta?.id,
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

  // Sync pending message
  useEffect(() => {
    if (pendingMsg && lastAssistant?.id === pendingMsg.id) {
      setPendingMsg(null);
    }
  }, [lastAssistant?.id, pendingMsg]);

  // Auto-scroll to bottom
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
        if (hasAssistant) {
          return withUser;
        }
        return { ...withUser, messages: [...withUser.messages, result.message] };
      };
      setPendingMsg(result.message);
      queryClient.setQueryData(["chat-session", session.id], appendMessages);
      queryClient.setQueryData(["chat-session-page", session.id], appendMessages);
    } catch (err) {
      setChatDraft(currentDraft);
      setErrorMessage(getApiErrorMessage(err, "发送失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
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
    } catch (err) {
      setFinalizeMessage(getApiErrorMessage(err, "更新报告失败。"));
    } finally {
      setFinalizingDraft(false);
    }
  };

  const allMessages = [
    ...session.messages,
    ...(pendingMsg ? [pendingMsg] : []),
  ];

  return (
    <div className="flex h-[70vh] min-h-[480px] flex-col rounded-[28px] border border-[color:var(--border-soft)] bg-[rgba(250,246,240,0.7)] backdrop-blur-sm overflow-hidden">

      {/* ── Chat header ─────────────────────────────────────────────── */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.7)] px-5 py-4">
        <div>
          <p className="text-sm font-semibold text-[color:var(--ink)]">PM 追问</p>
          <p className="text-xs text-[color:var(--muted)]">
            {reportReady
              ? `基于${reportLabel(assets.report?.stage)}·${stableVersionId ?? "工作草稿"}`
              : "等待报告生成后可追问"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {hasStableVersion && (
            <Button asChild variant="ghost">
              <Link href={`/research/jobs/${job.id}/report`}>
                <FileText className="mr-1.5 h-3.5 w-3.5" />
                查看报告
              </Link>
            </Button>
          )}
          <Badge tone={realtimeConnected ? "success" : "default"}>
            {realtimeConnected ? "实时" : "轮询"}
          </Badge>
        </div>
      </div>

      {/* ── Messages ─────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">

        {/* Starter prompts (shown when no messages) */}
        {session.messages.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-8 animate-fade-up">
            <div className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-[color:var(--accent)]">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <p className="text-sm font-medium text-[color:var(--ink)]">
              {reportReady ? "基于当前报告开始追问" : "报告生成后即可追问"}
            </p>
            {reportReady && (
              <div className="flex flex-wrap justify-center gap-2">
                {STARTER_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => setChatDraft(prompt)}
                    className="rounded-full border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.8)] px-3 py-2 text-xs text-[color:var(--muted-strong)] transition hover:border-[color:var(--accent)] hover:text-[color:var(--ink)]"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Message list */}
        {allMessages.map((msg, i) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isPending={msg.id === pendingMsg?.id}
          />
        ))}

        {/* Delta progress */}
        {deltaPending && <DeltaProgressIndicator />}

        {/* Finalize draft CTA */}
        {assistantMeta?.answer_mode === "delta_draft" && !finalizeBlocked && (
          <div className="animate-fade-in flex flex-wrap items-center gap-3 rounded-[18px] border border-emerald-200 bg-emerald-50/80 px-4 py-3">
            <p className="flex-1 text-sm text-emerald-900">补研草稿已生成，确认后可更新报告。</p>
            <Button
              disabled={finalizingDraft}
              onClick={() => void handleFinalizeDraft()}
              type="button"
            >
              {finalizingDraft ? "更新中..." : "更新报告"}
            </Button>
            {finalizeMessage && (
              <p className="w-full text-xs text-emerald-700">{finalizeMessage}</p>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Disabled reason ───────────────────────────────────────── */}
      {chatDisabledReason && (
        <div className="shrink-0 border-t border-amber-200 bg-amber-50/80 px-5 py-3 text-sm text-amber-900">
          {chatDisabledReason}
        </div>
      )}

      {/* ── Input area ───────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.8)] px-4 pb-4 pt-3">
        {errorMessage && (
          <p className="mb-2 text-xs text-rose-600">{errorMessage}</p>
        )}
        <div className="flex items-end gap-3">
          <textarea
            ref={textareaRef}
            value={chatDraft}
            onChange={(e) => setChatDraft(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={!chatEnabled || submitting}
            placeholder={
              reportReady
                ? "基于报告继续追问，或输入 / 触发快捷指令…"
                : "等待报告生成后即可追问…"
            }
            rows={2}
            className="flex-1 resize-none rounded-[16px] border border-[color:var(--border-soft)] bg-white px-4 py-2.5 text-sm text-[color:var(--ink)] placeholder:text-[color:var(--muted)] outline-none transition focus:border-[color:var(--accent)] disabled:opacity-60"
          />
          <Button
            type="button"
            disabled={!canSend}
            onClick={() => void onSend()}
            className="shrink-0"
          >
            {submitting ? (
              <span className="h-4 w-4 animate-spin-slow rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <SendHorizonal className="h-4 w-4" />
            )}
          </Button>
        </div>
        <p className="mt-1.5 text-[10px] text-[color:var(--muted)]">
          ⌘↵ 发送 · 输入 /delta 触发补研 · /report 跳到报告页
        </p>
      </div>
    </div>
  );
}
