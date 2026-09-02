"use client";

import { useMemo, useState } from "react";
import { Activity, Eye, Search } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import type { Agent, AgentOperationalStatus } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const filters = ["all", "active", "idle", "failed"] as const;

export function AgentMonitor({ agents }: { agents: Agent[] }) {
  const [filter, setFilter] = useState<(typeof filters)[number]>("all");

  const filtered = useMemo(() => {
    if (filter === "all") {
      return agents;
    }

    return agents.filter((agent) => agent.status === filter);
  }, [agents, filter]);

  return (
    <div className="space-y-6">
      <PageHeader
        description="Monitor MVP agent roles, status, health, recent activity, and execution history."
        title="Agent Monitoring"
      />

      <div className="flex flex-wrap gap-2 rounded-lg border bg-card p-2">
        {filters.map((item) => (
          <Button
            key={item}
            onClick={() => setFilter(item)}
            type="button"
            variant={filter === item ? "default" : "ghost"}
          >
            {item}
          </Button>
        ))}
      </div>

      {filtered.length ? (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {filtered.map((agent) => (
            <Card key={agent.id}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle>{agent.name}</CardTitle>
                    <CardDescription>{agent.role}</CardDescription>
                  </div>
                  <StatusDot status={agent.status} />
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Status" value={<StatusBadge status={agent.status} />} />
                  <Field label="Health" value={<StatusBadge status={agent.health} />} />
                  <Field label="Current task" value={agent.currentTask} />
                  <Field label="Last activity" value={agent.lastActivity} />
                </div>
                <Dialog>
                  <DialogTrigger asChild>
                    <Button variant="outline">
                      <Eye className="h-4 w-4" aria-hidden="true" />
                      Agent detail
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>{agent.name}</DialogTitle>
                      <DialogDescription>{agent.description}</DialogDescription>
                    </DialogHeader>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Field label="Role" value={agent.role} />
                      <Field label="Status" value={<StatusBadge status={agent.status} />} />
                      <Field label="Health" value={<StatusBadge status={agent.health} />} />
                      <Field label="Current task" value={agent.currentTask} />
                    </div>
                    <div className="mt-5 grid gap-5 md:grid-cols-2">
                      <section className="rounded-lg border p-4">
                        <h3 className="text-sm font-semibold">Recent Activity</h3>
                        <div className="mt-3 space-y-3">
                          {agent.recentActivity.map((item) => (
                            <div className="flex gap-2 text-sm text-muted-foreground" key={item}>
                              <Activity className="mt-0.5 h-4 w-4 shrink-0" />
                              <span>{item}</span>
                            </div>
                          ))}
                        </div>
                      </section>
                      <section className="rounded-lg border p-4">
                        <h3 className="text-sm font-semibold">Recent Executions</h3>
                        <div className="mt-3 space-y-3">
                          {agent.recentExecutions.map((execution) => (
                            <div className="rounded-md bg-muted/45 p-3" key={execution.id}>
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <p className="text-sm font-medium">{execution.task}</p>
                                <StatusBadge status={execution.status} />
                              </div>
                              <p className="mt-2 text-xs text-muted-foreground">
                                {formatDateTime(execution.timestamp)}
                              </p>
                            </div>
                          ))}
                        </div>
                      </section>
                    </div>
                  </DialogContent>
                </Dialog>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          description="Change the status filter to inspect other agents."
          icon={Search}
          title="No agents in this state"
        />
      )}
    </div>
  );
}

function StatusDot({ status }: { status: AgentOperationalStatus }) {
  const color =
    status === "active"
      ? "bg-emerald-500"
      : status === "failed"
        ? "bg-red-500"
        : "bg-amber-500";

  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      <span className="capitalize">{status}</span>
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-xs font-semibold uppercase text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 truncate text-sm">{value}</div>
    </div>
  );
}
