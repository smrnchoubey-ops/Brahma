"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, Clock, FileText } from "lucide-react";

import api from "@/lib/api";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { RiskBadge } from "@/components/common/risk-badge";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";

import { formatDateTime } from "@/lib/utils";
import type { Task } from "@/lib/types";

export function TaskDetailView({
  taskId,
}: {
  taskId: string;
}) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTask();
  }, []);

  async function loadTask() {
    try {
      const res = await api.get("/tasks/");
      const found = res.data.find(
        (t: Task) => String(t.id) === taskId
      );
      setTask(found ?? null);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  if (!task) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Task Not Found"
          description="Task doesn't exist."
          action={
            <Button asChild variant="outline">
              <Link href="/tasks">
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back
              </Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">

      <PageHeader
        title={task.title}
        description={task.prompt}
        action={
          <Button asChild variant="outline">
            <Link href="/tasks">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back
            </Link>
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Task Information</CardTitle>
        </CardHeader>

        <CardContent className="space-y-4">

          <div className="flex gap-2">
            <StatusBadge status={task.status} />
            <RiskBadge level={task.risk_level} />
          </div>

          <InfoRow
            label="Created"
            value={formatDateTime(task.created_at)}
          />

          {task.updated_at && (
            <InfoRow
              label="Updated"
              value={formatDateTime(task.updated_at)}
            />
          )}

        </CardContent>
      </Card>

      {task.plan && (
        <Card>
          <CardHeader>
            <CardTitle>PRAGYA PLAN</CardTitle>
            <CardDescription>
              {task.plan.summary}
            </CardDescription>
          </CardHeader>

          <CardContent>

            <h4 className="font-semibold mb-2">
              Steps
            </h4>

            <ol className="list-decimal ml-5 space-y-2">
              {task.plan.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>

            <h4 className="font-semibold mt-6 mb-2">
              Tools Needed
            </h4>

            <ul className="list-disc ml-5 space-y-1">
              {task.plan.tools_needed.map((tool) => (
                <li key={tool}>{tool}</li>
              ))}
            </ul>

            <h4 className="font-semibold mt-6 mb-2">
              Assumptions
            </h4>

            <ul className="space-y-2">
              {task.plan.assumptions.map((item) => (
                <li
                  key={item}
                  className="flex items-center gap-2"
                >
                  <Clock className="h-4 w-4" />
                  {item}
                </li>
              ))}
            </ul>

          </CardContent>
        </Card>
      )}

      {task.risk_report && (
        <Card>
          <CardHeader>
            <CardTitle>MURPHY Risk Report</CardTitle>
          </CardHeader>

          <CardContent className="space-y-4">

            <InfoRow
              label="Risk Level"
              value={task.risk_report.risk_level}
            />

            <div>
              <h4 className="font-semibold">
                Failure Modes
              </h4>

              <ul className="list-disc ml-5">
                {task.risk_report.failure_modes.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>

            <div>
              <h4 className="font-semibold">
                Security Concerns
              </h4>

              <ul className="list-disc ml-5">
                {task.risk_report.security_concerns.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>

            <InfoRow
              label="Recommendation"
              value={task.risk_report.recommendation}
            />

          </CardContent>
        </Card>
      )}

      {task.policy_verdict && (
        <Card>
          <CardHeader>
            <CardTitle>MARYADA Verdict</CardTitle>
          </CardHeader>

          <CardContent className="space-y-3">

            <InfoRow
              label="Risk Tier"
              value={task.policy_verdict.risk_tier}
            />

            <InfoRow
              label="Approved"
              value={
                task.policy_verdict.approved
                  ? "YES"
                  : "NO"
              }
            />

            <InfoRow
              label="Human Review"
              value={
                task.policy_verdict.requires_human
                  ? "Required"
                  : "Not Required"
              }
            />

            <InfoRow
              label="Justification"
              value={task.policy_verdict.justification}
            />

          </CardContent>
        </Card>
      )}

      {task.execution_result && (
        <Card>
          <CardHeader>
            <CardTitle>RACHIT Execution</CardTitle>
          </CardHeader>

          <CardContent>

            <div className="flex gap-2 items-center">
              <FileText className="h-4 w-4" />

              <span>
                {task.execution_result.message}
              </span>
            </div>

            <div className="mt-4">
              <InfoRow
                label="Status"
                value={task.execution_result.status}
              />

              <InfoRow
                label="Executed Steps"
                value={String(task.execution_result.executed_steps)}
              />
            </div>

          </CardContent>
        </Card>
      )}

    </div>
  );
}

function InfoRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase text-muted-foreground">
        {label}
      </p>

      <p className="mt-1 text-sm">
        {value}
      </p>
    </div>
  );
}