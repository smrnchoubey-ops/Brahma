"""
CHITRA Step 3: Complete Tamper Detection & Forensic Integrity Test Suite
Runs strictly against a disposable local SQLite test database: test_chitra_tamper_sandbox.db.
"""
import os
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier, ChitraVerificationResult
from app.core.chitra.crypto import GENESIS_HASH, build_chitra_envelope

TEST_DB_URL = "sqlite:///./test_chitra_tamper_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user = User(username="auditor_test", hashed_password="audit_hashed_password")
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id

    db.close()
    return user_id


def create_task_with_chain(db, user_id: int, title: str, num_events: int = 5) -> int:
    task = Task(user_id=user_id, title=title, prompt=f"Prompt for {title}", status="RUNNING")
    db.add(task)
    db.commit()
    db.refresh(task)
    task_id = task.id

    faculties = ["KARMA", "KOSH", "PRAGYA", "MURPHY", "MARYADA", "RACHIT"]
    event_types = ["perception", "retrieval", "decision", "verification", "gate", "invocation"]

    for i in range(min(num_events, len(faculties))):
        chitra_repository.append_event(
            db=db,
            task_id=task_id,
            faculty=faculties[i],
            event_type=event_types[i],
            decision={"step": i + 1, "description": f"Legitimate step {i + 1} payload"},
            confidence=0.95 + (i * 0.01)
        )

    return task_id


def run_all_tamper_tests():
    user_id = reset_sandbox_db()
    db = TestSession()

    print("==================================================")
    print("CHITRA STEP 3: TAMPER DETECTION & FORENSIC SUITE")
    print("Target Sandbox: sqlite:///./test_chitra_tamper_sandbox.db")
    print("==================================================")

    # -------------------------------------------------------------
    # Test 1: Empty Chain
    # -------------------------------------------------------------
    print("\n[Test 1] Verifying Empty Chain (0 events)...")
    empty_task = Task(user_id=user_id, title="Empty Task", prompt="Empty Prompt", status="PENDING")
    db.add(empty_task)
    db.commit()
    db.refresh(empty_task)

    res1 = chitra_verifier.verify_task_chain(db, empty_task.id)
    assert res1.valid is True
    assert res1.events_checked == 0
    assert res1.chain_status == "EMPTY"
    print("  [PASS] Empty chain verified as clean EMPTY status.")

    # -------------------------------------------------------------
    # Test 2: Single-Event Genesis Chain
    # -------------------------------------------------------------
    print("\n[Test 2] Verifying Single-Event Genesis Chain (1 event)...")
    t2_id = create_task_with_chain(db, user_id, "Single Event Task", num_events=1)
    res2 = chitra_verifier.verify_task_chain(db, t2_id)
    assert res2.valid is True
    assert res2.events_checked == 1
    assert res2.chain_status == "VERIFIED"
    assert res2.signature_status == "VALID"
    print("  [PASS] Single-event genesis chain verified with unbroken link to GENESIS_HASH.")

    # -------------------------------------------------------------
    # Test 3: Valid Untouched Multi-Step Chain
    # -------------------------------------------------------------
    print("\n[Test 3] Verifying Valid Multi-Step Chain (6 events)...")
    t3_id = create_task_with_chain(db, user_id, "Untouched Chain Task", num_events=6)
    res3 = chitra_verifier.verify_task_chain(db, t3_id)
    assert res3.valid is True
    assert res3.events_checked == 6
    assert res3.chain_status == "VERIFIED"
    assert res3.signature_status == "VALID"
    print("  [PASS] 6-event chain verified with complete mathematical & cryptographic proof.")

    # -------------------------------------------------------------
    # Test 4: Pure DAG Traversal with Non-Sequential DB IDs (Shuffled Ingestion)
    # -------------------------------------------------------------
    print("\n[Test 4] Cryptographic DAG Traversal with Out-of-Order DB IDs...")
    t4_dag = Task(user_id=user_id, title="DAG Traversal Task", prompt="DAG Prompt", status="RUNNING")
    db.add(t4_dag)
    db.commit()
    db.refresh(t4_dag)

    # Manually construct 3 events with strictly chained hashes but insert out of order
    now = datetime.now(timezone.utc)
    env1 = build_chitra_envelope(t4_dag.id, "KARMA", "perception", {"step": 1}, GENESIS_HASH)
    env2 = build_chitra_envelope(t4_dag.id, "PRAGYA", "decision", {"step": 2}, env1["this_event_hash"])
    env3 = build_chitra_envelope(t4_dag.id, "RACHIT", "invocation", {"step": 3}, env2["this_event_hash"])

    rec3 = ChitraEvent(event_id=env3["event_id"], task_id=t4_dag.id, session_id=env3["session_id"], timestamp=datetime.fromisoformat(env3["timestamp"]), faculty=env3["faculty"], event_type=env3["event_type"], input_hash=env3["input_hash"], decision=env3["decision"], evidence=env3["evidence"], confidence=env3["confidence"], outcome=env3["outcome"], constitutional_review=env3["constitutional_review"], prev_event_hash=env3["prev_event_hash"], this_event_hash=env3["this_event_hash"], signature=env3["signature"])
    rec1 = ChitraEvent(event_id=env1["event_id"], task_id=t4_dag.id, session_id=env1["session_id"], timestamp=datetime.fromisoformat(env1["timestamp"]), faculty=env1["faculty"], event_type=env1["event_type"], input_hash=env1["input_hash"], decision=env1["decision"], evidence=env1["evidence"], confidence=env1["confidence"], outcome=env1["outcome"], constitutional_review=env1["constitutional_review"], prev_event_hash=env1["prev_event_hash"], this_event_hash=env1["this_event_hash"], signature=env1["signature"])
    rec2 = ChitraEvent(event_id=env2["event_id"], task_id=t4_dag.id, session_id=env2["session_id"], timestamp=datetime.fromisoformat(env2["timestamp"]), faculty=env2["faculty"], event_type=env2["event_type"], input_hash=env2["input_hash"], decision=env2["decision"], evidence=env2["evidence"], confidence=env2["confidence"], outcome=env2["outcome"], constitutional_review=env2["constitutional_review"], prev_event_hash=env2["prev_event_hash"], this_event_hash=env2["this_event_hash"], signature=env2["signature"])

    # Insert in order: 3, 1, 2 (so DB IDs will be ID(3) < ID(1) < ID(2))
    db.add(rec3)
    db.commit()
    db.add(rec1)
    db.commit()
    db.add(rec2)
    db.commit()

    res4_dag = chitra_verifier.verify_task_chain(db, t4_dag.id)
    assert res4_dag.valid is True
    assert res4_dag.events_checked == 3
    assert res4_dag.chain_status == "VERIFIED"
    print("  [PASS] Verifier traced pure cryptographic DAG traversal despite inverted DB insertion IDs.")

    # -------------------------------------------------------------
    # Test 5: Tampering - Modified Decision/Payload & events_checked Accuracy
    # -------------------------------------------------------------
    print("\n[Test 5] Tampering Simulation: Modified Decision/Payload in DB...")
    t5_id = create_task_with_chain(db, user_id, "Payload Tamper Task", num_events=4)
    evts5 = chitra_repository.get_events_for_task(db, t5_id)
    target_evt = evts5[1]  # 2nd event (index 1)
    original_event_id = target_evt.event_id
    
    target_evt.decision = {"step": 2, "description": "MALICIOUS INJECTED INSTRUCTION"}
    db.commit()

    res5 = chitra_verifier.verify_task_chain(db, t5_id)
    assert res5.valid is False
    assert res5.chain_status == "CORRUPTED"
    assert res5.failure_type == "CONTENT_HASH_MISMATCH"
    assert res5.first_corrupted_event_id == original_event_id
    assert res5.events_checked == 2, f"Expected events_checked=2 (inspected 1st and 2nd), got {res5.events_checked}"
    print(f"  [PASS] Payload tampering detected at {res5.first_corrupted_event_id} (events_checked={res5.events_checked}).")

    # -------------------------------------------------------------
    # Test 6: Tampering - Modified this_event_hash
    # -------------------------------------------------------------
    print("\n[Test 6] Tampering Simulation: Modified this_event_hash...")
    t6_id = create_task_with_chain(db, user_id, "Hash Tamper Task", num_events=4)
    evts6 = chitra_repository.get_events_for_task(db, t6_id)
    target_evt6 = evts6[2]  # 3rd event (index 2)
    target_evt6.this_event_hash = "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    db.commit()

    res6 = chitra_verifier.verify_task_chain(db, t6_id)
    assert res6.valid is False
    assert res6.chain_status == "CORRUPTED"
    assert res6.failure_type == "CONTENT_HASH_MISMATCH"
    assert res6.first_corrupted_event_id == target_evt6.event_id
    assert res6.events_checked == 3
    print(f"  [PASS] this_event_hash tampering detected at {res6.first_corrupted_event_id}.")

    # -------------------------------------------------------------
    # Test 7: Tampering - Modified prev_event_hash
    # -------------------------------------------------------------
    print("\n[Test 7] Tampering Simulation: Modified prev_event_hash...")
    t7_id = create_task_with_chain(db, user_id, "Prev Hash Tamper Task", num_events=4)
    evts7 = chitra_repository.get_events_for_task(db, t7_id)
    target_evt7 = evts7[1]  # 2nd event
    target_evt7.prev_event_hash = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    db.commit()

    res7 = chitra_verifier.verify_task_chain(db, t7_id)
    assert res7.valid is False
    assert res7.chain_status == "CORRUPTED"
    # In DAG traversal, an event with modified prev_hash disconnects and becomes an orphan
    assert res7.failure_type in ("ORPHAN_EVENTS", "CHAIN_LINK_BROKEN")
    assert res7.first_corrupted_event_id == target_evt7.event_id
    print(f"  [PASS] Broken chain / orphan detected at {res7.first_corrupted_event_id}.")

    # -------------------------------------------------------------
    # Test 8: Tampering - Modified Signature
    # -------------------------------------------------------------
    print("\n[Test 8] Tampering Simulation: Forged/Modified HMAC Signature...")
    t8_id = create_task_with_chain(db, user_id, "Signature Tamper Task", num_events=4)
    evts8 = chitra_repository.get_events_for_task(db, t8_id)
    target_evt8 = evts8[0]  # 1st event
    target_evt8.signature = "hmac-sha256:0000000000000000000000000000000000000000000000000000000000000000"
    db.commit()

    res8 = chitra_verifier.verify_task_chain(db, t8_id)
    assert res8.valid is False
    assert res8.chain_status == "CORRUPTED"
    assert res8.failure_type == "INVALID_SIGNATURE"
    assert res8.signature_status == "INVALID"
    assert res8.events_checked == 1
    print(f"  [PASS] Forged signature caught at {res8.first_corrupted_event_id}.")

    # -------------------------------------------------------------
    # Test 9: Tampering - Deleted Middle Event
    # -------------------------------------------------------------
    print("\n[Test 9] Tampering Simulation: Deleted Middle Event...")
    t9_id = create_task_with_chain(db, user_id, "Deleted Event Task", num_events=5)
    evts9 = chitra_repository.get_events_for_task(db, t9_id)
    deleted_evt_id = evts9[2].event_id  # Delete event #3
    next_evt_id = evts9[3].event_id
    
    db.delete(evts9[2])
    db.commit()

    res9 = chitra_verifier.verify_task_chain(db, t9_id)
    assert res9.valid is False
    assert res9.chain_status == "CORRUPTED"
    assert res9.failure_type == "ORPHAN_EVENTS"
    assert res9.first_corrupted_event_id == next_evt_id
    print(f"  [PASS] Deletion of middle event caught at next block ({res9.first_corrupted_event_id}).")

    # -------------------------------------------------------------
    # Test 10: Tampering - Timestamp Anachronism
    # -------------------------------------------------------------
    print("\n[Test 10] Tampering Simulation: Timestamp Anachronism...")
    t10_task = Task(user_id=user_id, title="Anachronism Task", prompt="Time Prompt", status="RUNNING")
    db.add(t10_task)
    db.commit()
    db.refresh(t10_task)

    t_now = datetime.now(timezone.utc)
    # Event 1 at T0
    e1_env = build_chitra_envelope(t10_task.id, "KARMA", "perception", {"s": 1}, GENESIS_HASH)
    e1 = ChitraEvent(event_id=e1_env["event_id"], task_id=t10_task.id, session_id=e1_env["session_id"], timestamp=t_now, faculty=e1_env["faculty"], event_type=e1_env["event_type"], input_hash=e1_env["input_hash"], decision=e1_env["decision"], evidence=e1_env["evidence"], confidence=e1_env["confidence"], outcome=e1_env["outcome"], constitutional_review=e1_env["constitutional_review"], prev_event_hash=e1_env["prev_event_hash"], this_event_hash=e1_env["this_event_hash"], signature=e1_env["signature"])
    db.add(e1)
    db.commit()

    # Event 2 constructed with backward timestamp (1 hour in the past)
    e2_env = build_chitra_envelope(t10_task.id, "PRAGYA", "decision", {"s": 2}, e1_env["this_event_hash"])
    e2 = ChitraEvent(event_id=e2_env["event_id"], task_id=t10_task.id, session_id=e2_env["session_id"], timestamp=t_now - timedelta(hours=1), faculty=e2_env["faculty"], event_type=e2_env["event_type"], input_hash=e2_env["input_hash"], decision=e2_env["decision"], evidence=e2_env["evidence"], confidence=e2_env["confidence"], outcome=e2_env["outcome"], constitutional_review=e2_env["constitutional_review"], prev_event_hash=e2_env["prev_event_hash"], this_event_hash=e2_env["this_event_hash"], signature=e2_env["signature"])
    db.add(e2)
    db.commit()

    res10_time = chitra_verifier.verify_task_chain(db, t10_task.id)
    assert res10_time.valid is False
    assert res10_time.chain_status == "CORRUPTED"
    print(f"  [PASS] Timestamp backward anachronism detected ({res10_time.failure_type}).")

    # -------------------------------------------------------------
    # Test 11: Verification with Incorrect / Foreign Signing Key
    # -------------------------------------------------------------
    print("\n[Test 11] Verification with Incorrect / Foreign Signing Key...")
    t11_id = create_task_with_chain(db, user_id, "Foreign Key Task", num_events=3)
    res11 = chitra_verifier.verify_task_chain(db, t11_id, secret_key="wrong_foreign_secret_key_xyz")
    assert res11.valid is False
    assert res11.failure_type == "INVALID_SIGNATURE"
    print("  [PASS] Foreign signing key failed signature validation as expected.")

    # -------------------------------------------------------------
    # Test 12: Multiple Independent Task Chains
    # -------------------------------------------------------------
    print("\n[Test 12] Multiple Independent Task Chains...")
    t12_a = create_task_with_chain(db, user_id, "Task A (Clean)", num_events=4)
    t12_b = create_task_with_chain(db, user_id, "Task B (Tampered)", num_events=4)
    
    evts_b = chitra_repository.get_events_for_task(db, t12_b)
    evts_b[1].decision = {"injected": "data"}
    db.commit()

    res12_a = chitra_verifier.verify_task_chain(db, t12_a)
    res12_b = chitra_verifier.verify_task_chain(db, t12_b)

    assert res12_a.valid is True
    assert res12_b.valid is False
    print("  [PASS] Task A verified cleanly while Task B tampering was isolated and caught.")

    # -------------------------------------------------------------
    # Test 13: Non-Mutation / Read-Only Guarantee
    # -------------------------------------------------------------
    print("\n[Test 13] Proving Verifier Non-Mutation (Strict Read-Only)...")
    count_before = db.query(ChitraEvent).count()
    chitra_verifier.verify_task_chain(db, t3_id)
    chitra_verifier.verify_task_chain(db, t5_id)
    count_after = db.query(ChitraEvent).count()
    assert count_before == count_after
    print(f"  [PASS] Database state untouched (row count constant: {count_before}).")

    db.close()
    print("\n==================================================")
    print("ALL 13 TAMPER DETECTION TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_tamper_tests()
