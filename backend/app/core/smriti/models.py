"""
SMRITI Data Models (Whitesheet §5 F5 Temporal Memory, §4.1 Path 2, §13 / CA-008).
Defines structured records and payloads for SMRITI conversational/episodic memory operations.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class SmritiRecord(BaseModel):
    """
    Pydantic representation of a persistent SMRITI memory record.
    Enforces tenant scoping, session linkage, and metadata auditability.
    """
    id: int
    tenant_id: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    task_id: Optional[int] = None
    memory_type: str = "conversation"
    content: str
    source: str = "user"
    approved: str = "APPROVED"
    metadata_payload: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)



class SmritiWriteRequest(BaseModel):
    """
    Input payload for creating or appending memory in SMRITI.
    """
    content: str
    tenant_id: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    task_id: Optional[int] = None
    memory_type: str = "conversation"
    source: str = "user"
    approved: str = "APPROVED"
    metadata_payload: Optional[Dict[str, Any]] = None


class SmritiQuery(BaseModel):
    """
    Input query parameters for retrieving memory from SMRITI.
    Strictly requires tenant_id.
    """
    tenant_id: str
    session_id: Optional[str] = None
    user_id: Optional[int] = None
    task_id: Optional[int] = None
    memory_type: Optional[str] = None
    limit: int = 50
    offset: int = 0
