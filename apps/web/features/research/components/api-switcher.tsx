"use client";

import { CheckCircle2, ChevronDown, RotateCcw, Wifi } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { Badge, Button, Input } from "@pm-agent/ui";

import { getApiBaseUrl, getApiBaseUrlCandidates, getDefaultApiBaseUrl, setApiBaseUrl } from "../../../lib/api-base-url";

function normalizeApiBaseUrl(value: string) {
  return value.trim().replace(/\/$/, "");
}

function isValidApiBaseUrl(value: string) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function shortApiLabel(value: string) {
  try {
    const parsed = new URL(value);
    return `${parsed.hostname}${parsed.port ? `:${parsed.port}` : ""}`;
  } catch {
    return value;
  }
}

export function ApiSwitcher() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(getDefaultApiBaseUrl());
  const [panelOpen, setPanelOpen] = useState(false);
  const [feedback, setFeedback] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setValue(getApiBaseUrl());
  }, []);

  const currentBaseUrl = getApiBaseUrl();
  const normalizedValue = normalizeApiBaseUrl(value);
  const hasChanges = normalizedValue !== currentBaseUrl;
  const quickCandidates = useMemo(
    () =>
      Array.from(
        new Set([
          currentBaseUrl,
          getDefaultApiBaseUrl(),
          ...getApiBaseUrlCandidates().filter((item) => item.includes("127.0.0.1:8000") || item.includes("127.0.0.1:8001") || item.includes("localhost:8000")),
        ]),
      ).slice(0, 5),
    [currentBaseUrl],
  );

  const refreshApiQueries = async () => {
    await queryClient.invalidateQueries();
    router.refresh();
  };

  const onSave = async () => {
    if (!normalizedValue) {
      setFeedback({ tone: "danger", text: "请输入可访问的 API 地址。" });
      return;
    }
    if (!isValidApiBaseUrl(normalizedValue)) {
      setFeedback({ tone: "danger", text: "API 地址必须是完整的 http(s) URL，例如 http://127.0.0.1:8000。" });
      return;
    }
    if (!hasChanges) {
      setFeedback({ tone: "success", text: "当前已经在使用这个 API 地址。" });
      return;
    }
    setSaving(true);
    setApiBaseUrl(normalizedValue);
    setFeedback({ tone: "success", text: `已切换到 ${normalizedValue}，正在刷新当前页面数据。` });
    await refreshApiQueries();
    setSaving(false);
  };

  const onReset = async () => {
    const defaultValue = getDefaultApiBaseUrl();
    setValue(defaultValue);
    setApiBaseUrl(defaultValue);
    setSaving(true);
    setFeedback({ tone: "success", text: `已恢复默认地址 ${defaultValue}。` });
    await refreshApiQueries();
    setSaving(false);
  };

  return (
    <div className="relative w-full lg:w-auto">
      <div className="glass-panel flex flex-wrap items-center justify-between gap-3 rounded-[28px] px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="status-glow flex h-9 w-9 items-center justify-center rounded-2xl border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.7)]">
            <Wifi className="h-4 w-4 text-[color:var(--accent)]" />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.2em] text-[color:var(--muted)]">服务连接</p>
            <p className="truncate text-sm font-medium text-[color:var(--ink)]">{shortApiLabel(currentBaseUrl)}</p>
          </div>
        </div>
        <Button
          className="shrink-0"
          onClick={() => setPanelOpen((current) => !current)}
          type="button"
          variant="secondary"
        >
          连接选项
          <ChevronDown className={`ml-2 h-4 w-4 transition ${panelOpen ? "rotate-180" : ""}`} />
        </Button>
      </div>
      {panelOpen ? (
        <div className="glass-panel mt-3 w-full rounded-[30px] p-5 shadow-[0_22px_48px_rgba(23,32,51,0.14)] lg:absolute lg:right-0 lg:z-30 lg:mt-2 lg:w-[32rem]">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-[color:var(--ink)]">切换服务地址</p>
              <p className="mt-1 text-xs text-[color:var(--muted)]">修改后会自动刷新当前页面数据，不再整页 reload。</p>
            </div>
            <Badge>{`当前 ${shortApiLabel(currentBaseUrl)}`}</Badge>
          </div>

          <div className="mt-4 space-y-3">
            <Input
              className="bg-white"
              onChange={(event) => {
                setValue(event.target.value);
                setFeedback(null);
              }}
              placeholder="http://127.0.0.1:8000"
              value={value}
            />
            <div className="flex flex-wrap gap-2">
              {quickCandidates.map((candidate) => (
                <Button key={candidate} onClick={() => setValue(candidate)} type="button" variant="ghost">
                  {shortApiLabel(candidate)}
                </Button>
              ))}
            </div>
            <div className="flex flex-wrap gap-3">
              <Button disabled={saving} onClick={() => void onSave()} type="button">
                {saving ? "刷新中..." : hasChanges ? "应用并刷新" : "使用当前地址"}
              </Button>
              <Button disabled={saving} onClick={() => void onReset()} type="button" variant="secondary">
                <RotateCcw className="mr-2 h-4 w-4" />
                恢复默认
              </Button>
              <Button onClick={() => setPanelOpen(false)} type="button" variant="ghost">
                收起
              </Button>
            </div>
          </div>

          <div className="mt-4 space-y-2 text-xs text-slate-500">
            <p>{`默认地址：${getDefaultApiBaseUrl()}`}</p>
            {feedback ? (
              <p className={feedback.tone === "success" ? "text-emerald-700" : "text-rose-700"}>
                {feedback.tone === "success" ? <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" /> : null}
                {feedback.text}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
