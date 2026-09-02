import { RiskBadge } from "@/components/common/risk-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { RiskReport } from "@/lib/types";

export function RiskReview({ report }: { report: RiskReport }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>Risk Review</CardTitle>
          <RiskBadge level={report.riskLevel} />
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div>
          <p className="text-xs font-semibold uppercase text-muted-foreground">
            Category
          </p>
          <p className="mt-1 text-sm">{report.category}</p>
        </div>
        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <p className="text-xs font-semibold uppercase text-muted-foreground">
              Failure Modes
            </p>
            <ul className="mt-2 space-y-2 text-sm text-muted-foreground">
              {report.failureModes.map((item) => (
                <li key={item} className="leading-6">
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase text-muted-foreground">
              Security Concerns
            </p>
            <ul className="mt-2 space-y-2 text-sm text-muted-foreground">
              {report.securityConcerns.map((item) => (
                <li key={item} className="leading-6">
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="rounded-md border bg-muted/45 p-4">
          <p className="text-xs font-semibold uppercase text-muted-foreground">
            Recommendation
          </p>
          <p className="mt-1 text-sm">{report.recommendation}</p>
        </div>
      </CardContent>
    </Card>
  );
}
