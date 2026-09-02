import type { Task } from "@/lib/types";

const commonTrace = [
  {
    id: "karma",
    agentName: "KARMA",
    status: "completed",
    activity: "Captured founder intent and normalized the task envelope.",
    timestamp: "2026-08-13T03:20:00Z"
  },
  {
    id: "kosh-smriti",
    agentName: "KOSH / SMRITI",
    status: "completed",
    activity: "Retrieved relevant operating memory and prior execution context.",
    timestamp: "2026-08-13T03:24:00Z"
  },
  {
    id: "pragya",
    agentName: "PRAGYA",
    status: "completed",
    activity: "Drafted an execution plan with assumptions and expected outcomes.",
    timestamp: "2026-08-13T03:31:00Z"
  },
  {
    id: "murphy",
    agentName: "MURPHY",
    status: "completed",
    activity: "Reviewed operational, policy, and failure mode risk.",
    timestamp: "2026-08-13T03:38:00Z"
  },
  {
    id: "maryada",
    agentName: "MARYADA",
    status: "waiting_approval",
    activity: "Flagged the task for Founder approval before execution.",
    timestamp: "2026-08-13T03:42:00Z"
  },
  {
    id: "rachit",
    agentName: "RACHIT",
    status: "pending",
    activity: "Awaiting approval gate before delivery orchestration.",
    timestamp: "2026-08-13T03:42:00Z"
  }
] satisfies Task["trace"];

export const tasks: Task[] = [
  {
    id: "task-001",
    title: "Prepare investor diligence workspace",
    description:
      "Create a structured diligence package outline using current metrics, founder notes, and prior board questions.",
    status: "waiting_approval",
    currentAgent: "MARYADA",
    currentStage: "Policy approval",
    riskLevel: "high",
    createdAt: "2026-08-13T03:12:00Z",
    updatedAt: "2026-08-13T03:42:00Z",
    plan: {
      summary:
        "Assemble a diligence workspace, identify sensitive materials, and route high-risk disclosures for approval.",
      steps: [
        "Map requested diligence categories to existing source material.",
        "Draft a clean workspace index and access policy.",
        "Mark financial and customer references that need founder review.",
        "Prepare the delivery checklist for RACHIT after approval."
      ],
      assumptions: [
        "Founder approval is required for sensitive financial disclosures.",
        "No documents are sent externally until policy clearance is complete."
      ]
    },
    riskReport: {
      riskLevel: "high",
      category: "Sensitive disclosure",
      failureModes: [
        "Draft package may include unapproved financial assumptions.",
        "External recipients may receive customer references too early."
      ],
      securityConcerns: [
        "Investor workspace should use least-privilege access.",
        "Customer names and revenue data need explicit clearance."
      ],
      recommendation:
        "Proceed only after Founder confirms disclosure scope and recipient access policy."
    },
    policyVerdict: {
      riskTier: "high",
      approved: false,
      humanApprovalRequired: true,
      justification:
        "The task touches sensitive commercial and financial material, so execution must wait for founder approval."
    },
    trace: commonTrace
  },
  {
    id: "task-002",
    title: "Summarize product telemetry anomalies",
    description:
      "Review the latest telemetry digest and summarize anomalies that may affect enterprise onboarding.",
    status: "running",
    currentAgent: "MURPHY",
    currentStage: "Risk review",
    riskLevel: "medium",
    createdAt: "2026-08-13T02:48:00Z",
    updatedAt: "2026-08-13T03:30:00Z",
    plan: {
      summary:
        "Identify anomalous usage patterns and convert them into a concise operational risk summary.",
      steps: [
        "Group anomalies by customer segment.",
        "Separate noise from repeated operational signals.",
        "Draft mitigation options for onboarding owners."
      ],
      assumptions: [
        "Telemetry has already been scrubbed of private user content.",
        "This phase is summarization only, not remediation."
      ]
    },
    riskReport: {
      riskLevel: "medium",
      category: "Operational reliability",
      failureModes: [
        "Anomalies may be over-attributed without enough historical comparison.",
        "Medium-priority signals may crowd out urgent onboarding blockers."
      ],
      securityConcerns: ["Telemetry summaries should avoid raw identifiers."],
      recommendation:
        "Keep the report scoped to aggregate patterns and include confidence notes."
    },
    policyVerdict: {
      riskTier: "medium",
      approved: true,
      humanApprovalRequired: false,
      justification:
        "Aggregated operational telemetry is allowed for internal review when identifiers remain excluded."
    },
    trace: [
      {
        id: "karma",
        agentName: "KARMA",
        status: "completed",
        activity: "Captured request and converted it into analysis criteria.",
        timestamp: "2026-08-13T02:50:00Z"
      },
      {
        id: "kosh-smriti",
        agentName: "KOSH / SMRITI",
        status: "completed",
        activity: "Retrieved prior onboarding anomaly patterns.",
        timestamp: "2026-08-13T03:00:00Z"
      },
      {
        id: "pragya",
        agentName: "PRAGYA",
        status: "completed",
        activity: "Prepared the analysis plan and output structure.",
        timestamp: "2026-08-13T03:12:00Z"
      },
      {
        id: "murphy",
        agentName: "MURPHY",
        status: "running",
        activity: "Evaluating false positive risk and security exposure.",
        timestamp: "2026-08-13T03:30:00Z"
      },
      {
        id: "maryada",
        agentName: "MARYADA",
        status: "pending",
        activity: "Policy verdict pending risk review completion.",
        timestamp: "2026-08-13T03:30:00Z"
      },
      {
        id: "rachit",
        agentName: "RACHIT",
        status: "pending",
        activity: "Waiting for finalized internal summary.",
        timestamp: "2026-08-13T03:30:00Z"
      }
    ]
  },
  {
    id: "task-003",
    title: "Draft customer renewal briefing",
    description:
      "Create a short renewal briefing for a strategic account using approved memory and recent account activity.",
    status: "completed",
    currentAgent: "RACHIT",
    currentStage: "Delivered",
    riskLevel: "low",
    createdAt: "2026-08-12T15:10:00Z",
    updatedAt: "2026-08-12T16:05:00Z",
    executionResult:
      "Renewal briefing prepared with approved milestones, open risks, and recommended next steps.",
    trace: [
      {
        id: "karma",
        agentName: "KARMA",
        status: "completed",
        activity: "Captured briefing objective and audience.",
        timestamp: "2026-08-12T15:13:00Z"
      },
      {
        id: "kosh-smriti",
        agentName: "KOSH / SMRITI",
        status: "completed",
        activity: "Retrieved approved account milestones and recent notes.",
        timestamp: "2026-08-12T15:24:00Z"
      },
      {
        id: "pragya",
        agentName: "PRAGYA",
        status: "completed",
        activity: "Built a briefing outline and renewal narrative.",
        timestamp: "2026-08-12T15:36:00Z"
      },
      {
        id: "murphy",
        agentName: "MURPHY",
        status: "completed",
        activity: "Confirmed low risk and no sensitive financial exposure.",
        timestamp: "2026-08-12T15:44:00Z"
      },
      {
        id: "maryada",
        agentName: "MARYADA",
        status: "completed",
        activity: "Approved internal account briefing generation.",
        timestamp: "2026-08-12T15:48:00Z"
      },
      {
        id: "rachit",
        agentName: "RACHIT",
        status: "completed",
        activity: "Generated and packaged the final briefing.",
        timestamp: "2026-08-12T16:05:00Z"
      }
    ]
  },
  {
    id: "task-004",
    title: "Validate hiring plan assumptions",
    description:
      "Compare proposed team expansion assumptions against operating priorities and runway guardrails.",
    status: "blocked",
    currentAgent: "KOSH",
    currentStage: "Context retrieval",
    riskLevel: "critical",
    createdAt: "2026-08-12T11:05:00Z",
    updatedAt: "2026-08-12T11:42:00Z",
    errors: [
      "Runway model memory is marked deprecated.",
      "Latest hiring constraints require founder confirmation."
    ],
    trace: [
      {
        id: "karma",
        agentName: "KARMA",
        status: "completed",
        activity: "Converted hiring plan prompt into structured review criteria.",
        timestamp: "2026-08-12T11:08:00Z"
      },
      {
        id: "kosh-smriti",
        agentName: "KOSH / SMRITI",
        status: "blocked",
        activity: "Found conflicting memory for runway and hiring constraints.",
        timestamp: "2026-08-12T11:42:00Z"
      },
      {
        id: "pragya",
        agentName: "PRAGYA",
        status: "pending",
        activity: "Waiting for canonical memory confirmation.",
        timestamp: "2026-08-12T11:42:00Z"
      },
      {
        id: "murphy",
        agentName: "MURPHY",
        status: "pending",
        activity: "Risk analysis pending plan generation.",
        timestamp: "2026-08-12T11:42:00Z"
      },
      {
        id: "maryada",
        agentName: "MARYADA",
        status: "pending",
        activity: "Policy review pending risk analysis.",
        timestamp: "2026-08-12T11:42:00Z"
      },
      {
        id: "rachit",
        agentName: "RACHIT",
        status: "pending",
        activity: "Delivery paused while context is blocked.",
        timestamp: "2026-08-12T11:42:00Z"
      }
    ]
  }
];
