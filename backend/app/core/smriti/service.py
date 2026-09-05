"""
SMRITI Memory Service (Whitesheet §5 F5 Temporal Memory, §4.1 Path 2, §13 / CA-008).
Provides the authoritative production-grade interface for SMRITI conversational and episodic
memory operations backed strictly by PostgreSQL.
"""
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.core.smriti.models import SmritiRecord, SmritiWriteRequest, SmritiQuery
from app.core.smriti.repository import SmritiRepository
from app.models.memory import Memory


class SmritiMemoryService:
    """
    SMRITI Temporal Memory Service.
    Orchestrates session continuity, episodic memory capture, and tenant-scoped retrieval.
    """

    def __init__(self, repository: Optional[SmritiRepository] = None):
        self.repository = repository or SmritiRepository()

    def record_interaction(
        self,
        tenant_id: str,
        content: str,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        task_id: Optional[int] = None,
        memory_type: str = "conversation",
        source: str = "user",
        metadata_payload: Optional[Dict[str, Any]] = None,
        db_session: Optional[Session] = None
    ) -> SmritiRecord:
        """
        Records a conversational or episodic memory entry into persistent PostgreSQL storage.
        Fails closed on missing or empty tenant_id.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Memory operation aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            mem = self.repository.store_memory(
                db=db,
                tenant_id=tenant_id.strip(),
                content=content,
                user_id=user_id,
                session_id=session_id,
                task_id=task_id,
                memory_type=memory_type,
                source=source,
                approved="APPROVED",
                metadata_payload=metadata_payload
            )
            return self._to_record(mem)
        finally:
            if should_close:
                db.close()

    def get_memory(
        self,
        memory_id: int,
        tenant_id: str,
        db_session: Optional[Session] = None
    ) -> Optional[SmritiRecord]:
        """
        Retrieves a single memory record strictly scoped to tenant_id.
        Returns None if record does not exist or tenant mismatch (fail-closed).
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Memory retrieval aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            mem = self.repository.get_memory_by_id(db=db, memory_id=memory_id, tenant_id=tenant_id.strip())
            return self._to_record(mem) if mem else None
        finally:
            if should_close:
                db.close()

    def load_session_context(
        self,
        tenant_id: str,
        session_id: str,
        limit: int = 20,
        db_session: Optional[Session] = None
    ) -> List[SmritiRecord]:
        """
        Loads past conversational continuity context for a session within a tenant boundary.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Session context loading aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            memories = self.repository.get_session_history(
                db=db,
                tenant_id=tenant_id.strip(),
                session_id=session_id,
                limit=limit
            )
            return [self._to_record(m) for m in memories]
        finally:
            if should_close:
                db.close()

    def query_memories(
        self,
        query: SmritiQuery,
        db_session: Optional[Session] = None
    ) -> List[SmritiRecord]:
        """
        Executes a tenant-scoped structured memory query.
        """
        if not query.tenant_id or not str(query.tenant_id).strip():
            raise ValueError("Security Violation: Memory query aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            memories = self.repository.query_memories(
                db=db,
                tenant_id=query.tenant_id.strip(),
                user_id=query.user_id,
                session_id=query.session_id,
                task_id=query.task_id,
                memory_type=query.memory_type,
                limit=query.limit,
                offset=query.offset
            )
            return [self._to_record(m) for m in memories]
        finally:
            if should_close:
                db.close()

    def delete_memory(
        self,
        memory_id: int,
        tenant_id: str,
        db_session: Optional[Session] = None
    ) -> bool:
        """
        Deletes a memory record with strict tenant isolation check.
        Returns False if record does not belong to tenant_id.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Memory deletion aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            return self.repository.delete_memory(db=db, memory_id=memory_id, tenant_id=tenant_id.strip())
        finally:
            if should_close:
                db.close()

    @staticmethod
    def _to_record(mem: Memory) -> SmritiRecord:
        return SmritiRecord(
            id=mem.id,
            tenant_id=mem.tenant_id,
            user_id=mem.user_id,
            session_id=mem.session_id,
            task_id=mem.task_id,
            memory_type=mem.memory_type,
            content=mem.content,
            source=mem.source,
            approved=mem.approved,
            metadata_payload=mem.metadata_payload,
            created_at=mem.created_at.isoformat() if mem.created_at else None,
            updated_at=mem.updated_at.isoformat() if mem.updated_at else None
        )


smriti_service = SmritiMemoryService()
