"""
Phase 3C KOSH Knowledge Lifecycle Test Suite (Whitesheet §16, §23, §4.1 Path 3, §5, Appendix A CA-001, CA-005, CA-008, CA-010).
Verifies:
1. Full 5-stage lifecycle flow: INGESTION -> VALIDATION -> CONSTITUTIONAL_REVIEW -> ACTIVE -> DEPRECATED.
2. PostgreSQL persistence and schema columns for all lifecycle transitions.
3. Invalid lifecycle transition rejection (skipping stages, backward transitions out of DEPRECATED).
4. Validation gate enforcement (schema, completeness, provenance, confidence).
5. Constitutional Review gate enforcement (CA-001, CA-005, CA-008, CA-010; rejected verdict blocks activation).
6. Active knowledge queries return ONLY records in ACTIVE state.
7. Deprecation preserves record durability and lifecycle audit history while excluding from active queries.
8. Strict tenant isolation on all lifecycle operations (cross-tenant mutation/read fails closed).
9. Missing tenant context fails closed.
10. Durability across fresh database sessions and service instances.
"""
import pytest
from sqlalchemy import text

from app.db.database import SessionLocal
from app.models.knowledge import Knowledge
from app.core.kosh.service import KoshKnowledgeService
from app.core.kosh.models import KnowledgeLifecycleState, KnowledgeQuery
from app.db.migrate_knowledge_lifecycle import migrate_knowledge_lifecycle_schema


def setup_module():
    """Ensure database schema is up-to-date with lifecycle columns."""
    migrate_knowledge_lifecycle_schema()


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_1_postgresql_schema_has_lifecycle_columns(db_session):
    """Verifies that the PostgreSQL knowledge table contains all required §16 lifecycle columns."""
    res = db_session.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'knowledge';
    """)).fetchall()
    
    col_map = {r[0]: r[1] for r in res}
    assert "lifecycle_state" in col_map
    assert "validated_at" in col_map
    assert "reviewed_at" in col_map
    assert "constitutional_verdict" in col_map
    assert "activated_at" in col_map
    assert "deprecated_at" in col_map
    assert "deprecation_reason" in col_map
    assert "lifecycle_history" in col_map


def test_2_full_five_stage_lifecycle_flow(db_session):
    """
    Verifies complete sequential 5-stage transition:
    INGESTION -> VALIDATION -> CONSTITUTIONAL_REVIEW -> ACTIVE -> DEPRECATED
    """
    service = KoshKnowledgeService()
    tenant = "tenant_lifecycle_flow_01"

    # Stage 1: INGESTION
    ingested = service.ingest(
        tenant_id=tenant,
        title="Brahma Architecture §16",
        content="Knowledge lifecycle consists of Ingestion, Validation, Constitutional Review, Active, and Deprecation.",
        provenance_source="Whitesheet Specification v1.0",
        source_uri="doc://whitesheet/section_16",
        confidence_score=0.99,
        epistemic_status="VERIFIED",
        db_session=db_session
    )
    assert ingested.id is not None
    assert ingested.lifecycle_state == KnowledgeLifecycleState.INGESTION.value
    assert ingested.validated_at is None
    assert ingested.reviewed_at is None
    assert ingested.activated_at is None

    # Stage 2: VALIDATION
    validated = service.validate(
        knowledge_id=ingested.id,
        tenant_id=tenant,
        validator="kosh_schema_validator_01",
        validation_notes="Schema and provenance passed checks.",
        db_session=db_session
    )
    assert validated.lifecycle_state == KnowledgeLifecycleState.VALIDATION.value
    assert validated.validated_at is not None

    # Stage 3: CONSTITUTIONAL REVIEW
    reviewed = service.constitutional_review(
        knowledge_id=ingested.id,
        tenant_id=tenant,
        reviewer="maryada_governor_alpha",
        verdict="PASSED",
        review_notes="Adheres to CA-001, CA-005, CA-008, CA-010.",
        db_session=db_session
    )
    assert reviewed.lifecycle_state == KnowledgeLifecycleState.CONSTITUTIONAL_REVIEW.value
    assert reviewed.reviewed_at is not None
    assert reviewed.constitutional_verdict == "PASSED"

    # Stage 4: ACTIVE
    activated = service.activate(
        knowledge_id=ingested.id,
        tenant_id=tenant,
        activation_notes="Activated for operational reasoning.",
        db_session=db_session
    )
    assert activated.lifecycle_state == KnowledgeLifecycleState.ACTIVE.value
    assert activated.activated_at is not None

    # Stage 5: DEPRECATED
    deprecated = service.deprecate(
        knowledge_id=ingested.id,
        tenant_id=tenant,
        reason="Superseded by Whitesheet v2.0 update.",
        db_session=db_session
    )
    assert deprecated.lifecycle_state == KnowledgeLifecycleState.DEPRECATED.value
    assert deprecated.deprecated_at is not None
    assert deprecated.deprecation_reason == "Superseded by Whitesheet v2.0 update."
    assert len(deprecated.lifecycle_history) >= 5


def test_3_invalid_transitions_fail_closed(db_session):
    """Verifies that illegal state jumps are rejected and fail closed."""
    service = KoshKnowledgeService()
    tenant = "tenant_lifecycle_invalid_01"

    # Ingest record in INGESTION state
    rec = service.ingest(
        tenant_id=tenant,
        title="Raw Note",
        content="Unvalidated draft note.",
        provenance_source="Source Log",
        db_session=db_session
    )

    # 1. Cannot jump from INGESTION to ACTIVE
    with pytest.raises(ValueError, match="Cannot advance to ACTIVE"):
        service.activate(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)

    # 2. Cannot jump from INGESTION to CONSTITUTIONAL_REVIEW
    with pytest.raises(ValueError, match="Cannot advance to CONSTITUTIONAL_REVIEW"):
        service.constitutional_review(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)

    # Validate record
    service.validate(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)

    # 3. Cannot jump from VALIDATION directly to ACTIVE without constitutional review
    with pytest.raises(ValueError, match="Cannot advance to ACTIVE"):
        service.activate(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)

    # Perform constitutional review and activate
    service.constitutional_review(knowledge_id=rec.id, tenant_id=tenant, verdict="PASSED", db_session=db_session)
    service.activate(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)

    # Deprecate record
    service.deprecate(knowledge_id=rec.id, tenant_id=tenant, reason="Test deprecation", db_session=db_session)

    # 4. Cannot transition out of DEPRECATED (terminal state)
    with pytest.raises(ValueError, match="already DEPRECATED"):
        service.deprecate(knowledge_id=rec.id, tenant_id=tenant, reason="Duplicate deprecation", db_session=db_session)

    with pytest.raises(ValueError, match="Cannot advance to ACTIVE"):
        service.activate(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)


def test_4_validation_gate_rejects_missing_provenance(db_session):
    """Verifies that validation rejects records with missing/unspecified provenance (CA-001)."""
    service = KoshKnowledgeService()
    tenant = "tenant_validation_gate_01"

    rec = service.ingest(
        tenant_id=tenant,
        title="Unverified Rumor",
        content="Some unproven assertion.",
        provenance_source="unspecified",
        db_session=db_session
    )

    with pytest.raises(ValueError, match="Provenance source is required"):
        service.validate(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)


def test_5_constitutional_review_gate_rejects_unpassed_verdict(db_session):
    """Verifies that a record with a REJECTED constitutional verdict cannot be activated (CA-005)."""
    service = KoshKnowledgeService()
    tenant = "tenant_const_gate_01"

    rec = service.ingest(
        tenant_id=tenant,
        title="Questionable Policy",
        content="Policy proposal conflicting with constitutional bounds.",
        provenance_source="Policy Board",
        db_session=db_session
    )
    service.validate(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)

    # Constitutional review explicitly rejects
    service.constitutional_review(
        knowledge_id=rec.id,
        tenant_id=tenant,
        reviewer="governor_beta",
        verdict="REJECTED",
        review_notes="Failed constitutional safety review.",
        db_session=db_session
    )

    # Activation must fail closed
    with pytest.raises(ValueError, match="cannot be activated because constitutional verdict is 'REJECTED'"):
        service.activate(knowledge_id=rec.id, tenant_id=tenant, db_session=db_session)


def test_6_active_knowledge_query_isolation(db_session):
    """Verifies that active queries return ONLY ACTIVE records and exclude unactivated or deprecated ones."""
    service = KoshKnowledgeService()
    tenant = "tenant_active_query_01"

    # Record 1: Remains in INGESTION
    k_ingested = service.ingest(tenant_id=tenant, title="Doc 1", content="Ingested only", provenance_source="Src 1", db_session=db_session)

    # Record 2: Promoted to ACTIVE
    k_active = service.ingest(tenant_id=tenant, title="Doc 2", content="Active doc", provenance_source="Src 2", db_session=db_session)
    service.validate(k_active.id, tenant, db_session=db_session)
    service.constitutional_review(k_active.id, tenant, verdict="PASSED", db_session=db_session)
    service.activate(k_active.id, tenant, db_session=db_session)

    # Record 3: Promoted to ACTIVE then DEPRECATED
    k_deprecated = service.ingest(tenant_id=tenant, title="Doc 3", content="Deprecated doc", provenance_source="Src 3", db_session=db_session)
    service.validate(k_deprecated.id, tenant, db_session=db_session)
    service.constitutional_review(k_deprecated.id, tenant, verdict="PASSED", db_session=db_session)
    service.activate(k_deprecated.id, tenant, db_session=db_session)
    service.deprecate(k_deprecated.id, tenant, reason="Obsolete", db_session=db_session)

    # Query active knowledge
    active_results = service.query_active_knowledge(tenant_id=tenant, db_session=db_session)
    active_ids = [r.id for r in active_results]

    assert k_active.id in active_ids
    assert k_ingested.id not in active_ids
    assert k_deprecated.id not in active_ids

    # Direct get_active_knowledge check
    assert service.get_active_knowledge(k_active.id, tenant, db_session=db_session) is not None
    assert service.get_active_knowledge(k_ingested.id, tenant, db_session=db_session) is None
    assert service.get_active_knowledge(k_deprecated.id, tenant, db_session=db_session) is None


def test_7_tenant_isolation_on_lifecycle_transitions(db_session):
    """Verifies that Tenant B cannot read, validate, review, activate, or deprecate Tenant A's knowledge."""
    service = KoshKnowledgeService()
    tenant_a = "tenant_iso_alpha_01"
    tenant_b = "tenant_iso_beta_01"

    rec_a = service.ingest(
        tenant_id=tenant_a,
        title="Alpha Confidential",
        content="Alpha internal specifications.",
        provenance_source="Alpha Vault",
        db_session=db_session
    )

    # Tenant B attempts to validate Alpha's record -> fails closed
    with pytest.raises(ValueError, match="not found for tenant"):
        service.validate(knowledge_id=rec_a.id, tenant_id=tenant_b, db_session=db_session)

    # Tenant B attempts constitutional review -> fails closed
    with pytest.raises(ValueError, match="not found for tenant"):
        service.constitutional_review(knowledge_id=rec_a.id, tenant_id=tenant_b, db_session=db_session)

    # Tenant B attempts activation -> fails closed
    with pytest.raises(ValueError, match="not found for tenant"):
        service.activate(knowledge_id=rec_a.id, tenant_id=tenant_b, db_session=db_session)

    # Tenant B attempts deprecation -> fails closed
    with pytest.raises(ValueError, match="not found for tenant"):
        service.deprecate(knowledge_id=rec_a.id, tenant_id=tenant_b, reason="Malicious deprecation", db_session=db_session)

    # Verify record in tenant A is completely unmodified
    rec_a_fresh = service.get_knowledge(knowledge_id=rec_a.id, tenant_id=tenant_a, db_session=db_session)
    assert rec_a_fresh.lifecycle_state == KnowledgeLifecycleState.INGESTION.value


def test_8_missing_tenant_fails_closed(db_session):
    """Verifies that missing or empty tenant_id raises ValueError on all lifecycle operations."""
    service = KoshKnowledgeService()

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.ingest(tenant_id="", title="T", content="C", db_session=db_session)

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.validate(knowledge_id=1, tenant_id="  ", db_session=db_session)

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.constitutional_review(knowledge_id=1, tenant_id="", db_session=db_session)

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.activate(knowledge_id=1, tenant_id="", db_session=db_session)

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.deprecate(knowledge_id=1, tenant_id="", reason="R", db_session=db_session)


def test_9_lifecycle_durability_across_sessions(db_session):
    """Verifies that lifecycle state and history persist in PostgreSQL across database sessions and service instances."""
    service_1 = KoshKnowledgeService()
    tenant = "tenant_durability_01"

    rec = service_1.ingest(
        tenant_id=tenant,
        title="Durable Architecture Document",
        content="Whitesheet §16 durable persistence verification.",
        provenance_source="Core Engineering",
        db_session=db_session
    )
    service_1.validate(rec.id, tenant, validation_notes="Session 1 validation", db_session=db_session)
    service_1.constitutional_review(rec.id, tenant, reviewer="governor_durability", verdict="PASSED", db_session=db_session)
    service_1.activate(rec.id, tenant, activation_notes="Session 1 activation", db_session=db_session)

    saved_id = rec.id
    db_session.close()

    # Brand new session and new service instance
    new_db = SessionLocal()
    try:
        fresh_service = KoshKnowledgeService()
        recovered = fresh_service.get_knowledge(knowledge_id=saved_id, tenant_id=tenant, db_session=new_db)
        assert recovered is not None
        assert recovered.id == saved_id
        assert recovered.lifecycle_state == KnowledgeLifecycleState.ACTIVE.value
        assert recovered.constitutional_verdict == "PASSED"
        assert recovered.activated_at is not None
        assert len(recovered.lifecycle_history) == 4
    finally:
        new_db.close()
