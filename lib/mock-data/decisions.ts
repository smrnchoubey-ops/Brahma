import type { Decision } from "@/lib/types";
import { tasks } from "@/lib/mock-data/tasks";

const diligenceTask = tasks[0];

export const decisions: Decision[] = [
  {
    id: "decision-001",
    taskId: "task-001",
    taskName: diligenceTask.title,
    pragyaSummary:
      "Prepare a diligence workspace index and package approved materials after explicit founder disclosure confirmation.",
    riskLevel: "high",
    murphyRiskSummary:
      "The main risks are early disclosure of financial assumptions and broad investor access to sensitive customer context.",
    maryadaVerdict: diligenceTask.policyVerdict!,
    approvalStatus: "pending",
    plan: diligenceTask.plan!,
    riskReport: diligenceTask.riskReport!,
    updatedAt: "2026-08-13T03:44:00Z"
  },
  {
    id: "decision-002",
    taskId: "task-004",
    taskName: "Validate hiring plan assumptions",
    pragyaSummary:
      "Proceed only after the runway memory conflict is resolved and a canonical hiring guardrail is selected.",
    riskLevel: "critical",
    murphyRiskSummary:
      "Outdated runway assumptions could produce an unsafe hiring recommendation with budget consequences.",
    maryadaVerdict: {
      riskTier: "critical",
      approved: false,
      humanApprovalRequired: true,
      justification:
        "The task must pause until the Founder confirms which runway and hiring constraints are canonical."
    },
    approvalStatus: "pending",
    plan: {
      summary:
        "Resolve memory conflicts before generating hiring plan validation.",
      steps: [
        "Show conflicting runway memories to the Founder.",
        "Select the canonical constraint set.",
        "Run a fresh plan validation using only approved context."
      ],
      assumptions: [
        "Budget and runway guidance may have changed.",
        "Deprecated memory should not be used for final recommendations."
      ]
    },
    riskReport: {
      riskLevel: "critical",
      category: "Strategic finance",
      failureModes: [
        "Hiring recommendation could exceed runway guardrails.",
        "Deprecated constraints could override founder intent."
      ],
      securityConcerns: [
        "Compensation and runway data should remain access restricted."
      ],
      recommendation:
        "Block automated planning until Founder selects the canonical finance memory."
    },
    updatedAt: "2026-08-12T11:46:00Z"
  }
];
