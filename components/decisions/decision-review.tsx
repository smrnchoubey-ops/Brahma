"use client";

import { useState } from "react";
import { Check, X } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { RiskBadge } from "@/components/common/risk-badge";
import { RiskReview } from "@/components/common/risk-review";
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
import type { ApprovalStatus, Decision } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export function DecisionReview({ initialDecisions }: { initialDecisions: Decision[] }) {
  const [statuses, setStatuses] = useState<Record<string, ApprovalStatus>>(
    Object.fromEntries(
      initialDecisions.map((decision) => [decision.id, decision.approvalStatus])
    )
  );
  const [message, setMessage] = useState("");

  function updateDecision(id: string, status: ApprovalStatus) {
    setStatuses((current) => ({ ...current, [id]: status }));
    setMessage(
      status === "approved"
        ? "Decision approved locally."
        : "Decision rejected locally."
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        description="Review PRAGYA plans, MURPHY risk reports, and MARYADA policy verdicts before execution."
        title="Decision Review"
      />

      {message ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
          {message}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {initialDecisions.map((decision) => {
          const status = statuses[decision.id];

          return (
            <Card key={decision.id}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle>{decision.taskName}</CardTitle>
                    <CardDescription>
                      Updated {formatDateTime(decision.updatedAt)}
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <RiskBadge level={decision.riskLevel} />
                    <StatusBadge status={status} />
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <SummaryBlock label="PRAGYA summary" value={decision.pragyaSummary} />
                <SummaryBlock
                  label="MURPHY risk summary"
                  value={decision.murphyRiskSummary}
                />
                <SummaryBlock
                  label="MARYADA verdict"
                  value={decision.maryadaVerdict.justification}
                />
                <Dialog>
                  <DialogTrigger asChild>
                    <Button variant="outline">Review decision</Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>{decision.taskName}</DialogTitle>
                      <DialogDescription>
                        Local review modal. Approval changes are kept in browser state only.
                      </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-5">
                      <Section title="PRAGYA Plan">
                        <p className="text-sm text-muted-foreground">
                          {decision.plan.summary}
                        </p>
                        <div className="mt-4 grid gap-4 md:grid-cols-2">
                          <NumberedList title="Steps" items={decision.plan.steps} />
                          <NumberedList
                            title="Assumptions"
                            items={decision.plan.assumptions}
                          />
                        </div>
                      </Section>

                      <RiskReview report={decision.riskReport} />

                      <Section title="MARYADA Policy Verdict">
                        <div className="grid gap-4 md:grid-cols-3">
                          <VerdictField
                            label="Risk tier"
                            value={<RiskBadge level={decision.maryadaVerdict.riskTier} />}
                          />
                          <VerdictField
                            label="Approved"
                            value={decision.maryadaVerdict.approved ? "Yes" : "No"}
                          />
                          <VerdictField
                            label="Human approval"
                            value={
                              decision.maryadaVerdict.humanApprovalRequired
                                ? "Required"
                                : "Not required"
                            }
                          />
                        </div>
                        <p className="mt-4 text-sm text-muted-foreground">
                          {decision.maryadaVerdict.justification}
                        </p>
                      </Section>

                      <div className="flex flex-wrap gap-3">
                        <Button
                          disabled={status === "approved"}
                          onClick={() => updateDecision(decision.id, "approved")}
                          type="button"
                        >
                          <Check className="h-4 w-4" aria-hidden="true" />
                          Approve
                        </Button>
                        <Button
                          disabled={status === "rejected"}
                          onClick={() => updateDecision(decision.id, "rejected")}
                          type="button"
                          variant="destructive"
                        >
                          <X className="h-4 w-4" aria-hidden="true" />
                          Reject
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function SummaryBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{value}</p>
    </div>
  );
}

function Section({
  title,
  children
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border p-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function NumberedList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase text-muted-foreground">
        {title}
      </p>
      <ol className="mt-2 space-y-2 text-sm text-muted-foreground">
        {items.map((item, index) => (
          <li className="flex gap-2" key={item}>
            <span className="font-medium text-foreground">{index + 1}.</span>
            <span>{item}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function VerdictField({
  label,
  value
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase text-muted-foreground">
        {label}
      </p>
      <div className="mt-2 text-sm">{value}</div>
    </div>
  );
}
