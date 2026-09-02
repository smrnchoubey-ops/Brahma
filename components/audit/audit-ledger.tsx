"use client";

import { useMemo, useState } from "react";
import { Eye, Search } from "lucide-react";

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
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import type { AuditEvent, AuditStatus } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const statuses = ["All", "success", "warning", "failed", "blocked"] as const;

export function AuditLedger({ events }: { events: AuditEvent[] }) {
  const [query, setQuery] = useState("");
  const [agent, setAgent] = useState("All");
  const [status, setStatus] = useState<(typeof statuses)[number]>("All");
  const [date, setDate] = useState("");

  const agents = useMemo(
    () => ["All", ...Array.from(new Set(events.map((event) => event.agent)))],
    [events]
  );

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();

    return events.filter((event) => {
      const matchesQuery =
        !normalized ||
        [event.task, event.agent, event.action, event.event, event.details]
          .join(" ")
          .toLowerCase()
          .includes(normalized);
      const matchesAgent = agent === "All" || event.agent === agent;
      const matchesStatus = status === "All" || event.status === status;
      const matchesDate =
        !date || event.timestamp.slice(0, 10) === date;

      return matchesQuery && matchesAgent && matchesStatus && matchesDate;
    });
  }, [agent, date, events, query, status]);

  return (
    <div className="space-y-6">
      <PageHeader
        description="Search event history across tasks, agents, actions, status, and timestamps."
        title="Audit Ledger"
      />

      <Card>
        <CardHeader>
          <CardTitle>Event Filters</CardTitle>
          <CardDescription>
            Filter mock ledger entries without making any backend calls.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 lg:grid-cols-[1fr_180px_180px_180px]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search audit events"
                value={query}
              />
            </div>
            <Select
              aria-label="Filter by agent"
              onChange={(event) => setAgent(event.target.value)}
              value={agent}
            >
              {agents.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Filter by status"
              onChange={(event) =>
                setStatus(event.target.value as (typeof statuses)[number])
              }
              value={status}
            >
              {statuses.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
            <Input
              aria-label="Filter by date"
              onChange={(event) => setDate(event.target.value)}
              type="date"
              value={date}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Events</CardTitle>
          <CardDescription>{filtered.length} matching entries</CardDescription>
        </CardHeader>
        <CardContent>
          {filtered.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>Task</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((event) => (
                  <TableRow key={event.id}>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(event.timestamp)}
                    </TableCell>
                    <TableCell className="min-w-52 font-medium">
                      {event.task}
                    </TableCell>
                    <TableCell>{event.agent}</TableCell>
                    <TableCell className="whitespace-nowrap">
                      {event.action}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={event.status as AuditStatus} />
                    </TableCell>
                    <TableCell className="min-w-64 text-muted-foreground">
                      {event.event}
                    </TableCell>
                    <TableCell>
                      <Dialog>
                        <DialogTrigger asChild>
                          <Button size="sm" variant="outline">
                            <Eye className="h-4 w-4" aria-hidden="true" />
                            View
                          </Button>
                        </DialogTrigger>
                        <DialogContent>
                          <DialogHeader>
                            <DialogTitle>{event.action}</DialogTitle>
                            <DialogDescription>
                              Audit event detail for {event.agent}.
                            </DialogDescription>
                          </DialogHeader>
                          <div className="grid gap-4 md:grid-cols-2">
                            <Field label="Timestamp" value={formatDateTime(event.timestamp)} />
                            <Field label="Task" value={event.task} />
                            <Field label="Agent" value={event.agent} />
                            <Field
                              label="Status"
                              value={<StatusBadge status={event.status} />}
                            />
                          </div>
                          <div className="mt-5 rounded-lg border bg-muted/45 p-4">
                            <p className="text-xs font-semibold uppercase text-muted-foreground">
                              Event
                            </p>
                            <p className="mt-2 text-sm">{event.event}</p>
                            <p className="mt-4 text-sm text-muted-foreground">
                              {event.details}
                            </p>
                          </div>
                        </DialogContent>
                      </Dialog>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              description="Adjust search, agent, status, or date filters."
              icon={Search}
              title="No audit events found"
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 text-sm">{value}</div>
    </div>
  );
}
