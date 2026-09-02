"use client";

import { CheckCircle2, Clock, XCircle, AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Task } from "@/lib/api";

const statusConfig = {
  pending: { icon: Clock, color: "text-blue-500", label: "In Progress" },
  approved: { icon: CheckCircle2, color: "text-green-500", label: "Approved" },
  executed: { icon: CheckCircle2, color: "text-emerald-500", label: "Executed" },
  failed: { icon: XCircle, color: "text-red-500", label: "Failed" },
  escalated: { icon: AlertTriangle, color: "text-amber-500", label: "Needs Approval" },
};

export function TaskFeed({ tasks }: { tasks: Task[] }) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold tracking-tight">Recent Activity</h3>
      
      {tasks.length === 0 ? (
        <div className="text-sm text-muted-foreground p-4 text-center border border-dashed border-border rounded-lg">
          No tasks yet. Create a goal directive to begin.
        </div>
      ) : (
        <div className="space-y-3">
          {tasks.map((task) => {
            const statusKey = (task.status || "pending").toLowerCase() as keyof typeof statusConfig;
            const config = statusConfig[statusKey] || statusConfig.pending;
            const Icon = config.icon;
            
            return (
              <Card key={task.id} className="p-4 hover:border-primary/50 transition-colors cursor-pointer">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 space-y-1">
                    <p className="text-sm font-medium leading-none mb-2">{task.prompt}</p>
                    <p className="text-xs text-muted-foreground">{new Date(task.created_at).toLocaleString()} • ID: {task.id}</p>
                  </div>
                  <Badge variant="outline" className={`flex items-center gap-1.5 ${config.color} border-${config.color.split('-')[1]}/30`}>
                    <Icon className="w-3 h-3" />
                    {config.label}
                  </Badge>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
