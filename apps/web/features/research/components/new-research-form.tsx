"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { depthPresets, industryTemplateCatalog } from "@pm-agent/research-core";
import { useQuery } from "@tanstack/react-query";
import type { CreateResearchJobDto, DepthPreset, FailurePolicy, IndustryTemplate, ResearchMode, WorkflowCommandId } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, Input, Label, Select, Textarea } from "@pm-agent/ui";

import { createResearchJob, fetchRuntimeStatus, getApiErrorMessage } from "../../../lib/api-client";
import { useDraftStore } from "../store/draft-store";
import { formatBrowserMode, formatRuntimeSource } from "./research-ui-utils";
import { WorkflowCommandCenter } from "./workflow-command-center";

type NumericField = "max_sources" | "max_subtasks" | "max_competitors" | "review_sample_target" | "time_budget_minutes";
type FormFieldError = "topic" | NumericField;

const NUMERIC_FIELD_CONFIG: Record<NumericField, { label: string; min: number; max: number }> = {
  max_sources: { label: "来源数", min: 5, max: 120 },
  max_subtasks: { label: "子任务数", min: 1, max: 12 },
  max_competitors: { label: "竞品数量", min: 1, max: 20 },
  review_sample_target: { label: "评论样本量", min: 10, max: 1000 },
  time_budget_minutes: { label: "时间预算", min: 5, max: 240 },
};

function buildNumericDrafts(form: CreateResearchJobDto): Record<NumericField, string> {
  return {
    max_sources: String(form.max_sources ?? ""),
    max_subtasks: String(form.max_subtasks ?? ""),
    max_competitors: String(form.max_competitors ?? ""),
    review_sample_target: String(form.review_sample_target ?? ""),
    time_budget_minutes: String(form.time_budget_minutes ?? ""),
  };
}

function parseNumericDraft(field: NumericField, rawValue: string): { value?: number; error?: string } {
  const trimmedValue = rawValue.trim();
  const config = NUMERIC_FIELD_CONFIG[field];
  if (!trimmedValue) {
    return { error: `请填写${config.label}。` };
  }
  const parsedValue = Number(trimmedValue);
  if (!Number.isFinite(parsedValue)) {
    return { error: `${config.label}必须是数字。` };
  }
  const normalizedValue = Math.round(parsedValue);
  if (normalizedValue < config.min || normalizedValue > config.max) {
    return { error: `${config.label}需在 ${config.min} - ${config.max} 之间。` };
  }
  return { value: normalizedValue };
}

export function NewResearchForm() {
  const router = useRouter();
  const form = useDraftStore((state) => state.newResearchForm);
  const patchNewResearchForm = useDraftStore((state) => state.patchNewResearchForm);
  const resetNewResearchForm = useDraftStore((state) => state.resetNewResearchForm);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FormFieldError, string>>>({});
  const [numericDrafts, setNumericDrafts] = useState<Record<NumericField, string>>(() => buildNumericDrafts(form));
  const runtimeQuery = useQuery({
    queryKey: ["runtime-status"],
    queryFn: fetchRuntimeStatus,
    refetchInterval: 10000,
  });

  useEffect(() => {
    setNumericDrafts(buildNumericDrafts(form));
  }, [form.max_competitors, form.max_sources, form.max_subtasks, form.review_sample_target, form.time_budget_minutes]);

  const onPresetChange = (depthPreset: DepthPreset) => {
    const preset = depthPresets[depthPreset];
    const presetPatch = {
      depth_preset: depthPreset,
      max_sources: preset.max_sources,
      max_subtasks: preset.max_subtasks,
      time_budget_minutes: preset.time_budget_minutes,
      max_competitors: preset.max_competitors,
      review_sample_target: preset.review_sample_target,
    };
    patchNewResearchForm(presetPatch);
    setFieldErrors((current) => ({
      ...current,
      max_sources: undefined,
      max_subtasks: undefined,
      max_competitors: undefined,
      review_sample_target: undefined,
      time_budget_minutes: undefined,
    }));
  };

  const providerLabel = runtimeQuery.data?.provider === "openai_compatible" ? "OpenAI 兼容接口" : "MiniMax";
  const updateNumericDraft = (field: NumericField, rawValue: string) => {
    setNumericDrafts((current) => ({ ...current, [field]: rawValue }));
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    const trimmedValue = rawValue.trim();
    if (!trimmedValue) {
      return;
    }
    const parsedValue = Number(trimmedValue);
    if (!Number.isFinite(parsedValue)) {
      return;
    }
    patchNewResearchForm({ [field]: Math.round(parsedValue) } as Partial<CreateResearchJobDto>);
  };

  const normalizeNumericDraft = (field: NumericField) => {
    const parsed = parseNumericDraft(field, numericDrafts[field]);
    if (!parsed.value) {
      return;
    }
    setNumericDrafts((current) => ({ ...current, [field]: String(parsed.value) }));
    patchNewResearchForm({ [field]: parsed.value } as Partial<CreateResearchJobDto>);
  };

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextFieldErrors: Partial<Record<FormFieldError, string>> = {};
    const sanitizedNumbers = {} as Record<NumericField, number>;
    const sanitizedTopic = form.topic.trim();

    if (!sanitizedTopic) {
      nextFieldErrors.topic = "请输入研究主题。";
    }

    (Object.keys(NUMERIC_FIELD_CONFIG) as NumericField[]).forEach((field) => {
      const parsed = parseNumericDraft(field, numericDrafts[field]);
      if (parsed.error) {
        nextFieldErrors[field] = parsed.error;
        return;
      }
      sanitizedNumbers[field] = parsed.value as number;
    });

    if (Object.keys(nextFieldErrors).length > 0) {
      setFieldErrors(nextFieldErrors);
      setErrorMessage("请先修正表单里的必填项和数值范围。");
      return;
    }

    const payload: CreateResearchJobDto = {
      ...form,
      topic: sanitizedTopic,
      project_memory: form.project_memory?.trim() ?? "",
      geo_scope: form.geo_scope.map((item) => item.trim()).filter(Boolean),
      ...sanitizedNumbers,
    };

    setSubmitting(true);
    setErrorMessage(null);
    try {
      patchNewResearchForm(payload);
      const job = await createResearchJob(payload);
      router.push(`/research/jobs/${job.id}`);
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error, "创建研究任务失败。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="grid gap-6 lg:grid-cols-[1.4fr_0.9fr]" onSubmit={onSubmit}>
      <Card className="space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>发起研究</CardTitle>
            <CardDescription>确定研究主题、执行方式和输出要求，开始一条新的研究任务。</CardDescription>
          </div>
          <Button
            onClick={() => {
              resetNewResearchForm();
              setFieldErrors({});
              setErrorMessage(null);
            }}
            type="button"
            variant="ghost"
          >
            重置草稿
          </Button>
        </div>

        <div>
          <Label htmlFor="topic">研究主题</Label>
          <Input
            id="topic"
            onChange={(event) => {
              patchNewResearchForm({ topic: event.target.value });
              setFieldErrors((current) => ({ ...current, topic: undefined }));
            }}
            placeholder="例如：AI 产品团队的研究助手，优先切入哪类 PM 场景更容易形成留存？"
            value={form.topic}
          />
          {fieldErrors.topic ? <p className="mt-2 text-sm text-red-600">{fieldErrors.topic}</p> : null}
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <Label htmlFor="industry">行业模板</Label>
            <Select
              id="industry"
              value={form.industry_template}
              onChange={(event) => patchNewResearchForm({ industry_template: event.target.value as IndustryTemplate })}
            >
              {Object.entries(industryTemplateCatalog).map(([value, template]) => (
                <option key={value} value={value}>
                  {template.label}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="mode">研究模式</Label>
            <Select
              id="mode"
              value={form.research_mode}
              onChange={(event) => patchNewResearchForm({ research_mode: event.target.value as ResearchMode })}
            >
              <option value="standard">标准调查</option>
              <option value="deep">深度调查</option>
            </Select>
          </div>
          <div>
            <Label htmlFor="failure-policy">证据要求</Label>
            <Select
              id="failure-policy"
              value={form.failure_policy}
              onChange={(event) => patchNewResearchForm({ failure_policy: event.target.value as FailurePolicy })}
            >
              <option value="graceful">优先交付可复核结果</option>
              <option value="strict">依据补齐后再给结论</option>
            </Select>
          </div>
        </div>
        <p className="text-sm text-slate-500">
          前者会先交付当前可核对的结果，后者会等待关键依据补齐后再输出正式结论。
        </p>

        <WorkflowCommandCenter
          description="模板会影响任务拆分方式、证据侧重点和最终报告结构。"
          onSelectCommand={(commandId) => patchNewResearchForm({ workflow_command: commandId })}
          selectedCommand={form.workflow_command as WorkflowCommandId}
          title="研究模板"
        />

        <div>
          <Label htmlFor="preset">调查量预设</Label>
          <Select id="preset" value={form.depth_preset} onChange={(event) => onPresetChange(event.target.value as DepthPreset)}>
            <option value="light">轻量</option>
            <option value="standard">标准</option>
            <option value="deep">深度</option>
          </Select>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <Label htmlFor="geo-scope">地域范围</Label>
            <Input
              id="geo-scope"
              value={form.geo_scope.join(" / ")}
              onChange={(event) =>
                patchNewResearchForm({ geo_scope: event.target.value.split("/").map((item) => item.trim()).filter(Boolean) })
              }
            />
          </div>
          <div>
            <Label htmlFor="language">输出语言</Label>
            <Select id="language" value={form.output_locale} onChange={(event) => patchNewResearchForm({ output_locale: event.target.value })}>
              <option value="zh-CN">中文</option>
              <option value="en-US">英文</option>
            </Select>
          </div>
        </div>

        <div>
          <Label htmlFor="project-memory">项目背景 / 报告要求</Label>
          <Textarea
            id="project-memory"
            rows={5}
            value={form.project_memory ?? ""}
            onChange={(event) => patchNewResearchForm({ project_memory: event.target.value })}
            placeholder="例如：面向管理层汇报，突出竞品差异、行动建议与风险边界。"
          />
          <p className="mt-2 text-sm text-slate-500">
            这里用于补充项目背景、写作要求和关注重点，后续研究与报告都会参考这些信息。
          </p>
        </div>

        <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-900">当前服务配置</p>
              <p className="mt-1 text-sm text-slate-500">
                新建任务会自动继承当前保存的模型、接口地址和浏览器能力。
              </p>
            </div>
            <Button asChild variant="secondary">
              <Link href="/settings/runtime">打开服务设置</Link>
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {runtimeQuery.data ? (
              <>
                <Badge tone={runtimeQuery.data.configured ? "success" : "warning"}>
                  {runtimeQuery.data.configured ? "模型已配置" : "模型未配置"}
                </Badge>
                <Badge>{providerLabel}</Badge>
                <Badge>{runtimeQuery.data.model}</Badge>
                <Badge>{formatBrowserMode(runtimeQuery.data.browser_mode)}</Badge>
                <Badge>{formatRuntimeSource(runtimeQuery.data.source)}</Badge>
              </>
            ) : runtimeQuery.error ? (
              <Badge tone="danger">当前配置读取失败</Badge>
            ) : (
              <Badge>读取中</Badge>
            )}
          </div>
          <div className="mt-3 space-y-2">
            <p className={`text-sm ${runtimeQuery.error ? "text-red-600" : runtimeQuery.data?.configured ? "text-slate-500" : "text-amber-700"}`}>
              {runtimeQuery.error
                ? getApiErrorMessage(runtimeQuery.error, "无法读取当前服务配置。")
                : runtimeQuery.data?.validation_message ?? "刷新后这里会继续保留当前可用配置，不需要每次重新填写。"}
            </p>
            {runtimeQuery.error ? (
              <Button onClick={() => void runtimeQuery.refetch()} type="button" variant="ghost">
                重新读取当前配置
              </Button>
            ) : null}
            {runtimeQuery.data && !runtimeQuery.data.configured ? (
              <p className="text-sm text-amber-700">当前仍可创建任务，但会以基础模式运行，建议先补好模型配置。</p>
            ) : null}
          </div>
        </div>
      </Card>

      <Card className="space-y-5">
        <div>
          <CardTitle>高级参数</CardTitle>
          <CardDescription>在预设基础上微调调查量、竞品数和评论样本量。</CardDescription>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <Label>来源数</Label>
            <Input
              min={NUMERIC_FIELD_CONFIG.max_sources.min}
              max={NUMERIC_FIELD_CONFIG.max_sources.max}
              onBlur={() => normalizeNumericDraft("max_sources")}
              onChange={(event) => updateNumericDraft("max_sources", event.target.value)}
              type="number"
              value={numericDrafts.max_sources}
            />
            {fieldErrors.max_sources ? <p className="mt-2 text-sm text-red-600">{fieldErrors.max_sources}</p> : null}
          </div>
          <div>
            <Label>子任务数</Label>
            <Input
              min={NUMERIC_FIELD_CONFIG.max_subtasks.min}
              max={NUMERIC_FIELD_CONFIG.max_subtasks.max}
              onBlur={() => normalizeNumericDraft("max_subtasks")}
              onChange={(event) => updateNumericDraft("max_subtasks", event.target.value)}
              type="number"
              value={numericDrafts.max_subtasks}
            />
            {fieldErrors.max_subtasks ? <p className="mt-2 text-sm text-red-600">{fieldErrors.max_subtasks}</p> : null}
          </div>
          <div>
            <Label>竞品数量</Label>
            <Input
              min={NUMERIC_FIELD_CONFIG.max_competitors.min}
              max={NUMERIC_FIELD_CONFIG.max_competitors.max}
              onBlur={() => normalizeNumericDraft("max_competitors")}
              onChange={(event) => updateNumericDraft("max_competitors", event.target.value)}
              type="number"
              value={numericDrafts.max_competitors}
            />
            {fieldErrors.max_competitors ? <p className="mt-2 text-sm text-red-600">{fieldErrors.max_competitors}</p> : null}
          </div>
          <div>
            <Label>评论样本量</Label>
            <Input
              max={NUMERIC_FIELD_CONFIG.review_sample_target.max}
              min={NUMERIC_FIELD_CONFIG.review_sample_target.min}
              onBlur={() => normalizeNumericDraft("review_sample_target")}
              onChange={(event) => updateNumericDraft("review_sample_target", event.target.value)}
              type="number"
              value={numericDrafts.review_sample_target}
            />
            {fieldErrors.review_sample_target ? <p className="mt-2 text-sm text-red-600">{fieldErrors.review_sample_target}</p> : null}
          </div>
          <div className="md:col-span-2">
            <Label>时间预算（分钟）</Label>
            <Input
              max={NUMERIC_FIELD_CONFIG.time_budget_minutes.max}
              min={NUMERIC_FIELD_CONFIG.time_budget_minutes.min}
              onBlur={() => normalizeNumericDraft("time_budget_minutes")}
              onChange={(event) => updateNumericDraft("time_budget_minutes", event.target.value)}
              type="number"
              value={numericDrafts.time_budget_minutes}
            />
            {fieldErrors.time_budget_minutes ? <p className="mt-2 text-sm text-red-600">{fieldErrors.time_budget_minutes}</p> : null}
          </div>
        </div>

        <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-600">
          <p>系统会按所选模板组织研究步骤，范围和输出要求会体现在最终报告中。</p>
          <p className="mt-2">草稿会自动保存，刷新后仍会保留；如果想重新开始，可以使用上方“重置草稿”。</p>
        </div>

        <Button className="w-full" disabled={submitting} type="submit">
          {submitting ? "创建中..." : "创建研究任务"}
        </Button>
        {errorMessage ? <p className="text-sm text-red-600">{errorMessage}</p> : null}
      </Card>
    </form>
  );
}
