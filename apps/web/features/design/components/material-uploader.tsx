"use client";

import { useRef, useState } from "react";
import { ImagePlus, Link2, UploadCloud } from "lucide-react";
import { Button, Card, Input, useToast } from "@pm-agent/ui";

import { useUploadMaterial, useUploadMaterialFromUrl } from "../hooks/use-materials";

interface MaterialUploaderProps {
  onUploaded?: (materialId: string) => void;
}

export function MaterialUploader({ onUploaded }: MaterialUploaderProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [urlTags, setUrlTags] = useState("");
  const toast = useToast();
  const uploadMaterialMutation = useUploadMaterial();
  const uploadUrlMutation = useUploadMaterialFromUrl();

  const isUploading = uploadMaterialMutation.isPending || uploadUrlMutation.isPending;

  const handleFile = async (file: File) => {
    try {
      const material = await uploadMaterialMutation.mutateAsync(file);
      toast.success("素材上传成功。");
      onUploaded?.(material.id);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "素材上传失败。");
    }
  };

  const handleUrlUpload = async () => {
    if (!url.trim()) {
      toast.warn("请先填写图片地址。");
      return;
    }
    try {
      const material = await uploadUrlMutation.mutateAsync({
        url: url.trim(),
        tags: urlTags
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      setUrl("");
      setUrlTags("");
      toast.success("远程图片已导入素材库。");
      onUploaded?.(material.id);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "远程图片导入失败。");
    }
  };

  return (
    <Card className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-[-0.03em] text-[color:var(--ink)]">上传素材</h2>
          <p className="mt-1 text-sm leading-6 text-[color:var(--muted)]">支持本地图片上传，也支持通过 URL 采集灵感图。</p>
        </div>
        <Button onClick={() => fileInputRef.current?.click()} type="button" disabled={isUploading}>
          <UploadCloud className="mr-2 h-4 w-4" />
          {uploadMaterialMutation.isPending ? "上传中..." : "选择本地图片"}
        </Button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) {
            void handleFile(file);
          }
          event.currentTarget.value = "";
        }}
      />

      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        className="flex min-h-[180px] w-full flex-col items-center justify-center rounded-[28px] border border-dashed border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.68)] px-5 py-8 text-center transition hover:border-[color:var(--accent)] hover:bg-white"
      >
        <ImagePlus className="h-8 w-8 text-[color:var(--accent)]" />
        <p className="mt-4 text-base font-medium text-[color:var(--ink)]">拖拽或点击上传设计素材</p>
        <p className="mt-2 max-w-md text-sm leading-6 text-[color:var(--muted)]">
          上传后会自动生成缩略图、提取主色，并为关联网络图准备初始标签。
        </p>
      </button>

      <div className="grid gap-3 md:grid-cols-[1.6fr_1fr_auto]">
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--muted)]">图片链接</label>
          <Input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://example.com/inspiration.png"
          />
        </div>
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--muted)]">初始标签</label>
          <Input
            value={urlTags}
            onChange={(event) => setUrlTags(event.target.value)}
            placeholder="极简, 冷色调, 海报"
          />
        </div>
        <div className="flex items-end">
          <Button onClick={handleUrlUpload} type="button" variant="secondary" disabled={isUploading}>
            <Link2 className="mr-2 h-4 w-4" />
            {uploadUrlMutation.isPending ? "导入中..." : "导入链接"}
          </Button>
        </div>
      </div>
    </Card>
  );
}
