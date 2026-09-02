import {
  CheckCircle2,
  Circle,
  Clock,
  Loader2,
  OctagonAlert,
  XCircle
} from "lucide-react";

import { StatusBadge } from "@/components/common/status-badge";
import type { AgentTraceStep, WorkflowStatus } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

const statusIcons: Record<WorkflowStatus, typeof Circle> = {
  pending: Circle,
  running: Loader2,
  completed: CheckCircle2,
  failed: XCircle,
  blocked: OctagonAlert,
  waiting_approval: Clock
};

const iconTone: Record<WorkflowStatus, string> = {
  pending: "border-muted bg-background text-muted-foreground",
  running: "border-amber-200 bg-amber-50 text-amber-700",
  completed: "border-emerald-200 bg-emerald-50 text-emerald-700",
  failed: "border-red-200 bg-red-50 text-red-700",
  blocked: "border-red-200 bg-red-50 text-red-700",
  waiting_approval: "border-amber-200 bg-amber-50 text-amber-700"
};

export function AgentTimeline({ trace }: { trace: AgentTraceStep[] }) {
  return (
    <div className="space-y-0">
      {trace.map((step, index) => {
        const Icon = statusIcons[step.status];
        const isLast = index === trace.length - 1;

        return (
          <div className="relative flex gap-4 pb-6 last:pb-0" key={step.id}>
            {!isLast ? (
              <div className="absolute left-5 top-10 h-[calc(100%-2.5rem)] w-px bg-border" />
            ) : null}
            <div
              className={cn(
                "z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border",
                iconTone[step.status]
              )}
            >
              <Icon
                className={cn("h-5 w-5", step.status === "running" && "animate-spin")}
                aria-hidden="true"
              />
            </div>
            <div className="min-w-0 flex-1 rounded-lg border bg-card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold">{step.agentName}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {step.activity}
                  </p>
                </div>
                <StatusBadge status={step.status} />
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                {formatDateTime(step.timestamp)}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
