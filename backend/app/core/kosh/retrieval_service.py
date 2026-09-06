"""
KOSH Multi-Tier Retrieval Service & CHITRA Audit Integration
Strictly conforms to BRAHMA COS Whitesheet §9.4, §9.5 & §9.7.

Coordinates vector queries, dynamic similarity thresholding, Top-K ranking,
multi-tenant isolation, and canonical CHITRA retrieval audit logging.
"""
from typing import Dict, Any, Optional, List, Tuple
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.kosh.memory_tiers import KoshChunk, MemoryTier
from app.core.kosh.vector_engine import KoshVectorStore, generate_deterministic_test_embedding
from app.repositories.chitra_repository import chitra_repository


class KoshRetrievalResult(BaseModel):
    """
    Structured outcome of a KOSH semantic retrieval operation.
    Matches Whitesheet §9.5 & §9.7.
    """
    query: str
    tenant_id: str
    results_count: int
    chunks: List[Dict[str, Any]]
    confidence_score: float
    chitra_event_id: Optional[str] = None
    evaluated_candidates_count: int = 0


class KoshRetrievalService:
    """
    KOSH Semantic Retrieval Engine with multi-tier filtering and CHITRA audit integration.
    """
    def __init__(
        self,
        vector_store: Optional[KoshVectorStore] = None,
        embedding_fn: Optional[callable] = None
    ):
        self.vector_store = vector_store or KoshVectorStore()
        self.embedding_fn = embedding_fn or generate_deterministic_test_embedding

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        min_similarity: float = 0.70,
        tier_filter: Optional[List[MemoryTier]] = None,
        db_session: Optional[Session] = None,
        task_id: Optional[int] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> KoshRetrievalResult:
        """
        Executes tenant-isolated semantic retrieval and records CHITRA audit event.
        """
        if not query or not query.strip():
            return KoshRetrievalResult(
                query=query,
                tenant_id=tenant_id,
                results_count=0,
                chunks=[],
                confidence_score=0.0
            )

        if not tenant_id or not tenant_id.strip():
            raise ValueError("Tenant ID is required for tenant-scoped retrieval.")

        # 1. Generate query embedding (§9.1)
        query_vec = self.embedding_fn(query)

        # 2. Query Vector Store (§9.4, §9.5, §9.6)
        matched_items = self.vector_store.query(
            query_vector=query_vec,
            tenant_id=tenant_id,
            top_k=top_k,
            min_similarity=min_similarity,
            tier_filter=tier_filter
        )

        formatted_chunks: List[Dict[str, Any]] = []
        chunk_refs: List[str] = []
        for chunk, score in matched_items:
            chunk_refs.append(chunk.chunk_id)
            formatted_chunks.append({
                "chunk_id": chunk.chunk_id,
                "title": chunk.title,
                "content": chunk.content,
                "tier": chunk.tier.value,
                "similarity_score": round(score, 4),
                "audit_trail_refs": chunk.audit_trail_refs,
                "metadata": chunk.metadata
            })

        avg_confidence = (
            sum(item[1] for item in matched_items) / len(matched_items)
            if matched_items else 0.0
        )

        # 3. Append CHITRA Retrieval Audit Event (§9.7, §8.2)
        chitra_event_id: Optional[str] = None
        if db_session and task_id:
            try:
                chitra_evt = chitra_repository.append_event(
                    db=db_session,
                    task_id=task_id,
                    faculty="KOSH",
                    event_type="retrieval",
                    decision={
                        "query": query,
                        "tenant_id": tenant_id,
                        "top_k": top_k,
                        "min_similarity": min_similarity,
                        "results_count": len(formatted_chunks),
                        "retrieved_chunk_ids": chunk_refs
                    },
                    confidence=round(avg_confidence, 4) if avg_confidence > 0 else 1.0,
                    outcome=f"Retrieved {len(formatted_chunks)} chunks for query: '{query}'",
                    session_id=session_id or f"ses_kosh_{task_id}",
                    user_id=user_id
                )
                chitra_event_id = chitra_evt.event_id
            except Exception:
                pass

        return KoshRetrievalResult(
            query=query,
            tenant_id=tenant_id,
            results_count=len(formatted_chunks),
            chunks=formatted_chunks,
            confidence_score=round(avg_confidence, 4),
            chitra_event_id=chitra_event_id,
            evaluated_candidates_count=len(self.vector_store._chunks)
        )
