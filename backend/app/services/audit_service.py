"""
CHITRA Audit & Runtime Event Logging Service
Conforms to BRAHMA COS Whitesheet §8.0 - §8.8.

Routes all runtime agent events (KARMA, KOSH, PRAGYA, MURPHY, MARYADA, RACHIT, SYSTEM)
directly into the CHITRA immutable cryptographic ledger.
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.chitra import ChitraEvent
from app.repositories.chitra_repository import chitra_repository
from migrate_audit_to_chitra import map_legacy_event_type


class AuditService:
    """
    Unified service mapping all runtime and agent events into canonical CHITRA records.
    """
    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    @property
    def session_factory(self):
        if self._session_factory:
            return self._session_factory
        from app.db.database import SessionLocal
        return SessionLocal

    @session_factory.setter
    def session_factory(self, factory):
        self._session_factory = factory

    def create_chitra_event(
        self,
        db: Session,
        task_id: int,
        faculty: str,
        event_type: str,
        decision: Dict[str, Any],
        session_id: Optional[str] = None,
        evidence: Optional[List[str]] = None,
        confidence: float = 1.0,
        outcome: Optional[Any] = None,
        constitutional_review: str = "passed",
        input_data: Optional[Any] = None
    ) -> ChitraEvent:
        """Appends a cryptographically verified and signed CHITRA event record."""
        return chitra_repository.append_event(
            db=db,
            task_id=task_id,
            faculty=faculty,
            event_type=event_type,
            decision=decision,
            session_id=session_id,
            evidence=evidence,
            confidence=confidence,
            outcome=outcome,
            constitutional_review=constitutional_review,
            input_data=input_data
        )

    def log_runtime_event(
        self,
        task_id: int,
        agent: str,
        event_type: str,
        status: str = "SUCCESS",
        payload_snapshot: Optional[dict] = None,
        confidence: float = 1.0,
        evidence: Optional[List[str]] = None
    ) -> ChitraEvent:
        """
        Translates a runtime agent node event into a canonical Whitesheet §8.2 CHITRA envelope.
        """
        canonical_category = map_legacy_event_type(event_type, agent)
        constitutional_verdict = "failed" if (status in ["BLOCKED", "MARYADA_BLOCKED", "FAILED"] and (agent in ["MARYADA", "SYSTEM"] or "Security" in event_type or "Crash" in event_type)) else "passed"

        decision_payload = {
            "runtime_status": status,
            "runtime_event": event_type,
            "payload": payload_snapshot or {}
        }

        db = self.session_factory()
        try:
            chitra_record = self.create_chitra_event(
                db=db,
                task_id=task_id,
                faculty=agent,
                event_type=canonical_category,
                decision=decision_payload,
                session_id=f"ses_{task_id}",
                evidence=evidence or [],
                confidence=confidence,
                constitutional_review=constitutional_verdict
            )
            return chitra_record
        finally:
            db.close()


audit_service = AuditService()


def log_audit_event(
    task_id: int,
    agent: str,
    event_type: str,
    status: str = "SUCCESS",
    payload_snapshot: Optional[dict] = None
) -> ChitraEvent:
    """
    Direct runtime gateway used by KARMA, KOSH, PRAGYA, MURPHY, MARYADA, RACHIT, and main.py.
    Emits canonical CHITRA records.
    """
    return audit_service.log_runtime_event(
        task_id=task_id,
        agent=agent,
        event_type=event_type,
        status=status,
        payload_snapshot=payload_snapshot
    )