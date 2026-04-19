"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Select } from "@pm-agent/ui";

import { MaterialDetailSheet } from "../../../features/design/components/material-detail-sheet";
import { MaterialGallery } from "../../../features/design/components/material-gallery";
import { MaterialUploader } from "../../../features/design/components/material-uploader";
import { useMaterialTags, useMaterials } from "../../../features/design/hooks/use-materials";
import { useDesignStore } from "../../../features/design/store/design-store";

const FILTER_CATEGORIES = [
  { label: "全部类别", value: "" },
  { label: "色彩标签", value: "color" },
  { label: "风格标签", value: "style" },
  { label: "情绪标签", value: "mood" },
  { label: "构图标签", value: "composition" },
  { label: "元素标签", value: "element" },
  { label: "自定义标签", value: "custom" },
];

export default function DesignMaterialsPage() {
  const router = useRouter();
  const { selected_material_id, setMaterialsSnapshot, setSelectedMaterialId } = useDesignStore();
  const [tagFilter, setTagFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [page, setPage] = useState(1);

  const materialsQuery = useMaterials({
    tag: tagFilter || undefined,
    category: categoryFilter || undefined,
    page,
    page_size: 30,
  });
  const tagsQuery = useMaterialTags();

  useEffect(() => {
    if (!materialsQuery.data?.items) {
      return;
    }
    setMaterialsSnapshot(materialsQuery.data.items);
  }, [materialsQuery.data?.items, setMaterialsSnapshot]);

  const totalPages = useMemo(() => {
    if (!materialsQuery.data) {
      return 1;
    }
    return Math.max(1, Math.ceil(materialsQuery.data.total / materialsQuery.data.page_size));
  }, [materialsQuery.data]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-[color:var(--muted)]">Material Library</p>
          <h1 className="mt-2 text-[clamp(2rem,4vw,3rem)] font-semibold tracking-[-0.05em] text-[color:var(--ink)]">设计素材库</h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-[color:var(--muted)]">把上传图片、趋势收藏和远程灵感图沉淀成一套可筛选、可联想的视觉资产库。</p>
        </div>
        <div className="flex gap-3">
          <Button asChild type="button" variant="secondary">
            <Link href="/design/trend">回到趋势页</Link>
          </Button>
        </div>
      </div>

      <MaterialUploader onUploaded={(materialId) => setSelectedMaterialId(materialId)} />

      <Card className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-[color:var(--ink)]">筛选与浏览</h2>
            <p className="text-sm text-[color:var(--muted)]">按标签类别或具体标签筛选素材，点击卡片打开详情侧栏。</p>
          </div>
          <Button
            onClick={() => router.push(`/design/network${selected_material_id ? `?highlight=${encodeURIComponent(selected_material_id)}` : ""}`)}
            type="button"
          >
            查看关联网络
          </Button>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--muted)]">标签类别</label>
            <Select
              value={categoryFilter}
              onChange={(event) => {
                setPage(1);
                setCategoryFilter(event.target.value);
              }}
            >
              {FILTER_CATEGORIES.map((item) => (
                <option key={item.value || "all"} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--muted)]">具体标签</label>
            <Select
              value={tagFilter}
              onChange={(event) => {
                setPage(1);
                setTagFilter(event.target.value);
              }}
            >
              <option value="">全部标签</option>
              {(tagsQuery.data || []).map((tag) => (
                <option key={tag} value={tag}>
                  {tag}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </Card>

      {materialsQuery.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <Card key={index} className="space-y-4">
              <div className="skeleton h-60 rounded-[24px]" />
              <div className="skeleton h-5 rounded-[12px]" />
              <div className="skeleton h-12 rounded-[18px]" />
            </Card>
          ))}
        </div>
      ) : materialsQuery.data?.items?.length ? (
        <>
          <MaterialGallery
            items={materialsQuery.data.items}
            selectedId={selected_material_id}
            onSelect={setSelectedMaterialId}
            onOpenNetwork={() =>
              router.push(`/design/network${selected_material_id ? `?highlight=${encodeURIComponent(selected_material_id)}` : ""}`)
            }
          />

          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-[color:var(--muted)]">
              共 {materialsQuery.data.total} 条素材 · 第 {materialsQuery.data.page} / {totalPages} 页
            </p>
            <div className="flex gap-2">
              <Button onClick={() => setPage((value) => Math.max(1, value - 1))} type="button" variant="secondary" disabled={page <= 1}>
                上一页
              </Button>
              <Button onClick={() => setPage((value) => Math.min(totalPages, value + 1))} type="button" variant="secondary" disabled={page >= totalPages}>
                下一页
              </Button>
            </div>
          </div>
        </>
      ) : (
        <Card className="flex min-h-[240px] items-center justify-center text-center">
          <div className="space-y-3">
            <h2 className="text-xl font-semibold text-[color:var(--ink)]">还没有素材</h2>
            <p className="text-sm leading-7 text-[color:var(--muted)]">先上传一张图片，或者从趋势页把灵感收藏进来。</p>
          </div>
        </Card>
      )}

      <MaterialDetailSheet
        open={Boolean(selected_material_id)}
        materialId={selected_material_id}
        onClose={() => setSelectedMaterialId(null)}
        onDeleted={() => setSelectedMaterialId(null)}
      />
    </div>
  );
}
