"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import { Trash2 } from "lucide-react";
import { Badge, Button, Input, Sheet, useToast } from "@pm-agent/ui";

import { useDeleteMaterial, useMaterial, useUpdateMaterialTags } from "../hooks/use-materials";

interface MaterialDetailSheetProps {
  materialId?: string | null;
  open: boolean;
  onClose: () => void;
  onDeleted?: () => void;
}

export function MaterialDetailSheet({ materialId, open, onClose, onDeleted }: MaterialDetailSheetProps) {
  const { data: material, isLoading } = useMaterial(open ? materialId : null);
  const updateTagsMutation = useUpdateMaterialTags(materialId);
  const deleteMaterialMutation = useDeleteMaterial();
  const [newTag, setNewTag] = useState("");
  const toast = useToast();

  const manualTags = useMemo(
    () => (material?.tags || []).filter((tag) => tag.type === "manual"),
    [material?.tags],
  );

  const handleAddTag = async () => {
    if (!materialId || !newTag.trim()) {
      return;
    }
    try {
      await updateTagsMutation.mutateAsync({
        add: [{ name: newTag.trim(), category: "custom", type: "manual" }],
        remove: [],
      });
      setNewTag("");
      toast.success("标签已更新。");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "标签更新失败。");
    }
  };

  const handleRemoveTag = async (name: string) => {
    if (!materialId) {
      return;
    }
    try {
      await updateTagsMutation.mutateAsync({ add: [], remove: [name] });
      toast.success("标签已移除。");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "标签移除失败。");
    }
  };

  const handleDelete = async () => {
    if (!materialId) {
      return;
    }
    try {
      await deleteMaterialMutation.mutateAsync(materialId);
      toast.success("素材已删除。");
      onDeleted?.();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败。");
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="素材详情" description="查看图片信息、颜色与标签。">
      {isLoading || !material ? (
        <div className="space-y-3">
          <div className="skeleton h-56 rounded-[24px]" />
          <div className="skeleton h-10 rounded-[18px]" />
          <div className="skeleton h-28 rounded-[22px]" />
        </div>
      ) : (
        <div className="space-y-6">
          <div className="overflow-hidden rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(248,250,252,0.9)]">
            <Image
              src={material.full_url}
              alt={material.filename}
              width={Math.max(material.width, 1)}
              height={Math.max(material.height, 1)}
              className="h-auto w-full object-cover"
              unoptimized
            />
          </div>

          <div className="space-y-2">
            <h3 className="text-lg font-semibold text-[color:var(--ink)]">{material.filename}</h3>
            <p className="text-sm text-[color:var(--muted)]">
              {material.width} × {material.height} · {material.mime_type} · {Math.round(material.file_size / 1024)} KB
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {material.colors.map((color) => (
              <span key={color} className="inline-flex items-center gap-2 rounded-full border border-[color:var(--border-soft)] bg-white px-3 py-1.5 text-xs text-[color:var(--ink)]">
                <span className="h-3 w-3 rounded-full border border-white/80" style={{ backgroundColor: color }} />
                {color}
              </span>
            ))}
          </div>

          <div className="space-y-3 rounded-[24px] border border-[color:var(--border-soft)] bg-white/70 p-4">
            <div className="flex items-center justify-between gap-3">
              <h4 className="text-sm font-semibold uppercase tracking-[0.18em] text-[color:var(--muted)]">标签</h4>
              <Badge className="normal-case tracking-[0.02em]">{material.source === "trend" ? "趋势来源" : "图片素材"}</Badge>
            </div>

            <div className="flex flex-wrap gap-2">
              {material.tags.map((tag) => (
                <button
                  key={`${tag.category}-${tag.name}`}
                  onClick={() => (tag.type === "manual" ? void handleRemoveTag(tag.name) : undefined)}
                  type="button"
                  className="rounded-full border border-[color:var(--border-soft)] bg-white px-3 py-1.5 text-xs text-[color:var(--ink)] transition hover:border-[color:var(--accent)]"
                  title={tag.type === "manual" ? "点击移除手动标签" : "自动标签"}
                >
                  {tag.name}
                </button>
              ))}
            </div>

            <div className="flex gap-2">
              <Input value={newTag} onChange={(event) => setNewTag(event.target.value)} placeholder="添加手动标签" />
              <Button onClick={handleAddTag} type="button" variant="secondary" disabled={updateTagsMutation.isPending}>
                添加
              </Button>
            </div>
            {manualTags.length === 0 ? <p className="text-xs text-[color:var(--muted)]">当前还没有手动标签。</p> : null}
          </div>

          <div className="flex justify-end">
            <Button onClick={handleDelete} type="button" variant="ghost" disabled={deleteMaterialMutation.isPending}>
              <Trash2 className="mr-2 h-4 w-4" />
              删除素材
            </Button>
          </div>
        </div>
      )}
    </Sheet>
  );
}
