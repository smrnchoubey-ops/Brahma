"""
MANUSH Human Oversight Decision & Review Item Schemas
Strictly conforms to BRAHMA COS Whitesheet §12.1 & §12.4.
"""
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED_BY_HUMAN = "APPROVED_BY_HUMAN"
    REJECTED_BY_HUMAN = "REJECTED_BY_HUMAN"
    AMENDED_BY_HUMAN = "AMENDED_BY_HUMAN"
    TERMINATED_BY_HUMAN = "TERMINATED_BY_HUMAN"
    DELEGATED_BY_HUMAN = "DELEGATED_BY_HUMAN"
    TIMEOUT_EXPIRED = "TIMEOUT_EXPIRED"


class ReviewDecisionType(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    AMEND = "AMEND"
    TERMINATE = "TERMINATE"
    DELEGATE = "DELEGATE"


class HumanReviewDecision(BaseModel):
    """
    Structured submission of a human reviewer's verdict.
    Matches Whitesheet §12.4.
    """
    reviewer_id: str
    decision: ReviewDecisionType
    justification: str
    signature: str
    amended_action: Optional[str] = None
    amended_parameters: Optional[Dict[str, Any]] = None
    delegate_id: Optional[str] = None
    delegated_scope: Optional[List[str]] = None
    delegated_authority_tier: Optional[str] = None
    delegation_expiry: Optional[str] = None
    reviewed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReviewItem(BaseModel):
    """
    Escalated task / step representation in the human review queue.
    Matches Whitesheet §12.1.
    """
    review_id: str
    task_id: int
    tenant_id: str
    step_id: Optional[str] = None
    action_summary: str
    original_action: Optional[str] = None
    original_parameters: Optional[Dict[str, Any]] = None
    amended_action: Optional[str] = None
    amended_parameters: Optional[Dict[str, Any]] = None
    delegate_id: Optional[str] = None
    delegated_scope: Optional[List[str]] = None
    delegated_authority_tier: Optional[str] = None
    delegation_expiry: Optional[str] = None
    risk_tier: str = "HIGH"
    requires_dual_auth: bool = False
    status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    approvals: List[HumanReviewDecision] = Field(default_factory=list)
    rejections: List[HumanReviewDecision] = Field(default_factory=list)
    amendments: List[HumanReviewDecision] = Field(default_factory=list)
    terminations: List[HumanReviewDecision] = Field(default_factory=list)
    delegations: List[HumanReviewDecision] = Field(default_factory=list)
    final_justification: Optional[str] = None
    chitra_event_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


