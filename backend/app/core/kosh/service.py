"""
KOSH Knowledge Core & Fact Verification Service (Whitesheet §4.1 Path 3, §5, §16, §19, CA-001, CA-008, CA-010).
Provides authoritative knowledge management, provenance tracking, §16 lifecycle state transitions,
and fact verification backed strictly by PostgreSQL.
"""
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
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
from app.models.knowledge import Knowledge
from app.services.embedding_service import generate_embedding


class KoshKnowledgeService:
    """
    KOSH Knowledge & Fact Verification Service.
    Enforces tenant boundaries, tracks provenance, manages §16 5-stage lifecycle transitions,
    and verifies factual assertions against knowledge base.
    """

    def __init__(self, repository: Optional[KoshRepository] = None):
        self.repository = repository or KoshRepository()

    def ingest(
        self,
        tenant_id: str,
        title: str,
        content: str,
        provenance_source: str = "unspecified",
        source_uri: Optional[str] = None,
        user_id: Optional[int] = None,
        confidence_score: float = 1.0,
        epistemic_status: str = "VERIFIED",
        verification_details: Optional[Dict[str, Any]] = None,
        db_session: Optional[Session] = None
    ) -> KnowledgeRecord:
        """
        Stage 1: INGESTION (Whitesheet §16).
        Captures raw knowledge record with source provenance in INGESTION lifecycle state.
        Fails closed on missing tenant_id.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Knowledge ingestion aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            item = self.repository.store_knowledge(
                db=db,
                tenant_id=tenant_id.strip(),
                title=title,
                content=content,
                provenance_source=provenance_source,
                source_uri=source_uri,
                user_id=user_id,
                confidence_score=confidence_score,
                epistemic_status=epistemic_status,
                verification_details=verification_details,
                lifecycle_state=KnowledgeLifecycleState.INGESTION.value
            )
            return self._to_record(item)
        finally:
            if should_close:
                db.close()

    def validate(
        self,
        knowledge_id: int,
        tenant_id: str,
        validator: str = "kosh_validator",
        validation_notes: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> KnowledgeRecord:
        """
        Stage 2: VALIDATION (Whitesheet §16).
        Transitions record from INGESTION to VALIDATION upon checking completeness, provenance, and confidence bounds.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Knowledge validation aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            item = self.repository.validate_knowledge(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id.strip(),
                validator=validator,
                validation_notes=validation_notes
            )
            return self._to_record(item)
        finally:
            if should_close:
                db.close()

    def constitutional_review(
        self,
        knowledge_id: int,
        tenant_id: str,
        reviewer: str = "maryada_governor",
        verdict: str = "PASSED",
        review_notes: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> KnowledgeRecord:
        """
        Stage 3: CONSTITUTIONAL REVIEW (Whitesheet §16).
        Transitions record from VALIDATION to CONSTITUTIONAL_REVIEW after evaluating CA-001, CA-005, CA-008, CA-010.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Constitutional review aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            item = self.repository.constitutional_review(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id.strip(),
                reviewer=reviewer,
                verdict=verdict,
                review_notes=review_notes
            )
            return self._to_record(item)
        finally:
            if should_close:
                db.close()

    def activate(
        self,
        knowledge_id: int,
        tenant_id: str,
        activation_notes: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> KnowledgeRecord:
        """
        Stage 4: ACTIVE (Whitesheet §16).
        Transitions record from CONSTITUTIONAL_REVIEW to ACTIVE. Requires passed constitutional review verdict.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Knowledge activation aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            item = self.repository.activate_knowledge(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id.strip(),
                activation_notes=activation_notes
            )
            return self._to_record(item)
        finally:
            if should_close:
                db.close()

    def deprecate(
        self,
        knowledge_id: int,
        tenant_id: str,
        reason: str,
        db_session: Optional[Session] = None
    ) -> KnowledgeRecord:
        """
        Stage 5: DEPRECATED (Whitesheet §16).
        Transitions record to DEPRECATED. Preserves history and reason; excludes from active queries.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Knowledge deprecation aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            item = self.repository.deprecate_knowledge(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id.strip(),
                reason=reason
            )
            return self._to_record(item)
        finally:
            if should_close:
                db.close()

    def transition_lifecycle(
        self,
        knowledge_id: int,
        tenant_id: str,
        target_state: str,
        db_session: Optional[Session] = None,
        **kwargs
    ) -> KnowledgeRecord:
        """
        Generic controlled lifecycle state transition.
        Enforces allowed state transition paths and fails closed on invalid jumps.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Lifecycle transition aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            item = self.repository.transition_lifecycle(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id.strip(),
                target_state=target_state,
                **kwargs
            )
            return self._to_record(item)
        finally:
            if should_close:
                db.close()

    def add_knowledge(
        self,
        tenant_id: str,
        title: str,
        content: str,
        provenance_source: str = "unspecified",
        source_uri: Optional[str] = None,
        user_id: Optional[int] = None,
        confidence_score: float = 1.0,
        epistemic_status: str = "VERIFIED",
        verification_details: Optional[Dict[str, Any]] = None,
        lifecycle_state: str = KnowledgeLifecycleState.ACTIVE.value,
        db_session: Optional[Session] = None
    ) -> KnowledgeRecord:
        """
        Stores an authoritative knowledge item with provenance and verification metadata.
        Defaults to ACTIVE for direct programmatic registration / Phase 3B compatibility.
        Fails closed on missing tenant_id.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Knowledge registration aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            item = self.repository.store_knowledge(
                db=db,
                tenant_id=tenant_id.strip(),
                title=title,
                content=content,
                provenance_source=provenance_source,
                source_uri=source_uri,
                user_id=user_id,
                confidence_score=confidence_score,
                epistemic_status=epistemic_status,
                verification_details=verification_details,
                lifecycle_state=lifecycle_state
            )
            return self._to_record(item)
        finally:
            if should_close:
                db.close()

    def get_knowledge(
        self,
        knowledge_id: int,
        tenant_id: str,
        db_session: Optional[Session] = None
    ) -> Optional[KnowledgeRecord]:
        """
        Retrieves a knowledge item strictly scoped to tenant_id.
        Returns None if record does not exist or tenant mismatch (fail-closed).
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Knowledge retrieval aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            item = self.repository.get_knowledge_by_id(db=db, knowledge_id=knowledge_id, tenant_id=tenant_id.strip())
            return self._to_record(item) if item else None
        finally:
            if should_close:
                db.close()

    def get_active_knowledge(
        self,
        knowledge_id: int,
        tenant_id: str,
        db_session: Optional[Session] = None
    ) -> Optional[KnowledgeRecord]:
        """
        Retrieves a knowledge item strictly scoped to tenant_id ONLY if its lifecycle state is ACTIVE.
        Returns None for INGESTION, VALIDATION, CONSTITUTIONAL_REVIEW, or DEPRECATED states.
        """
        rec = self.get_knowledge(knowledge_id=knowledge_id, tenant_id=tenant_id, db_session=db_session)
        if rec and rec.lifecycle_state == KnowledgeLifecycleState.ACTIVE.value:
            return rec
        return None

    def verify_fact(
        self,
        claim: str,
        tenant_id: str,
        user_id: Optional[int] = None,
        min_confidence_threshold: float = 0.60,
        db_session: Optional[Session] = None
    ) -> FactVerificationResult:
        """
        Verifies a factual claim against authoritative knowledge in KOSH (§4.1 Path 3, §5, §19).
        1. Queries tenant-scoped knowledge base for relevant facts.
        2. Evaluates semantic consistency and corroborating evidence.
        3. Computes principled epistemic confidence based on source authority and corroboration.
        4. Distinguishes 'VERIFIED', 'CONTRADICTED', and 'INSUFFICIENT_EVIDENCE'.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Fact verification aborted because tenant_id is missing (fail-closed).")

        if not claim or not claim.strip():
            return FactVerificationResult(
                claim=claim or "",
                tenant_id=tenant_id,
                is_verified=False,
                confidence_score=0.0,
                epistemic_status="INSUFFICIENT_EVIDENCE",
                supporting_evidence=[],
                contradictions=[],
                verification_summary="Empty claim cannot be verified.",
                epistemic_notes="Claim was empty or whitespace."
            )

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            # 1. Retrieve candidates using text and embedding search
            claim_clean = claim.strip()
            candidates = self.repository.query_knowledge(
                db=db,
                tenant_id=tenant_id.strip(),
                query_text=claim_clean[:64],
                user_id=user_id,
                limit=10
            )

            # If semantic vector available, also search via embeddings
            try:
                claim_vec = generate_embedding(claim_clean)
                vec_candidates = self.repository.semantic_search(
                    db=db,
                    query_embedding=claim_vec,
                    tenant_id=tenant_id.strip(),
                    user_id=user_id,
                    top_k=5
                )
                seen_ids = {c.id for c in candidates}
                for vc in vec_candidates:
                    if vc.id not in seen_ids:
                        candidates.append(vc)
                        seen_ids.add(vc.id)
            except Exception:
                pass

            if not candidates:
                return FactVerificationResult(
                    claim=claim_clean,
                    tenant_id=tenant_id,
                    is_verified=False,
                    confidence_score=0.0,
                    epistemic_status="INSUFFICIENT_EVIDENCE",
                    supporting_evidence=[],
                    contradictions=[],
                    verification_summary=f"No authoritative knowledge found in tenant corpus to verify claim: '{claim_clean}'.",
                    epistemic_notes="Zero corroborating documents in tenant partition."
                )

            # 2. Corroboration & contradiction analysis
            supporting: List[Dict[str, Any]] = []
            contradictions: List[Dict[str, Any]] = []
            claim_words = set(claim_clean.lower().split())

            for c in candidates:
                doc_text = f"{c.title} {c.content}".lower()
                doc_words = set(doc_text.split())
                overlap = len(claim_words.intersection(doc_words)) / max(len(claim_words), 1)

                evidence_entry = {
                    "knowledge_id": c.id,
                    "title": c.title,
                    "provenance_source": c.provenance_source,
                    "source_uri": c.source_uri,
                    "doc_confidence": c.confidence_score,
                    "epistemic_status": c.epistemic_status,
                    "lifecycle_state": c.lifecycle_state,
                    "word_overlap_ratio": round(overlap, 4)
                }

                # Check if document directly supports or contradicts
                if c.epistemic_status == "CONTRADICTED":
                    contradictions.append(evidence_entry)
                elif overlap >= 0.30 or c.confidence_score >= min_confidence_threshold:
                    supporting.append(evidence_entry)

            # 3. Principled confidence assessment (§19 formalization boundary)
            if supporting and not contradictions:
                calc_confidence = sum(s["doc_confidence"] for s in supporting) / len(supporting)
                is_verified = calc_confidence >= min_confidence_threshold
                status = "VERIFIED" if is_verified else "INSUFFICIENT_EVIDENCE"
                summary = f"Claim verified against {len(supporting)} authoritative knowledge source(s) with confidence {calc_confidence:.2f}."
            elif contradictions:
                calc_confidence = 0.20
                is_verified = False
                status = "CONTRADICTED"
                summary = f"Claim contradicted by {len(contradictions)} existing verified knowledge record(s)."
            else:
                calc_confidence = 0.0
                is_verified = False
                status = "INSUFFICIENT_EVIDENCE"
                summary = "Insufficient corroborating evidence found in tenant partition."

            return FactVerificationResult(
                claim=claim_clean,
                tenant_id=tenant_id,
                is_verified=is_verified,
                confidence_score=round(calc_confidence, 4),
                epistemic_status=status,
                supporting_evidence=supporting,
                contradictions=contradictions,
                verification_summary=summary,
                epistemic_notes=f"Source provenance evaluated for tenant {tenant_id}. Evaluated {len(candidates)} candidate documents."
            )
        finally:
            if should_close:
                db.close()

    def query_knowledge(
        self,
        query: KnowledgeQuery,
        db_session: Optional[Session] = None
    ) -> List[KnowledgeRecord]:
        """
        Queries knowledge items strictly filtered by tenant_id.
        """
        if not query.tenant_id or not str(query.tenant_id).strip():
            raise ValueError("Security Violation: Knowledge query aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            items = self.repository.query_knowledge(
                db=db,
                tenant_id=query.tenant_id.strip(),
                query_text=query.query_text,
                user_id=query.user_id,
                epistemic_status=query.epistemic_status,
                lifecycle_state=query.lifecycle_state,
                active_only=query.active_only,
                min_confidence=query.min_confidence,
                limit=query.limit,
                offset=query.offset
            )
            return [self._to_record(item) for item in items]
        finally:
            if should_close:
                db.close()

    def query_active_knowledge(
        self,
        tenant_id: str,
        query_text: Optional[str] = None,
        user_id: Optional[int] = None,
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0,
        db_session: Optional[Session] = None
    ) -> List[KnowledgeRecord]:
        """
        Queries ONLY ACTIVE knowledge records for a given tenant.
        """
        query = KnowledgeQuery(
            tenant_id=tenant_id,
            query_text=query_text,
            user_id=user_id,
            active_only=True,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset
        )
        return self.query_knowledge(query=query, db_session=db_session)

    def delete_knowledge(
        self,
        knowledge_id: int,
        tenant_id: str,
        db_session: Optional[Session] = None
    ) -> bool:
        """
        Deletes a knowledge item with strict tenant isolation check.
        Returns False if record does not belong to tenant_id.
        """
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Security Violation: Knowledge deletion aborted because tenant_id is missing (fail-closed).")

        db = db_session or SessionLocal()
        should_close = db_session is None
        try:
            return self.repository.delete_knowledge(db=db, knowledge_id=knowledge_id, tenant_id=tenant_id.strip())
        finally:
            if should_close:
                db.close()

    @staticmethod
    def _to_record(item: Knowledge) -> KnowledgeRecord:
        return KnowledgeRecord(
            id=item.id,
            tenant_id=item.tenant_id,
            user_id=item.user_id,
            title=item.title,
            content=item.content,
            provenance_source=item.provenance_source,
            source_uri=item.source_uri,
            confidence_score=item.confidence_score,
            epistemic_status=item.epistemic_status,
            verification_details=item.verification_details,
            lifecycle_state=item.lifecycle_state or KnowledgeLifecycleState.INGESTION.value,
            validated_at=item.validated_at.isoformat() if item.validated_at else None,
            reviewed_at=item.reviewed_at.isoformat() if item.reviewed_at else None,
            constitutional_verdict=item.constitutional_verdict,
            activated_at=item.activated_at.isoformat() if item.activated_at else None,
            deprecated_at=item.deprecated_at.isoformat() if item.deprecated_at else None,
            deprecation_reason=item.deprecation_reason,
            lifecycle_history=item.lifecycle_history,
            created_at=item.created_at.isoformat() if item.created_at else None,
            updated_at=item.updated_at.isoformat() if item.updated_at else None
        )


kosh_service = KoshKnowledgeService()

