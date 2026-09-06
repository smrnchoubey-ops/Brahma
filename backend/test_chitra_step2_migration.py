"""
Test Suite for Step 2: Database Schema, Concurrency Safeguards & Migration
Runs against local SQLite test database (test_chitra_local_copy.db).
"""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.task import Task
from app.models.user import User
from app.models.audit import Audit
from app.models.chitra import ChitraEvent
from app.repositories.chitra_repository import chitra_repository
from app.core.chitra.crypto import GENESIS_HASH, verify_event_signature
from migrate_audit_to_chitra import run_migration, map_legacy_event_type

TEST_DB_URL = "sqlite:///./test_chitra_local_copy.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def setup_test_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user = User(username="test_user", hashed_password="hashed_test_pass")
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create 2 tasks
    t1 = Task(user_id=user.id, title="Task 1", prompt="Prompt 1", status="COMPLETED")
    t2 = Task(user_id=user.id, title="Task 2", prompt="Prompt 2", status="FAILED")
    db.add(t1)
    db.add(t2)
    db.commit()
    db.refresh(t1)
    db.refresh(t2)

    # Populate legacy audit_logs across the full spectrum of legacy event types
    legacy_events = [
        # Task 1 (Successful flow)
        (t1.id, "KARMA", "Ingest Intent", "SUCCESS", {"intent": "Generate financial report"}),
        (t1.id, "KOSH", "Context Retrieval", "SUCCESS", {"results_count": 3}),
        (t1.id, "PRAGYA", "Plan Generation", "SUCCESS", {"plan": "Step 1, Step 2"}),
        (t1.id, "MURPHY", "Risk Assessment", "SUCCESS", {"risk_level": "LOW"}),
        (t1.id, "MARYADA", "Policy Enforcement", "APPROVED", {"risk_tier": "LOW"}),
        (t1.id, "RACHIT", "Task Execution", "SUCCESS", {"result": "Report generated"}),

        # Task 2 (Blocked/Failed flow)
        (t2.id, "KARMA", "Security Scan", "FAILED", {"reason": "Prompt injection detected"}),
        (t2.id, "MARYADA", "Policy Enforcement", "BLOCKED", {"risk_tier": "HIGH"}),
        (t2.id, "SYSTEM", "Workflow Crash", "FAILED", {"error": "Execution terminated"})
    ]

    for tid, agent, ev_type, status, payload in legacy_events:
        db.add(Audit(task_id=tid, agent=agent, event_type=ev_type, status=status, payload_snapshot=payload))

    db.commit()
    t1_id = t1.id
    t2_id = t2.id
    db.close()
    return t1_id, t2_id


def test_migration_on_local_copy():
    print("\n--- 1. Testing Event Type Mapping Matrix ---")
    assert map_legacy_event_type("Ingest Intent", "KARMA") == "perception"
    assert map_legacy_event_type("Context Retrieval", "KOSH") == "retrieval"
    assert map_legacy_event_type("Plan Generation", "PRAGYA") == "decision"
    assert map_legacy_event_type("Risk Assessment", "MURPHY") == "verification"
    assert map_legacy_event_type("Policy Enforcement", "MARYADA") == "gate"
    assert map_legacy_event_type("Task Execution", "RACHIT") == "invocation"
    assert map_legacy_event_type("Workflow Crash", "SYSTEM") == "escalation"
    print("  [PASS] All legacy event types mapped to Whitesheet categories accurately.")

    print("\n--- 2. Setting up Local Test Database with Legacy Data ---")
    t1_id, t2_id = setup_test_db()
    print("  [PASS] Test database seeded with 9 legacy audit records across 2 tasks.")

    print("\n--- 3. Running Atomic Migration Against Local Test DB ---")
    success = run_migration(db_url=TEST_DB_URL)
    assert success is True, "Migration failed!"

    print("\n--- 4. Verifying Migrated CHITRA Records ---")
    db = TestSession()
    t1_events = chitra_repository.get_events_for_task(db, t1_id)
    t2_events = chitra_repository.get_events_for_task(db, t2_id)

    assert len(t1_events) == 6, f"Expected 6 events for task 1, got {len(t1_events)}"
    assert len(t2_events) == 3, f"Expected 3 events for task 2, got {len(t2_events)}"

    # Check Task 1 chain
    prev = GENESIS_HASH
    for evt in t1_events:
        assert evt.prev_event_hash == prev
        assert verify_event_signature(evt.this_event_hash, evt.signature)
        prev = evt.this_event_hash

    # Check Task 2 chain
    prev = GENESIS_HASH
    for evt in t2_events:
        assert evt.prev_event_hash == prev
        assert verify_event_signature(evt.this_event_hash, evt.signature)
        prev = evt.this_event_hash

    print("  [PASS] All migrated tasks verified with unbroken hash chains and valid HMAC signatures.")

    print("\n--- 5. Testing Runtime append_event() on Migrated Ledger ---")
    # Append an 7th event to Task 1
    new_evt = chitra_repository.append_event(
        db=db,
        task_id=t1_id,
        faculty="BRAHMA",
        event_type="validation",
        decision={"summary": "Task complete and validated"},
        confidence=1.0
    )
    assert new_evt.prev_event_hash == t1_events[-1].this_event_hash
    assert verify_event_signature(new_evt.this_event_hash, new_evt.signature)
    print("  [PASS] Runtime append_event() successfully chained onto migrated event without drift.")

    print("\n--- 6. Testing Concurrency / Fork Prevention Constraint ---")
    duplicate_evt = ChitraEvent(
        event_id="evt_DUPLICATE_FORK",
        task_id=t1_id,
        session_id="ses_1",
        timestamp=new_evt.timestamp,
        faculty="MALICIOUS_AGENT",
        event_type="invocation",
        input_hash=new_evt.input_hash,
        decision={},
        evidence=[],
        confidence=1.0,
        outcome=None,
        constitutional_review="passed",
        prev_event_hash=new_evt.prev_event_hash,  # Colliding parent hash!
        this_event_hash="sha256:fake_hash",
        signature="hmac-sha256:fake_sig"
    )
    db.add(duplicate_evt)
    with pytest.raises(Exception):
        db.commit()
    db.rollback()
    print("  [PASS] Concurrency fork attempt was rejected by unique constraint.")

    db.close()
    print("\n==================================================")
    print("ALL STEP 2 VALIDATION TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    test_migration_on_local_copy()
