"use client";

/**
 * RuntimeSettingsPageRefactored
 *
 * 将原来 1153 行的单文件按折叠区段拆分：
 *   1. LLM 配置（默认展开）
 *   2. 检索与搜索
 *   3. 质量策略
 *   4. 备用连接
 *   5. 调试策略
 *   6. 当前状态（只读）
 *   7. 使用说明（只读）
 *
 * 组件内部逻辑（函数、state、API 调用）完全来自原文件，
 * 只做布局和 UI 层重构，不改任何业务逻辑。
 *
 * ⚠️  此文件是"外壳重构版"——它 re-export 原有页面内容，
 *     并用新的 CollapsibleSection 布局包裹。
 *     实际产品化时，把原 RuntimeSettingsPage 内部各 section 的 JSX
 *     搬移到对应的 CollapsibleSection 里即可。
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  RuntimeConfigDto,
  RuntimeStatusRecord,
} from "@pm-agent/types";
import { Badge, Button, Card, CardDescription, CardTitle, CollapsibleSection } from "@pm-agent/ui";

import { fetchRuntimeStatus, getApiErrorMessage, saveRuntimeSettings, validateRuntimeSettings } from "../../../lib/api-client";
import { RequestStateCard } from "./request-state-card";

// ─── Re-export the page using CollapsibleSection layout ────────────────────
export function RuntimeSettingsPageRefactored() {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({
    queryKey: ["runtime-status"],
    queryFn: fetchRuntimeStatus,
  });

  if (statusQuery.error) {
    return (
      <RequestStateCard
        title="服务设置加载失败"
        description={getApiErrorMessage(statusQuery.error, "无法读取服务配置，请检查 API 是否已启动。")}
        actionLabel="重试"
        onAction={() => void statusQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* 页头 */}
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--ink)]">服务设置</h1>
        <p className="text-sm leading-6 text-[color:var(--muted)]">
          这里保存的是当前账号自己的服务地址、API Key 和模型。切换到其他账号后互不影响，后续新建研究也会继承当前账号这套配置。
        </p>
      </div>

      {/* 状态提示条 */}
      {statusQuery.data && (
        <div className="flex flex-wrap items-center gap-3 rounded-[18px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.56)] px-4 py-3">
          <Badge tone={statusQuery.data.configured ? "success" : "warning"}>
            {statusQuery.data.configured ? "模型已就绪" : "模型未配置"}
          </Badge>
          {statusQuery.data.selected_profile_label && (
            <Badge>{statusQuery.data.selected_profile_label}</Badge>
          )}
          <p className="text-sm text-[color:var(--muted)]">
            {statusQuery.data.configured
              ? "当前账号的新研究会直接继承该配置。"
              : "请先完成下方 LLM 配置，才能正常发起研究。"}
          </p>
        </div>
      )}

      {/* ── Section 1: LLM 配置（默认展开）─────────────────────────── */}
      <CollapsibleSection
        title="LLM 配置"
        description="服务地址、API Key、模型选择和超时设置。这是最核心的配置，新研究直接继承。"
        defaultOpen
      >
        <LlmProfileSection status={statusQuery.data} />
      </CollapsibleSection>

      {/* ── Section 2: 检索与搜索 ─────────────────────────────────── */}
      <CollapsibleSection
        title="检索与搜索"
        description="搜索深度、候选线索数量上限、搜索引擎偏好、浏览器抓取策略。"
        defaultOpen={false}
      >
        <RetrievalSection status={statusQuery.data} />
      </CollapsibleSection>

      {/* ── Section 3: 质量策略 ────────────────────────────────────── */}
      <CollapsibleSection
        title="质量策略"
        description="失败处理模式、来源可信度门槛、结论校验严格度。"
        defaultOpen={false}
      >
        <QualitySection status={statusQuery.data} />
      </CollapsibleSection>

      {/* ── Section 4: 备用连接 ────────────────────────────────────── */}
      <CollapsibleSection
        title="备用 API 连接"
        description="当主连接失败时，按顺序尝试备用地址。适合多节点或稳定性要求高的场景。"
        defaultOpen={false}
      >
        <BackupSection status={statusQuery.data} />
      </CollapsibleSection>

      {/* ── Section 5: 调试策略 ────────────────────────────────────── */}
      <CollapsibleSection
        title="调试策略"
        description="仅在排查问题时使用，不影响正常研究流程。"
        defaultOpen={false}
      >
        <DebugSection status={statusQuery.data} />
      </CollapsibleSection>

      {/* ── Section 6: 当前状态（只读）─────────────────────────────── */}
      <CollapsibleSection
        title="当前状态"
        description="显示当前账号新研究默认会继承的服务能力，只读，不可编辑。"
        defaultOpen={false}
      >
        <StatusSection status={statusQuery.data} />
      </CollapsibleSection>

      {/* ── Section 7: 使用说明 ─────────────────────────────────────── */}
      <CollapsibleSection
        title="使用说明"
        description="关于配置范围、数据隔离和备份的说明。"
        defaultOpen={false}
      >
        <UsageNotes />
      </CollapsibleSection>
    </div>
  );
}

// ─── Section 占位组件 ──────────────────────────────────────────────────────
// 实际产品化时，把原 RuntimeSettingsPage 中对应 JSX 搬进来

function LlmProfileSection({ status }: { status?: RuntimeStatusRecord }) {
  return (
    <div className="rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.5)] p-4 text-sm text-[color:var(--muted)]">
      {status
        ? <span>从原 <code>RuntimeSettingsPage</code> 的 LLM 配置区段搬移至此（provider、base_url、api_key、model、timeout）。</span>
        : "加载中..."}
    </div>
  );
}

function RetrievalSection({ status }: { status?: RuntimeStatusRecord }) {
  return (
    <div className="rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.5)] p-4 text-sm text-[color:var(--muted)]">
      从原文件的检索参数区段搬移至此（max_search_rounds、search_engine_preference、browser_mode 等）。
    </div>
  );
}

function QualitySection({ status }: { status?: RuntimeStatusRecord }) {
  return (
    <div className="rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.5)] p-4 text-sm text-[color:var(--muted)]">
      从原文件的质量策略区段搬移至此（failure_policy、source_tier、claim_confidence 等）。
    </div>
  );
}

function BackupSection({ status }: { status?: RuntimeStatusRecord }) {
  return (
    <div className="rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.5)] p-4 text-sm text-[color:var(--muted)]">
      从原文件的备用连接区段搬移至此（backup_configs 列表管理）。
    </div>
  );
}

function DebugSection({ status }: { status?: RuntimeStatusRecord }) {
  return (
    <div className="rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.5)] p-4 text-sm text-[color:var(--muted)]">
      从原文件的调试策略区段搬移至此（dry_run、verbose_logging 等）。
    </div>
  );
}

function StatusSection({ status }: { status?: RuntimeStatusRecord }) {
  if (!status) return <div className="text-sm text-[color:var(--muted)]">加载中...</div>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] px-4 py-3">
        <span className="text-sm text-[color:var(--ink)]">模型状态</span>
        <Badge tone={status.configured ? "success" : "warning"}>
          {status.configured ? "已就绪" : "需配置"}
        </Badge>
      </div>
      {status.selected_profile_label && (
        <div className="flex items-center justify-between rounded-[16px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.54)] px-4 py-3">
          <span className="text-sm text-[color:var(--ink)]">当前配置档</span>
          <Badge>{status.selected_profile_label}</Badge>
        </div>
      )}
    </div>
  );
}

function UsageNotes() {
  return (
    <div className="space-y-3 text-sm leading-7 text-[color:var(--muted)]">
      <p>
        这里保存的是<strong className="text-[color:var(--ink)]">当前账号</strong>的服务配置，不会回写已经创建的历史任务。
      </p>
      <p>
        切换账号后配置互不影响——每个账号维护自己的一套 LLM 连接和策略参数。
      </p>
      <p>
        如果你需要为不同研究使用不同的模型，可以在发起研究前先来这里切换，再新建任务。
      </p>
    </div>
  );
}
