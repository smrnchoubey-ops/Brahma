"""
KOSH Knowledge Repository Layer (Whitesheet §4.1 Path 3, §5, §16, §13 / CA-008).
Executes strictly tenant-scoped CRUD and controlled lifecycle state transitions against the PostgreSQL 'knowledge' table.
Fails closed on missing tenant_id or cross-tenant access attempts.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from app.models.knowledge import Knowledge
from app.core.kosh.models import KnowledgeLifecycleState
from app.services.embedding_service import generate_embedding


ALLOWED_TRANSITIONS = {
    KnowledgeLifecycleState.INGESTION.value: [
        KnowledgeLifecycleState.VALIDATION.value,
        KnowledgeLifecycleState.DEPRECATED.value
    ],
    KnowledgeLifecycleState.VALIDATION.value: [
        KnowledgeLifecycleState.CONSTITUTIONAL_REVIEW.value,
        KnowledgeLifecycleState.DEPRECATED.value
    ],
    KnowledgeLifecycleState.CONSTITUTIONAL_REVIEW.value: [
        KnowledgeLifecycleState.ACTIVE.value,
        KnowledgeLifecycleState.DEPRECATED.value
    ],
    KnowledgeLifecycleState.ACTIVE.value: [
        KnowledgeLifecycleState.DEPRECATED.value
    ],
    KnowledgeLifecycleState.DEPRECATED.value: []  # Terminal state
}


class KoshRepository:
    """
    Direct PostgreSQL data access repository for KOSH knowledge and verified facts.
    Every operation strictly enforces tenant boundary isolation and §16 lifecycle transitions.
    """

    @staticmethod
    def store_knowledge(
        db: Session,
        tenant_id: str,
        title: str,
        content: str,
        provenance_source: str = "unspecified",
        source_uri: Optional[str] = None,
        user_id: Optional[int] = None,
        confidence_score: float = 1.0,
        epistemic_status: str = "VERIFIED",
        verification_details: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
        lifecycle_state: str = KnowledgeLifecycleState.INGESTION.value
    ) -> Knowledge:
        """
        Stores an authoritative knowledge item with provenance, verification, and lifecycle metadata.
        Fails closed on missing or empty tenant_id.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot store knowledge without a valid tenant_id (CA-008 fail-closed).")

        if not title or not title.strip() or not content or not content.strip():
            raise ValueError("Invalid Input: Knowledge title and content cannot be empty.")

        # Compute embedding if not supplied
        if embedding is None:
            try:
                embedding = generate_embedding(f"{title}\n{content}")
            except Exception:
                embedding = None

        now_iso = datetime.now(timezone.utc).isoformat()
        initial_history = [{
            "state": lifecycle_state,
            "timestamp": now_iso,
            "action": "ingest",
            "actor": "system"
        }]

        record = Knowledge(
            tenant_id=tenant_id.strip(),
            user_id=user_id,
            title=title.strip(),
            content=content.strip(),
            provenance_source=provenance_source.strip() if provenance_source else "unspecified",
            source_uri=source_uri.strip() if source_uri else None,
            confidence_score=max(0.0, min(1.0, float(confidence_score))),
            epistemic_status=epistemic_status.strip() if epistemic_status else "VERIFIED",
            verification_details=verification_details or {},
            embedding=embedding,
            lifecycle_state=lifecycle_state,
            lifecycle_history=initial_history
        )

        # If created directly with a later lifecycle state (e.g. for legacy or test setup), set timestamps
        if lifecycle_state == KnowledgeLifecycleState.ACTIVE.value:
            record.activated_at = func.now()
            record.constitutional_verdict = "PASSED"

        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def get_knowledge_by_id(
        db: Session,
        knowledge_id: int,
        tenant_id: str
    ) -> Optional[Knowledge]:
        """
        Retrieves a knowledge item by primary key strictly scoped to tenant_id.
        Returns None if record does not exist OR if tenant_id does not match (fail-closed).
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot retrieve knowledge without a valid tenant_id (CA-008 fail-closed).")

        if not knowledge_id or not isinstance(knowledge_id, int) or knowledge_id <= 0:
            return None

        return db.query(Knowledge).filter(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id.strip()
        ).first()

    @staticmethod
    def validate_knowledge(
        db: Session,
        knowledge_id: int,
        tenant_id: str,
        validator: str = "kosh_validator",
        validation_notes: Optional[str] = None
    ) -> Knowledge:
        """
        Transitions knowledge record from INGESTION to VALIDATION (Whitesheet §16 Stage 2).
        Validates completeness, provenance presence, confidence bounds, and epistemic consistency.
        Fails closed on tenant mismatch or invalid state.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot validate knowledge without a valid tenant_id (CA-008 fail-closed).")

        record = db.query(Knowledge).filter(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            raise ValueError(f"Knowledge record {knowledge_id} not found for tenant '{tenant_id}' (fail-closed).")

        if record.lifecycle_state != KnowledgeLifecycleState.INGESTION.value:
            raise ValueError(
                f"Invalid Lifecycle Transition: Cannot advance to VALIDATION from current state '{record.lifecycle_state}'. Must be INGESTION."
            )

        # Validation gate checks (Whitesheet §16 / §5 F4)
        if not record.title or not record.title.strip():
            raise ValueError("Validation Failure: Title cannot be empty.")
        if not record.content or not record.content.strip():
            raise ValueError("Validation Failure: Content cannot be empty.")
        if not record.provenance_source or record.provenance_source.strip() in ("", "unspecified"):
            raise ValueError("Validation Failure: Provenance source is required before validation can pass (CA-001).")
        if record.confidence_score is None or not (0.0 <= record.confidence_score <= 1.0):
            raise ValueError("Validation Failure: Confidence score must be between 0.0 and 1.0.")

        valid_epistemic_statuses = {"VERIFIED", "UNVERIFIED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"}
        if record.epistemic_status not in valid_epistemic_statuses:
            raise ValueError(f"Validation Failure: Epistemic status '{record.epistemic_status}' is invalid.")

        # Update state
        record.lifecycle_state = KnowledgeLifecycleState.VALIDATION.value
        record.validated_at = func.now()

        history = list(record.lifecycle_history or [])
        history.append({
            "state": KnowledgeLifecycleState.VALIDATION.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "validate",
            "validator": validator,
            "notes": validation_notes or "Schema, provenance, and confidence validated."
        })
        record.lifecycle_history = history

        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def constitutional_review(
        db: Session,
        knowledge_id: int,
        tenant_id: str,
        reviewer: str = "maryada_governor",
        verdict: str = "PASSED",
        review_notes: Optional[str] = None
    ) -> Knowledge:
        """
        Performs Constitutional Review transition from VALIDATION to CONSTITUTIONAL_REVIEW (Whitesheet §16 Stage 3).
        Evaluates adherence to constitutional principles (CA-001, CA-005, CA-008, CA-010).
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot perform constitutional review without a valid tenant_id (CA-008 fail-closed).")

        record = db.query(Knowledge).filter(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            raise ValueError(f"Knowledge record {knowledge_id} not found for tenant '{tenant_id}' (fail-closed).")

        if record.lifecycle_state != KnowledgeLifecycleState.VALIDATION.value:
            raise ValueError(
                f"Invalid Lifecycle Transition: Cannot advance to CONSTITUTIONAL_REVIEW from current state '{record.lifecycle_state}'. Must be VALIDATION."
            )

        verdict_clean = verdict.strip().upper()
        if verdict_clean not in ("PASSED", "REJECTED"):
            raise ValueError("Constitutional Review verdict must be either 'PASSED' or 'REJECTED'.")

        # Specific constitutional guardrails
        # CA-001 (Honesty): Contradicted knowledge cannot pass constitutional review for active promotion
        if verdict_clean == "PASSED" and record.epistemic_status == "CONTRADICTED":
            raise ValueError("Constitutional Gate Violation: Contradicted knowledge cannot receive PASSED constitutional verdict (CA-001).")

        # CA-008 (Privacy): Tenant isolation verification
        if not record.tenant_id or not record.tenant_id.strip():
            raise ValueError("Constitutional Gate Violation: Missing tenant isolation boundary (CA-008).")

        record.lifecycle_state = KnowledgeLifecycleState.CONSTITUTIONAL_REVIEW.value
        record.reviewed_at = func.now()
        record.constitutional_verdict = verdict_clean

        history = list(record.lifecycle_history or [])
        history.append({
            "state": KnowledgeLifecycleState.CONSTITUTIONAL_REVIEW.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "constitutional_review",
            "reviewer": reviewer,
            "verdict": verdict_clean,
            "notes": review_notes or f"Constitutional review evaluated with verdict: {verdict_clean}"
        })
        record.lifecycle_history = history

        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def activate_knowledge(
        db: Session,
        knowledge_id: int,
        tenant_id: str,
        activation_notes: Optional[str] = None
    ) -> Knowledge:
        """
        Transitions knowledge record from CONSTITUTIONAL_REVIEW to ACTIVE (Whitesheet §16 Stage 4).
        Only records with PASSED constitutional verdict can become ACTIVE.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot activate knowledge without a valid tenant_id (CA-008 fail-closed).")

        record = db.query(Knowledge).filter(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            raise ValueError(f"Knowledge record {knowledge_id} not found for tenant '{tenant_id}' (fail-closed).")

        if record.lifecycle_state != KnowledgeLifecycleState.CONSTITUTIONAL_REVIEW.value:
            raise ValueError(
                f"Invalid Lifecycle Transition: Cannot advance to ACTIVE from current state '{record.lifecycle_state}'. Must be CONSTITUTIONAL_REVIEW."
            )

        if record.constitutional_verdict != "PASSED":
            raise ValueError(
                f"Constitutional Gate Violation: Knowledge record {knowledge_id} cannot be activated because constitutional verdict is '{record.constitutional_verdict}'. Must be 'PASSED'."
            )

        record.lifecycle_state = KnowledgeLifecycleState.ACTIVE.value
        record.activated_at = func.now()

        history = list(record.lifecycle_history or [])
        history.append({
            "state": KnowledgeLifecycleState.ACTIVE.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "activate",
            "notes": activation_notes or "Knowledge activated for operational citation."
        })
        record.lifecycle_history = history

        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def deprecate_knowledge(
        db: Session,
        knowledge_id: int,
        tenant_id: str,
        reason: str
    ) -> Knowledge:
        """
        Transitions knowledge record to DEPRECATED (Whitesheet §16 Stage 5).
        Preserves durability and audit history; marks deprecated_at and deprecation_reason.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot deprecate knowledge without a valid tenant_id (CA-008 fail-closed).")

        if not reason or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Deprecation Failure: A valid deprecation reason is required (Whitesheet §16).")

        record = db.query(Knowledge).filter(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            raise ValueError(f"Knowledge record {knowledge_id} not found for tenant '{tenant_id}' (fail-closed).")

        if record.lifecycle_state == KnowledgeLifecycleState.DEPRECATED.value:
            raise ValueError(f"Invalid Lifecycle Transition: Knowledge record {knowledge_id} is already DEPRECATED.")

        record.lifecycle_state = KnowledgeLifecycleState.DEPRECATED.value
        record.deprecated_at = func.now()
        record.deprecation_reason = reason.strip()

        history = list(record.lifecycle_history or [])
        history.append({
            "state": KnowledgeLifecycleState.DEPRECATED.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "deprecate",
            "reason": reason.strip()
        })
        record.lifecycle_history = history

        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def transition_lifecycle(
        db: Session,
        knowledge_id: int,
        tenant_id: str,
        target_state: str,
        **kwargs
    ) -> Knowledge:
        """
        Generic state machine transition handler.
        Enforces allowed state transitions and invokes the dedicated transition method.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot transition knowledge without a valid tenant_id (CA-008 fail-closed).")

        record = db.query(Knowledge).filter(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            raise ValueError(f"Knowledge record {knowledge_id} not found for tenant '{tenant_id}' (fail-closed).")

        current_state = record.lifecycle_state
        target_clean = target_state.strip().upper()

        allowed = ALLOWED_TRANSITIONS.get(current_state, [])
        if target_clean not in allowed:
            raise ValueError(
                f"Invalid Lifecycle Transition: Transition from '{current_state}' to '{target_clean}' is not permitted (Whitesheet §16)."
            )

        if target_clean == KnowledgeLifecycleState.VALIDATION.value:
            return KoshRepository.validate_knowledge(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id,
                validator=kwargs.get("validator", "kosh_validator"),
                validation_notes=kwargs.get("validation_notes")
            )
        elif target_clean == KnowledgeLifecycleState.CONSTITUTIONAL_REVIEW.value:
            return KoshRepository.constitutional_review(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id,
                reviewer=kwargs.get("reviewer", "maryada_governor"),
                verdict=kwargs.get("verdict", "PASSED"),
                review_notes=kwargs.get("review_notes")
            )
        elif target_clean == KnowledgeLifecycleState.ACTIVE.value:
            return KoshRepository.activate_knowledge(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id,
                activation_notes=kwargs.get("activation_notes")
            )
        elif target_clean == KnowledgeLifecycleState.DEPRECATED.value:
            return KoshRepository.deprecate_knowledge(
                db=db,
                knowledge_id=knowledge_id,
                tenant_id=tenant_id,
                reason=kwargs.get("reason", "Deprecated via lifecycle transition")
            )
        else:
            raise ValueError(f"Unsupported target lifecycle state: '{target_clean}'")

    @staticmethod
    def query_knowledge(
        db: Session,
        tenant_id: str,
        query_text: Optional[str] = None,
        user_id: Optional[int] = None,
        epistemic_status: Optional[str] = None,
        lifecycle_state: Optional[str] = None,
        active_only: bool = False,
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0
    ) -> List[Knowledge]:
        """
        Queries knowledge items strictly filtered by tenant_id and optional lifecycle state.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot query knowledge without a valid tenant_id (CA-008 fail-closed).")

        query = db.query(Knowledge).filter(
            Knowledge.tenant_id == tenant_id.strip(),
            Knowledge.confidence_score >= min_confidence
        )

        if active_only:
            query = query.filter(Knowledge.lifecycle_state == KnowledgeLifecycleState.ACTIVE.value)
        elif lifecycle_state is not None and lifecycle_state.strip():
            query = query.filter(Knowledge.lifecycle_state == lifecycle_state.strip())

        if user_id is not None:
            query = query.filter(Knowledge.user_id == user_id)

        if epistemic_status is not None and epistemic_status.strip():
            query = query.filter(Knowledge.epistemic_status == epistemic_status.strip())

        if query_text and query_text.strip():
            like_pattern = f"%{query_text.strip()}%"
            query = query.filter(
                (Knowledge.title.ilike(like_pattern)) | (Knowledge.content.ilike(like_pattern))
            )

        return query.order_by(Knowledge.confidence_score.desc(), Knowledge.created_at.desc()).offset(offset).limit(limit).all()

    @staticmethod
    def semantic_search(
        db: Session,
        query_embedding: List[float],
        tenant_id: str,
        user_id: Optional[int] = None,
        top_k: int = 5,
        active_only: bool = False
    ) -> List[Knowledge]:
        """
        Performs pgvector cosine distance search on PostgreSQL strictly scoped to tenant_id.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot perform semantic search without a valid tenant_id (CA-008 fail-closed).")

        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

        base_where = "tenant_id = :tenant_id"
        if active_only:
            base_where += " AND lifecycle_state = 'ACTIVE'"

        if user_id is not None:
            sql = text(f"""
                SELECT id, tenant_id, user_id, title, content, provenance_source, source_uri,
                       confidence_score, epistemic_status, verification_details,
                       lifecycle_state, validated_at, reviewed_at, constitutional_verdict,
                       activated_at, deprecated_at, deprecation_reason, lifecycle_history,
                       created_at, updated_at
                FROM knowledge
                WHERE {base_where} AND (user_id = :user_id OR user_id IS NULL)
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
            """)
            params = {"embedding": embedding_str, "tenant_id": tenant_id.strip(), "user_id": user_id, "top_k": top_k}
        else:
            sql = text(f"""
                SELECT id, tenant_id, user_id, title, content, provenance_source, source_uri,
                       confidence_score, epistemic_status, verification_details,
                       lifecycle_state, validated_at, reviewed_at, constitutional_verdict,
                       activated_at, deprecated_at, deprecation_reason, lifecycle_history,
                       created_at, updated_at
                FROM knowledge
                WHERE {base_where}
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
            """)
            params = {"embedding": embedding_str, "tenant_id": tenant_id.strip(), "top_k": top_k}

        result = db.execute(sql, params)
        rows = result.fetchall()

        items: List[Knowledge] = []
        for r in rows:
            k = Knowledge(
                id=r.id,
                tenant_id=r.tenant_id,
                user_id=r.user_id,
                title=r.title,
                content=r.content,
                provenance_source=r.provenance_source,
                source_uri=r.source_uri,
                confidence_score=r.confidence_score,
                epistemic_status=r.epistemic_status,
                verification_details=r.verification_details,
                lifecycle_state=r.lifecycle_state,
                validated_at=r.validated_at,
                reviewed_at=r.reviewed_at,
                constitutional_verdict=r.constitutional_verdict,
                activated_at=r.activated_at,
                deprecated_at=r.deprecated_at,
                deprecation_reason=r.deprecation_reason,
                lifecycle_history=r.lifecycle_history,
                created_at=r.created_at,
                updated_at=r.updated_at
            )
            items.append(k)

        return items

    @staticmethod
    def update_knowledge(
        db: Session,
        knowledge_id: int,
        tenant_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        confidence_score: Optional[float] = None,
        epistemic_status: Optional[str] = None,
        verification_details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Updates a knowledge item strictly scoped to tenant_id.
        Fails closed and returns False if record does not belong to tenant_id.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot update knowledge without a valid tenant_id (CA-008 fail-closed).")

        record = db.query(Knowledge).filter(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            return False

        if title is not None:
            record.title = title.strip()
        if content is not None:
            record.content = content.strip()
        if confidence_score is not None:
            record.confidence_score = max(0.0, min(1.0, float(confidence_score)))
        if epistemic_status is not None:
            record.epistemic_status = epistemic_status.strip()
        if verification_details is not None:
            record.verification_details = verification_details

        db.commit()
        db.refresh(record)
        return True

    @staticmethod
    def delete_knowledge(
        db: Session,
        knowledge_id: int,
        tenant_id: str
    ) -> bool:
        """
        Deletes a knowledge item strictly scoped to tenant_id.
        Fails closed and returns False if record does not belong to tenant_id.
        """
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: Cannot delete knowledge without a valid tenant_id (CA-008 fail-closed).")

        record = db.query(Knowledge).filter(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id.strip()
        ).first()

        if not record:
            return False

        db.delete(record)
        db.commit()
        return True

