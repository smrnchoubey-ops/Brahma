"""
SAGA Distributed Rollback & Compensating Transactions: Data Models
Strictly conforms to BRAHMA COS Whitesheet §14.0–§14.6.
"""
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class SagaStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    ABORTED = "ABORTED"


class SagaStepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    SKIPPED = "SKIPPED"
    ABORTED = "ABORTED"


class SagaStep(BaseModel):
    """
    Independent unit of work within a Saga with forward and compensating action declarations.
    """
    step_id: str
    forward_action: str
    compensating_action: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    status: SagaStepStatus = SagaStepStatus.PENDING
    forward_output: Optional[Any] = None
    forward_error: Optional[str] = None
    compensation_output: Optional[Any] = None
    compensation_error: Optional[str] = None
    executed_at: Optional[str] = None
    compensated_at: Optional[str] = None
    compensation_attempts: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SagaDefinition(BaseModel):
    """
    Formal Saga specification containing ordered / DAG-structured steps.
    """
    saga_id: str
    task_id: int
    tenant_id: str
    summary: str
    status: SagaStatus = SagaStatus.PENDING
    steps: List[SagaStep] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SagaCompensationRecord(BaseModel):
    """
    Structured audit evidence for a single step compensation attempt.
    """
    saga_id: str
    task_id: int
    tenant_id: str
    step_id: str
    forward_action: str
    compensating_action: str
    status: str  # "COMPENSATED" | "COMPENSATION_FAILED"
    result: Optional[Any] = None
    error: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    chitra_event_id: Optional[str] = None


class SagaExecutionReport(BaseModel):
    """
    Final outcome of a Saga execution including forward progress and rollback evidence.
    """
    saga_id: str
    task_id: int
    tenant_id: str
    status: SagaStatus
    steps_completed: List[str] = Field(default_factory=list)
    steps_compensated: List[str] = Field(default_factory=list)
    compensation_failures: List[str] = Field(default_factory=list)
    compensation_records: List[SagaCompensationRecord] = Field(default_factory=list)
    error: Optional[str] = None
    duration_ms: float = 0.0
    executed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
