"use client";

import { AlertTriangle, Loader2 } from "lucide-react";

import { Button, Card, CardDescription, CardTitle } from "@pm-agent/ui";

export function RequestStateCard({
  title,
  description,
  actionLabel,
  loading = false,
  onAction,
}: {
  title: string;
  description: string;
  actionLabel?: string;
  loading?: boolean;
  onAction?: () => void;
}) {
  return (
    <Card className="space-y-5">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-[20px] border border-[color:var(--border-soft)] bg-[rgba(255,255,255,0.72)] p-3 text-[color:var(--accent)]">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
        </div>
        <div className="space-y-1">
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
      </div>
      {actionLabel && onAction ? (
        <div className="flex justify-end">
          <Button onClick={onAction} type="button" variant="secondary">
            {actionLabel}
          </Button>
        </div>
      ) : null}
    </Card>
  );
}
