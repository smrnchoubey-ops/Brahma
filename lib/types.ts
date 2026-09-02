export type WorkflowStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "BLOCKED";

export type RiskLevel =
  | "LOW"
  | "MEDIUM"
  | "HIGH"
  | "CRITICAL";

export interface PragyaPlan {
  summary: string;
  steps: string[];
  tools_needed: string[];
  assumptions: string[];
}

export interface RiskReport {
  risk_level: RiskLevel;
  failure_modes: string[];
  security_concerns: string[];
  recommendation: string;
}

export interface PolicyVerdict {
  risk_tier: RiskLevel;
  approved: boolean;
  requires_human: boolean;
  justification: string;
}

export interface ExecutionResult {
  status: string;
  message: string;
  executed_steps: number;
}

export interface Task {
  id: number;

  title: string;

  prompt: string;

  status: WorkflowStatus;

  risk_level: RiskLevel;

  created_at: string;

  updated_at?: string;

  plan?: PragyaPlan;

  risk_report?: RiskReport;

  policy_verdict?: PolicyVerdict;

  execution_result?: ExecutionResult;

  errors?: string[];
}