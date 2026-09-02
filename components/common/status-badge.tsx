import { Badge } from "@/components/ui/badge";
import type { WorkflowStatus } from "@/lib/types";

const workflowLabels: Record<WorkflowStatus, string> = {
  PENDING: "Pending",
  RUNNING: "Running",
  COMPLETED: "Completed",
  FAILED: "Failed",
  BLOCKED: "Blocked",
};

function variantForStatus(
  status: WorkflowStatus
): "success" | "warning" | "danger" | "secondary" {
  switch (status) {
    case "COMPLETED":
      return "success";

    case "RUNNING":
      return "warning";

    case "FAILED":
    case "BLOCKED":
      return "danger";

    case "PENDING":
    default:
      return "secondary";
  }
}

export function StatusBadge({
  status,
}: {
  status: WorkflowStatus;
}) {
  return (
    <Badge variant={variantForStatus(status)}>
      {workflowLabels[status]}
    </Badge>
  );
}