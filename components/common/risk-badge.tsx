import { Badge } from "@/components/ui/badge";
import type { RiskLevel } from "@/lib/types";

const riskVariants: Record<
  RiskLevel,
  "success" | "warning" | "danger" | "secondary"
> = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "danger",
  CRITICAL: "danger",
};

export function RiskBadge({
  level,
}: {
  level: RiskLevel;
}) {
  return (
    <Badge
      variant={riskVariants[level]}
      className={
        level === "CRITICAL"
          ? "border-red-300 bg-red-100"
          : ""
      }
    >
      {level}
    </Badge>
  );
}