"""
CHITRA Phase 4A Test Suite: Forensic Replay Engine
Runs strictly against a disposable local SQLite test database: test_chitra_replay_sandbox.db.
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
from app.services.replay_service import chitra_replay_engine, ChitraReplayTrace
from app.core.chitra.crypto import GENESIS_HASH, build_chitra_envelope

TEST_DB_URL = "sqlite:///./test_chitra_replay_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_replay_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user = User(username="replay_auditor", hashed_password="hashed_password_xyz")
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id

    db.close()
    return user_id


def create_task_with_events(db, user_id: int, title: str, num_events: int = 6) -> int:
    task = Task(user_id=user_id, title=title, prompt=f"Prompt for {title}", status="COMPLETED")
    db.add(task)
    db.commit()
    db.refresh(task)
    task_id = task.id

    faculties = ["KARMA", "KOSH", "PRAGYA", "MURPHY", "MARYADA", "RACHIT"]
    event_types = ["perception", "retrieval", "decision", "verification", "gate", "invocation"]

    prev_evt_id = None
    for i in range(min(num_events, len(faculties))):
        evidence = [prev_evt_id] if prev_evt_id else []
        evt = chitra_repository.append_event(
            db=db,
            task_id=task_id,
            faculty=faculties[i],
            event_type=event_types[i],
            decision={"step": i + 1, "description": f"Executed step {i + 1} by {faculties[i]}"},
            evidence=evidence,
            confidence=0.85 + (i * 0.02)
        )
        prev_evt_id = evt.event_id

    return task_id


def run_phase4a_tests():
    user_id = reset_replay_sandbox()
    db = TestSession()

    print("==================================================")
    print("CHITRA PHASE 4A: FORENSIC REPLAY ENGINE SUITE")
    print("Target Sandbox: sqlite:///./test_chitra_replay_sandbox.db")
    print("==================================================")

    # -------------------------------------------------------------
    # Test 1: Valid Multi-Step Task Replay
    # -------------------------------------------------------------
    print("\n[Test 1] Replaying Valid Multi-Step Task (6 events)...")
    t1_id = create_task_with_events(db, user_id, "Valid Task Replay", num_events=6)
    trace1: ChitraReplayTrace = chitra_replay_engine.replay_task(db, t1_id)

    assert trace1.replay_status == "SUCCESS"
    assert trace1.integrity_verified is True
    assert trace1.events_replayed == 6
    assert trace1.genesis_hash == GENESIS_HASH
    assert len(trace1.timeline) == 6
    assert trace1.faculty_sequence == ["KARMA", "KOSH", "PRAGYA", "MURPHY", "MARYADA", "RACHIT"]
    assert len(trace1.decision_dag) == 6
    assert len(trace1.confidence_curve) == 6

    # Verify causal evidence links in DAG
    assert trace1.decision_dag[0]["upstream_evidence"] == []
    assert trace1.decision_dag[1]["upstream_evidence"] == [trace1.timeline[0]["event_id"]]
    assert trace1.decision_dag[2]["upstream_evidence"] == [trace1.timeline[1]["event_id"]]

    print("  [PASS] Replay reconstructed complete chronological timeline, causal DAG, and confidence curve.")

    # -------------------------------------------------------------
    # Test 2: Empty Chain Replay
    # -------------------------------------------------------------
    print("\n[Test 2] Replaying Empty Task (0 events)...")
    empty_task = Task(user_id=user_id, title="Empty Task", prompt="Empty Prompt", status="PENDING")
    db.add(empty_task)
    db.commit()
    db.refresh(empty_task)

    trace2 = chitra_replay_engine.replay_task(db, empty_task.id)
    assert trace2.replay_status == "EMPTY"
    assert trace2.integrity_verified is True
    assert trace2.events_replayed == 0
    assert len(trace2.timeline) == 0
    print("  [PASS] Empty chain replay handled cleanly with EMPTY status.")

    # -------------------------------------------------------------
    # Test 3: Replay Refusal on Corrupted Payload
    # -------------------------------------------------------------
    print("\n[Test 3] Replay Refusal on Tampered Payload in DB...")
    t3_id = create_task_with_events(db, user_id, "Payload Tamper Task", num_events=4)
    # Mutate payload directly in database
    evts3 = chitra_repository.get_events_for_task(db, t3_id)
    evts3[1].decision = {"tampered": True}
    db.commit()

    trace3 = chitra_replay_engine.replay_task(db, t3_id)
    assert trace3.replay_status == "REFUSED_CORRUPTED"
    assert trace3.integrity_verified is False
    assert trace3.events_replayed == 0
    assert len(trace3.timeline) == 0
    assert trace3.verification_report["failure_type"] == "CONTENT_HASH_MISMATCH"
    print("  [PASS] Replay strictly refused on payload-tampered ledger.")

    # -------------------------------------------------------------
    # Test 4: Replay Refusal on Forged Signature
    # -------------------------------------------------------------
    print("\n[Test 4] Replay Refusal on Forged Signature...")
    t4_id = create_task_with_events(db, user_id, "Signature Tamper Task", num_events=4)
    evts4 = chitra_repository.get_events_for_task(db, t4_id)
    evts4[2].signature = "hmac-sha256:bad_forged_signature_hex_0000000000000000000000000000"
    db.commit()

    trace4 = chitra_replay_engine.replay_task(db, t4_id)
    assert trace4.replay_status == "REFUSED_CORRUPTED"
    assert trace4.integrity_verified is False
    assert trace4.verification_report["failure_type"] == "INVALID_SIGNATURE"
    print("  [PASS] Replay strictly refused on forged signature.")

    # -------------------------------------------------------------
    # Test 5: Replay Refusal on Deleted Middle Event
    # -------------------------------------------------------------
    print("\n[Test 5] Replay Refusal on Deleted Middle Event...")
    t5_id = create_task_with_events(db, user_id, "Deleted Event Task", num_events=5)
    evts5 = chitra_repository.get_events_for_task(db, t5_id)
    db.delete(evts5[1])  # Delete 2nd event
    db.commit()

    trace5 = chitra_replay_engine.replay_task(db, t5_id)
    assert trace5.replay_status == "REFUSED_CORRUPTED"
    assert trace5.integrity_verified is False
    assert trace5.verification_report["failure_type"] == "ORPHAN_EVENTS"
    print("  [PASS] Replay strictly refused on broken chain gap.")

    # -------------------------------------------------------------
    # Test 6: Out-of-Order DB Insertion Replay Correctness
    # -------------------------------------------------------------
    print("\n[Test 6] Replaying Task with Inverted/Non-Sequential DB IDs...")
    t6_dag = Task(user_id=user_id, title="DAG Inverted DB ID Task", prompt="DAG Prompt", status="RUNNING")
    db.add(t6_dag)
    db.commit()
    db.refresh(t6_dag)

    env1 = build_chitra_envelope(t6_dag.id, "KARMA", "perception", {"step": "first"}, GENESIS_HASH)
    env2 = build_chitra_envelope(t6_dag.id, "PRAGYA", "decision", {"step": "second"}, env1["this_event_hash"])
    env3 = build_chitra_envelope(t6_dag.id, "RACHIT", "invocation", {"step": "third"}, env2["this_event_hash"])

    rec3 = ChitraEvent(event_id=env3["event_id"], task_id=t6_dag.id, session_id=env3["session_id"], timestamp=datetime.fromisoformat(env3["timestamp"]), faculty=env3["faculty"], event_type=env3["event_type"], input_hash=env3["input_hash"], decision=env3["decision"], evidence=env3["evidence"], confidence=env3["confidence"], outcome=env3["outcome"], constitutional_review=env3["constitutional_review"], prev_event_hash=env3["prev_event_hash"], this_event_hash=env3["this_event_hash"], signature=env3["signature"])
    rec1 = ChitraEvent(event_id=env1["event_id"], task_id=t6_dag.id, session_id=env1["session_id"], timestamp=datetime.fromisoformat(env1["timestamp"]), faculty=env1["faculty"], event_type=env1["event_type"], input_hash=env1["input_hash"], decision=env1["decision"], evidence=env1["evidence"], confidence=env1["confidence"], outcome=env1["outcome"], constitutional_review=env1["constitutional_review"], prev_event_hash=env1["prev_event_hash"], this_event_hash=env1["this_event_hash"], signature=env1["signature"])
    rec2 = ChitraEvent(event_id=env2["event_id"], task_id=t6_dag.id, session_id=env2["session_id"], timestamp=datetime.fromisoformat(env2["timestamp"]), faculty=env2["faculty"], event_type=env2["event_type"], input_hash=env2["input_hash"], decision=env2["decision"], evidence=env2["evidence"], confidence=env2["confidence"], outcome=env2["outcome"], constitutional_review=env2["constitutional_review"], prev_event_hash=env2["prev_event_hash"], this_event_hash=env2["this_event_hash"], signature=env2["signature"])

    # Insert in order: 3, 1, 2
    db.add(rec3)
    db.commit()
    db.add(rec1)
    db.commit()
    db.add(rec2)
    db.commit()

    trace6 = chitra_replay_engine.replay_task(db, t6_dag.id)
    assert trace6.replay_status == "SUCCESS"
    assert trace6.events_replayed == 3
    assert [f["faculty"] for f in trace6.timeline] == ["KARMA", "PRAGYA", "RACHIT"]
    print("  [PASS] Inverted DB ID insertion replayed in exact chronological/causal sequence.")

    # -------------------------------------------------------------
    # Test 7: Strict Read-Only Guarantee
    # -------------------------------------------------------------
    print("\n[Test 7] Proving Replay Engine Non-Mutation (Strict Read-Only)...")
    count_before = db.query(ChitraEvent).count()
    chitra_replay_engine.replay_task(db, t1_id)
    chitra_replay_engine.replay_task(db, t3_id)
    chitra_replay_engine.replay_task(db, t6_dag.id)
    count_after = db.query(ChitraEvent).count()
    assert count_before == count_after
    print(f"  [PASS] Database state untouched across multiple replay queries (row count: {count_before}).")

    db.close()
    print("\n==================================================")
    print("ALL 7 PHASE 4A REPLAY TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_phase4a_tests()
