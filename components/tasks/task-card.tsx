import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/common/status-badge";
import { RiskBadge } from "@/components/common/risk-badge";

import type { Task } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export function TaskCard({ task }: { task: Task }) {
  return (
    <Card className="transition-colors hover:border-slate-300">
      <CardContent className="p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">

            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-base font-semibold">
                {task.title}
              </h3>

              <StatusBadge status={task.status} />

              <RiskBadge level={task.risk_level} />
            </div>

            <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
              {task.prompt}
            </p>

            <div className="mt-3 text-xs text-muted-foreground">
              Created : {formatDateTime(task.created_at)}
            </div>
          </div>

          <Link
            href={`/tasks/${task.id}`}
            className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium hover:bg-muted"
          >
            Open
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}