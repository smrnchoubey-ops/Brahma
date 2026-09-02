import { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string | number;
  detail: string;
  icon: LucideIcon;
  risk?: boolean;
}

export function StatCard({ label, value, detail, icon: Icon, risk }: StatCardProps) {
  return (
    <Card 
      className={cn(
        "transition-all duration-300 hover:scale-[1.02] bg-card/80 backdrop-blur-sm",
        risk 
          ? "border-amber-500/30 hover:shadow-[0_0_20px_rgba(251,191,36,0.15)] hover:border-amber-500/50" 
          : "hover:shadow-[0_0_20px_rgba(59,130,246,0.15)] hover:border-blue-500/30"
      )}
    >
      <CardContent className="flex items-start justify-between gap-4 p-5">
        <div>
          <p className={cn("text-sm font-medium", risk ? "text-amber-500/80" : "text-muted-foreground")}>{label}</p>
          <p className="mt-2 text-3xl font-semibold tracking-normal">{value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
        </div>
        <div className={cn(
          "rounded-md border p-2",
          risk ? "bg-amber-500/10 text-amber-500 border-amber-500/20" : "bg-muted text-muted-foreground"
        )}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
      </CardContent>
    </Card>
  );
}
