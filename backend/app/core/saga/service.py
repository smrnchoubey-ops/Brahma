"""
SAGA Service: High-Level Workflow Management
Strictly conforms to BRAHMA COS Whitesheet §14.0 & §14.6.
"""
from typing import Dict, Any, Optional, List, Callable
from sqlalchemy.orm import Session

from app.core.saga.models import SagaDefinition, SagaStep, SagaStatus, SagaExecutionReport
from app.core.saga.executor import SagaExecutor
from app.core.chitra.crypto import generate_ulid


class SagaService:
    """
    High-level facade for creating and executing Sagas.
    """

    @classmethod
    def create_saga(
        cls,
        task_id: int,
        tenant_id: str,
        summary: str,
        steps: List[SagaStep],
        metadata: Optional[Dict[str, Any]] = None
    ) -> SagaDefinition:
        """
        Initializes a new formal Saga definition.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Authenticated Tenant ID is required to create a Saga.")

        saga_id = generate_ulid(prefix="saga_")
        return SagaDefinition(
            saga_id=saga_id,
            task_id=task_id,
            tenant_id=tenant_id,
            summary=summary,
            status=SagaStatus.PENDING,
            steps=steps,
            metadata=metadata or {}
        )

    @classmethod
    def execute(
        cls,
        saga: SagaDefinition,
        action_dispatcher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        compensation_dispatcher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> SagaExecutionReport:
        """
        Runs the Saga workflow through the executor.
        """
        return SagaExecutor.execute_saga(
            saga=saga,
            action_dispatcher=action_dispatcher,
            compensation_dispatcher=compensation_dispatcher,
            db_session=db_session,
            user_id=user_id,
            session_id=session_id
        )
