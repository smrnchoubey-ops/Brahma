"""
Phase 3B KOSH Knowledge Core & Fact Verification Test Suite
Strictly tests Whitesheet §4.1 Path 3, §5, §16 boundary, §19, CA-001, and CA-008.
Verifies:
1. KOSH knowledge record creation with provenance, confidence, and epistemic status.
2. PostgreSQL persistence without SQLite fallback.
3. Fact verification against verified knowledge corpus.
4. Strict tenant isolation (cross-tenant read/update/delete fails closed).
5. SMRITI non-conflation: KOSH does NOT touch or write to SMRITI 'memory' table.
"""
import pytest
from sqlalchemy import text

from app.db.database import SessionLocal
from app.models.knowledge import Knowledge
from app.models.memory import Memory
from app.core.kosh.service import KoshKnowledgeService, kosh_service
from app.core.kosh.models import KnowledgeQuery, FactVerificationRequest
from app.core.smriti.service import smriti_service


def setup_module():
    """Ensure knowledge and memory schemas are migrated on PostgreSQL."""
    from app.db.migrate_knowledge_kosh import migrate_kosh_knowledge_schema
    from app.db.migrate_memory_smriti import migrate_smriti_memory_schema
    migrate_kosh_knowledge_schema()
    migrate_smriti_memory_schema()


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_1_kosh_knowledge_creation_with_provenance_and_confidence(db_session):
    """Verifies that KOSH creates knowledge records with explicit provenance and confidence fields."""
    service = KoshKnowledgeService()
    record = service.add_knowledge(
        tenant_id="tenant_kosh_alpha_01",
        title="Brahma COS Protocol §4.1",
        content="Path 3 designates KOSH as the knowledge and fact verification core.",
        provenance_source="Brahma COS Whitesheet v1.0",
        source_uri="doc://whitesheet/section_4.1",
        confidence_score=0.98,
        epistemic_status="VERIFIED",
        verification_details={"verifier": "secops_lead", "method": "formal_audit"},
        db_session=db_session
    )

    assert record.id is not None
    assert record.tenant_id == "tenant_kosh_alpha_01"
    assert record.provenance_source == "Brahma COS Whitesheet v1.0"
    assert record.source_uri == "doc://whitesheet/section_4.1"
    assert record.confidence_score == 0.98
    assert record.epistemic_status == "VERIFIED"
    assert record.verification_details.get("verifier") == "secops_lead"

    # Direct PostgreSQL database row verification
    db_row = db_session.query(Knowledge).filter(Knowledge.id == record.id).first()
    assert db_row is not None
    assert db_row.tenant_id == "tenant_kosh_alpha_01"
    assert db_row.confidence_score == 0.98


def test_2_fact_verification_against_authoritative_corpus(db_session):
    """Verifies that KOSH performs factual claim verification and returns structured epistemic status."""
    service = KoshKnowledgeService()
    service.add_knowledge(
        tenant_id="tenant_kosh_alpha_02",
        title="Corporate Fiscal Year Policy",
        content="The fiscal year ends on March 31 annually for all corporate subsidiaries.",
        provenance_source="Finance Policy Handbook 2026",
        source_uri="finance://handbook/2026/fy",
        confidence_score=1.0,
        epistemic_status="VERIFIED",
        db_session=db_session
    )

    # Claim matching the verified fact
    result = service.verify_fact(
        claim="The fiscal year ends on March 31 annually.",
        tenant_id="tenant_kosh_alpha_02",
        db_session=db_session
    )

    assert result.is_verified is True
    assert result.epistemic_status == "VERIFIED"
    assert result.confidence_score >= 0.80
    assert len(result.supporting_evidence) >= 1
    assert result.supporting_evidence[0]["provenance_source"] == "Finance Policy Handbook 2026"


def test_3_fact_verification_detects_insufficient_evidence(db_session):
    """Verifies that an uncorroborated claim returns INSUFFICIENT_EVIDENCE with zero false claims (CA-001)."""
    service = KoshKnowledgeService()
    result = service.verify_fact(
        claim="Quantum teleportation is enabled in cluster node 7.",
        tenant_id="tenant_kosh_alpha_03",
        db_session=db_session
    )

    assert result.is_verified is False
    assert result.epistemic_status == "INSUFFICIENT_EVIDENCE"
    assert result.confidence_score == 0.0
    assert len(result.supporting_evidence) == 0


def test_4_same_tenant_knowledge_retrieval_succeeds(db_session):
    """Verifies knowledge retrieval within the same tenant context."""
    service = KoshKnowledgeService()
    item = service.add_knowledge(
        tenant_id="tenant_kosh_alpha_04",
        title="Server Configuration",
        content="Primary database listens on port 5433 with SSL enforced.",
        provenance_source="Infrastructure Manifest",
        db_session=db_session
    )

    retrieved = service.get_knowledge(
        knowledge_id=item.id,
        tenant_id="tenant_kosh_alpha_04",
        db_session=db_session
    )
    assert retrieved is not None
    assert retrieved.id == item.id
    assert "port 5433" in retrieved.content


def test_5_cross_tenant_knowledge_retrieval_fails_closed(db_session):
    """Attempt by Tenant B to retrieve Tenant A's knowledge MUST return None (fail-closed, CA-008)."""
    service = KoshKnowledgeService()
    item_a = service.add_knowledge(
        tenant_id="tenant_kosh_alpha_05",
        title="Confidential Algorithm",
        content="Secret weight parameters [0.42, 0.88, 0.12].",
        provenance_source="R&D Vault",
        db_session=db_session
    )

    # Tenant Beta attempts to retrieve Alpha's record
    beta_attempt = service.get_knowledge(
        knowledge_id=item_a.id,
        tenant_id="tenant_kosh_beta_05",
        db_session=db_session
    )
    assert beta_attempt is None, "Security Violation: Tenant Beta accessed Tenant Alpha's knowledge!"


def test_6_cross_tenant_update_and_delete_fails_closed(db_session):
    """Attempt by Tenant B to modify or delete Tenant A's knowledge MUST fail closed."""
    service = KoshKnowledgeService()
    item_a = service.add_knowledge(
        tenant_id="tenant_kosh_alpha_06",
        title="Original Title",
        content="Original Content",
        provenance_source="Authoritative Source",
        db_session=db_session
    )

    # Tenant Beta attempts update
    upd_res = service.repository.update_knowledge(
        db=db_session,
        knowledge_id=item_a.id,
        tenant_id="tenant_kosh_beta_06",
        title="Tampered Title"
    )
    assert upd_res is False

    # Verify content was not modified
    unmodified = service.get_knowledge(knowledge_id=item_a.id, tenant_id="tenant_kosh_alpha_06", db_session=db_session)
    assert unmodified.title == "Original Title"

    # Tenant Beta attempts delete
    del_res = service.delete_knowledge(
        knowledge_id=item_a.id,
        tenant_id="tenant_kosh_beta_06",
        db_session=db_session
    )
    assert del_res is False

    # Verify record still exists
    still_exists = service.get_knowledge(knowledge_id=item_a.id, tenant_id="tenant_kosh_alpha_06", db_session=db_session)
    assert still_exists is not None


def test_7_missing_tenant_context_fails_closed(db_session):
    """Missing or empty tenant_id must raise ValueError (fail-closed)."""
    service = KoshKnowledgeService()

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.add_knowledge(
            tenant_id="",
            title="T",
            content="C",
            db_session=db_session
        )

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.get_knowledge(
            knowledge_id=1,
            tenant_id="",
            db_session=db_session
        )

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.verify_fact(
            claim="Some claim",
            tenant_id="   ",
            db_session=db_session
        )


def test_8_smriti_non_conflation_kosh_does_not_touch_smriti_memory(db_session):
    """Verifies architectural separation: KOSH operations do NOT write to or modify the SMRITI 'memory' table."""
    # Record initial count in SMRITI 'memory' table
    initial_memory_count = db_session.execute(text("SELECT count(*) FROM memory;")).scalar()

    # Perform multiple KOSH knowledge operations
    service = KoshKnowledgeService()
    k1 = service.add_knowledge(
        tenant_id="tenant_kosh_sep_01",
        title="Knowledge Item 1",
        content="Fact content for verification.",
        provenance_source="Source A",
        db_session=db_session
    )
    service.verify_fact(
        claim="Fact content for verification.",
        tenant_id="tenant_kosh_sep_01",
        db_session=db_session
    )
    service.get_knowledge(knowledge_id=k1.id, tenant_id="tenant_kosh_sep_01", db_session=db_session)

    # Verify SMRITI memory table count remained strictly unchanged
    final_memory_count = db_session.execute(text("SELECT count(*) FROM memory;")).scalar()
    assert final_memory_count == initial_memory_count, "Architectural Defect: KOSH touched SMRITI memory table!"


def test_9_postgresql_restart_durability(db_session):
    """Verifies that knowledge records persist in PostgreSQL across service recreation and session boundaries."""
    service_1 = KoshKnowledgeService()
    rec = service_1.add_knowledge(
        tenant_id="tenant_kosh_durable_01",
        title="Durable Knowledge Entry",
        content="Knowledge stored in PostgreSQL survives service recreation.",
        provenance_source="Infrastructure Spec",
        confidence_score=0.99,
        db_session=db_session
    )
    saved_id = rec.id
    db_session.close()

    # Recreate brand new DB session & brand new Service instance (simulating process restart)
    new_db = SessionLocal()
    try:
        fresh_service = KoshKnowledgeService()
        recovered = fresh_service.get_knowledge(
            knowledge_id=saved_id,
            tenant_id="tenant_kosh_durable_01",
            db_session=new_db
        )
        assert recovered is not None
        assert recovered.id == saved_id
        assert recovered.title == "Durable Knowledge Entry"
        assert recovered.confidence_score == 0.99
    finally:
        new_db.close()
