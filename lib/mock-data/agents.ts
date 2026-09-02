import type { Agent } from "@/lib/types";

export const agents: Agent[] = [
  {
    id: "karma",
    name: "KARMA",
    role: "Task intake and intent routing",
    status: "idle",
    currentTask: "No active intake",
    lastActivity: "Captured diligence workspace task",
    health: "healthy",
    description:
      "Converts Founder intent into normalized task envelopes and routes work into the agent workflow.",
    recentActivity: [
      "Normalized investor diligence request",
      "Created telemetry anomaly review task",
      "Marked hiring validation as context-dependent"
    ],
    recentExecutions: [
      {
        id: "exec-karma-01",
        task: "Prepare investor diligence workspace",
        status: "completed",
        timestamp: "2026-08-13T03:20:00Z"
      },
      {
        id: "exec-karma-02",
        task: "Summarize product telemetry anomalies",
        status: "completed",
        timestamp: "2026-08-13T02:50:00Z"
      }
    ]
  },
  {
    id: "kosh",
    name: "KOSH",
    role: "Knowledge retrieval",
    status: "active",
    currentTask: "Validate hiring plan assumptions",
    lastActivity: "Detected conflicting runway memory",
    health: "degraded",
    description:
      "Finds relevant knowledge sources and flags missing or conflicting context before planning begins.",
    recentActivity: [
      "Retrieved enterprise onboarding checklist",
      "Flagged deprecated runway model",
      "Linked investor disclosure boundary"
    ],
    recentExecutions: [
      {
        id: "exec-kosh-01",
        task: "Validate hiring plan assumptions",
        status: "blocked",
        timestamp: "2026-08-12T11:42:00Z"
      }
    ]
  },
  {
    id: "smriti",
    name: "SMRITI",
    role: "Memory ledger coordination",
    status: "idle",
    currentTask: "Memory review queue",
    lastActivity: "Marked renewal style as candidate memory",
    health: "healthy",
    description:
      "Maintains working, episodic, semantic, and strategic memory candidates for review.",
    recentActivity: [
      "Added renewal briefing style candidate",
      "Confirmed onboarding checklist canonical status",
      "Tagged telemetry episode as approved"
    ],
    recentExecutions: [
      {
        id: "exec-smriti-01",
        task: "Draft customer renewal briefing",
        status: "completed",
        timestamp: "2026-08-12T15:24:00Z"
      }
    ]
  },
  {
    id: "pragya",
    name: "PRAGYA",
    role: "Planning and reasoning",
    status: "idle",
    currentTask: "No active plan",
    lastActivity: "Prepared diligence package plan",
    health: "healthy",
    description:
      "Creates structured plans, assumptions, and execution steps for downstream review.",
    recentActivity: [
      "Drafted diligence workspace plan",
      "Built telemetry summary structure",
      "Prepared customer renewal briefing outline"
    ],
    recentExecutions: [
      {
        id: "exec-pragya-01",
        task: "Prepare investor diligence workspace",
        status: "completed",
        timestamp: "2026-08-13T03:31:00Z"
      }
    ]
  },
  {
    id: "murphy",
    name: "MURPHY",
    role: "Risk and failure analysis",
    status: "active",
    currentTask: "Summarize product telemetry anomalies",
    lastActivity: "Reviewing aggregate telemetry risk",
    health: "healthy",
    description:
      "Stress-tests plans for failure modes, operational risk, and security exposure.",
    recentActivity: [
      "Flagged investor disclosure risk",
      "Reviewed telemetry privacy exposure",
      "Blocked outdated runway assumptions"
    ],
    recentExecutions: [
      {
        id: "exec-murphy-01",
        task: "Summarize product telemetry anomalies",
        status: "running",
        timestamp: "2026-08-13T03:30:00Z"
      }
    ]
  },
  {
    id: "maryada",
    name: "MARYADA",
    role: "Policy and approval gate",
    status: "active",
    currentTask: "Prepare investor diligence workspace",
    lastActivity: "Requested Founder approval",
    health: "healthy",
    description:
      "Applies policy verdicts, risk tiers, and human approval gates before execution proceeds.",
    recentActivity: [
      "Required Founder approval for diligence workspace",
      "Approved internal renewal briefing",
      "Blocked finance-memory conflict"
    ],
    recentExecutions: [
      {
        id: "exec-maryada-01",
        task: "Prepare investor diligence workspace",
        status: "waiting_approval",
        timestamp: "2026-08-13T03:42:00Z"
      }
    ]
  },
  {
    id: "rachit",
    name: "RACHIT",
    role: "Delivery orchestration",
    status: "idle",
    currentTask: "Awaiting approved work",
    lastActivity: "Delivered renewal briefing",
    health: "healthy",
    description:
      "Packages approved outputs and coordinates final task delivery after review gates clear.",
    recentActivity: [
      "Delivered customer renewal briefing",
      "Queued diligence workspace after approval",
      "Prepared internal summary format"
    ],
    recentExecutions: [
      {
        id: "exec-rachit-01",
        task: "Draft customer renewal briefing",
        status: "completed",
        timestamp: "2026-08-12T16:05:00Z"
      }
    ]
  },
  {
    id: "niyantra",
    name: "NIYANTRA",
    role: "Control plane coordination",
    status: "idle",
    currentTask: "Workflow supervision",
    lastActivity: "Updated active workflow counters",
    health: "healthy",
    description:
      "Monitors workflow state, approvals, and operating constraints across the MVP agent graph.",
    recentActivity: [
      "Updated Founder command center counters",
      "Tracked waiting approval state",
      "Recorded blocked context dependency"
    ],
    recentExecutions: [
      {
        id: "exec-niyantra-01",
        task: "System monitoring tick",
        status: "completed",
        timestamp: "2026-08-13T03:45:00Z"
      }
    ]
  },
  {
    id: "lisa",
    name: "LISA",
    role: "Interface and notification layer",
    status: "failed",
    currentTask: "Notification digest",
    lastActivity: "Digest generation paused",
    health: "offline",
    description:
      "Surfaces concise updates, reminders, and founder-facing workflow notifications.",
    recentActivity: [
      "Queued approval notification",
      "Paused digest after channel configuration error",
      "Logged notification issue for review"
    ],
    recentExecutions: [
      {
        id: "exec-lisa-01",
        task: "Founder approval digest",
        status: "failed",
        timestamp: "2026-08-13T03:10:00Z"
      }
    ]
  }
];
