import { CheckCircle2 } from "lucide-react";
import { cn } from "../lib/cn";

export interface Step {
  id: string;
  label: string;
  sublabel?: string;
}

type StepStatus = "done" | "active" | "pending";

interface StepIndicatorProps {
  steps: Step[];
  activeId: string;
  className?: string;
  /** "horizontal"（默认）| "vertical" */
  orientation?: "horizontal" | "vertical";
}

function getStepStatus(steps: Step[], activeId: string, stepId: string): StepStatus {
  const activeIndex = steps.findIndex((s) => s.id === activeId);
  const thisIndex   = steps.findIndex((s) => s.id === stepId);
  if (thisIndex < activeIndex) return "done";
  if (thisIndex === activeIndex) return "active";
  return "pending";
}

/**
 * StepIndicator — 研究阶段进度指示器
 *
 * 用法：
 *   const PHASES = [
 *     { id: "scoping",     label: "界定范围" },
 *     { id: "planning",    label: "任务规划" },
 *     { id: "collecting",  label: "证据采集" },
 *     { id: "verifying",   label: "结论校验" },
 *     { id: "synthesizing",label: "初稿成文" },
 *     { id: "finalizing",  label: "终稿整理" },
 *   ];
 *   <StepIndicator steps={PHASES} activeId={job.current_phase} />
 */
export function StepIndicator({
  steps,
  activeId,
  className,
  orientation = "horizontal",
}: StepIndicatorProps) {
  if (orientation === "vertical") {
    return (
      <ol className={cn("flex flex-col gap-0", className)}>
        {steps.map((step, i) => {
          const status = getStepStatus(steps, activeId, step.id);
          const isLast = i === steps.length - 1;
          return (
            <li key={step.id} className="flex items-start gap-3">
              {/* Dot + connector */}
              <div className="flex flex-col items-center">
                <StepDot status={status} />
                {!isLast && (
                  <div
                    className={cn(
                      "mt-1 w-0.5 flex-1 min-h-[24px]",
                      status === "done" ? "bg-[color:var(--accent)]" : "bg-[color:var(--border-soft)]",
                    )}
                  />
                )}
              </div>
              {/* Label */}
              <div className="pb-5 pt-0.5">
                <p
                  className={cn(
                    "text-sm font-medium leading-5",
                    status === "active"  && "text-[color:var(--ink)]",
                    status === "done"    && "text-[color:var(--muted-strong)]",
                    status === "pending" && "text-[color:var(--muted)]",
                  )}
                >
                  {step.label}
                </p>
                {step.sublabel && (
                  <p className="mt-0.5 text-xs text-[color:var(--muted)]">{step.sublabel}</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    );
  }

  // horizontal
  return (
    <ol className={cn("flex items-center gap-0 overflow-x-auto", className)}>
      {steps.map((step, i) => {
        const status = getStepStatus(steps, activeId, step.id);
        const isLast = i === steps.length - 1;
        return (
          <li key={step.id} className="flex min-w-0 flex-1 items-center">
            <div className="flex min-w-0 flex-col items-center gap-2">
              <StepDot status={status} />
              <div className="text-center">
                <p
                  className={cn(
                    "truncate text-[11px] font-medium leading-4",
                    status === "active"  && "text-[color:var(--ink)]",
                    status === "done"    && "text-[color:var(--muted-strong)]",
                    status === "pending" && "text-[color:var(--muted)]",
                  )}
                >
                  {step.label}
                </p>
                {step.sublabel && (
                  <p className="truncate text-[10px] text-[color:var(--muted)]">{step.sublabel}</p>
                )}
              </div>
            </div>
            {!isLast && (
              <div
                className={cn(
                  "mx-2 h-0.5 flex-1 rounded-full",
                  status === "done" ? "bg-[color:var(--accent)]" : "bg-[color:var(--border-soft)]",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function StepDot({ status }: { status: StepStatus }) {
  if (status === "done") {
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[color:var(--accent)]">
        <CheckCircle2 className="h-3.5 w-3.5 text-white" />
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="relative flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-[color:var(--accent)] bg-white">
        <span className="h-2 w-2 rounded-full bg-[color:var(--accent)] animate-agent-pulse" />
      </span>
    );
  }
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.6)]" />
  );
}
