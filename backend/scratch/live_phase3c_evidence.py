"""
Live demonstration script capturing raw PostgreSQL evidence for Phase 3C Knowledge Lifecycle.
"""
import json
from app.db.database import SessionLocal, engine
from sqlalchemy import text
from app.core.kosh.service import KoshKnowledgeService
from app.core.kosh.models import KnowledgeLifecycleState, KnowledgeQuery


def run_live_evidence():
    print("=== 1. RAW POSTGRESQL SCHEMA AFTER MIGRATION ===")
    with engine.connect() as conn:
        res = conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default 
            FROM information_schema.columns 
            WHERE table_name = 'knowledge' 
            ORDER BY ordinal_position;
        """))
        for row in res:
            print(f"  {row[0]}: {row[1]} (nullable={row[2]}, default={row[3]})")

    service = KoshKnowledgeService()
    tenant = "tenant_live_evidence_3c"

    print("\n=== 2. RAW 5-STAGE LIFECYCLE TRANSITION EVIDENCE ===")
    # Stage 1: INGESTION
    print("\n--- [Stage 1: INGESTION] ---")
    rec = service.ingest(
        tenant_id=tenant,
        title="Brahma Architectural Whitesheet §16",
        content="The lifecycle of knowledge transitions across five explicit gates: Ingestion, Validation, Constitutional Review, Active, and Deprecation.",
        provenance_source="Brahma COS Whitesheet v1.0",
        source_uri="doc://whitesheet/section_16",
        confidence_score=0.98,
        epistemic_status="VERIFIED"
    )
    print(f"Ingested Record ID: {rec.id}")
    print(f"Lifecycle State: {rec.lifecycle_state}")
    print(f"Created At: {rec.created_at}")
    print(f"Validated At: {rec.validated_at}")
    print(f"Reviewed At: {rec.reviewed_at}")
    print(f"Activated At: {rec.activated_at}")
    print(f"Lifecycle History: {json.dumps(rec.lifecycle_history, indent=2)}")

    # Stage 2: VALIDATION
    print("\n--- [Stage 2: VALIDATION] ---")
    val_rec = service.validate(
        knowledge_id=rec.id,
        tenant_id=tenant,
        validator="kosh_schema_verifier_v1",
        validation_notes="Schema completeness, source provenance, and confidence score within bounds verified."
    )
    print(f"Validated Record ID: {val_rec.id}")
    print(f"Lifecycle State: {val_rec.lifecycle_state}")
    print(f"Validated At: {val_rec.validated_at}")
    print(f"Lifecycle History: {json.dumps(val_rec.lifecycle_history, indent=2)}")

    # Stage 3: CONSTITUTIONAL REVIEW
    print("\n--- [Stage 3: CONSTITUTIONAL REVIEW] ---")
    rev_rec = service.constitutional_review(
        knowledge_id=rec.id,
        tenant_id=tenant,
        reviewer="maryada_governor_alpha",
        verdict="PASSED",
        review_notes="Evaluation confirmed compliance with CA-001, CA-005, CA-008, CA-010."
    )
    print(f"Reviewed Record ID: {rev_rec.id}")
    print(f"Lifecycle State: {rev_rec.lifecycle_state}")
    print(f"Reviewed At: {rev_rec.reviewed_at}")
    print(f"Constitutional Verdict: {rev_rec.constitutional_verdict}")
    print(f"Lifecycle History: {json.dumps(rev_rec.lifecycle_history, indent=2)}")

    # Stage 4: ACTIVE
    print("\n--- [Stage 4: ACTIVE] ---")
    act_rec = service.activate(
        knowledge_id=rec.id,
        tenant_id=tenant,
        activation_notes="Activated for authoritative agent reasoning and citation."
    )
    print(f"Activated Record ID: {act_rec.id}")
    print(f"Lifecycle State: {act_rec.lifecycle_state}")
    print(f"Activated At: {act_rec.activated_at}")
    print(f"Lifecycle History: {json.dumps(act_rec.lifecycle_history, indent=2)}")

    # Stage 5: DEPRECATED
    print("\n--- [Stage 5: DEPRECATED] ---")
    dep_rec = service.deprecate(
        knowledge_id=rec.id,
        tenant_id=tenant,
        reason="Archived following architectural revision v1.1."
    )
    print(f"Deprecated Record ID: {dep_rec.id}")
    print(f"Lifecycle State: {dep_rec.lifecycle_state}")
    print(f"Deprecated At: {dep_rec.deprecated_at}")
    print(f"Deprecation Reason: {dep_rec.deprecation_reason}")
    print(f"Lifecycle History: {json.dumps(dep_rec.lifecycle_history, indent=2)}")

    print("\n=== 3. RAW INVALID TRANSITION REJECTION EVIDENCE ===")
    raw_ingested = service.ingest(
        tenant_id=tenant,
        title="Unvalidated Draft",
        content="Draft content not yet validated.",
        provenance_source="User Draft"
    )
    try:
        service.activate(knowledge_id=raw_ingested.id, tenant_id=tenant)
        print("ERROR: Ingestion -> Active succeeded unexpectedly!")
    except ValueError as e:
        print(f"Caught expected rejection (INGESTION -> ACTIVE): {e}")

    try:
        service.constitutional_review(knowledge_id=raw_ingested.id, tenant_id=tenant)
        print("ERROR: Ingestion -> Constitutional Review succeeded unexpectedly!")
    except ValueError as e:
        print(f"Caught expected rejection (INGESTION -> CONSTITUTIONAL_REVIEW): {e}")

    print("\n=== 4. RAW CROSS-TENANT DENIAL EVIDENCE ===")
    tenant_a = "tenant_sec_alpha"
    tenant_b = "tenant_sec_beta"
    rec_sec_a = service.ingest(
        tenant_id=tenant_a,
        title="Confidential Specification",
        content="Alpha internal trade secrets.",
        provenance_source="Security Vault Alpha"
    )
    try:
        service.validate(knowledge_id=rec_sec_a.id, tenant_id=tenant_b)
        print("ERROR: Cross-tenant validation succeeded unexpectedly!")
    except ValueError as e:
        print(f"Caught expected cross-tenant validation denial: {e}")

    try:
        service.activate(knowledge_id=rec_sec_a.id, tenant_id=tenant_b)
        print("ERROR: Cross-tenant activation succeeded unexpectedly!")
    except ValueError as e:
        print(f"Caught expected cross-tenant activation denial: {e}")

    print("\n=== 5. RAW MISSING-TENANT FAIL-CLOSED EVIDENCE ===")
    try:
        service.ingest(tenant_id="", title="T", content="C")
    except ValueError as e:
        print(f"Caught expected missing-tenant ingest denial: {e}")

    try:
        service.validate(knowledge_id=1, tenant_id="  ")
    except ValueError as e:
        print(f"Caught expected missing-tenant validate denial: {e}")

    print("\n=== 6. RAW DURABILITY & POSTGRESQL ROW EVIDENCE ===")
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT id, tenant_id, title, lifecycle_state, constitutional_verdict, deprecation_reason FROM knowledge WHERE id = {rec.id}")).fetchone()
        print(f"Direct PostgreSQL Row Query: id={row.id}, tenant_id={row.tenant_id}, title='{row.title}', lifecycle_state='{row.lifecycle_state}', constitutional_verdict='{row.constitutional_verdict}', deprecation_reason='{row.deprecation_reason}'")


if __name__ == "__main__":
    run_live_evidence()
