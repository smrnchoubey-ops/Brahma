"""
Forensic verification runner for Phase 3C Knowledge Lifecycle.
Executes live PostgreSQL assertions with zero mocks and returns raw output.
"""
import json
from sqlalchemy import text
from app.db.database import SessionLocal, engine
from app.core.kosh.service import KoshKnowledgeService
from app.core.kosh.models import KnowledgeLifecycleState, KnowledgeQuery


def run_forensic_verification():
    service = KoshKnowledgeService()
    db = SessionLocal()

    print("==================================================")
    print("CHECK 4: CONSTITUTIONAL REVIEW GATE LIVE PROOF")
    print("==================================================")
    tenant_g = "tenant_const_gate_forensic"
    
    # Test A: Passed verdict -> activation succeeds
    k_pass = service.ingest(
        tenant_id=tenant_g,
        title="Passed Doc",
        content="Honest verifiable content.",
        provenance_source="Source Alpha",
        confidence_score=0.95,
        epistemic_status="VERIFIED",
        db_session=db
    )
    service.validate(k_pass.id, tenant_g, db_session=db)
    service.constitutional_review(k_pass.id, tenant_g, verdict="PASSED", reviewer="gov_lead", db_session=db)
    activated_pass = service.activate(k_pass.id, tenant_g, db_session=db)
    print(f"Test A (PASSED verdict -> activation): record_id={activated_pass.id}, state={activated_pass.lifecycle_state}, constitutional_verdict={activated_pass.constitutional_verdict}, activated_at={activated_pass.activated_at}")

    # Test B: Rejected verdict -> activation fails
    k_rej = service.ingest(
        tenant_id=tenant_g,
        title="Rejected Doc",
        content="Unsafe or non-compliant content.",
        provenance_source="Source Beta",
        confidence_score=0.90,
        epistemic_status="VERIFIED",
        db_session=db
    )
    service.validate(k_rej.id, tenant_g, db_session=db)
    service.constitutional_review(k_rej.id, tenant_g, verdict="REJECTED", reviewer="gov_lead", db_session=db)
    try:
        service.activate(k_rej.id, tenant_g, db_session=db)
        print("Test B FAILED: Activation succeeded unexpectedly for REJECTED verdict!")
    except ValueError as e:
        print(f"Test B (REJECTED verdict -> activation failure): SUCCESS -> Caught expected exception: {e}")

    # Test C: Contradicted epistemic status -> constitutional review PASSED blocked (CA-001)
    k_contra = service.ingest(
        tenant_id=tenant_g,
        title="Contradicted Doc",
        content="Directly contradicted assertion.",
        provenance_source="Source Gamma",
        confidence_score=0.20,
        epistemic_status="CONTRADICTED",
        db_session=db
    )
    service.validate(k_contra.id, tenant_g, db_session=db)
    try:
        service.constitutional_review(k_contra.id, tenant_g, verdict="PASSED", db_session=db)
        print("Test C FAILED: Constitutional review passed unexpectedly for CONTRADICTED status!")
    except ValueError as e:
        print(f"Test C (CONTRADICTED epistemic status -> PASSED blocked): SUCCESS -> Caught expected exception: {e}")

    print("\n==================================================")
    print("CHECK 5: STATE / EPISTEMIC / CONFIDENCE SEPARATION")
    print("==================================================")
    k_sep = service.ingest(
        tenant_id="tenant_separation_test",
        title="Separation Spec",
        content="Testing field orthogonality.",
        provenance_source="Spec Source",
        confidence_score=0.88,
        epistemic_status="UNVERIFIED",
        db_session=db
    )
    print(f"Initial: lifecycle_state='{k_sep.lifecycle_state}', epistemic_status='{k_sep.epistemic_status}', confidence_score={k_sep.confidence_score}")
    v_sep = service.validate(k_sep.id, "tenant_separation_test", db_session=db)
    print(f"Post-Validate: lifecycle_state='{v_sep.lifecycle_state}', epistemic_status='{v_sep.epistemic_status}', confidence_score={v_sep.confidence_score}")
    r_sep = service.constitutional_review(k_sep.id, "tenant_separation_test", verdict="PASSED", db_session=db)
    print(f"Post-Review: lifecycle_state='{r_sep.lifecycle_state}', epistemic_status='{r_sep.epistemic_status}', confidence_score={r_sep.confidence_score}")
    a_sep = service.activate(k_sep.id, "tenant_separation_test", db_session=db)
    print(f"Post-Activate: lifecycle_state='{a_sep.lifecycle_state}', epistemic_status='{a_sep.epistemic_status}', confidence_score={a_sep.confidence_score}")
    d_sep = service.deprecate(k_sep.id, "tenant_separation_test", reason="Archival test", db_session=db)
    print(f"Post-Deprecate: lifecycle_state='{d_sep.lifecycle_state}', epistemic_status='{d_sep.epistemic_status}', confidence_score={d_sep.confidence_score}")
    assert d_sep.epistemic_status == "UNVERIFIED"
    assert d_sep.confidence_score == 0.88
    print("CONFIRMATION: Epistemic status ('UNVERIFIED') and confidence score (0.88) remained strictly un-mutated throughout all lifecycle transitions.")

    print("\n==================================================")
    print("CHECK 6: TENANT SECURITY & ISOLATION PROOF")
    print("==================================================")
    t_a = "tenant_forensic_alpha"
    t_b = "tenant_forensic_beta"

    rec_a = service.ingest(tenant_id=t_a, title="Alpha Private Spec", content="Confidential Data", provenance_source="Alpha Vault", db_session=db)
    rec_b = service.ingest(tenant_id=t_b, title="Beta Private Spec", content="Confidential Data", provenance_source="Beta Vault", db_session=db)

    # Tenant A transitions own record -> succeeds
    val_a = service.validate(rec_a.id, t_a, db_session=db)
    print(f"Tenant A validating own record: SUCCESS -> id={val_a.id}, state={val_a.lifecycle_state}")

    # Tenant B cannot validate Tenant A record -> fails closed
    try:
        service.validate(rec_a.id, t_b, db_session=db)
        print("FAIL: Tenant B validated Tenant A record!")
    except ValueError as e:
        print(f"Tenant B validating Tenant A record: FAIL-CLOSED -> {e}")

    # Tenant A cannot activate Tenant B record -> fails closed
    try:
        service.activate(rec_b.id, t_a, db_session=db)
        print("FAIL: Tenant A activated Tenant B record!")
    except ValueError as e:
        print(f"Tenant A activating Tenant B record: FAIL-CLOSED -> {e}")

    # Tenant A cannot deprecate Tenant B record -> fails closed
    try:
        service.deprecate(rec_b.id, t_a, reason="Malicious deprecation", db_session=db)
        print("FAIL: Tenant A deprecated Tenant B record!")
    except ValueError as e:
        print(f"Tenant A deprecating Tenant B record: FAIL-CLOSED -> {e}")

    # Missing tenant -> fails closed
    try:
        service.ingest(tenant_id="", title="T", content="C", db_session=db)
        print("FAIL: Ingestion with empty tenant succeeded!")
    except ValueError as e:
        print(f"Missing tenant ingestion: FAIL-CLOSED -> {e}")

    print("\n==================================================")
    print("CHECK 7: DATABASE DURABILITY PROOF")
    print("==================================================")
    t_dur = "tenant_durability_forensic"
    k_dur = service.ingest(tenant_id=t_dur, title="Durability Doc", content="Durable Content", provenance_source="Core Arch", db_session=db)
    service.validate(k_dur.id, t_dur, db_session=db)
    service.constitutional_review(k_dur.id, t_dur, verdict="PASSED", db_session=db)
    service.activate(k_dur.id, t_dur, db_session=db)
    saved_id = k_dur.id
    db.close()

    # Recreate brand new DB session & brand new Service instance
    new_db = SessionLocal()
    fresh_service = KoshKnowledgeService()
    recovered = fresh_service.get_knowledge(knowledge_id=saved_id, tenant_id=t_dur, db_session=new_db)
    print(f"Recovered in fresh session: id={recovered.id}, tenant_id={recovered.tenant_id}, lifecycle_state={recovered.lifecycle_state}, constitutional_verdict={recovered.constitutional_verdict}, activated_at={recovered.activated_at}")
    new_db.close()

    print("\n==================================================")
    print("CHECK 8: DEPRECATION & ACTIVE-ONLY ISOLATION PROOF")
    print("==================================================")
    db2 = SessionLocal()
    t_dep = "tenant_dep_forensic"
    k_act = service.ingest(tenant_id=t_dep, title="Active Doc", content="Content", provenance_source="Src", db_session=db2)
    service.validate(k_act.id, t_dep, db_session=db2)
    service.constitutional_review(k_act.id, t_dep, verdict="PASSED", db_session=db2)
    service.activate(k_act.id, t_dep, db_session=db2)

    k_to_dep = service.ingest(tenant_id=t_dep, title="To Deprecate Doc", content="Content", provenance_source="Src", db_session=db2)
    service.validate(k_to_dep.id, t_dep, db_session=db2)
    service.constitutional_review(k_to_dep.id, t_dep, verdict="PASSED", db_session=db2)
    service.activate(k_to_dep.id, t_dep, db_session=db2)
    dep_res = service.deprecate(k_to_dep.id, t_dep, reason="Superseded by standard v2.0", db_session=db2)

    # Query raw PostgreSQL row for deprecated item
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT id, tenant_id, lifecycle_state, deprecated_at, deprecation_reason, lifecycle_history FROM knowledge WHERE id = {dep_res.id}")).fetchone()
        print(f"Raw PostgreSQL row: id={row.id}, tenant_id={row.tenant_id}, lifecycle_state='{row.lifecycle_state}', deprecated_at={row.deprecated_at}, deprecation_reason='{row.deprecation_reason}'")
        print(f"Lifecycle history:\n{json.dumps(row.lifecycle_history, indent=2)}")

    # Active-only query proof
    active_items = service.query_active_knowledge(tenant_id=t_dep, db_session=db2)
    active_ids = [a.id for a in active_items]
    print(f"Active-only query returned IDs: {active_ids}")
    print(f"Is k_act (id={k_act.id}) present in active list? {k_act.id in active_ids}")
    print(f"Is k_to_dep (id={k_to_dep.id}) present in active list? {k_to_dep.id in active_ids}")
    db2.close()

    print("\n==================================================")
    print("CHECK 10: TENANT_ID DEFAULT COLUMN INSPECTION")
    print("==================================================")
    with engine.connect() as conn:
        col_res = conn.execute(text("SELECT column_name, column_default, is_nullable FROM information_schema.columns WHERE table_name = 'knowledge' AND column_name = 'tenant_id';")).fetchone()
        print(f"knowledge.tenant_id definition: column_name='{col_res[0]}', column_default='{col_res[1]}', is_nullable='{col_res[2]}'")


if __name__ == "__main__":
    run_forensic_verification()
