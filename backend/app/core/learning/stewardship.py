"""
F15: Evolutionary Stewardship & Promotion Safeguards
Strictly conforms to BRAHMA COS Whitesheet F15 Specification.

Governs state transitions of learning patterns:
CANDIDATE -> VALIDATED -> SHADOW -> PROMOTED
Failure/Rollback paths: REJECTED | ROLLED_BACK
Enforces constitutional validation (MARYADA), LE thresholds, regression assertions,
and canonical CHITRA auditing.
"""
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.learning.models import (
    LearningCandidate,
    PatternStatus,
    ShadowEvaluationResult,
    RegressionTestResult,
    LEResult
)
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.repositories.chitra_repository import chitra_repository


class StewardshipError(Exception):
    """Raised when an illegal learning lifecycle transition is attempted."""
    pass


class F15EvolutionarySteward:
    """
    Controlled promotion, deployment, and rollback authority for learning candidates.
    """

    @classmethod
    def validate_candidate(
        cls,
        candidate: LearningCandidate,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> bool:
        """
        Validates candidate against MARYADA constitutional safety matrix.
        Transitions candidate from CANDIDATE -> VALIDATED.
        """
        if candidate.status != PatternStatus.CANDIDATE:
            raise StewardshipError(f"Cannot validate candidate in status '{candidate.status.value}'. Expected CANDIDATE.")

        # Evaluate against constitutional gate
        verdict = MaryadaGatekeeper.evaluate_action_gate(
            action=f"LEARNING_PATTERN_{candidate.pattern_type.value}: {candidate.name}",
            caller_authority="HIGH",
            tenant_id=candidate.tenant_id,
            db_session=db_session,
            task_id=task_id,
            user_id=user_id
        )

        if not verdict.approved:
            candidate.status = PatternStatus.REJECTED
            candidate.constitutional_approved = False
            cls._log_chitra_event(
                candidate=candidate, event_type="rejected",
                outcome=f"Constitutional validation rejected: {verdict.justification}",
                db_session=db_session, user_id=user_id, task_id=task_id
            )
            return False

        candidate.status = PatternStatus.VALIDATED
        candidate.constitutional_approved = True
        cls._log_chitra_event(
            candidate=candidate, event_type="validated",
            outcome="Constitutional validation approved",
            db_session=db_session, user_id=user_id, task_id=task_id
        )
        return True

    @classmethod
    def deploy_to_shadow(
        cls,
        candidate: LearningCandidate,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> None:
        """
        Transitions candidate from VALIDATED -> SHADOW.
        """
        if candidate.status != PatternStatus.VALIDATED:
            raise StewardshipError(f"Cannot deploy candidate in status '{candidate.status.value}' to SHADOW. Expected VALIDATED.")

        candidate.status = PatternStatus.SHADOW
        cls._log_chitra_event(
            candidate=candidate, event_type="shadow_deployed",
            outcome="Candidate deployed to non-authoritative shadow evaluation mode",
            db_session=db_session, user_id=user_id, task_id=task_id
        )

    @classmethod
    def evaluate_and_promote(
        cls,
        candidate: LearningCandidate,
        le_result: LEResult,
        regression_result: RegressionTestResult,
        shadow_result: Optional[ShadowEvaluationResult] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Evaluates candidate against promotion criteria:
        1. Status must be SHADOW.
        2. Constitutional approval == True.
        3. Regression tests passed (zero regressions).
        4. LE score >= threshold.
        5. Shadow evaluation passed.
        Transitions to PROMOTED or REJECTED.
        """
        if candidate.status != PatternStatus.SHADOW:
            raise StewardshipError(f"Cannot promote candidate in status '{candidate.status.value}'. Expected SHADOW.")

        candidate.le_score = le_result.le_score
        candidate.regression_passed = regression_result.passed
        candidate.shadow_passed = shadow_result.passed if shadow_result else True

        # Check all promotion gates fail-closed
        if not candidate.constitutional_approved:
            candidate.status = PatternStatus.REJECTED
            msg = "Promotion blocked: Constitutional safety check not approved."
            cls._log_chitra_event(candidate, "rejected", msg, db_session, user_id, task_id)
            return False, msg

        if not regression_result.passed or regression_result.regressions_detected > 0:
            candidate.status = PatternStatus.REJECTED
            msg = f"Promotion blocked: {regression_result.regressions_detected} regressions detected."
            cls._log_chitra_event(candidate, "rejected", msg, db_session, user_id, task_id)
            return False, msg

        if not le_result.passed:
            candidate.status = PatternStatus.REJECTED
            msg = f"Promotion blocked: LE Score {le_result.le_score} below required threshold {le_result.threshold}."
            cls._log_chitra_event(candidate, "rejected", msg, db_session, user_id, task_id)
            return False, msg

        if shadow_result and not shadow_result.passed:
            candidate.status = PatternStatus.REJECTED
            msg = "Promotion blocked: Shadow evaluation failed to beat or match baseline."
            cls._log_chitra_event(candidate, "rejected", msg, db_session, user_id, task_id)
            return False, msg

        # All gates passed: PROMOTION APPROVED
        candidate.status = PatternStatus.PROMOTED
        candidate.promoted_at = datetime.now(timezone.utc).isoformat()
        msg = f"Candidate {candidate.pattern_id} PROMOTED successfully (LE Score: {candidate.le_score})."
        cls._log_chitra_event(candidate, "promoted", msg, db_session, user_id, task_id)
        return True, msg

    @classmethod
    def rollback(
        cls,
        candidate: LearningCandidate,
        reason: str,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> None:
        """
        Rolls back a previously PROMOTED candidate to ROLLED_BACK.
        """
        if candidate.status != PatternStatus.PROMOTED:
            raise StewardshipError(f"Cannot rollback candidate in status '{candidate.status.value}'. Expected PROMOTED.")

        candidate.status = PatternStatus.ROLLED_BACK
        msg = f"Rolled back candidate {candidate.pattern_id}. Reason: {reason}"
        cls._log_chitra_event(candidate, "rolled_back", msg, db_session, user_id, task_id)

    @classmethod
    def _log_chitra_event(
        cls,
        candidate: LearningCandidate,
        event_type: str,
        outcome: str,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> None:
        """Appends canonical CHITRA Learning audit event."""
        if db_session and task_id:
            try:
                chitra_repository.append_event(
                    db=db_session,
                    task_id=task_id,
                    faculty="LEARNING",
                    event_type=event_type,
                    decision={
                        "pattern_id": candidate.pattern_id,
                        "tenant_id": candidate.tenant_id,
                        "status": candidate.status.value,
                        "le_score": candidate.le_score,
                        "version": candidate.version,
                        "pattern_type": candidate.pattern_type.value
                    },
                    confidence=candidate.confidence,
                    outcome=outcome,
                    session_id=f"ses_learn_{candidate.pattern_id}",
                    user_id=user_id
                )
            except Exception:
                pass
