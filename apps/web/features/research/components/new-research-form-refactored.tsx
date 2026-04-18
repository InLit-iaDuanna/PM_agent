"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, ChevronRight } from "lucide-react";

import { orchestrationPresetCatalog } from "@pm-agent/research-core";
import { useQuery } from "@tanstack/react-query";
import type {
  CreateResearchJobDto,
  DepthPreset,
  FailurePolicy,
  ResearchMode,
  WorkflowCommandId,
} from "@pm-agent/types";
import {
  Badge,
  Button,
  Card,
  CardDescription,
  CardTitle,
  Collapsible,
  Input,
  Label,
  Select,
  StepIndicator,
  Textarea,
} from "@pm-agent/ui";

import { createResearchJob, fetchRuntimeStatus, getApiErrorMessage } from "../../../lib/api-client";
import { useDraftStore } from "../store/draft-store";
import { commandIcons, formatBrowserMode, formatRuntimeSource } from "./research-ui-utils";

// ─── Wizard steps ───────────────────────────────────────────────────────────
const WIZARD_STEPS = [
  { id: "template", label: "选择模板" },
  { id: "config",   label: "配置参数" },
  { id: "confirm",  label: "确认发起" },
];

type WizardStep = "template" | "config" | "confirm";
type NumericField = "max_sources" | "max_subtasks" | "max_competitors" | "review_sample_target" | "time_budget_minutes";

const NUMERIC_CONFIG: Record<NumericField, { label: string; min: number; max: number }> = {
  max_sources:           { label: "来源数",   min: 5,  max: 120 },
  max_subtasks:          { label: "子任务数", min: 1,  max: 16 },
  max_competitors:       { label: "竞品数量", min: 1,  max: 20 },
  review_sample_target:  { label: "评论样本量", min: 10, max: 1000 },
  time_budget_minutes:   { label: "时间预算", min: 5,  max: 240 },
};

const DEPTH_OPTIONS: Array<{ id: DepthPreset; label: string }> = [
  { id: "light", label: "轻量" },
  { id: "standard", label: "标准" },
  { id: "deep", label: "深度" },
];

function parseNumeric(field: NumericField, raw: string): { value?: number; error?: string } {
  const cfg = NUMERIC_CONFIG[field];
  const trimmed = raw.trim();
  if (!trimmed) return { error: `请填写${cfg.label}。` };
  const n = Number(trimmed);
  if (!Number.isFinite(n)) return { error: `${cfg.label}必须是数字。` };
  const v = Math.round(n);
  if (v < cfg.min || v > cfg.max) return { error: `${cfg.label}需在 ${cfg.min}–${cfg.max} 之间。` };
  return { value: v };
}

// ─── Main component ─────────────────────────────────────────────────────────
export function NewResearchFormRefactored() {
  const router      = useRouter();
  const searchParams = useSearchParams();
  const form        = useDraftStore((s) => s.newResearchForm);
  const patchForm   = useDraftStore((s) => s.patchNewResearchForm);
  const resetForm   = useDraftStore((s) => s.resetNewResearchForm);

  // Pre-select command from URL param (from quick-search-panel)
  useEffect(() => {
    const cmd = searchParams.get("command") as WorkflowCommandId | null;
    if (cmd && orchestrationPresetCatalog[cmd]) {
      patchForm({ workflow_command: cmd });
    }
  }, [searchParams, patchForm]);

  const [step, setStep]           = useState<WizardStep>("template");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [topicError, setTopicError]   = useState<string | null>(null);
  const [numericDrafts, setNumericDrafts] = useState<Record<NumericField, string>>({
    max_sources:          String(form.max_sources ?? ""),
    max_subtasks:         String(form.max_subtasks ?? ""),
    max_competitors:      String(form.max_competitors ?? ""),
    review_sample_target: String(form.review_sample_target ?? ""),
    time_budget_minutes:  String(form.time_budget_minutes ?? ""),
  });

  const runtimeQuery = useQuery({
    queryKey: ["runtime-status"],
    queryFn: fetchRuntimeStatus,
    staleTime: 30_000,
  });

  const runtime       = runtimeQuery.data;
  const runtimeReady  = Boolean(runtime?.configured);

  // ── Step: template ─────────────────────────────────────────────────────
  const handleSelectTemplate = (id: WorkflowCommandId) => {
    patchForm({ workflow_command: id, research_mode: "deep" });
    setStep("config");
  };

  // ── Step: config → confirm ──────────────────────────────────────────────
  const handleGoToConfirm = () => {
    if (!form.topic?.trim()) { setTopicError("请输入研究主题。"); return; }
    setTopicError(null);
    setStep("confirm");
  };

  // ── Submit ───────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    setSubmitError(null);
    setSubmitting(true);
    try {
      // Validate & coerce numerics
      const numericOverrides: Partial<CreateResearchJobDto> = {};
      for (const field of Object.keys(NUMERIC_CONFIG) as NumericField[]) {
        const raw = numericDrafts[field];
        if (raw.trim()) {
          const { value, error } = parseNumeric(field, raw);
          if (error) { setSubmitError(error); setStep("config"); setSubmitting(false); return; }
          if (value !== undefined) (numericOverrides as Record<string, number>)[field] = value;
        }
      }
      const payload: CreateResearchJobDto = { ...form, ...numericOverrides };
      const job = await createResearchJob(payload);
      resetForm();
      router.push(`/research/jobs/${job.id}`);
    } catch (err) {
      setSubmitError(getApiErrorMessage(err, "发起研究失败，请重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  const selectedPreset = form.workflow_command ? orchestrationPresetCatalog[form.workflow_command] : null;

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="mx-auto max-w-3xl space-y-7">

      {/* Page title */}
      <div>
        <h1 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">新建研究</h1>
        <p className="mt-1 text-sm text-[color:var(--muted)]">选择研究模板 → 配置参数 → 确认发起</p>
      </div>

      {/* Step indicator */}
      <StepIndicator steps={WIZARD_STEPS} activeId={step} />

      {/* ── Step 1: Template ────────────────────────────────────────── */}
      {step === "template" && (
        <div className="space-y-4 animate-fade-up">
          <p className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
            选择研究模板（点击直接进入下一步）
          </p>

          <div className="grid gap-4">
            {(Object.entries(orchestrationPresetCatalog) as Array<
              [WorkflowCommandId, (typeof orchestrationPresetCatalog)[WorkflowCommandId]]
            >).map(([id, preset]) => {
              const Icon = commandIcons[id];
              const isSelected = form.workflow_command === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => handleSelectTemplate(id)}
                  className={`card-lift rounded-[26px] border p-5 text-left transition ${
                    isSelected
                      ? "border-[color:var(--accent)] bg-[linear-gradient(135deg,rgba(29,76,116,0.1),rgba(255,255,255,0.9))]"
                      : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] hover:border-[color:var(--border-strong)] hover:bg-white"
                  }`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-4">
                      <div className={`shrink-0 rounded-[18px] p-3 ${isSelected ? "bg-[color:var(--accent)] text-white" : "bg-[rgba(29,76,116,0.1)] text-[color:var(--accent)]"}`}>
                        <Icon className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="text-base font-semibold text-[color:var(--ink)]">{preset.label}</p>
                        <p className="mt-1 text-sm leading-6 text-[color:var(--muted)]">{preset.summary}</p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {(preset.recommendedFor ?? []).map((tag) => (
                            <Badge key={tag} tone="success">{tag}</Badge>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {isSelected && <Badge tone="success">当前草稿</Badge>}
                      <ChevronRight className="h-4 w-4 text-[color:var(--muted)]" />
                    </div>
                  </div>
                  <div className="mt-4 rounded-[16px] bg-[rgba(247,241,231,0.82)] px-4 py-3">
                    <p className="text-xs text-[color:var(--muted)]">研究焦点</p>
                    <p className="mt-1 text-sm text-[color:var(--ink)]">{preset.focusInstruction}</p>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Skip template */}
          {form.workflow_command && (
            <div className="flex justify-end">
              <Button type="button" onClick={() => setStep("config")} variant="secondary">
                使用已选模板（{selectedPreset?.label}）
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          )}
        </div>
      )}

      {/* ── Step 2: Config ──────────────────────────────────────────── */}
      {step === "config" && (
        <div className="space-y-5 animate-fade-up">
          {/* Back */}
          <button
            type="button"
            onClick={() => setStep("template")}
            className="flex items-center gap-2 text-sm text-[color:var(--muted)] hover:text-[color:var(--ink)]"
          >
            <ArrowLeft className="h-4 w-4" />
            返回模板选择
          </button>

          {/* Selected template badge */}
          {selectedPreset && (
            <div className="flex items-center gap-3 rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] px-4 py-3">
              <Badge tone="success">已选模板</Badge>
              <p className="text-sm font-medium text-[color:var(--ink)]">{selectedPreset.label}</p>
              <p className="text-sm text-[color:var(--muted)]">{selectedPreset.summary}</p>
            </div>
          )}

          {/* Core fields */}
          <Card className="space-y-5">
            <CardTitle>研究配置</CardTitle>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="topic">研究主题 *</Label>
                <Textarea
                  id="topic"
                  value={form.topic ?? ""}
                  onChange={(e) => { patchForm({ topic: e.target.value }); setTopicError(null); }}
                  placeholder='描述你想研究的核心问题，越具体越好，例如："国内 B2B SaaS 定价策略对比"'
                  rows={3}
                />
                {topicError && <p className="text-sm text-rose-600">{topicError}</p>}
              </div>

              <div className="space-y-2">
                <Label htmlFor="project_memory">项目背景（可选）</Label>
                <Textarea
                  id="project_memory"
                  value={form.project_memory ?? ""}
                  onChange={(e) => patchForm({ project_memory: e.target.value })}
                  placeholder="补充你的产品背景、目标用户、已有认知等，帮助 Agent 更准确地聚焦研究方向。"
                  rows={3}
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="depth">研究深度</Label>
                  <Select
                    id="depth"
                    value={form.depth_preset ?? "standard"}
                    onChange={(e) => patchForm({ depth_preset: e.target.value as DepthPreset })}
                  >
                    {DEPTH_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>{option.label}</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="mode">研究模式</Label>
                  <Select
                    id="mode"
                    value={form.research_mode ?? "deep"}
                    onChange={(e) => patchForm({ research_mode: e.target.value as ResearchMode })}
                  >
                    <option value="deep">深度研究</option>
                    <option value="standard">标准调查</option>
                  </Select>
                </div>
              </div>
            </div>
          </Card>

          {/* Advanced params (collapsed) */}
          <Collapsible
            trigger={
              <span className="text-sm text-[color:var(--muted-strong)]">
                高级参数（可选，不填则使用默认值）
              </span>
            }
            defaultOpen={false}
          >
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {(Object.entries(NUMERIC_CONFIG) as Array<[NumericField, { label: string; min: number; max: number }]>).map(([field, cfg]) => (
                  <div key={field} className="space-y-2">
                    <Label htmlFor={field}>
                      {cfg.label}
                      <span className="ml-1 text-[color:var(--muted)]">({cfg.min}–{cfg.max})</span>
                    </Label>
                    <Input
                      id={field}
                      value={numericDrafts[field]}
                      onChange={(e) => setNumericDrafts((prev) => ({ ...prev, [field]: e.target.value }))}
                      placeholder={`默认`}
                      type="text"
                      inputMode="numeric"
                    />
                  </div>
                ))}
              </div>

              <div className="space-y-2">
                <Label htmlFor="failure_policy">失败处理</Label>
                <Select
                  id="failure_policy"
                  value={form.failure_policy ?? "graceful"}
                  onChange={(e) => patchForm({ failure_policy: e.target.value as FailurePolicy })}
                >
                  <option value="graceful">标准模式（部分失败继续）</option>
                  <option value="strict">严谨模式（遇错即停）</option>
                </Select>
              </div>
            </div>
          </Collapsible>

          {/* Runtime status */}
          {!runtimeReady && (
            <div className="rounded-[18px] border border-amber-200 bg-amber-50/90 px-4 py-3 text-sm text-amber-900">
              当前模型尚未配置，发起前请先完成
              <Link href="/settings/runtime" className="mx-1 underline">服务设置</Link>。
            </div>
          )}

          <div className="flex flex-wrap gap-3 pt-1">
            <Button type="button" onClick={handleGoToConfirm}>
              下一步：确认配置
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
            <Button type="button" variant="secondary" onClick={() => setStep("template")}>
              返回
            </Button>
          </div>
        </div>
      )}

      {/* ── Step 3: Confirm ─────────────────────────────────────────── */}
      {step === "confirm" && (
        <div className="space-y-5 animate-fade-up">
          <button
            type="button"
            onClick={() => setStep("config")}
            className="flex items-center gap-2 text-sm text-[color:var(--muted)] hover:text-[color:var(--ink)]"
          >
            <ArrowLeft className="h-4 w-4" />
            返回配置
          </button>

          <Card className="space-y-5">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
              <CardTitle>确认研究配置</CardTitle>
            </div>

            <div className="space-y-4">
              {/* Summary rows */}
              <SummaryRow label="研究主题"  value={form.topic ?? "（未填写）"} />
              {form.project_memory && <SummaryRow label="项目背景" value={form.project_memory} />}
              {selectedPreset && (
                <SummaryRow label="研究模板" value={selectedPreset.label} />
              )}
              <SummaryRow label="研究模式" value={form.research_mode === "standard" ? "标准调查" : "深度研究"} />
              <SummaryRow label="失败处理" value={form.failure_policy === "strict" ? "严谨模式" : "标准模式"} />
            </div>

            {/* Runtime check */}
            <div className={`rounded-[16px] border px-4 py-3 text-sm ${
              runtimeReady
                ? "border-emerald-200 bg-emerald-50/80 text-emerald-900"
                : "border-amber-200 bg-amber-50/80 text-amber-900"
            }`}>
              {runtimeReady
                ? "模型已就绪，可以直接发起。"
                : "模型尚未配置，请先完成服务设置再发起。"}
            </div>

            {submitError && (
              <div className="rounded-[16px] border border-rose-200 bg-rose-50/80 px-4 py-3 text-sm text-rose-800">
                {submitError}
              </div>
            )}

            <div className="flex flex-wrap gap-3">
              <Button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={submitting || !runtimeReady}
              >
                {submitting ? "发起中..." : "发起研究"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setStep("config")}>
                返回修改
              </Button>
              <Button type="button" variant="ghost" onClick={resetForm}>
                清空草稿
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

// ─── SummaryRow ─────────────────────────────────────────────────────────────
function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-4 rounded-[14px] border border-[color:var(--border-soft)] bg-[rgba(247,241,231,0.7)] px-4 py-3">
      <span className="w-20 shrink-0 text-xs text-[color:var(--muted)]">{label}</span>
      <span className="text-sm text-[color:var(--ink)] break-all">{value}</span>
    </div>
  );
}
