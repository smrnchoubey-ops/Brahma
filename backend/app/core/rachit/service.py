"""
RACHIT Tool Execution Service & Governance Coordination
Strictly conforms to BRAHMA COS Whitesheet §13.0, §13.5 & §13.6.

Coordinates:
- Pre-execution validation against MARYADA policy verdicts, MURPHY risk reports, and MANUSH human approvals
- Tool execution dispatch inside isolated RachitSandbox
- Output hashing and canonical CHITRA invocation audit logging (faculty="RACHIT", event_type="invocation")
"""
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session

from app.core.rachit.limits import SandboxStatus, ExecutionQuotas, SandboxExecutionResult
from app.core.rachit.sandbox import RachitSandbox
from app.core.maryada.verdict import MaryadaVerdict, GateStatus
from app.core.murphy.report import MurphyRiskReport, MurphyRecommendation
from app.core.manush.decision import ReviewStatus
from app.repositories.chitra_repository import chitra_repository


class RachitExecutionService:
    """
    High-level RACHIT Tool Execution & Containment Service.
    """

    @classmethod
    def execute_sandboxed_tool(
        cls,
        tool_id: str,
        action_name: str,
        handler_fn: Any,
        tenant_id: str,
        task_id: int,
        params: Optional[Dict[str, Any]] = None,
        quotas: Optional[ExecutionQuotas] = None,
        maryada_verdict: Optional[MaryadaVerdict] = None,
        murphy_report: Optional[MurphyRiskReport] = None,
        human_review_status: Optional[ReviewStatus] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> SandboxExecutionResult:
        """
        Executes a tool within the RACHIT sandbox after verifying governance gates.
        """
        params = params or {}

        # -------------------------------------------------------------
        # 1. Governance Pre-flight Gates (§10, §11, §12)
        # -------------------------------------------------------------
        # Gate 1: MARYADA Approval
        if maryada_verdict and not maryada_verdict.approved:
            return cls._finalize_result(
                res=SandboxExecutionResult(
                    status=SandboxStatus.BLOCKED,
                    tool_id=tool_id,
                    action_name=action_name,
                    error=f"Execution blocked by MARYADA: {maryada_verdict.justification}",
                    exit_code=126
                ),
                task_id=task_id, tenant_id=tenant_id, db_session=db_session, user_id=user_id, session_id=session_id
            )

        # Gate 2: MURPHY Risk Recommendation
        if murphy_report and murphy_report.recommendation == MurphyRecommendation.BLOCKED:
            return cls._finalize_result(
                res=SandboxExecutionResult(
                    status=SandboxStatus.BLOCKED,
                    tool_id=tool_id,
                    action_name=action_name,
                    error=f"Execution blocked by MURPHY predictive simulation: {'; '.join(murphy_report.failure_modes)}",
                    exit_code=126
                ),
                task_id=task_id, tenant_id=tenant_id, db_session=db_session, user_id=user_id, session_id=session_id
            )

        # Gate 3: MANUSH Human Oversight
        if human_review_status and human_review_status != ReviewStatus.APPROVED_BY_HUMAN:
            return cls._finalize_result(
                res=SandboxExecutionResult(
                    status=SandboxStatus.BLOCKED,
                    tool_id=tool_id,
                    action_name=action_name,
                    error=f"Execution blocked pending human oversight: current status is '{human_review_status.value}'.",
                    exit_code=126
                ),
                task_id=task_id, tenant_id=tenant_id, db_session=db_session, user_id=user_id, session_id=session_id
            )

        # -------------------------------------------------------------
        # 2. Initialize Sandbox & Execute (§13.1, §13.4)
        # -------------------------------------------------------------
        sandbox = RachitSandbox(
            tenant_id=tenant_id,
            task_id=task_id,
            quotas=quotas
        )

        try:
            result = sandbox.execute_tool(
                tool_id=tool_id,
                action_name=action_name,
                handler_fn=handler_fn,
                params=params
            )
        finally:
            sandbox.cleanup()

        # -------------------------------------------------------------
        # 3. Append CHITRA Invocation Audit Event (§13.6, §8.2)
        # -------------------------------------------------------------
        return cls._finalize_result(
            res=result,
            task_id=task_id,
            tenant_id=tenant_id,
            db_session=db_session,
            user_id=user_id,
            session_id=session_id
        )

    @classmethod
    def _finalize_result(
        cls,
        res: SandboxExecutionResult,
        task_id: int,
        tenant_id: str,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> SandboxExecutionResult:
        """Appends canonical CHITRA invocation audit log."""
        if db_session and task_id:
            try:
                chitra_evt = chitra_repository.append_event(
                    db=db_session,
                    task_id=task_id,
                    faculty="RACHIT",
                    event_type="invocation",
                    decision={
                        "tool_id": res.tool_id,
                        "action_name": res.action_name,
                        "status": res.status.value,
                        "execution_time_ms": res.execution_time_ms,
                        "exit_code": res.exit_code,
                        "output_hash": res.output_hash,
                        "tenant_id": tenant_id
                    },
                    confidence=1.0 if res.status == SandboxStatus.SUCCESS else 0.0,
                    outcome=f"Executed {res.tool_id} (Status: {res.status.value}, Exit: {res.exit_code})",
                    session_id=session_id or f"ses_rachit_{task_id}",
                    user_id=user_id
                )
                res.chitra_event_id = chitra_evt.event_id
            except Exception:
                pass

        return res
