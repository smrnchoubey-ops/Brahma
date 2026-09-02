import type { MemoryItem } from "@/lib/types";

export const memoryItems: MemoryItem[] = [
  {
    id: "mem-001",
    title: "Enterprise onboarding risk checklist",
    type: "Semantic",
    status: "Canonical",
    source: "Founder operating note",
    confidence: 94,
    createdDate: "2026-07-28T09:30:00Z",
    reviewDate: "2026-09-01T09:30:00Z",
    details:
      "Approved checklist for evaluating onboarding blockers across security, support, and implementation readiness."
  },
  {
    id: "mem-002",
    title: "Investor disclosure boundary",
    type: "Strategic",
    status: "Approved",
    source: "Board prep workspace",
    confidence: 88,
    createdDate: "2026-08-04T14:10:00Z",
    reviewDate: "2026-08-20T14:10:00Z",
    details:
      "Only approved revenue ranges, customer references, and roadmap commitments may be shared externally."
  },
  {
    id: "mem-003",
    title: "Renewal briefing style",
    type: "Working",
    status: "Candidate",
    source: "Sales leadership note",
    confidence: 72,
    createdDate: "2026-08-12T12:45:00Z",
    reviewDate: "2026-08-19T12:45:00Z",
    details:
      "Candidate preference for concise renewal briefs with adoption highlights, open risks, and next-step asks."
  },
  {
    id: "mem-004",
    title: "Deprecated runway model Q2",
    type: "Strategic",
    status: "Deprecated",
    source: "Finance model import",
    confidence: 41,
    createdDate: "2026-06-15T10:15:00Z",
    reviewDate: "2026-08-12T10:15:00Z",
    details:
      "Old runway assumptions superseded by updated hiring constraints and revised burn-rate guidance."
  },
  {
    id: "mem-005",
    title: "Telemetry anomaly handling episode",
    type: "Episodic",
    status: "Approved",
    source: "Incident review",
    confidence: 83,
    createdDate: "2026-08-02T18:05:00Z",
    reviewDate: "2026-08-30T18:05:00Z",
    details:
      "Past anomaly review showed aggregate-only summaries helped avoid privacy exposure while preserving operational signal."
  }
];
