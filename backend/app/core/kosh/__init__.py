"""
KOSH Knowledge Core Package (Whitesheet §4.1 Path 3, §5, §16, §19, CA-001, CA-008, CA-010).
Authoritative core module for KOSH knowledge management, provenance tracking, and fact verification.
"""
from app.core.kosh.models import (
    KnowledgeRecord,
    KnowledgeCreateRequest,
    KnowledgeLifecycleState,
    ValidationRequest,
    ConstitutionalReviewRequest,
    ActivationRequest,
    DeprecationRequest,
    FactVerificationRequest,
    FactVerificationResult,
    KnowledgeQuery
)
from app.core.kosh.repository import KoshRepository
from app.core.kosh.service import KoshKnowledgeService, kosh_service

# Legacy compatibility exports for test harness references
from app.core.kosh.memory_tiers import MemoryTier, KoshChunk
from app.core.kosh.vector_engine import (
    compute_cosine_similarity,
    generate_deterministic_test_embedding,
    KoshVectorStore
)
from app.core.kosh.episodic_handoff import (
    KoshEpisodicHandoffController,
    KoshEpisodicHandoffResult
)
from app.core.kosh.retrieval_service import (
    KoshRetrievalService,
    KoshRetrievalResult
)

__all__ = [
    # Authoritative Phase 3B/3C KOSH interfaces
    "KnowledgeRecord",
    "KnowledgeCreateRequest",
    "KnowledgeLifecycleState",
    "ValidationRequest",
    "ConstitutionalReviewRequest",
    "ActivationRequest",
    "DeprecationRequest",
    "FactVerificationRequest",
    "FactVerificationResult",
    "KnowledgeQuery",
    "KoshRepository",
    "KoshKnowledgeService",
    "kosh_service",
    # Legacy compatibility interfaces
    "MemoryTier",
    "KoshChunk",
    "compute_cosine_similarity",
    "generate_deterministic_test_embedding",
    "KoshVectorStore",
    "KoshEpisodicHandoffController",
    "KoshEpisodicHandoffResult",
    "KoshRetrievalService",
    "KoshRetrievalResult"
]
