import type { ReactNode } from "react";

import { Card, CardDescription, CardTitle } from "./card";

export function StatCard({
  label,
  value,
  helper,
  icon,
}: {
  label: string;
  value: string;
  helper: string;
  icon?: ReactNode;
}) {
  return (
    <Card className="space-y-3 overflow-hidden">
      <div className="flex items-center justify-between gap-3">
        <CardDescription className="text-[11px] uppercase tracking-[0.18em]">{label}</CardDescription>
        {icon}
      </div>
      <CardTitle className="text-3xl sm:text-[2rem]">{value}</CardTitle>
      <CardDescription className="max-w-[26ch]">{helper}</CardDescription>
    </Card>
  );
}
