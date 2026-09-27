"""
F15: Evolutionary Stewardship & Promotion Safeguards
Strictly conforms to BRAHMA COS Whitesheet F15 Specification.

Governs state transitions of learning patterns:
CANDIDATE -> VALIDATED -> SHADOW -> PROMOTED
Failure/Rollback paths: REJECTED | ROLLED_BACK
Enforces constitutional validation (MARYADA), LE thresholds, regression assertions,
and canonical CHITRA auditing.
"""
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

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
            cls._persist_candidate(candidate=candidate, db_session=db_session)
            return False

        candidate.status = PatternStatus.VALIDATED
        candidate.constitutional_approved = True
        cls._log_chitra_event(
            candidate=candidate, event_type="validated",
            outcome="Constitutional validation approved",
            db_session=db_session, user_id=user_id, task_id=task_id
        )
        cls._persist_candidate(candidate=candidate, db_session=db_session)
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
        now_iso = datetime.now(timezone.utc).isoformat()
        if not candidate.metadata.get("shadow_entered_at"):
            candidate.metadata["shadow_entered_at"] = now_iso
        candidate.metadata.setdefault("shadow_eval_count", 0)
        candidate.metadata.setdefault("live_shadow_evaluations", [])

        cls._log_chitra_event(
            candidate=candidate, event_type="shadow_deployed",
            outcome="Candidate deployed to non-authoritative shadow evaluation mode",
            db_session=db_session, user_id=user_id, task_id=task_id
        )
        cls._persist_candidate(candidate=candidate, db_session=db_session)

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

        # Extract comparative evaluation provenance (§17.4, §19.5, §20.3)
        comparative_provenance = (
            shadow_result.evidence.get("comparative_provenance", [])
            if shadow_result and isinstance(shadow_result.evidence, dict)
            else []
        )
        if comparative_provenance:
            candidate.metadata["comparative_provenance"] = comparative_provenance
            candidate.metadata["tau_LE"] = le_result.threshold
            candidate.metadata["lambda_reg"] = le_result.factors.get("lambda_reg", 0.50)
            candidate.metadata["regression_count"] = le_result.factors.get("regression_count", 0)
            candidate.metadata["LE"] = le_result.le_score

        # Check all promotion gates fail-closed
        if not candidate.constitutional_approved:
            candidate.status = PatternStatus.REJECTED
            msg = "Promotion blocked: Constitutional safety check not approved."
            cls._log_chitra_event(
                candidate=candidate, event_type="rejected", outcome=msg,
                db_session=db_session, user_id=user_id, task_id=task_id,
                comparative_provenance=comparative_provenance,
                le_result=le_result, regression_result=regression_result
            )
            cls._persist_candidate(candidate=candidate, db_session=db_session)
            return False, msg

        if not regression_result.passed or regression_result.regressions_detected > 0:
            candidate.status = PatternStatus.REJECTED
            msg = f"Promotion blocked: {regression_result.regressions_detected} regressions detected."
            cls._log_chitra_event(
                candidate=candidate, event_type="rejected", outcome=msg,
                db_session=db_session, user_id=user_id, task_id=task_id,
                comparative_provenance=comparative_provenance,
                le_result=le_result, regression_result=regression_result
            )
            cls._persist_candidate(candidate=candidate, db_session=db_session)
            return False, msg

        if not le_result.passed:
            candidate.status = PatternStatus.REJECTED
            msg = f"Promotion blocked: LE Score {le_result.le_score} below required threshold {le_result.threshold}."
            cls._log_chitra_event(
                candidate=candidate, event_type="rejected", outcome=msg,
                db_session=db_session, user_id=user_id, task_id=task_id,
                comparative_provenance=comparative_provenance,
                le_result=le_result, regression_result=regression_result
            )
            cls._persist_candidate(candidate=candidate, db_session=db_session)
            return False, msg

        if shadow_result and not shadow_result.passed:
            candidate.status = PatternStatus.REJECTED
            msg = "Promotion blocked: Shadow evaluation failed to beat or match baseline."
            cls._log_chitra_event(
                candidate=candidate, event_type="rejected", outcome=msg,
                db_session=db_session, user_id=user_id, task_id=task_id,
                comparative_provenance=comparative_provenance,
                le_result=le_result, regression_result=regression_result
            )
            cls._persist_candidate(candidate=candidate, db_session=db_session)
            return False, msg

        # All gates passed: PROMOTION APPROVED
        candidate.status = PatternStatus.PROMOTED
        candidate.promoted_at = datetime.now(timezone.utc).isoformat()
        msg = f"Candidate {candidate.pattern_id} PROMOTED successfully (LE Score: {candidate.le_score})."
        cls._log_chitra_event(
            candidate=candidate, event_type="promoted", outcome=msg,
            db_session=db_session, user_id=user_id, task_id=task_id,
            comparative_provenance=comparative_provenance,
            le_result=le_result, regression_result=regression_result
        )
        cls._persist_candidate(candidate=candidate, db_session=db_session)
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
        cls._persist_candidate(candidate=candidate, db_session=db_session)

    @classmethod
    def persist_candidate(
        cls,
        candidate: LearningCandidate,
        db_session: Optional[Session] = None
    ) -> Optional[Any]:
        """
        Explicit persistence helper for an initial CANDIDATE or existing candidate.
        """
        return cls._persist_candidate(candidate, db_session=db_session)

    @classmethod
    def _persist_candidate(
        cls,
        candidate: LearningCandidate,
        db_session: Optional[Session] = None
    ) -> Optional[Any]:
        """
        Persists or updates the LearningCandidate in PostgreSQL learning_patterns table.
        Guarantees pattern state survives process restarts with strict tenant isolation.
        """
        source_ep_ids = candidate.metadata.get("unique_episode_keys", [])
        if not source_ep_ids and candidate.evidence:
            source_ep_ids = (
                [f"t:{t}" for t in candidate.evidence.source_task_ids] +
                [f"e:{e}" for e in candidate.evidence.source_event_ids]
            )

        evidence_dict = (
            candidate.evidence.model_dump()
            if hasattr(candidate.evidence, "model_dump")
            else candidate.evidence.dict()
        )

        promoted_dt = None
        if candidate.promoted_at:
            try:
                promoted_dt = datetime.fromisoformat(candidate.promoted_at)
            except Exception:
                promoted_dt = datetime.now(timezone.utc)

        fingerprint = candidate.metadata.get("fingerprint")

        def _upsert_record(session: Session):
            from app.models.learning_pattern import LearningPattern
            record = session.query(LearningPattern).filter(
                LearningPattern.pattern_id == candidate.pattern_id,
                LearningPattern.tenant_id == candidate.tenant_id
            ).first()

            if record:
                record.pattern_type = candidate.pattern_type.value
                record.name = candidate.name
                record.description = candidate.description
                record.status = candidate.status.value
                record.fingerprint = fingerprint
                record.confidence = candidate.confidence
                record.version = candidate.version
                record.le_score = candidate.le_score
                record.constitutional_approved = candidate.constitutional_approved
                record.shadow_passed = candidate.shadow_passed
                record.regression_passed = candidate.regression_passed
                record.action_template = candidate.action_template or {}
                record.evidence = evidence_dict
                record.source_episode_ids = source_ep_ids
                record.metadata_payload = candidate.metadata or {}
                record.promoted_at = promoted_dt
                record.updated_at = datetime.now(timezone.utc)
            else:
                record = LearningPattern(
                    pattern_id=candidate.pattern_id,
                    tenant_id=candidate.tenant_id,
                    pattern_type=candidate.pattern_type.value,
                    name=candidate.name,
                    description=candidate.description,
                    status=candidate.status.value,
                    fingerprint=fingerprint,
                    confidence=candidate.confidence,
                    version=candidate.version,
                    le_score=candidate.le_score,
                    constitutional_approved=candidate.constitutional_approved,
                    shadow_passed=candidate.shadow_passed,
                    regression_passed=candidate.regression_passed,
                    action_template=candidate.action_template or {},
                    evidence=evidence_dict,
                    source_episode_ids=source_ep_ids,
                    metadata_payload=candidate.metadata or {},
                    promoted_at=promoted_dt
                )
                session.add(record)
            session.commit()
            return record

        if db_session is not None:
            try:
                return _upsert_record(db_session)
            except Exception:
                try:
                    db_session.rollback()
                except Exception:
                    pass
                raise
        else:
            try:
                from app.db.database import SessionLocal
                with SessionLocal() as db:
                    return _upsert_record(db)
            except Exception as e:
                logger.error(
                    f"Failed to persist learning candidate '{candidate.pattern_id}' (tenant='{candidate.tenant_id}', status='{candidate.status.value}') to PostgreSQL: {e}",
                    exc_info=True
                )
                return None

    @classmethod
    def _log_chitra_event(
        cls,
        candidate: LearningCandidate,
        event_type: str,
        outcome: str,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None,
        comparative_provenance: Optional[List[Dict[str, Any]]] = None,
        le_result: Optional[LEResult] = None,
        regression_result: Optional[RegressionTestResult] = None
    ) -> None:
        """Appends canonical CHITRA Learning audit event with full comparative provenance (§17.4, §19.5, §20.3)."""
        if db_session and task_id:
            try:
                decision_payload: Dict[str, Any] = {
                    "pattern_id": candidate.pattern_id,
                    "tenant_id": candidate.tenant_id,
                    "status": candidate.status.value,
                    "le_score": candidate.le_score,
                    "version": candidate.version,
                    "pattern_type": candidate.pattern_type.value
                }
                if comparative_provenance:
                    decision_payload["comparative_provenance"] = comparative_provenance
                if le_result:
                    decision_payload["tau_LE"] = le_result.threshold
                    decision_payload["lambda_reg"] = le_result.factors.get("lambda_reg", 0.50)
                    decision_payload["regression_count"] = le_result.factors.get("regression_count", 0)
                    decision_payload["mean_delta"] = le_result.factors.get("mean_outcome_delta", 0.0)
                    decision_payload["LE"] = le_result.le_score

                chitra_repository.append_event(
                    db=db_session,
                    task_id=task_id,
                    faculty="LEARNING",
                    event_type=event_type,
                    decision=decision_payload,
                    confidence=candidate.confidence,
                    outcome=outcome,
                    session_id=f"ses_learn_{candidate.pattern_id}",
                    user_id=user_id
                )
            except Exception:
                pass
