"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Button } from "@pm-agent/ui";

import { MaterialDetailSheet } from "../../../features/design/components/material-detail-sheet";
import { NetworkControls } from "../../../features/design/components/network-controls";
import { NetworkGraph } from "../../../features/design/components/network-graph";
import { useMaterialNetwork } from "../../../features/design/hooks/use-materials";
import { useDesignStore } from "../../../features/design/store/design-store";

export default function DesignNetworkPage() {
  const searchParams = useSearchParams();
  const networkQuery = useMaterialNetwork();
  const { selected_material_id, setNetworkViewActive, setSelectedMaterialId } = useDesignStore();
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [showLabels, setShowLabels] = useState(true);
  const [clusterColored, setClusterColored] = useState(true);
  const [threshold, setThreshold] = useState(0.15);
  const [selectedCategory, setSelectedCategory] = useState("全部");
  const [controlAction, setControlAction] = useState<{ type: "zoom_in" | "center" | "reset"; token: number } | null>(null);

  const highlightNodeId = searchParams.get("highlight") || selected_material_id || undefined;

  useEffect(() => {
    setNetworkViewActive(true);
    const updateViewport = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => {
      setNetworkViewActive(false);
      window.removeEventListener("resize", updateViewport);
    };
  }, [setNetworkViewActive]);

  const categoryOptions = useMemo(
    () =>
      Array.from(new Set((networkQuery.data?.links || []).map((item) => item.shared_category).filter((value): value is string => Boolean(value)))),
    [networkQuery.data?.links],
  );

  return (
    <div className="fixed inset-0 z-[70] bg-[var(--bg)]">
      <div className="absolute left-4 top-4 z-20 flex items-center gap-3">
        <Button asChild type="button" variant="secondary">
          <Link href="/design/materials">
            <ArrowLeft className="mr-2 h-4 w-4" />
            返回素材库
          </Link>
        </Button>
      </div>

      <NetworkControls
        categories={categoryOptions}
        selectedCategory={selectedCategory}
        onCategoryChange={setSelectedCategory}
        threshold={threshold}
        onThresholdChange={setThreshold}
        showLabels={showLabels}
        onToggleLabels={() => setShowLabels((value) => !value)}
        clusterColored={clusterColored}
        onToggleClusterColors={() => setClusterColored((value) => !value)}
        onZoomIn={() => setControlAction({ type: "zoom_in", token: Date.now() })}
        onCenter={() => setControlAction({ type: "center", token: Date.now() })}
        onReset={() => setControlAction({ type: "reset", token: Date.now() })}
      />

      {networkQuery.isLoading ? (
        <div className="flex h-full items-center justify-center">
          <div className="space-y-3 text-center">
            <p className="text-xs uppercase tracking-[0.22em] text-[color:var(--muted)]">Material Network</p>
            <p className="text-base text-[color:var(--ink)]">正在编织素材之间的关系...</p>
          </div>
        </div>
      ) : networkQuery.error ? (
        <div className="flex h-full items-center justify-center px-4">
          <div className="max-w-lg rounded-[28px] border border-[color:var(--border-soft)] bg-white/88 p-6 text-center shadow-[var(--shadow-lg)]">
            <h2 className="text-xl font-semibold text-[color:var(--ink)]">网络图加载失败</h2>
            <p className="mt-3 text-sm leading-7 text-[color:var(--muted)]">
              {networkQuery.error instanceof Error ? networkQuery.error.message : "请稍后重试。"}
            </p>
          </div>
        </div>
      ) : (networkQuery.data?.nodes.length || 0) === 0 ? (
        <div className="flex h-full items-center justify-center px-4">
          <div className="max-w-lg rounded-[28px] border border-[color:var(--border-soft)] bg-white/88 p-6 text-center shadow-[var(--shadow-lg)]">
            <h2 className="text-xl font-semibold text-[color:var(--ink)]">还没有足够素材</h2>
            <p className="mt-3 text-sm leading-7 text-[color:var(--muted)]">至少上传几张素材，网络图才会显示更丰富的连接。</p>
          </div>
        </div>
      ) : (
        <NetworkGraph
          data={networkQuery.data!}
          width={viewport.width}
          height={viewport.height}
          threshold={threshold}
          categoryFilter={selectedCategory}
          showLabels={showLabels}
          clusterColored={clusterColored}
          controlAction={controlAction}
          highlightNodeId={highlightNodeId}
          onNodeClick={(nodeId) => setSelectedMaterialId(nodeId)}
          onNodeHover={() => undefined}
        />
      )}

      <MaterialDetailSheet open={Boolean(selected_material_id)} materialId={selected_material_id} onClose={() => setSelectedMaterialId(null)} />
    </div>
  );
}
