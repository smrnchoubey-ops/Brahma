import os
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session

# Ensure dedicated signing key for test environment
os.environ["CHITRA_SIGNING_KEY"] = "chitra-phase3e-test-secret-key-9999"

from app.db.database import SessionLocal, engine
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.repositories.chitra_repository import chitra_repository
from app.services.audit_service import audit_service, log_audit_event
from app.services.chitra_verifier import chitra_verifier
from app.services.replay_service import chitra_replay_engine
from app.core.chitra.crypto import GENESIS_HASH, verify_event_signature, compute_chained_hash, compute_content_hash

def setup_test_users_and_tasks():
    db: Session = SessionLocal()
    try:
        # Create User A (Tenant A)
        user_a = db.query(User).filter(User.username == "tenant_a_3e").first()
        if not user_a:
            user_a = User(
                username="tenant_a_3e",
                hashed_password="hashed_pass_3e",
                is_active=True
            )
            db.add(user_a)
            db.commit()
            db.refresh(user_a)

        # Create User B (Tenant B)
        user_b = db.query(User).filter(User.username == "tenant_b_3e").first()
        if not user_b:
            user_b = User(
                username="tenant_b_3e",
                hashed_password="hashed_pass_3e",
                is_active=True
            )
            db.add(user_b)
            db.commit()
            db.refresh(user_b)

        # Create Task for Tenant A
        task_a = Task(
            title="Phase 3E Task Tenant A",
            prompt="Analyze financial risk",
            status="PENDING",
            risk_level="MEDIUM",
            user_id=user_a.id
        )
        db.add(task_a)

        # Create Task for Tenant B
        task_b = Task(
            title="Phase 3E Task Tenant B",
            prompt="Process operations",
            status="PENDING",
            risk_level="LOW",
            user_id=user_b.id
        )
        db.add(task_b)

        db.commit()
        db.refresh(task_a)
        db.refresh(task_b)
        return user_a.id, user_b.id, task_a.id, task_b.id
    finally:
        db.close()


def test_1_postgresql_dialect_strictly_verified():
    """Verify PostgreSQL database engine connection."""
    assert engine.dialect.name == "postgresql", f"Error: SQLite or non-PostgreSQL dialect detected: {engine.dialect.name}"


def test_2_chitra_valid_event_append_and_hash_chain():
    """Verify CHITRA events are cryptographically chained and signed in PostgreSQL."""
    user_a_id, _, task_a_id, _ = setup_test_users_and_tasks()
    db: Session = SessionLocal()
    try:
        # Append Event 1 (Genesis parent)
        evt1 = audit_service.create_chitra_event(
            db=db,
            task_id=task_a_id,
            faculty="KARMA",
            event_type="perception",
            decision={"action": "perceive_intent"},
            session_id=f"ses_{task_a_id}",
            confidence=0.95,
            input_data={"prompt": "Analyze financial risk"}
        )

        assert evt1.event_id.startswith("evt_")
        assert evt1.prev_event_hash == GENESIS_HASH
        assert evt1.this_event_hash.startswith("sha256:")
        assert evt1.signature.startswith("hmac-sha256:")

        # Append Event 2 (Chained to Event 1)
        evt2 = audit_service.create_chitra_event(
            db=db,
            task_id=task_a_id,
            faculty="KOSH",
            event_type="retrieval",
            decision={"action": "query_active_knowledge"},
            session_id=f"ses_{task_a_id}",
            confidence=0.98,
            input_data={"intent": "Analyze financial risk"}
        )

        assert evt2.prev_event_hash == evt1.this_event_hash
        assert verify_event_signature(evt2.this_event_hash, evt2.signature) is True
    finally:
        db.close()


def test_3_chitra_hmac_signature_verification():
    """Verify HMAC signature is mathematically verified and fails on wrong key."""
    _, _, task_a_id, _ = setup_test_users_and_tasks()
    db: Session = SessionLocal()
    try:
        evt = audit_service.create_chitra_event(
            db=db,
            task_id=task_a_id,
            faculty="PRAGYA",
            event_type="decision",
            decision={"action": "reasoning_plan"},
            confidence=0.9
        )
        # Signature verification with correct secret key
        assert verify_event_signature(evt.this_event_hash, evt.signature) is True
        # Signature verification fails with incorrect secret key
        assert verify_event_signature(evt.this_event_hash, evt.signature, secret_key="wrong-secret") is False
    finally:
        db.close()


def test_4_chitra_tamper_detection_in_database():
    """Verify tampering detection when payload or hash chain is mutated in PostgreSQL."""
    _, _, task_a_id, _ = setup_test_users_and_tasks()
    db: Session = SessionLocal()
    try:
        evt = audit_service.create_chitra_event(
            db=db,
            task_id=task_a_id,
            faculty="MURPHY",
            event_type="validation",
            decision={"action": "redteam_simulation"},
            confidence=0.92
        )

        # Initial state must be valid
        report_before = chitra_verifier.verify_task_chain(db, task_a_id)
        assert report_before.valid is True
        assert report_before.chain_status == "VERIFIED"

        # Tamper with decision payload of an event in DB
        original_decision = evt.decision
        evt.decision = {"action": "TAMPERED_ACTION_MALICIOUS"}
        db.commit()

        # Integrity verifier must catch the tamper
        report_tampered = chitra_verifier.verify_task_chain(db, task_a_id)
        assert report_tampered.valid is False
        assert report_tampered.chain_status == "CORRUPTED"
        assert report_tampered.failure_type == "CONTENT_HASH_MISMATCH"

        # Restore original decision payload
        evt.decision = original_decision
        db.commit()

        # Verify restoration returns chain to VERIFIED status
        report_restored = chitra_verifier.verify_task_chain(db, task_a_id)
        assert report_restored.valid is True
    finally:
        db.close()


def test_5_chitra_tenant_isolation_fails_closed():
    """Verify tenant isolation and resource-hiding checks fail closed."""
    user_a_id, user_b_id, task_a_id, task_b_id = setup_test_users_and_tasks()
    db: Session = SessionLocal()
    try:
        # Create event for Task B
        audit_service.create_chitra_event(
            db=db,
            task_id=task_b_id,
            faculty="RACHIT",
            event_type="invocation",
            decision={"action": "execute_task_b"},
            confidence=1.0
        )

        # Tenant A accessing Tenant B's task events returns empty/denied
        events = chitra_repository.get_events_for_task(db, task_b_id, user_id=user_a_id)
        assert len(events) == 0

        # Tenant A verifying Tenant B's chain returns ACCESS_DENIED report
        report = chitra_verifier.verify_task_chain(db, task_b_id, user_id=user_a_id)
        assert report.valid is False
        assert report.chain_status == "ACCESS_DENIED"

        # Tenant A replaying Tenant B's trace returns ACCESS_DENIED trace
        trace = chitra_replay_engine.replay_task(db, task_b_id, user_id=user_a_id)
        assert trace.replay_status == "ACCESS_DENIED"
    finally:
        db.close()


def test_6_chitra_missing_tenant_id_fails_closed():
    """Verify unauthorized or unowned task operations fail closed."""
    _, _, task_a_id, _ = setup_test_users_and_tasks()
    db: Session = SessionLocal()
    try:
        # Non-existent tenant user ID (999999) fails closed
        report = chitra_verifier.verify_task_chain(db, task_a_id, user_id=999999)
        assert report.valid is False
        assert report.chain_status == "ACCESS_DENIED"
    finally:
        db.close()


def test_7_chitra_durability_across_fresh_sessions():
    """Verify CHITRA events persist across fresh DB sessions."""
    _, _, task_a_id, _ = setup_test_users_and_tasks()
    db_setup: Session = SessionLocal()
    try:
        audit_service.create_chitra_event(
            db=db_setup,
            task_id=task_a_id,
            faculty="MARYADA",
            event_type="gate",
            decision={"action": "check_governance"},
            confidence=1.0
        )
    finally:
        db_setup.close()

    # Session 1: Read events
    s1: Session = SessionLocal()
    count_1 = len(chitra_repository.get_events_for_task(s1, task_a_id))
    s1.close()

    # Session 2: Fresh DB session
    s2: Session = SessionLocal()
    count_2 = len(chitra_repository.get_events_for_task(s2, task_a_id))
    s2.close()

    assert count_1 > 0
    assert count_1 == count_2


def test_8_chitra_runtime_event_emission():
    """Verify runtime node execution emits canonical CHITRA events."""
    user_a_id, _, task_a_id, _ = setup_test_users_and_tasks()
    log_audit_event(
        task_id=task_a_id,
        agent="MARYADA",
        event_type="Policy Enforcement",
        status="SUCCESS",
        payload_snapshot={"verdict": "ALLOWED", "policy": "DATA_PRIVACY"}
    )

    db: Session = SessionLocal()
    try:
        last_evt = chitra_repository.get_last_event(db, task_a_id)
        assert last_evt is not None
        assert last_evt.faculty == "MARYADA"
        assert last_evt.event_type == "gate"
        assert last_evt.constitutional_review == "passed"
    finally:
        db.close()


def test_9_chitra_forensic_replay_and_refusal_on_corrupted_ledger():
    """Verify forensic replay reconstructs decision trace and refuses execution on tampered ledger."""
    user_a_id, _, task_a_id, _ = setup_test_users_and_tasks()
    db: Session = SessionLocal()
    try:
        evt = audit_service.create_chitra_event(
            db=db,
            task_id=task_a_id,
            faculty="SYSTEM",
            event_type="invocation",
            decision={"action": "system_bootstrap"},
            confidence=1.0
        )

        # Replay valid task trace
        trace = chitra_replay_engine.replay_task(db, task_a_id, user_id=user_a_id)
        assert trace.replay_status == "SUCCESS"
        assert trace.integrity_verified is True
        assert len(trace.timeline) > 0

        # Corrupt chain in DB (tamper hash pointer)
        original_hash = evt.this_event_hash
        evt.this_event_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        db.commit()

        # Replay must be REFUSED on corrupted ledger
        refused_trace = chitra_replay_engine.replay_task(db, task_a_id, user_id=user_a_id)
        assert refused_trace.replay_status == "REFUSED_CORRUPTED"
        assert refused_trace.integrity_verified is False

        # Restore original hash pointer
        evt.this_event_hash = original_hash
        db.commit()
    finally:
        db.close()
