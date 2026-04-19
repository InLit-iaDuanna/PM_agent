"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, ChevronRight, Sparkles } from "lucide-react";

import { orchestrationPresetCatalog } from "@pm-agent/research-core";
import { useQuery } from "@tanstack/react-query";
import type {
  CreateResearchJobDto,
  DepthPreset,
  FailurePolicy,
  ResearchMode,
  RuntimeStatusRecord,
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

const WIZARD_STEPS = [
  { id: "template", label: "选择研究命令", sublabel: "决定这轮研究的主导视角" },
  { id: "config", label: "配置任务参数", sublabel: "补足主题、背景与预算约束" },
  { id: "confirm", label: "确认并发起", sublabel: "检查环境和最终摘要" },
];

type WizardStep = "template" | "config" | "confirm";
type NumericField = "max_sources" | "max_subtasks" | "max_competitors" | "review_sample_target" | "time_budget_minutes";

const NUMERIC_CONFIG: Record<NumericField, { label: string; min: number; max: number }> = {
  max_sources: { label: "来源数", min: 5, max: 500 },
  max_subtasks: { label: "子任务数", min: 1, max: 16 },
  max_competitors: { label: "竞品数量", min: 1, max: 20 },
  review_sample_target: { label: "评论样本量", min: 10, max: 1000 },
  time_budget_minutes: { label: "时间预算", min: 5, max: 240 },
};

const DEPTH_OPTIONS: Array<{ id: DepthPreset; label: string; helper: string }> = [
  { id: "light", label: "轻量", helper: "快速拿到方向感" },
  { id: "standard", label: "标准", helper: "平衡效率和覆盖面" },
  { id: "deep", label: "深度", helper: "为正式交付准备充分依据" },
];

function parseNumeric(field: NumericField, raw: string): { value?: number; error?: string } {
  const cfg = NUMERIC_CONFIG[field];
  const trimmed = raw.trim();
  if (!trimmed) return { error: `请填写${cfg.label}。` };
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return { error: `${cfg.label}必须是数字。` };
  const rounded = Math.round(value);
  if (rounded < cfg.min || rounded > cfg.max) return { error: `${cfg.label}需在 ${cfg.min}–${cfg.max} 之间。` };
  return { value: rounded };
}

function resolveRuntimeLaunchState(runtime?: RuntimeStatusRecord) {
  if (!runtime) {
    return {
      canLaunch: false,
      statusLabel: "检测中",
      summary: "正在读取当前运行环境，请稍候。",
      hint: "读取完成后会自动显示这次研究将以完整模型模式还是降级模式运行。",
    };
  }

  if (runtime.configured) {
    return {
      canLaunch: true,
      statusLabel: "已就绪",
      summary: "模型已就绪，可以直接发起研究。",
      hint: "这次会使用已保存的模型配置、检索策略和浏览能力执行研究。",
    };
  }

  return {
    canLaunch: true,
    statusLabel: "降级可用",
    summary: "当前没有可用模型 Key，但仍可用降级模式发起研究。",
    hint: "系统会继续执行规则化任务拆解、外部搜索、证据归档和回退报告生成。补齐 API Key 后可获得更好的成文与 PM Chat 质量。",
  };
}

export function NewResearchFormRefactored() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const form = useDraftStore((state) => state.newResearchForm);
  const patchForm = useDraftStore((state) => state.patchNewResearchForm);
  const resetForm = useDraftStore((state) => state.resetNewResearchForm);

  useEffect(() => {
    const command = searchParams.get("command") as WorkflowCommandId | null;
    if (command && orchestrationPresetCatalog[command]) {
      patchForm({ workflow_command: command });
    }
  }, [patchForm, searchParams]);

  const [step, setStep] = useState<WizardStep>("template");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [topicError, setTopicError] = useState<string | null>(null);
  const [numericDrafts, setNumericDrafts] = useState<Record<NumericField, string>>({
    max_sources: String(form.max_sources ?? ""),
    max_subtasks: String(form.max_subtasks ?? ""),
    max_competitors: String(form.max_competitors ?? ""),
    review_sample_target: String(form.review_sample_target ?? ""),
    time_budget_minutes: String(form.time_budget_minutes ?? ""),
  });

  const runtimeQuery = useQuery({
    queryKey: ["runtime-status"],
    queryFn: fetchRuntimeStatus,
    staleTime: 30_000,
  });

  const runtime = runtimeQuery.data;
  const runtimeLaunchState = resolveRuntimeLaunchState(runtime);
  const selectedPreset = form.workflow_command ? orchestrationPresetCatalog[form.workflow_command] : null;

  const handleSelectTemplate = (id: WorkflowCommandId) => {
    patchForm({ workflow_command: id, research_mode: "deep" });
    setStep("config");
  };

  const handleGoToConfirm = () => {
    if (!form.topic?.trim()) {
      setTopicError("请输入研究主题。");
      return;
    }
    setTopicError(null);
    setStep("confirm");
  };

  const handleSubmit = async () => {
    setSubmitError(null);
    setSubmitting(true);
    try {
      const numericOverrides: Partial<CreateResearchJobDto> = {};
      for (const field of Object.keys(NUMERIC_CONFIG) as NumericField[]) {
        const raw = numericDrafts[field];
        if (raw.trim()) {
          const { value, error } = parseNumeric(field, raw);
          if (error) {
            setSubmitError(error);
            setStep("config");
            setSubmitting(false);
            return;
          }
          if (value !== undefined) (numericOverrides as Record<string, number>)[field] = value;
        }
      }

      const payload: CreateResearchJobDto = { ...form, ...numericOverrides };
      const job = await createResearchJob(payload);
      resetForm();
      router.push(`/research/jobs/${job.id}`);
    } catch (error) {
      setSubmitError(getApiErrorMessage(error, "发起研究失败，请重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="paper-panel rounded-[36px] px-5 py-6 sm:px-7 xl:px-8 xl:py-8">
        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <div className="rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.84)] p-5 shadow-[var(--shadow-sm)]">
              <p className="eyebrow-label">研究发起器</p>
              <h1 className="section-title mt-3 text-3xl leading-tight text-[color:var(--ink)]">新建研究</h1>
              <p className="mt-2 text-sm leading-7 text-[color:var(--muted)]">
                先选研究命令，再补齐任务边界。这样启动出来的不是一条普通表单记录，而是一套可执行的研究编排。
              </p>
              <StepIndicator className="mt-6" steps={WIZARD_STEPS} activeId={step} orientation="vertical" />
            </div>

            <div className="rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.84)] p-5 shadow-[var(--shadow-sm)]">
              <p className="eyebrow-label">当前草稿</p>
              {selectedPreset ? (
                <div className="mt-3 space-y-3">
                  <Badge tone="success">已选命令</Badge>
                  <div>
                    <p className="text-lg font-semibold text-[color:var(--ink)]">{selectedPreset.label}</p>
                    <p className="mt-1 text-sm leading-6 text-[color:var(--muted)]">{selectedPreset.summary}</p>
                  </div>
                  <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-4 py-4 text-sm text-[color:var(--muted)]">
                    <p className="font-medium text-[color:var(--ink)]">研究焦点</p>
                    <p className="mt-2 leading-7">{selectedPreset.focusInstruction}</p>
                  </div>
                </div>
              ) : (
                <div className="mt-3 rounded-[20px] border border-dashed border-[color:var(--border-soft)] px-4 py-6 text-sm text-[color:var(--muted)]">
                  先从左侧选择一个研究命令，再进入参数配置。
                </div>
              )}
            </div>

            <div className="rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.84)] p-5 shadow-[var(--shadow-sm)]">
              <p className="eyebrow-label">运行环境</p>
              <div className="mt-3 space-y-3">
                <RuntimeRow label="模型状态" value={runtimeLaunchState.statusLabel} />
                <RuntimeRow label="配置来源" value={formatRuntimeSource(runtime?.source)} />
                <RuntimeRow label="浏览模式" value={formatBrowserMode(runtime?.browser_mode)} />
                <RuntimeRow label="当前配置" value={runtime?.selected_profile_label || runtime?.model || "默认"} />
              </div>
              {runtime && !runtime.configured ? (
                <p className="mt-3 text-xs leading-6 text-amber-800">
                  当前没有可用模型 Key，但仍然可以直接发起研究并验证整条链路。若希望获得更高质量成文和 PM Chat 表现，再去补齐
                  <Link href="/settings/runtime" className="mx-1 underline">
                    服务设置
                  </Link>
                  即可。
                </p>
              ) : null}
            </div>
          </aside>

          <div className="space-y-5">
            {step === "template" && (
              <div className="space-y-5 animate-fade-up">
                <div className="rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.76)] px-6 py-6">
                  <p className="eyebrow-label">第 1 步</p>
                  <h2 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">先决定这轮研究要怎么打</h2>
                  <p className="mt-2 max-w-3xl text-sm leading-7 text-[color:var(--muted)]">
                    不同命令会影响任务拆解、搜索倾向、补研方式和最终报告结构。先挑一个最接近你现在决策问题的主导视角。
                  </p>
                </div>

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
                        className={`card-lift rounded-[28px] border p-5 text-left transition ${
                          isSelected
                            ? "border-[color:var(--accent)] bg-[linear-gradient(135deg,rgba(29,76,116,0.08),rgba(255,251,246,0.9))]"
                            : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.62)] hover:border-[color:var(--border-strong)] hover:bg-white"
                        }`}
                      >
                        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                          <div className="flex min-w-0 gap-4">
                            <div
                              className={`shrink-0 rounded-[18px] p-3 ${
                                isSelected ? "bg-[color:var(--accent)] text-white" : "bg-[rgba(29,76,116,0.1)] text-[color:var(--accent)]"
                              }`}
                            >
                              <Icon className="h-5 w-5" />
                            </div>
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="text-lg font-semibold text-[color:var(--ink)]">{preset.label}</p>
                                {isSelected ? <Badge tone="success">当前草稿</Badge> : null}
                              </div>
                              <p className="mt-2 text-sm leading-7 text-[color:var(--muted)]">{preset.summary}</p>
                              <div className="mt-3 flex flex-wrap gap-1.5">
                                {(preset.recommendedFor ?? []).map((tag) => (
                                  <Badge key={tag} tone="success">
                                    {tag}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          </div>
                          <ChevronRight className="h-4 w-4 shrink-0 text-[color:var(--muted)]" />
                        </div>
                        <div className="mt-4 rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(252,247,241,0.9)] px-4 py-4">
                          <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">研究焦点</p>
                          <p className="mt-2 text-sm leading-7 text-[color:var(--ink)]">{preset.focusInstruction}</p>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {form.workflow_command ? (
                  <div className="flex justify-end">
                    <Button type="button" onClick={() => setStep("config")} variant="secondary">
                      使用这个命令继续配置
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                  </div>
                ) : null}
              </div>
            )}

            {step === "config" && (
              <div className="space-y-5 animate-fade-up">
                <button
                  type="button"
                  onClick={() => setStep("template")}
                  className="flex items-center gap-2 text-sm text-[color:var(--muted)] hover:text-[color:var(--ink)]"
                >
                  <ArrowLeft className="h-4 w-4" />
                  返回重新选命令
                </button>

                <Card className="space-y-5 rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.84)]">
                  <div>
                    <p className="eyebrow-label">第 2 步</p>
                    <CardTitle className="mt-3 text-2xl">给这轮研究补足边界条件</CardTitle>
                    <CardDescription className="mt-2">
                      把主题、项目背景和研究预算讲清楚，Agent 才会更像真正替你推进工作，而不是泛泛地搜一圈。
                    </CardDescription>
                  </div>

                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="topic">研究主题 *</Label>
                      <Textarea
                        id="topic"
                        value={form.topic ?? ""}
                        onChange={(event) => {
                          patchForm({ topic: event.target.value });
                          setTopicError(null);
                        }}
                        placeholder='例如："国内 AI 办公产品的定价策略、功能分层与商业化路径对比"'
                        rows={3}
                      />
                      {topicError ? <p className="text-sm text-rose-600">{topicError}</p> : null}
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="project_memory">项目背景（可选）</Label>
                      <Textarea
                        id="project_memory"
                        value={form.project_memory ?? ""}
                        onChange={(event) => patchForm({ project_memory: event.target.value })}
                        placeholder="补充你的产品背景、核心假设、目标用户或已知风险，让研究链路更贴近真实决策。"
                        rows={4}
                      />
                    </div>

                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="space-y-2">
                        <Label htmlFor="depth">研究深度</Label>
                        <Select
                          id="depth"
                          value={form.depth_preset ?? "standard"}
                          onChange={(event) => patchForm({ depth_preset: event.target.value as DepthPreset })}
                        >
                          {DEPTH_OPTIONS.map((option) => (
                            <option key={option.id} value={option.id}>
                              {`${option.label} · ${option.helper}`}
                            </option>
                          ))}
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="mode">研究模式</Label>
                        <Select
                          id="mode"
                          value={form.research_mode ?? "deep"}
                          onChange={(event) => patchForm({ research_mode: event.target.value as ResearchMode })}
                        >
                          <option value="deep">深度研究</option>
                          <option value="standard">标准调查</option>
                        </Select>
                      </div>
                    </div>
                  </div>
                </Card>

                <Card className="space-y-5 rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.84)]">
                  <div>
                    <CardTitle>高级约束</CardTitle>
                    <CardDescription className="mt-2">如果你已经知道预算、竞品范围或样本规模，可以在这里把边界讲清楚。</CardDescription>
                  </div>

                  <Collapsible
                    trigger={<span className="text-sm text-[color:var(--muted-strong)]">展开高级参数</span>}
                    defaultOpen={false}
                  >
                    <div className="space-y-4">
                      <div className="grid gap-4 sm:grid-cols-2">
                        {(Object.entries(NUMERIC_CONFIG) as Array<
                          [NumericField, { label: string; min: number; max: number }]
                        >).map(([field, cfg]) => (
                          <div key={field} className="space-y-2">
                            <Label htmlFor={field}>
                              {cfg.label}
                              <span className="ml-1 text-[color:var(--muted)]">
                                ({cfg.min}–{cfg.max})
                              </span>
                            </Label>
                            <Input
                              id={field}
                              value={numericDrafts[field]}
                              onChange={(event) => setNumericDrafts((current) => ({ ...current, [field]: event.target.value }))}
                              placeholder="默认"
                              type="text"
                              inputMode="numeric"
                            />
                          </div>
                        ))}
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="failure_policy">失败处理策略</Label>
                        <Select
                          id="failure_policy"
                          value={form.failure_policy ?? "graceful"}
                          onChange={(event) => patchForm({ failure_policy: event.target.value as FailurePolicy })}
                        >
                          <option value="graceful">标准模式：部分失败继续推进</option>
                          <option value="strict">严谨模式：关键失败立即停止</option>
                        </Select>
                      </div>
                    </div>
                  </Collapsible>
                </Card>

                {runtime && !runtime.configured ? (
                  <div className="rounded-[20px] border border-amber-200 bg-amber-50/90 px-4 py-3 text-sm text-amber-900">
                    当前未配置模型 Key，这次会以降级模式运行。你仍然可以继续发起；如果需要更强的成文与对话效果，再补齐
                    <Link href="/settings/runtime" className="mx-1 underline">
                      服务设置
                    </Link>
                    。
                  </div>
                ) : null}

                <div className="flex flex-wrap gap-3">
                  <Button type="button" onClick={handleGoToConfirm}>
                    下一步：确认发起
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                  <Button type="button" variant="secondary" onClick={() => setStep("template")}>
                    返回
                  </Button>
                </div>
              </div>
            )}

            {step === "confirm" && (
              <div className="space-y-5 animate-fade-up">
                <button
                  type="button"
                  onClick={() => setStep("config")}
                  className="flex items-center gap-2 text-sm text-[color:var(--muted)] hover:text-[color:var(--ink)]"
                >
                  <ArrowLeft className="h-4 w-4" />
                  返回修改配置
                </button>

                <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
                  <Card className="space-y-5 rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.84)]">
                    <div className="flex items-center gap-3">
                      <div className="rounded-full bg-[rgba(15,118,110,0.12)] p-2 text-[color:var(--success)]">
                        <CheckCircle2 className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="eyebrow-label">第 3 步</p>
                        <CardTitle className="mt-1 text-2xl">确认研究摘要</CardTitle>
                      </div>
                    </div>

                    <div className="space-y-3">
                      <SummaryRow label="研究主题" value={form.topic ?? "（未填写）"} />
                      {form.project_memory ? <SummaryRow label="项目背景" value={form.project_memory} /> : null}
                      {selectedPreset ? <SummaryRow label="研究命令" value={selectedPreset.label} /> : null}
                      <SummaryRow label="研究模式" value={form.research_mode === "standard" ? "标准调查" : "深度研究"} />
                      <SummaryRow label="失败策略" value={form.failure_policy === "strict" ? "严谨模式" : "标准模式"} />
                    </div>
                  </Card>

                  <Card className="space-y-5 rounded-[30px] border border-[color:var(--border-soft)] bg-[rgba(255,251,246,0.84)]">
                    <div className="flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-[color:var(--warm)]" />
                      <CardTitle>发起前检查</CardTitle>
                    </div>

                    <div
                      className={`rounded-[20px] border px-4 py-4 text-sm ${
                        runtime?.configured
                          ? "border-emerald-200 bg-emerald-50/80 text-emerald-900"
                          : runtime
                            ? "border-amber-200 bg-amber-50/80 text-amber-900"
                            : "border-slate-200 bg-slate-50 text-slate-700"
                      }`}
                    >
                      {runtimeLaunchState.summary}
                    </div>

                    <div className="space-y-3">
                      <RuntimeRow label="配置来源" value={formatRuntimeSource(runtime?.source)} />
                      <RuntimeRow label="浏览模式" value={formatBrowserMode(runtime?.browser_mode)} />
                      <RuntimeRow label="活动配置" value={runtime?.selected_profile_label || runtime?.model || "默认"} />
                    </div>

                    <p className="text-sm leading-6 text-[color:var(--muted)]">{runtimeLaunchState.hint}</p>

                    {submitError ? (
                      <div className="rounded-[18px] border border-rose-200 bg-rose-50/80 px-4 py-3 text-sm text-rose-800">
                        {submitError}
                      </div>
                    ) : null}

                    <div className="flex flex-wrap gap-3">
                      <Button
                        type="button"
                        onClick={() => void handleSubmit()}
                        disabled={submitting || runtimeQuery.isLoading || Boolean(runtimeQuery.error) || !runtimeLaunchState.canLaunch}
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
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function RuntimeRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-4 py-3">
      <span className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</span>
      <span className="text-right text-sm font-medium text-[color:var(--ink)]">{value}</span>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] px-4 py-4">
      <p className="text-[11px] uppercase tracking-[0.18em] text-[color:var(--muted)]">{label}</p>
      <p className="mt-2 break-all text-sm leading-7 text-[color:var(--ink)]">{value}</p>
    </div>
  );
}
