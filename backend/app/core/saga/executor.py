"""
SAGA Workflow Executor & Lifecycle Coordinator
Strictly conforms to BRAHMA COS Whitesheet §14.0–§14.6.

Coordinates:
- Forward step execution respecting dependency constraints
- Automatic rollback triggering on forward step failure
- Full CHITRA audit integration
- Multi-tenant boundary enforcement
"""
from typing import Dict, Any, Optional, List, Callable, Tuple
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.saga.models import (
    SagaDefinition,
    SagaStatus,
    SagaStep,
    SagaStepStatus,
    SagaExecutionReport,
    SagaCompensationRecord
)
from app.core.saga.state_machine import SagaStateMachine
from app.core.saga.compensation import SagaCompensationEngine
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.repositories.chitra_repository import chitra_repository


class SagaExecutor:
    """
    Executes distributed Saga workflows with automatic compensating rollbacks.
    """

    @classmethod
    def execute_saga(
        cls,
        saga: SagaDefinition,
        action_dispatcher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        compensation_dispatcher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> SagaExecutionReport:
        """
        Executes a Saga to completion or compensates on failure.
        """
        if not saga.tenant_id or not saga.tenant_id.strip():
            raise ValueError("Authenticated Tenant ID is required for Saga execution.")

        start_time = time.perf_counter()
        SagaStateMachine.validate_saga_transition(saga.status, SagaStatus.RUNNING)
        saga.status = SagaStatus.RUNNING

        # 1. Log Saga Start in CHITRA (§14.6)
        cls._log_saga_event(
            saga=saga, event_type="saga_lifecycle", outcome="SAGA_STARTED",
            db_session=db_session, user_id=user_id, session_id=session_id
        )

        completed_steps: List[SagaStep] = []
        comp_records: List[SagaCompensationRecord] = []
        failure_error: Optional[str] = None

        # 2. Forward Execution Loop (§14.2)
        for step in saga.steps:
            # Check dependencies
            prereqs_met = all(dep in [s.step_id for s in completed_steps] for dep in step.dependencies)
            if not prereqs_met:
                SagaStateMachine.validate_step_transition(step.status, SagaStepStatus.FAILED)
                step.status = SagaStepStatus.FAILED
                step.forward_error = f"Prerequisite dependency unmet for step '{step.step_id}'."
                failure_error = step.forward_error
                break

            SagaStateMachine.validate_step_transition(step.status, SagaStepStatus.RUNNING)
            step.status = SagaStepStatus.RUNNING

            # Pre-flight Governance for Forward Action
            gov_verdict = MaryadaGatekeeper.evaluate_action_gate(
                step.forward_action, caller_authority="LOW", db_session=db_session, user_id=user_id, session_id=session_id
            )

            if not gov_verdict.approved:
                SagaStateMachine.validate_step_transition(step.status, SagaStepStatus.FAILED)
                step.status = SagaStepStatus.FAILED
                step.forward_error = f"Forward action blocked by MARYADA: {gov_verdict.justification}"
                failure_error = step.forward_error
                break

            # Execute Forward Action
            try:
                if action_dispatcher:
                    f_out = action_dispatcher(step.forward_action, step.metadata)
                else:
                    f_out = {"status": "SUCCESS", "action": step.forward_action}

                SagaStateMachine.validate_step_transition(step.status, SagaStepStatus.SUCCEEDED)
                step.status = SagaStepStatus.SUCCEEDED
                step.forward_output = f_out
                step.executed_at = datetime.now(timezone.utc).isoformat()
                completed_steps.append(step)

                cls._log_saga_event(
                    saga=saga, event_type="forward_step", outcome=f"STEP_SUCCEEDED_{step.step_id}",
                    details={"step_id": step.step_id, "action": step.forward_action, "output": f_out},
                    db_session=db_session, user_id=user_id, session_id=session_id
                )

            except Exception as ex:
                SagaStateMachine.validate_step_transition(step.status, SagaStepStatus.FAILED)
                step.status = SagaStepStatus.FAILED
                step.forward_error = f"{type(ex).__name__}: {str(ex)}"
                failure_error = step.forward_error
                break

        # 3. Handle Failure / Rollback Triggering (§14.3)
        if failure_error:
            # Mark remaining steps as SKIPPED / ABORTED
            for s in saga.steps:
                if s.status == SagaStepStatus.PENDING:
                    SagaStateMachine.validate_step_transition(s.status, SagaStepStatus.SKIPPED)
                    s.status = SagaStepStatus.SKIPPED

            SagaStateMachine.validate_saga_transition(saga.status, SagaStatus.COMPENSATING)
            saga.status = SagaStatus.COMPENSATING

            cls._log_saga_event(
                saga=saga, event_type="saga_lifecycle", outcome="SAGA_COMPENSATION_STARTED",
                details={"failed_due_to": failure_error},
                db_session=db_session, user_id=user_id, session_id=session_id
            )

            # Trigger Reverse-order Compensation
            all_comp_ok, comp_records = SagaCompensationEngine.compensate_steps(
                saga_id=saga.saga_id,
                task_id=saga.task_id,
                tenant_id=saga.tenant_id,
                succeeded_steps=completed_steps,
                action_dispatcher=compensation_dispatcher or action_dispatcher,
                db_session=db_session,
                user_id=user_id,
                session_id=session_id
            )

            final_status = SagaStatus.COMPENSATED if all_comp_ok else SagaStatus.COMPENSATION_FAILED
            SagaStateMachine.validate_saga_transition(saga.status, final_status)
            saga.status = final_status

        else:
            SagaStateMachine.validate_saga_transition(saga.status, SagaStatus.SUCCEEDED)
            saga.status = SagaStatus.SUCCEEDED

        saga.completed_at = datetime.now(timezone.utc).isoformat()
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # 4. Log Final Outcome in CHITRA
        cls._log_saga_event(
            saga=saga, event_type="saga_lifecycle", outcome=f"SAGA_{saga.status.value}",
            details={"duration_ms": elapsed_ms, "error": failure_error},
            db_session=db_session, user_id=user_id, session_id=session_id
        )

        return SagaExecutionReport(
            saga_id=saga.saga_id,
            task_id=saga.task_id,
            tenant_id=saga.tenant_id,
            status=saga.status,
            steps_completed=[s.step_id for s in completed_steps],
            steps_compensated=[r.step_id for r in comp_records if r.status == "COMPENSATED"],
            compensation_failures=[r.step_id for r in comp_records if r.status == "COMPENSATION_FAILED"],
            compensation_records=comp_records,
            error=failure_error,
            duration_ms=elapsed_ms
        )

    @classmethod
    def _log_saga_event(
        cls,
        saga: SagaDefinition,
        event_type: str,
        outcome: str,
        details: Optional[Dict[str, Any]] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> None:
        """Appends canonical CHITRA Saga event."""
        if db_session and saga.task_id:
            try:
                chitra_repository.append_event(
                    db=db_session,
                    task_id=saga.task_id,
                    faculty="SAGA",
                    event_type=event_type,
                    decision={
                        "saga_id": saga.saga_id,
                        "status": saga.status.value,
                        "tenant_id": saga.tenant_id,
                        **(details or {})
                    },
                    confidence=1.0 if saga.status in [SagaStatus.SUCCEEDED, SagaStatus.COMPENSATED] else 0.0,
                    outcome=outcome,
                    session_id=session_id or f"ses_saga_{saga.saga_id}",
                    user_id=user_id
                )
            except Exception:
                pass
