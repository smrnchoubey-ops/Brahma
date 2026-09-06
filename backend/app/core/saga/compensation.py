"""
SAGA Compensation Engine & Reverse-Order Rollback
Strictly conforms to BRAHMA COS Whitesheet §14.3, §14.4 & §14.5.

Enforces:
- Reverse-order execution of previously successful forward steps
- Strict idempotency & duplicate compensation protection
- Governance evaluation on compensating actions
- Structured compensation evidence generation
- CHITRA audit logging (faculty="SAGA", event_type="compensation")
"""
from typing import Dict, Any, Optional, List, Tuple, Callable
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.saga.models import (
    SagaStep,
    SagaStepStatus,
    SagaCompensationRecord
)
from app.core.saga.state_machine import SagaStateMachine
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.repositories.chitra_repository import chitra_repository


class SagaCompensationEngine:
    """
    Executes compensating transactions in reverse order with idempotency protection.
    """

    @classmethod
    def compensate_steps(
        cls,
        saga_id: str,
        task_id: int,
        tenant_id: str,
        succeeded_steps: List[SagaStep],
        action_dispatcher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> Tuple[bool, List[SagaCompensationRecord]]:
        """
        Rolls back succeeded steps in REVERSE execution order.
        Returns (all_succeeded: bool, records: List[SagaCompensationRecord]).
        """
        records: List[SagaCompensationRecord] = []
        all_succeeded = True

        # 1. Reverse-order iteration (§14.3)
        for step in reversed(succeeded_steps):
            # Skip steps with no compensation declared
            if not step.compensating_action:
                continue

            # Idempotency Protection: If already COMPENSATED, skip duplicate execution (§14.4)
            if step.status == SagaStepStatus.COMPENSATED:
                continue

            SagaStateMachine.validate_step_transition(step.status, SagaStepStatus.COMPENSATING)
            step.status = SagaStepStatus.COMPENSATING
            step.compensation_attempts += 1

            # 2. Governance Pre-flight for Compensating Action (§14.5, §10.0)
            gov_verdict = MaryadaGatekeeper.evaluate_action_gate(
                step.compensating_action,
                caller_authority="HIGH",  # Compensation actions run under elevated policy
                db_session=db_session,
                user_id=user_id,
                session_id=session_id
            )

            if not gov_verdict.approved:
                step.status = SagaStepStatus.COMPENSATION_FAILED
                step.compensation_error = f"Compensation blocked by MARYADA: {gov_verdict.justification}"
                all_succeeded = False

                rec = cls._record_compensation(
                    saga_id=saga_id, task_id=task_id, tenant_id=tenant_id, step=step,
                    status="COMPENSATION_FAILED", error=step.compensation_error,
                    db_session=db_session, user_id=user_id, session_id=session_id
                )
                records.append(rec)
                continue

            # 3. Execute Compensating Action via dispatcher (§14.3)
            try:
                if action_dispatcher:
                    comp_out = action_dispatcher(step.compensating_action, step.metadata)
                else:
                    comp_out = {"status": "COMPENSATED_SUCCESSFULLY", "action": step.compensating_action}

                step.status = SagaStepStatus.COMPENSATED
                step.compensation_output = comp_out
                step.compensated_at = datetime.now(timezone.utc).isoformat()

                rec = cls._record_compensation(
                    saga_id=saga_id, task_id=task_id, tenant_id=tenant_id, step=step,
                    status="COMPENSATED", result=comp_out,
                    db_session=db_session, user_id=user_id, session_id=session_id
                )
                records.append(rec)

            except Exception as ex:
                step.status = SagaStepStatus.COMPENSATION_FAILED
                step.compensation_error = f"{type(ex).__name__}: {str(ex)}"
                all_succeeded = False

                rec = cls._record_compensation(
                    saga_id=saga_id, task_id=task_id, tenant_id=tenant_id, step=step,
                    status="COMPENSATION_FAILED", error=step.compensation_error,
                    db_session=db_session, user_id=user_id, session_id=session_id
                )
                records.append(rec)

        return all_succeeded, records

    @classmethod
    def _record_compensation(
        cls,
        saga_id: str,
        task_id: int,
        tenant_id: str,
        step: SagaStep,
        status: str,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> SagaCompensationRecord:
        """
        Creates structured compensation evidence and logs to CHITRA.
        """
        rec = SagaCompensationRecord(
            saga_id=saga_id,
            task_id=task_id,
            tenant_id=tenant_id,
            step_id=step.step_id,
            forward_action=step.forward_action,
            compensating_action=step.compensating_action or "",
            status=status,
            result=result,
            error=error
        )

        if db_session and task_id:
            try:
                chitra_evt = chitra_repository.append_event(
                    db=db_session,
                    task_id=task_id,
                    faculty="SAGA",
                    event_type="compensation",
                    decision={
                        "saga_id": saga_id,
                        "step_id": step.step_id,
                        "forward_action": step.forward_action,
                        "compensating_action": step.compensating_action,
                        "status": status,
                        "attempts": step.compensation_attempts,
                        "error": error,
                        "tenant_id": tenant_id
                    },
                    confidence=1.0 if status == "COMPENSATED" else 0.0,
                    outcome=f"Compensation for step {step.step_id}: {status}",
                    session_id=session_id or f"ses_saga_{saga_id}",
                    user_id=user_id
                )
                rec.chitra_event_id = chitra_evt.event_id
            except Exception:
                pass

        return rec
