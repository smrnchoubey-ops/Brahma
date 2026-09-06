from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.chitra import ChitraEvent
from app.models.task import Task
from app.core.chitra.crypto import GENESIS_HASH, build_chitra_envelope


class ChitraRepository:
    """
    Manages atomic, append-only writes, concurrency locking, and tenant-scoped queries for CHITRA events.
    """

    def get_last_event(self, db: Session, task_id: int, user_id: Optional[int] = None) -> Optional[ChitraEvent]:
        """Retrieves the most recent chained event for a given task_id, enforcing tenant ownership if user_id is provided."""
        if user_id is not None:
            task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
            if not task:
                return None

        return (
            db.query(ChitraEvent)
            .filter(ChitraEvent.task_id == task_id)
            .order_by(ChitraEvent.id.desc())
            .first()
        )

    def append_event(
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
        input_data: Optional[Any] = None,
        user_id: Optional[int] = None
    ) -> ChitraEvent:
        """
        Creates, cryptographically chains, signs, and commits a new CHITRA event.
        Includes row-level locking on Task and tenant ownership validation.
        """
        # 1. Row-level pessimistic lock on Task for concurrent serialization (PostgreSQL)
        # SQLite local test harnesses do not support SELECT ... FOR UPDATE (SQLite uses file-level locking)
        bind = db.get_bind()
        if bind and bind.dialect.name != "sqlite":
            task_lock = db.query(Task).filter(Task.id == task_id).with_for_update().first()
            if not task_lock:
                raise ValueError(f"Task with id {task_id} not found for CHITRA logging.")
            if user_id is not None and task_lock.user_id != user_id:
                raise PermissionError(f"Access Denied: Task {task_id} does not belong to tenant {user_id}")
        else:
            if user_id is not None:
                task = db.query(Task).filter(Task.id == task_id).first()
                if not task:
                    raise ValueError(f"Task with id {task_id} not found.")
                if task.user_id != user_id:
                    raise PermissionError(f"Access Denied: Task {task_id} does not belong to tenant {user_id}")

        # 2. Fetch previous event hash for this task (or GENESIS_HASH)
        last_event = self.get_last_event(db, task_id)
        prev_hash = last_event.this_event_hash if last_event else GENESIS_HASH

        # 3. Construct canonical envelope, calculate chained hash & sign
        envelope = build_chitra_envelope(
            task_id=task_id,
            faculty=faculty,
            event_type=event_type,
            decision=decision,
            prev_event_hash=prev_hash,
            session_id=session_id,
            evidence=evidence,
            confidence=confidence,
            outcome=outcome,
            constitutional_review=constitutional_review,
            input_data=input_data
        )

        # 4. Create and persist record
        chitra_record = ChitraEvent(
            event_id=envelope["event_id"],
            task_id=envelope["task_id"],
            session_id=envelope["session_id"],
            timestamp=datetime.fromisoformat(envelope["timestamp"]),
            faculty=envelope["faculty"],
            event_type=envelope["event_type"],
            input_hash=envelope["input_hash"],
            decision=envelope["decision"],
            evidence=envelope["evidence"],
            confidence=envelope["confidence"],
            outcome=envelope["outcome"],
            constitutional_review=envelope["constitutional_review"],
            prev_event_hash=envelope["prev_event_hash"],
            this_event_hash=envelope["this_event_hash"],
            signature=envelope["signature"]
        )

        db.add(chitra_record)
        db.commit()
        db.refresh(chitra_record)
        return chitra_record

    def get_events_for_task(self, db: Session, task_id: int, user_id: Optional[int] = None) -> List[ChitraEvent]:
        """Returns all events for a task in ascending chronological order, scoped to user_id if provided."""
        if user_id is not None:
            task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
            if not task:
                return []

        return (
            db.query(ChitraEvent)
            .filter(ChitraEvent.task_id == task_id)
            .order_by(ChitraEvent.id.asc())
            .all()
        )

    def query_ledger(
        self,
        db: Session,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None,
        faculty: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 50
    ) -> List[ChitraEvent]:
        """Multi-index filtered query scoped to tenant (Whitesheet §8.4 & §18.0)."""
        q = db.query(ChitraEvent)
        if user_id is not None:
            q = q.join(Task, ChitraEvent.task_id == Task.id).filter(Task.user_id == user_id)
        if task_id is not None:
            q = q.filter(ChitraEvent.task_id == task_id)
        if faculty is not None:
            q = q.filter(ChitraEvent.faculty == faculty)
        if event_type is not None:
            q = q.filter(ChitraEvent.event_type == event_type)

        return q.order_by(ChitraEvent.id.desc()).limit(limit).all()


chitra_repository = ChitraRepository()
