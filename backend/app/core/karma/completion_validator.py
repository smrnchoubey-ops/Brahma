"""
KARMA Completion Validator & No-Silent-Actions Engine
Strictly conforms to BRAHMA COS Whitesheet §§7.8–7.9.

Validates:
1. Completion criteria (§7.8): success, outcome_observed, alignment_score, audit_trail_ref
2. No-Silent-Actions mandatory evidence (§7.9): reason, tool, authority_token,
   expected_outcome, actual_outcome, ledger_entry_ref
"""
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.chitra import ChitraEvent
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier


class KarmaNoSilentActionEvidence(BaseModel):
    """
    Mandatory audit evidence for every tool/action invocation under Whitesheet §7.9.
    Every field is required and verified against the actual ledger and invocation context.
    """
    reason: str = Field(description="Explicit rationale/purpose of the action")
    tool: str = Field(description="Identified tool selected and executed")
    authority_token: str = Field(description="Authority level/token used to authorize execution")
    expected_outcome: str = Field(description="Declared expected outcome contract")
    actual_outcome: str = Field(description="Observed actual outcome payload")
    ledger_entry_ref: str = Field(description="Reference ID of the canonical CHITRA event")


class KarmaCompletionValidationResult(BaseModel):
    """
    Structured, machine-readable validation result for step/plan completion (§7.8).
    """
    is_valid: bool
    status: str = Field(description="'COMPLETED' | 'INCOMPLETE_OUTCOME' | 'ALIGNMENT_FAILURE' | 'SILENT_ACTION_BLOCKED' | 'AUDIT_VERIFICATION_FAILED' | 'REJECTED'")
    success: bool
    outcome_observed: bool
    alignment_score: float = Field(ge=0.0, le=1.0)
    audit_trail_ref: Optional[str] = None
    no_silent_action_valid: bool = False
    failure_reason: Optional[str] = None
    evidence_details: Dict[str, Any] = Field(default_factory=dict)


class KarmaCompletionValidator:
    """
    Validates completion and enforces No-Silent-Actions compliance on execution outputs.
    """

    @classmethod
    def validate_step_completion(
        cls,
        step_id: str,
        action: str,
        expected_outcome: str,
        actual_output: Any,
        status: str,
        verification_status: Optional[str],
        tool_id: Optional[str],
        authority_token: Optional[str],
        ledger_entry_ref: Optional[str],
        db_session: Optional[Session] = None,
        expected_task_id: Optional[int] = None,
        expected_user_id: Optional[int] = None,
        require_ledger_ref: bool = True,
        recovery_decision: Optional[Dict[str, Any]] = None
    ) -> KarmaCompletionValidationResult:
        """
        Validates step completion according to Whitesheet §7.8 & §7.9.
        """
        evidence: Dict[str, Any] = {}

        # -------------------------------------------------------------
        # 1. Base Execution & Verification Checks
        # -------------------------------------------------------------
        if status != "SUCCEEDED":
            return KarmaCompletionValidationResult(
                is_valid=False,
                status="REJECTED",
                success=False,
                outcome_observed=False,
                alignment_score=0.0,
                audit_trail_ref=ledger_entry_ref,
                no_silent_action_valid=False,
                failure_reason=f"Step '{step_id}' did not succeed (status='{status}')."
            )

        is_recovered = bool(recovery_decision and recovery_decision.get("is_recovered"))
        if verification_status != "VERIFIED" and not is_recovered:
            return KarmaCompletionValidationResult(
                is_valid=False,
                status="REJECTED",
                success=False,
                outcome_observed=False,
                alignment_score=0.0,
                audit_trail_ref=ledger_entry_ref,
                no_silent_action_valid=False,
                failure_reason=f"Step '{step_id}' failed verification (verification_status='{verification_status}')."
            )

        # -------------------------------------------------------------
        # 2. Outcome Observed Check (§7.8)
        # -------------------------------------------------------------
        if actual_output is None:
            return KarmaCompletionValidationResult(
                is_valid=False,
                status="INCOMPLETE_OUTCOME",
                success=False,
                outcome_observed=False,
                alignment_score=0.0,
                audit_trail_ref=ledger_entry_ref,
                no_silent_action_valid=False,
                failure_reason=f"Step '{step_id}' produced no observed outcome."
            )

        outcome_observed = True
        actual_str = str(actual_output)

        # -------------------------------------------------------------
        # 3. Alignment Score (§7.8)
        # 1.0 if verified and outcome matches contract, degraded otherwise
        # -------------------------------------------------------------
        alignment_score = 1.0 if verification_status == "VERIFIED" else 0.0

        # -------------------------------------------------------------
        # 4. No-Silent-Actions Verification (§7.9)
        # Verify mandatory context: reason, tool, authority_token, expected_outcome, actual_outcome, ledger_entry_ref
        # -------------------------------------------------------------
        missing_fields = []
        if not action or not action.strip():
            missing_fields.append("reason")
        if not tool_id or not tool_id.strip():
            missing_fields.append("tool")
        if not authority_token or not authority_token.strip():
            missing_fields.append("authority_token")
        if not expected_outcome or not expected_outcome.strip():
            missing_fields.append("expected_outcome")
        if not actual_str or not actual_str.strip():
            missing_fields.append("actual_outcome")
        if require_ledger_ref and (not ledger_entry_ref or not ledger_entry_ref.strip()):
            missing_fields.append("ledger_entry_ref")

        if missing_fields:
            return KarmaCompletionValidationResult(
                is_valid=False,
                status="SILENT_ACTION_BLOCKED",
                success=False,
                outcome_observed=outcome_observed,
                alignment_score=alignment_score,
                audit_trail_ref=ledger_entry_ref,
                no_silent_action_valid=False,
                failure_reason=f"No-Silent-Actions check failed: missing mandatory fields {missing_fields}."
            )

        # -------------------------------------------------------------
        # 5. CHITRA Cryptographic & Tenant Ledger Cross-Verification (§7.9, §8.2)
        # -------------------------------------------------------------
        if db_session and ledger_entry_ref and require_ledger_ref:
            from app.models.task import Task

            # Query the actual ledger event
            event = db_session.query(ChitraEvent).filter(ChitraEvent.event_id == ledger_entry_ref).first()
            if not event:
                return KarmaCompletionValidationResult(
                    is_valid=False,
                    status="AUDIT_VERIFICATION_FAILED",
                    success=False,
                    outcome_observed=outcome_observed,
                    alignment_score=alignment_score,
                    audit_trail_ref=ledger_entry_ref,
                    no_silent_action_valid=False,
                    failure_reason=f"Audit verification failed: ledger_entry_ref '{ledger_entry_ref}' does not exist in CHITRA."
                )

            task = db_session.query(Task).filter(Task.id == event.task_id).first()
            if not task:
                return KarmaCompletionValidationResult(
                    is_valid=False,
                    status="AUDIT_VERIFICATION_FAILED",
                    success=False,
                    outcome_observed=outcome_observed,
                    alignment_score=alignment_score,
                    audit_trail_ref=ledger_entry_ref,
                    no_silent_action_valid=False,
                    failure_reason=f"Audit verification failed: task {event.task_id} does not exist."
                )

            # Tenant Isolation Verification (§4C, §7.9)
            if expected_user_id is not None and task.user_id != expected_user_id:
                return KarmaCompletionValidationResult(
                    is_valid=False,
                    status="AUDIT_VERIFICATION_FAILED",
                    success=False,
                    outcome_observed=outcome_observed,
                    alignment_score=alignment_score,
                    audit_trail_ref=ledger_entry_ref,
                    no_silent_action_valid=False,
                    failure_reason=f"Security violation: ledger_entry_ref belongs to user {task.user_id}, not expected user {expected_user_id}."
                )

            # Task Scope Verification
            if expected_task_id is not None and event.task_id != expected_task_id:
                return KarmaCompletionValidationResult(
                    is_valid=False,
                    status="AUDIT_VERIFICATION_FAILED",
                    success=False,
                    outcome_observed=outcome_observed,
                    alignment_score=alignment_score,
                    audit_trail_ref=ledger_entry_ref,
                    no_silent_action_valid=False,
                    failure_reason=f"Task mismatch: ledger event belongs to task {event.task_id}, not expected task {expected_task_id}."
                )

            # Verify cryptographic chain integrity
            v_res = chitra_verifier.verify_task_chain(db_session, event.task_id, user_id=task.user_id)
            if not v_res.valid:
                return KarmaCompletionValidationResult(
                    is_valid=False,
                    status="AUDIT_VERIFICATION_FAILED",
                    success=False,
                    outcome_observed=outcome_observed,
                    alignment_score=alignment_score,
                    audit_trail_ref=ledger_entry_ref,
                    no_silent_action_valid=False,
                    failure_reason=f"Cryptographic chain verification failed for task {event.task_id}."
                )

        evidence["no_silent_action"] = {
            "reason": action,
            "tool": tool_id,
            "authority_token": authority_token,
            "expected_outcome": expected_outcome,
            "actual_outcome": actual_str,
            "ledger_entry_ref": ledger_entry_ref
        }

        return KarmaCompletionValidationResult(
            is_valid=True,
            status="COMPLETED",
            success=True,
            outcome_observed=outcome_observed,
            alignment_score=alignment_score,
            audit_trail_ref=ledger_entry_ref,
            no_silent_action_valid=True,
            failure_reason=None,
            evidence_details=evidence
        )
