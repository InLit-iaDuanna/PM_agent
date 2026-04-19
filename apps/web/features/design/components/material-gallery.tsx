"use client";

import Image from "next/image";
import { Network, Sparkles } from "lucide-react";
import { Badge, Button } from "@pm-agent/ui";

import type { MaterialItem } from "../data/trend-types";

interface MaterialGalleryProps {
  items: MaterialItem[];
  selectedId?: string | null;
  onSelect: (materialId: string) => void;
  onOpenNetwork?: () => void;
}

export function MaterialGallery({ items, selectedId, onSelect, onOpenNetwork }: MaterialGalleryProps) {
  return (
    <div className="relative">
      <div className="columns-1 gap-4 md:columns-2 xl:columns-3">
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => onSelect(item.id)}
            type="button"
            className="mb-4 inline-block w-full break-inside-avoid rounded-[28px] border bg-white/82 p-3 text-left shadow-[var(--shadow-sm)] transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-md)]"
            style={{
              borderColor: item.id === selectedId ? "var(--accent)" : "var(--border-soft)",
            }}
          >
            <div className="relative overflow-hidden rounded-[22px] bg-[rgba(15,23,42,0.05)]">
              <Image
                src={item.thumbnail_url}
                alt={item.filename}
                width={item.width}
                height={item.height}
                className="h-auto w-full object-cover"
                unoptimized
              />
            </div>

            <div className="mt-3 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-[color:var(--ink)]">{item.filename}</p>
                <Badge className="normal-case tracking-[0.02em]">{item.source === "trend" ? "趋势收藏" : "素材"}</Badge>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {item.colors.slice(0, 5).map((color) => (
                  <span key={`${item.id}-${color}`} className="h-3 w-3 rounded-full border border-white/80" style={{ backgroundColor: color }} />
                ))}
              </div>

              <div className="flex flex-wrap gap-1.5">
                {item.tags.slice(0, 4).map((tag) => (
                  <Badge key={`${item.id}-${tag.category}-${tag.name}`} className="normal-case tracking-[0.02em]">
                    {tag.name}
                  </Badge>
                ))}
              </div>

              <div className="flex items-center justify-between gap-2 text-xs text-[color:var(--muted)]">
                <span>{item.width} × {item.height}</span>
                {item.trend_id ? (
                  <span className="inline-flex items-center gap-1">
                    <Sparkles className="h-3.5 w-3.5" />
                    含趋势来源
                  </span>
                ) : null}
              </div>
            </div>
          </button>
        ))}
      </div>

      {onOpenNetwork ? (
        <div className="pointer-events-none fixed bottom-10 right-8 z-20">
          <Button onClick={onOpenNetwork} type="button" className="pointer-events-auto">
            <Network className="mr-2 h-4 w-4" />
            查看关联网络
          </Button>
        </div>
      ) : null}
    </div>
  );
}
