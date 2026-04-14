"use client";

import { orchestrationPresetCatalog } from "@pm-agent/research-core";
import type { ResearchJobRecord, WorkflowCommandId } from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle } from "@pm-agent/ui";
import { commandIcons, commandUsage, formatSkillPack, formatWorkflowCommand } from "./research-ui-utils";

interface WorkflowCommandCenterProps {
  selectedCommand: WorkflowCommandId;
  onSelectCommand: (commandId: WorkflowCommandId) => void;
  jobs?: ResearchJobRecord[];
  title?: string;
  description?: string;
  showQuickActions?: boolean;
  onApplyToDraft?: (commandId: WorkflowCommandId) => void;
  onLaunchFromCommand?: (commandId: WorkflowCommandId) => void;
  onOpenLatestJob?: (jobId: string) => void;
}

export function WorkflowCommandCenter({
  selectedCommand,
  onSelectCommand,
  jobs = [],
  title = "研究模板",
  description = "先确定研究路径，再补充主题、范围和交付要求。",
  showQuickActions = false,
  onApplyToDraft,
  onLaunchFromCommand,
  onOpenLatestJob,
}: WorkflowCommandCenterProps) {
  const entries = Object.entries(orchestrationPresetCatalog) as Array<[WorkflowCommandId, (typeof orchestrationPresetCatalog)[WorkflowCommandId]]>;

  return (
    <Card className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{`${entries.length} 个模板`}</Badge>
          <Badge tone="success">研究路径 / 输出侧重</Badge>
        </div>
      </div>

      <div aria-label="研究模板列表" className="grid gap-4 xl:grid-cols-2" role="radiogroup">
        {entries.map(([commandId, preset]) => {
          const isSelected = selectedCommand === commandId;
          const Icon = commandIcons[commandId];
          const usage = commandUsage(jobs, commandId);
          return (
            <div
              className={`rounded-[30px] border p-5 text-left transition ${
                isSelected
                  ? "border-[color:var(--accent)] bg-[linear-gradient(135deg,_rgba(29,76,116,0.1),_rgba(255,255,255,0.8))] shadow-[0_16px_34px_rgba(23,32,51,0.08)]"
                  : "border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)]"
              }`}
              key={commandId}
            >
              <button
                aria-checked={isSelected}
                aria-describedby={`${commandId}-summary ${commandId}-usage`}
                aria-label={`选择研究模板：${preset.label}`}
                className={`w-full rounded-[24px] text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--accent)] focus-visible:ring-offset-2 ${
                  isSelected ? "" : "hover:bg-[rgba(255,255,255,0.34)]"
                }`}
                onClick={() => onSelectCommand(commandId)}
                role="radio"
                type="button"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <div
                      className={`rounded-[20px] p-3 ${
                        isSelected ? "bg-[color:var(--accent)] text-white" : "bg-[rgba(29,76,116,0.1)] text-[color:var(--accent)]"
                      }`}
                    >
                      <Icon className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-base font-semibold text-[color:var(--ink)]">{preset.label}</p>
                      <p className="mt-1 text-sm leading-6 text-[color:var(--muted)]" id={`${commandId}-summary`}>
                        {preset.summary}
                      </p>
                    </div>
                  </div>
                  {isSelected ? <Badge tone="success">当前</Badge> : <Badge>{formatWorkflowCommand(commandId)}</Badge>}
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <div className="rounded-2xl bg-[rgba(247,241,231,0.82)] px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">输出侧重</p>
                    <p className="mt-2 text-sm text-[color:var(--ink)]">{preset.focusInstruction}</p>
                  </div>
                  <div className="rounded-2xl bg-[rgba(247,241,231,0.82)] px-4 py-3" id={`${commandId}-usage`}>
                    <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">最近使用</p>
                    <p className="mt-2 text-sm text-[color:var(--ink)]">
                      {usage.total ? `已有 ${usage.total} 个任务使用这个模板` : "当前还没有历史使用记录"}
                    </p>
                    <p className="mt-1 text-xs text-[color:var(--muted)]">{usage.latest?.topic ?? "适合直接发起新的研究任务"}</p>
                    {usage.latest?.updated_at ? (
                      <p className="mt-1 text-xs text-[color:var(--muted)]">{`最近更新：${new Date(usage.latest.updated_at).toLocaleString()}`}</p>
                    ) : null}
                  </div>
                </div>

                <div className="mt-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">默认能力</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(preset.defaultSkillPacks ?? []).map((item) => (
                      <Badge key={item}>{formatSkillPack(item)}</Badge>
                    ))}
                  </div>
                </div>

                <div className="mt-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-[color:var(--muted)]">适用场景</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(preset.recommendedFor ?? []).map((item) => (
                      <Badge key={item} tone="success">
                        {item}
                      </Badge>
                    ))}
                  </div>
                </div>
              </button>

              {showQuickActions ? (
                <div className="mt-5 flex flex-wrap gap-3">
                  <Button
                    onClick={(event) => {
                      event.stopPropagation();
                      onApplyToDraft?.(commandId);
                    }}
                    type="button"
                    variant={isSelected ? "primary" : "secondary"}
                  >
                    用于当前草稿
                  </Button>
                  <Button
                    onClick={(event) => {
                      event.stopPropagation();
                      onLaunchFromCommand?.(commandId);
                    }}
                    type="button"
                    variant="ghost"
                  >
                    以此模板新建
                  </Button>
                  {usage.latest ? (
                    <Button
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenLatestJob?.(usage.latest?.id);
                      }}
                      type="button"
                      variant="ghost"
                    >
                      打开最近任务
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
