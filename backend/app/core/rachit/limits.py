"""
RACHIT Resource Quotas & Execution Result Schemas
Strictly conforms to BRAHMA COS Whitesheet §13.2, §13.3 & §13.6.
"""
from typing import Dict, Any, Optional
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class SandboxStatus(str, Enum):
    SUCCESS = "SUCCESS"
    TIMEOUT_EXCEEDED = "TIMEOUT_EXCEEDED"
    MEMORY_EXCEEDED = "MEMORY_EXCEEDED"
    OUTPUT_EXCEEDED = "OUTPUT_EXCEEDED"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    BLOCKED = "BLOCKED"


class ExecutionQuotas(BaseModel):
    """
    Resource limits and execution bounds for a sandboxed tool invocation.
    Matches Whitesheet §13.2 & §13.3.
    """
    timeout_ms: int = Field(default=5000, ge=10, le=60000, description="Hard execution timeout in milliseconds")
    max_memory_mb: int = Field(default=128, ge=16, le=2048, description="Memory footprint quota in megabytes")
    max_output_bytes: int = Field(default=65536, ge=1024, le=10485760, description="Maximum output buffer size in bytes")
    allow_network: bool = Field(default=False, description="Out-of-band network access permission")
    max_workspace_files: int = Field(default=100, description="Max files allowed in sandbox workspace")


class SandboxExecutionResult(BaseModel):
    """
    Structured execution outcome returned by the RACHIT sandbox runtime.
    Matches Whitesheet §13.6.
    """
    status: SandboxStatus
    tool_id: str
    action_name: str
    output: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    memory_used_mb: float = 0.0
    exit_code: int = 0
    output_hash: Optional[str] = None
    chitra_event_id: Optional[str] = None
    executed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
