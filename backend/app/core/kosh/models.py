"""
KOSH Knowledge Core Data Models (Whitesheet §4.1 Path 3, §5, §16, §19, CA-001, CA-008).
Defines structured records, provenance metadata, fact-verification requests, and epistemic verdict schemas.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


class KnowledgeLifecycleState(str, Enum):
    """
    Controlled lifecycle states for KOSH knowledge records (Whitesheet §16).
    1. INGESTION: Raw input captured with source provenance.
    2. VALIDATION: Verified schema completeness, tenant isolation, and semantic integrity.
    3. CONSTITUTIONAL_REVIEW: Evaluated against constitutional principles (CA-001, CA-005, CA-008, CA-010).
    4. ACTIVE: Fully authoritative knowledge eligible for reasoning and runtime citation.
    5. DEPRECATED: Retired or superseded knowledge; preserved for audit durability but excluded from active queries.
    """
    INGESTION = "INGESTION"
    VALIDATION = "VALIDATION"
    CONSTITUTIONAL_REVIEW = "CONSTITUTIONAL_REVIEW"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class KnowledgeRecord(BaseModel):
    """
    Pydantic representation of an authoritative knowledge item in KOSH.
    Explicitly tracks lifecycle state, provenance, confidence score, and epistemic verification state.
    """
    id: int
    tenant_id: str
    user_id: Optional[int] = None
    title: str
    content: str
    provenance_source: str = "unspecified"
    source_uri: Optional[str] = None
    confidence_score: float = 1.0
    epistemic_status: str = "VERIFIED"
    verification_details: Optional[Dict[str, Any]] = None
    lifecycle_state: str = KnowledgeLifecycleState.INGESTION.value
    validated_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    constitutional_verdict: Optional[str] = None
    activated_at: Optional[str] = None
    deprecated_at: Optional[str] = None
    deprecation_reason: Optional[str] = None
    lifecycle_history: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class KnowledgeCreateRequest(BaseModel):
    """
    Input schema for registering knowledge into KOSH with provenance and initial verification state.
    """
    tenant_id: str
    title: str
    content: str
    provenance_source: str = "unspecified"
    source_uri: Optional[str] = None
    user_id: Optional[int] = None
    confidence_score: float = 1.0
    epistemic_status: str = "VERIFIED"
    verification_details: Optional[Dict[str, Any]] = None
    lifecycle_state: Optional[str] = KnowledgeLifecycleState.INGESTION.value


class ValidationRequest(BaseModel):
    """
    Input schema for advancing a knowledge record from INGESTION to VALIDATION.
    """
    knowledge_id: int
    tenant_id: str
    validation_notes: Optional[str] = None
    validator: str = "kosh_validator"


class ConstitutionalReviewRequest(BaseModel):
    """
    Input schema for advancing a knowledge record from VALIDATION to CONSTITUTIONAL_REVIEW.
    """
    knowledge_id: int
    tenant_id: str
    reviewer: str = "maryada_governor"
    verdict: str = "PASSED"
    review_notes: Optional[str] = None


class ActivationRequest(BaseModel):
    """
    Input schema for advancing a knowledge record from CONSTITUTIONAL_REVIEW to ACTIVE.
    """
    knowledge_id: int
    tenant_id: str
    activation_notes: Optional[str] = None


class DeprecationRequest(BaseModel):
    """
    Input schema for deprecating knowledge records.
    """
    knowledge_id: int
    tenant_id: str
    reason: str


class FactVerificationRequest(BaseModel):
    """
    Input schema for requesting fact/claim verification against KOSH knowledge base.
    """
    claim: str
    tenant_id: str
    context_hint: Optional[str] = None
    min_confidence_threshold: float = 0.60


class FactVerificationResult(BaseModel):
    """
    Structured outcome of a KOSH fact verification operation.
    Reports verification status, calculated epistemic confidence, supporting evidence,
    detected contradictions, and explicit verification caveats (Whitesheet §19, CA-001, CA-010).
    """
    claim: str
    tenant_id: str
    is_verified: bool
    confidence_score: float
    epistemic_status: str = Field(description="'VERIFIED' | 'UNVERIFIED' | 'CONTRADICTED' | 'INSUFFICIENT_EVIDENCE'")
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    verification_summary: str
    epistemic_notes: Optional[str] = None


class KnowledgeQuery(BaseModel):
    """
    Query schema for tenant-scoped knowledge search and retrieval.
    """
    tenant_id: str
    query_text: Optional[str] = None
    user_id: Optional[int] = None
    epistemic_status: Optional[str] = None
    lifecycle_state: Optional[str] = None
    active_only: bool = False
    min_confidence: float = 0.0
    limit: int = 50
    offset: int = 0
