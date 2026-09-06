"""
KARMA Error Recovery & Degradation Engine
Strictly conforms to BRAHMA COS Whitesheet §7.6.

Implements compensating actions, graceful degradation flags, and human escalation
routes for unrecoverable step failures.
"""
from typing import Dict, Any, Optional, List, Callable
from pydantic import BaseModel, Field

from app.core.karma.plan_dag import KarmaStep


class KarmaRecoveryDecision(BaseModel):
    """
    Structured outcome of the KARMA Error Recovery process.
    Matches Whitesheet §7.6.
    """
    recovery_strategy: str = Field(description="'COMPENSATED' | 'DEGRADED' | 'ESCALATED' | 'UNRECOVERED'")
    is_recovered: bool
    compensating_step: Optional[Dict[str, Any]] = None
    degraded_output: Optional[Any] = None
    escalation_reason: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class KarmaRecoveryEngine:
    """
    Evaluates failed steps and applies recovery strategies:
    1. Compensating action (must pass routing/authority/execution gates)
    2. Graceful degradation (partial outcome with explicit flag)
    3. Human escalation (routing unrecoverable states to oversight)
    """

    @classmethod
    def recover(
        cls,
        step: KarmaStep,
        error_message: str,
        caller_authority: str = "LOW",
        allow_degradation: bool = True,
        compensating_action_def: Optional[Dict[str, Any]] = None
    ) -> KarmaRecoveryDecision:
        """
        Processes unrecoverable step failure and outputs explicit recovery decision.
        """
        # 1. Compensating Action Strategy (§7.6)
        if compensating_action_def:
            comp_action = compensating_action_def.get("action", f"compensate_{step.action}")
            comp_tool = compensating_action_def.get("tool", step.tool)
            return KarmaRecoveryDecision(
                recovery_strategy="COMPENSATED",
                is_recovered=True,
                compensating_step={
                    "action": comp_action,
                    "tool": comp_tool,
                    "target_step_id": step.step_id,
                    "reason": f"Compensating for failed step '{step.step_id}': {error_message}"
                },
                details={"original_error": error_message}
            )

        # 2. Graceful Degradation Strategy (§7.6)
        if allow_degradation and ("read_only" in step.action.lower() or "lookup" in step.action.lower() or "status" in step.action.lower()):
            degraded_payload = {
                "degraded": True,
                "partial_result": None,
                "incompleteness_warning": f"Graceful degradation applied for step '{step.step_id}' due to: {error_message}",
                "step_id": step.step_id
            }
            return KarmaRecoveryDecision(
                recovery_strategy="DEGRADED",
                is_recovered=True,
                degraded_output=degraded_payload,
                details={"fallback_mode": "read_only_degradation"}
            )

        # 3. Human Escalation Strategy (§7.6 & §12)
        return KarmaRecoveryDecision(
            recovery_strategy="ESCALATED",
            is_recovered=False,
            escalation_reason=f"Unrecoverable failure in step '{step.step_id}': {error_message}. Routing to Human Oversight.",
            details={"requires_human_oversight": True, "step_id": step.step_id}
        )
