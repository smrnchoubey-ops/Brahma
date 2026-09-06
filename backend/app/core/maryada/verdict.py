"""
MARYADA Policy Verdict & Tier Schemas
Strictly conforms to BRAHMA COS Whitesheet §10.1 & §10.4.
"""
from typing import Dict, Any, Optional, List
from enum import Enum
from pydantic import BaseModel, Field


class AuthorityTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class GateStatus(str, Enum):
    APPROVED = "MARYADA_APPROVED"
    BLOCKED = "MARYADA_BLOCKED"
    HUMAN_REVIEW_REQUIRED = "MARYADA_HUMAN_REVIEW_REQUIRED"


class MaryadaVerdict(BaseModel):
    """
    Structured, machine-readable constitutional governance verdict.
    Matches Whitesheet §10.4.
    """
    approved: bool
    status: GateStatus
    risk_tier: RiskTier
    authority_required: AuthorityTier
    caller_authority: Optional[str] = None
    requires_human: bool = False
    justification: str
    policy_id: Optional[str] = "GOV-CONST-BASE"
    violated_invariants: List[str] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    chitra_event_id: Optional[str] = None
