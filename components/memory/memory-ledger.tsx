"use client";

import { useMemo, useState } from "react";
import { Check, Eye, Search } from "lucide-react";

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
import type { MemoryItem, MemoryStatus, MemoryType } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const allTypes = ["All", "Working", "Episodic", "Semantic", "Strategic"] as const;
const allStatuses = [
  "All",
  "Candidate",
  "Approved",
  "Canonical",
  "Deprecated"
] as const;

export function MemoryLedger({ items }: { items: MemoryItem[] }) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState<(typeof allTypes)[number]>("All");
  const [statusById, setStatusById] = useState<Record<string, MemoryStatus>>(
    Object.fromEntries(items.map((item) => [item.id, item.status]))
  );
  const [statusFilter, setStatusFilter] =
    useState<(typeof allStatuses)[number]>("All");

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();

    return items
      .map((item) => ({ ...item, status: statusById[item.id] ?? item.status }))
      .filter((item) => {
        const matchesQuery =
          !normalized ||
          [item.title, item.type, item.source, item.details]
            .join(" ")
            .toLowerCase()
            .includes(normalized);
        const matchesType = type === "All" || item.type === type;
        const matchesStatus =
          statusFilter === "All" || item.status === statusFilter;

        return matchesQuery && matchesType && matchesStatus;
      });
  }, [items, query, statusById, statusFilter, type]);

  function approveMemory(id: string) {
    setStatusById((current) => ({ ...current, [id]: "Approved" }));
  }

  return (
    <div className="space-y-6">
      <PageHeader
        description="Inspect memory candidates and review ledger state using static data and local approvals."
        title="Memory Ledger"
      />

      <Card>
        <CardHeader>
          <CardTitle>Search and Filters</CardTitle>
          <CardDescription>
            Narrow by memory type, status, source, or title.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-[1fr_180px_180px]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search memory"
                value={query}
              />
            </div>
            <Select
              aria-label="Filter by memory type"
              onChange={(event) =>
                setType(event.target.value as (typeof allTypes)[number])
              }
              value={type}
            >
              {allTypes.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Filter by memory status"
              onChange={(event) =>
                setStatusFilter(
                  event.target.value as (typeof allStatuses)[number]
                )
              }
              value={statusFilter}
            >
              {allStatuses.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </div>
        </CardContent>
      </Card>

      {filtered.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {filtered.map((item) => (
            <Card key={item.id}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle>{item.title}</CardTitle>
                    <CardDescription>{item.source}</CardDescription>
                  </div>
                  <StatusBadge status={item.status} />
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Type" value={item.type} />
                  <Field label="Confidence" value={`${item.confidence}%`} />
                  <Field label="Created" value={formatDate(item.createdDate)} />
                  <Field label="Review" value={formatDate(item.reviewDate)} />
                </div>
                <p className="line-clamp-2 text-sm text-muted-foreground">
                  {item.details}
                </p>
                <div className="flex flex-wrap gap-3">
                  <Dialog>
                    <DialogTrigger asChild>
                      <Button variant="outline">
                        <Eye className="h-4 w-4" aria-hidden="true" />
                        View details
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>{item.title}</DialogTitle>
                        <DialogDescription>
                          Memory ledger detail for review and approval.
                        </DialogDescription>
                      </DialogHeader>
                      <div className="grid gap-4 md:grid-cols-2">
                        <Field label="Type" value={item.type as MemoryType} />
                        <Field label="Status" value={item.status} />
                        <Field label="Source" value={item.source} />
                        <Field label="Confidence" value={`${item.confidence}%`} />
                        <Field label="Created" value={formatDate(item.createdDate)} />
                        <Field label="Review" value={formatDate(item.reviewDate)} />
                      </div>
                      <div className="mt-4 rounded-lg border bg-muted/45 p-4">
                        <p className="text-xs font-semibold uppercase text-muted-foreground">
                          Details
                        </p>
                        <p className="mt-2 text-sm text-muted-foreground">
                          {item.details}
                        </p>
                      </div>
                    </DialogContent>
                  </Dialog>
                  <Button
                    disabled={item.status !== "Candidate"}
                    onClick={() => approveMemory(item.id)}
                    type="button"
                    variant="secondary"
                  >
                    <Check className="h-4 w-4" aria-hidden="true" />
                    Approve
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          description="Adjust search or filters to inspect memory records."
          icon={Search}
          title="No memory records found"
        />
      )}
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
