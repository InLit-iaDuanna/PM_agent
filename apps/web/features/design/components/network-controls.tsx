"use client";

import { Crosshair, RefreshCw, ZoomIn } from "lucide-react";
import { Button, Select } from "@pm-agent/ui";

interface NetworkControlsProps {
  categories: string[];
  selectedCategory: string;
  onCategoryChange: (value: string) => void;
  threshold: number;
  onThresholdChange: (value: number) => void;
  showLabels: boolean;
  onToggleLabels: () => void;
  clusterColored: boolean;
  onToggleClusterColors: () => void;
  onZoomIn: () => void;
  onCenter: () => void;
  onReset: () => void;
}

export function NetworkControls({
  categories,
  selectedCategory,
  onCategoryChange,
  threshold,
  onThresholdChange,
  showLabels,
  onToggleLabels,
  clusterColored,
  onToggleClusterColors,
  onZoomIn,
  onCenter,
  onReset,
}: NetworkControlsProps) {
  return (
    <div className="absolute left-4 top-16 z-20 w-[280px] rounded-[28px] border border-[color:var(--border-soft)] bg-white/88 p-4 shadow-[var(--shadow-lg)] backdrop-blur-xl">
      <div className="space-y-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--muted)]">筛选类别</p>
          <div className="mt-2">
            <Select value={selectedCategory} onChange={(event) => onCategoryChange(event.target.value)}>
              <option value="全部">全部</option>
              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--muted)]">关联强度</p>
            <span className="text-sm text-[color:var(--ink)]">{threshold.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0.1}
            max={0.8}
            step={0.05}
            value={threshold}
            onChange={(event) => onThresholdChange(Number(event.target.value))}
            className="mt-2 w-full accent-[color:var(--accent)]"
          />
        </div>

        <div className="space-y-2">
          <label className="flex items-center justify-between gap-3 text-sm text-[color:var(--ink)]">
            <span>显示标签</span>
            <input type="checkbox" checked={showLabels} onChange={onToggleLabels} className="h-4 w-4 accent-[color:var(--accent)]" />
          </label>
          <label className="flex items-center justify-between gap-3 text-sm text-[color:var(--ink)]">
            <span>聚类着色</span>
            <input
              type="checkbox"
              checked={clusterColored}
              onChange={onToggleClusterColors}
              className="h-4 w-4 accent-[color:var(--accent)]"
            />
          </label>
        </div>

        <div className="flex gap-2">
          <Button onClick={onZoomIn} type="button" variant="secondary" className="flex-1">
            <ZoomIn className="mr-2 h-4 w-4" />
            放大
          </Button>
          <Button onClick={onCenter} type="button" variant="secondary" className="flex-1">
            <Crosshair className="mr-2 h-4 w-4" />
            居中
          </Button>
          <Button onClick={onReset} type="button" variant="ghost" className="flex-1">
            <RefreshCw className="mr-2 h-4 w-4" />
            重置
          </Button>
        </div>
      </div>
    </div>
  );
}
