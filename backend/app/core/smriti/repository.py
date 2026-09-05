"""
SMRITI Repository Layer (Whitesheet §5 F5 Temporal Memory, §4.1 Path 2, §13 / CA-008).
Executes strictly tenant-scoped CRUD operations against the PostgreSQL 'memory' table.
Fails closed on missing tenant_id or cross-tenant access attempts.
"""
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.memory import Memory


class SmritiRepository:
    """
    Direct PostgreSQL data access repository for SMRITI memory records.
    Every operation requires an explicit, non-empty tenant_id.
    """

    @staticmethod
    def store_memory(
        db: Session,
        tenant_id: str,
        content: str,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        task_id: Optional[int] = None,
        memory_type: str = "conversation",
        source: str = "user",
        approved: str = "APPROVED",
        metadata_payload: Optional[Dict[str, Any]] = None
    ) -> Memory:
        """
        Stores a new memory record bound to tenant_id and optional user/session/task context.
        Fails closed if tenant_id or content is empty.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot persist memory without a valid tenant_id (CA-008 fail-closed).")

        if not content or not isinstance(content, str) or not content.strip():
            raise ValueError("Invalid Input: Memory content cannot be empty.")

        record = Memory(
            tenant_id=tenant_id.strip(),
            user_id=user_id,
            session_id=session_id.strip() if session_id else None,
            task_id=task_id,
            memory_type=memory_type.strip() if memory_type else "conversation",
            content=content.strip(),
            source=source.strip() if source else "user",
            approved=approved.strip() if approved else "APPROVED",
            metadata_payload=metadata_payload or {}
        )

        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def get_memory_by_id(
        db: Session,
        memory_id: int,
        tenant_id: str
    ) -> Optional[Memory]:
        """
        Retrieves a single memory record by primary key, strictly scoped to tenant_id.
        Returns None if record does not exist OR if tenant_id does not match (fail-closed).
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot retrieve memory without a valid tenant_id (CA-008 fail-closed).")

        if not memory_id or not isinstance(memory_id, int) or memory_id <= 0:
            return None

        return db.query(Memory).filter(
            Memory.id == memory_id,
            Memory.tenant_id == tenant_id.strip()
        ).first()

    @staticmethod
    def query_memories(
        db: Session,
        tenant_id: str,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        task_id: Optional[int] = None,
        memory_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Memory]:
        """
        Queries memory records strictly filtered by tenant_id and optional query dimensions.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot query memories without a valid tenant_id (CA-008 fail-closed).")

        query = db.query(Memory).filter(Memory.tenant_id == tenant_id.strip())

        if user_id is not None:
            query = query.filter(Memory.user_id == user_id)

        if session_id is not None and session_id.strip():
            query = query.filter(Memory.session_id == session_id.strip())

        if task_id is not None:
            query = query.filter(Memory.task_id == task_id)

        if memory_type is not None and memory_type.strip():
            query = query.filter(Memory.memory_type == memory_type.strip())

        return query.order_by(Memory.created_at.asc()).offset(offset).limit(limit).all()

    @staticmethod
    def get_session_history(
        db: Session,
        tenant_id: str,
        session_id: str,
        limit: int = 20
    ) -> List[Memory]:
        """
        Retrieves chronological conversation context for a specific session within a tenant boundary.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot retrieve session history without a valid tenant_id (CA-008 fail-closed).")

        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            return []

        return db.query(Memory).filter(
            Memory.tenant_id == tenant_id.strip(),
            Memory.session_id == session_id.strip()
        ).order_by(Memory.created_at.asc()).limit(limit).all()

    @staticmethod
    def update_memory(
        db: Session,
        memory_id: int,
        tenant_id: str,
        content: Optional[str] = None,
        metadata_payload: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Updates a memory record strictly scoped to tenant_id.
        Fails closed and returns False if record does not belong to tenant_id.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot update memory without a valid tenant_id (CA-008 fail-closed).")

        record = db.query(Memory).filter(
            Memory.id == memory_id,
            Memory.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            return False

        if content is not None:
            record.content = content.strip()
        if metadata_payload is not None:
            record.metadata_payload = metadata_payload

        db.commit()
        db.refresh(record)
        return True

    @staticmethod
    def delete_memory(
        db: Session,
        memory_id: int,
        tenant_id: str
    ) -> bool:
        """
        Deletes a memory record strictly scoped to tenant_id.
        Fails closed and returns False if record does not belong to tenant_id.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot delete memory without a valid tenant_id (CA-008 fail-closed).")

        record = db.query(Memory).filter(
            Memory.id == memory_id,
            Memory.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            return False

        db.delete(record)
        db.commit()
        return True
