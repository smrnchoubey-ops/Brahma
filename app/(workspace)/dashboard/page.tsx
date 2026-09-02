"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  ClipboardCheck,
  ListChecks
} from "lucide-react";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageHeader } from "@/components/common/page-header";
import { RiskBadge } from "@/components/common/risk-badge";
import { StatCard } from "@/components/common/stat-card";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { agents, auditEvents, decisions } from "@/lib/mock-data";
import { formatDateTime } from "@/lib/utils";

// Generate mock data for the chart to show system throughput
const chartData = [
  { name: "Mon", tasks: 4 },
  { name: "Tue", tasks: 7 },
  { name: "Wed", tasks: 5 },
  { name: "Thu", tasks: 12 },
  { name: "Fri", tasks: 8 },
  { name: "Sat", tasks: 2 },
  { name: "Sun", tasks: 3 },
];

export default function DashboardPage() {
  const [tasksData, setTasksData] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Fetch live data from backend
    fetch("http://127.0.0.1:8000/tasks/")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch");
        return res.json();
      })
      .then((data) => {
        setTasksData(data || []);
      })
      .catch((err) => {
        console.error("API Error:", err);
        setTasksData([]); // Empty state fallback
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  const activeTasks = tasksData.filter((task) =>
    ["running", "pending", "waiting_approval", "blocked"].includes(task.status)
  );
  const pendingDecisions = decisions.filter(
    (decision) => decision.approvalStatus === "pending"
  );
  const activeAgents = agents.filter((agent) => agent.status === "active");
  const recentRisks = tasksData.filter((task) =>
    ["high", "critical"].includes(task.riskLevel || task.risk_level)
  );

  return (
    <div className="space-y-6">
      <PageHeader
        action={
          <Button asChild className="bg-primary/20 hover:bg-primary/30 text-primary border border-primary/50 shadow-[0_0_15px_rgba(59,130,246,0.2)]">
            <Link href="/tasks">Create task</Link>
          </Button>
        }
        description="A compact operating view for tasks, agent state, approvals, and recent risk signals."
        title="Founder Command Center"
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          detail={isLoading ? "Loading..." : `${activeTasks.length} active or waiting`}
          icon={ListChecks}
          label="Active Tasks"
          value={isLoading ? "-" : activeTasks.length}
        />
        <StatCard
          detail="Founder review queue"
          icon={ClipboardCheck}
          label="Pending Decisions"
          value={pendingDecisions.length}
        />
        <StatCard
          detail={`${agents.length} configured agents`}
          icon={Bot}
          label="Active Agents"
          value={activeAgents.length}
        />
        <StatCard
          detail={isLoading ? "Loading..." : "High and critical items"}
          icon={AlertTriangle}
          label="Recent Risks"
          value={isLoading ? "-" : recentRisks.length}
          risk={true}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.9fr)]">
        <div className="space-y-6">
          {/* New Chart Component for Enterprise Feel */}
          <Card className="bg-card/50 backdrop-blur border-primary/10 shadow-[0_0_20px_rgba(0,0,0,0.2)]">
            <CardHeader>
              <CardTitle>System Throughput</CardTitle>
              <CardDescription>Task processing volume over the last 7 days.</CardDescription>
            </CardHeader>
            <CardContent className="pb-4">
              <div className="h-[200px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <XAxis dataKey="name" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `${value}`} />
                    <Tooltip cursor={{ fill: "transparent" }} contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px" }} />
                    <Bar dataKey="tasks" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card/50 backdrop-blur border-primary/10">
            <CardHeader>
              <CardTitle>Recent Tasks</CardTitle>
              <CardDescription>
                Current agent, stage, and risk posture across the MVP workflow.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="space-y-4 py-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="flex items-center justify-between">
                      <div className="space-y-2">
                        <Skeleton className="h-4 w-[250px]" />
                        <Skeleton className="h-3 w-[150px]" />
                      </div>
                      <Skeleton className="h-8 w-20" />
                    </div>
                  ))}
                </div>
              ) : tasksData.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow className="border-border/50">
                      <TableHead>Task</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Agent</TableHead>
                      <TableHead>Risk</TableHead>
                      <TableHead>Updated</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tasksData.map((task) => (
                      <TableRow key={task.id} className="border-border/50 hover:bg-muted/20 transition-colors">
                        <TableCell>
                          <Link
                            className="font-medium hover:text-primary transition-colors"
                            href={`/tasks/${task.id}`}
                          >
                            {task.title || "Untitled Task"}
                          </Link>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {task.currentStage || task.current_stage || task.status}
                          </p>
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={task.status} />
                        </TableCell>
                        <TableCell>{task.currentAgent || task.current_agent || "KARMA"}</TableCell>
                        <TableCell>
                          <RiskBadge level={task.riskLevel || task.risk_level || "low"} />
                        </TableCell>
                        <TableCell className="text-muted-foreground font-mono">
                          {formatDateTime(task.updatedAt || task.updated_at || task.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 text-center bg-background/30 rounded-lg border border-dashed border-border/50">
                  <div className="relative mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-primary/10 shadow-[0_0_30px_rgba(59,130,246,0.15)]">
                    <div className="absolute inset-0 rounded-full border border-primary/30 animate-[ping_3s_cubic-bezier(0,0,0.2,1)_infinite]"></div>
                    <div className="absolute inset-2 rounded-full border border-primary/40 animate-[ping_2s_cubic-bezier(0,0,0.2,1)_infinite]"></div>
                    <Activity className="h-8 w-8 text-primary animate-pulse" />
                  </div>
                  <h3 className="text-xl font-semibold tracking-tight">No active tasks found</h3>
                  <p className="mt-2 text-sm text-muted-foreground max-w-sm">
                    The system is currently scanning for live connections and incoming data streams.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="bg-card/50 backdrop-blur border-amber-500/20 shadow-[0_0_20px_rgba(251,191,36,0.05)]">
            <CardHeader>
              <CardTitle className="text-amber-500/90">Pending Decisions</CardTitle>
              <CardDescription>
                Tasks waiting for Founder approval.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {pendingDecisions.map((decision) => (
                <Link
                  className="block rounded-lg border border-border/50 bg-background/50 p-4 transition-all hover:bg-muted/40 hover:border-amber-500/30"
                  href="/decisions"
                  key={decision.id}
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-medium">{decision.taskName}</p>
                    <RiskBadge level={decision.riskLevel} />
                  </div>
                  <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
                    {decision.murphyRiskSummary}
                  </p>
                </Link>
              ))}
            </CardContent>
          </Card>

          <Card className="bg-card/50 backdrop-blur border-primary/10">
            <CardHeader>
              <CardTitle>Audit Ledger Feed</CardTitle>
              <CardDescription>
                Live event stream from the agent network.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {auditEvents.slice(0, 5).map((event) => (
                <div className="flex gap-3" key={event.id}>
                  <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/5 text-primary">
                    <Activity className="h-4 w-4" aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium">{event.agent}</p>
                      <StatusBadge status={event.status} />
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {event.event}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground font-mono">
                      {formatDateTime(event.timestamp)}
                    </p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
