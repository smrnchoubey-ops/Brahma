"""
KOSH Multi-Tier Memory Hierarchy Models
Strictly conforms to BRAHMA COS Whitesheet §9.1, §9.2 & §9.6.

Defines:
- Tier 1: Active Working Context
- Tier 2: Episodic Task Memory (Indexed from verified KARMA plans)
- Tier 3: Semantic Corporate Store (Persistent domain knowledge)
"""
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class MemoryTier(str, Enum):
    WORKING_CONTEXT = "WORKING_CONTEXT"
    EPISODIC = "EPISODIC"
    SEMANTIC_STORE = "SEMANTIC_STORE"


class KoshChunk(BaseModel):
    """
    Unified knowledge and memory chunk record across all tiers.
    Matches Whitesheet §9.1, §9.2 & §9.6.
    """
    chunk_id: str
    tenant_id: str
    title: str
    content: str
    tier: MemoryTier = MemoryTier.SEMANTIC_STORE
    version: int = 1
    is_tombstoned: bool = False
    task_id: Optional[int] = None
    step_id: Optional[str] = None
    audit_trail_refs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
