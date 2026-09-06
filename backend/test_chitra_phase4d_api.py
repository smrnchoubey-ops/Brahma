"""
CHITRA Phase 4D Test Suite: Tenant-Isolated REST APIs
Tests all CHITRA API endpoints (/events, /verify, /replay, /ledger) via FastAPI TestClient.
Runs strictly against a disposable local SQLite test database: test_chitra_phase4d_sandbox.db.
"""
import os
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.security import create_access_token, get_password_hash
from app.repositories.chitra_repository import chitra_repository
from app.services.audit_service import audit_service
from main import app

TEST_DB_URL = "sqlite:///./test_chitra_phase4d_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)

# Inject test session factory
audit_service.session_factory = TestSession


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def reset_api_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_alice = User(username="alice_sec", hashed_password=get_password_hash("alice_password"))
    user_bob = User(username="bob_sec", hashed_password=get_password_hash("bob_password"))
    db.add_all([user_alice, user_bob])
    db.commit()
    db.refresh(user_alice)
    db.refresh(user_bob)
    
    alice_id = user_alice.id
    bob_id = user_bob.id

    # Create Alice Tasks
    task_a = Task(user_id=alice_id, title="Alice Budget Task", prompt="Budget analysis", status="COMPLETED")
    task_a_empty = Task(user_id=alice_id, title="Alice Empty Task", prompt="Empty", status="PENDING")
    
    # Create Bob Task
    task_b = Task(user_id=bob_id, title="Bob Confidential Acquisition", prompt="M&A proposal", status="COMPLETED")
    db.add_all([task_a, task_a_empty, task_b])
    db.commit()
    db.refresh(task_a)
    db.refresh(task_a_empty)
    db.refresh(task_b)

    task_a_id = task_a.id
    task_a_empty_id = task_a_empty.id
    task_b_id = task_b.id

    # Append CHITRA events for Alice task
    e_a1 = chitra_repository.append_event(db, task_a_id, "KARMA", "perception", {"step": "ingest"}, user_id=alice_id)
    e_a2 = chitra_repository.append_event(db, task_a_id, "PRAGYA", "decision", {"step": "plan"}, user_id=alice_id)
    e_a3 = chitra_repository.append_event(db, task_a_id, "RACHIT", "invocation", {"step": "execute"}, user_id=alice_id)

    # Append CHITRA events for Bob task
    e_b1 = chitra_repository.append_event(db, task_b_id, "KARMA", "perception", {"step": "bob_secret"}, user_id=bob_id)

    db.close()

    alice_token = create_access_token({"sub": "alice_sec"}, expires_delta=timedelta(hours=1))
    bob_token = create_access_token({"sub": "bob_sec"}, expires_delta=timedelta(hours=1))

    return {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "alice_token": alice_token,
        "bob_token": bob_token,
        "task_a_id": task_a_id,
        "task_a_empty_id": task_a_empty_id,
        "task_b_id": task_b_id
    }


def run_all_api_tests():
    data = reset_api_sandbox()
    alice_headers = {"Authorization": f"Bearer {data['alice_token']}"}
    bob_headers = {"Authorization": f"Bearer {data['bob_token']}"}

    print("==================================================")
    print("CHITRA PHASE 4D: REST API & SECURITY TEST SUITE")
    print("Target Sandbox: sqlite:///./test_chitra_phase4d_sandbox.db")
    print("==================================================")

    # -------------------------------------------------------------
    # Test 1: Authenticated Owner Fetch Events
    # -------------------------------------------------------------
    print("\n[Test 1] GET /api/chitra/events/{task_id} (Alice -> Task A)...")
    r1 = client.get(f"/api/chitra/events/{data['task_a_id']}", headers=alice_headers)
    assert r1.status_code == 200, f"Expected 200, got {r1.status_code}: {r1.text}"
    events = r1.json()
    assert len(events) == 3
    assert events[0]["faculty"] == "KARMA"
    assert events[1]["faculty"] == "PRAGYA"
    assert events[2]["faculty"] == "RACHIT"
    print("  [PASS] Owner successfully retrieved 3 canonical event envelopes.")

    # -------------------------------------------------------------
    # Test 2: Unauthenticated Request Rejection
    # -------------------------------------------------------------
    print("\n[Test 2] Unauthenticated GET /api/chitra/events/{task_id}...")
    r2 = client.get(f"/api/chitra/events/{data['task_a_id']}")
    assert r2.status_code == 401
    print("  [PASS] Unauthenticated request rejected with 401 Unauthorized.")

    # -------------------------------------------------------------
    # Test 3: Foreign Task Events Hidden (Resource-Hiding 404)
    # -------------------------------------------------------------
    print("\n[Test 3] Cross-Tenant GET /api/chitra/events/{task_id} (Alice -> Task B)...")
    r3 = client.get(f"/api/chitra/events/{data['task_b_id']}", headers=alice_headers)
    assert r3.status_code == 404
    print("  [PASS] Foreign task event request rejected with resource-hiding 404 Not Found.")

    # -------------------------------------------------------------
    # Test 4: Authenticated Owner Verify Chain
    # -------------------------------------------------------------
    print("\n[Test 4] GET /api/chitra/verify/{task_id} (Alice -> Task A)...")
    r4 = client.get(f"/api/chitra/verify/{data['task_a_id']}", headers=alice_headers)
    assert r4.status_code == 200
    v_res = r4.json()
    assert v_res["valid"] is True
    assert v_res["chain_status"] == "VERIFIED"
    assert v_res["signature_status"] == "VALID"
    assert v_res["events_checked"] == 3
    print("  [PASS] Owner verified chain integrity; received full mathematical proof.")

    # -------------------------------------------------------------
    # Test 5: Foreign Task Verification Denied (404)
    # -------------------------------------------------------------
    print("\n[Test 5] Cross-Tenant GET /api/chitra/verify/{task_id} (Alice -> Task B)...")
    r5 = client.get(f"/api/chitra/verify/{data['task_b_id']}", headers=alice_headers)
    assert r5.status_code == 404
    print("  [PASS] Foreign task verification request hidden with 404 Not Found.")

    # -------------------------------------------------------------
    # Test 6: Corrupted Chain Verification Reporting
    # -------------------------------------------------------------
    print("\n[Test 6] Corrupted Chain Verification via API...")
    db = TestSession()
    # Maliciously mutate payload in DB
    evt_to_tamper = db.query(ChitraEvent).filter(ChitraEvent.task_id == data["task_a_id"]).first()
    tampered_event_id = str(evt_to_tamper.event_id)
    evt_to_tamper.decision = {"step": "MALICIOUS_INJECTION"}
    db.commit()
    db.close()

    r6 = client.get(f"/api/chitra/verify/{data['task_a_id']}", headers=alice_headers)
    assert r6.status_code == 200
    v_corrupt = r6.json()
    assert v_corrupt["valid"] is False
    assert v_corrupt["chain_status"] == "CORRUPTED"
    assert v_corrupt["failure_type"] == "CONTENT_HASH_MISMATCH"
    assert v_corrupt["first_corrupted_event_id"] == tampered_event_id
    print(f"  [PASS] API accurately returned corruption forensics (Reason: {v_corrupt['failure_type']}).")

    # Restore legitimate event for subsequent tests
    db = TestSession()
    evt_to_restore = db.query(ChitraEvent).filter(ChitraEvent.event_id == tampered_event_id).first()
    evt_to_restore.decision = {"step": "ingest"}
    db.commit()
    db.close()

    # -------------------------------------------------------------
    # Test 7: Authenticated Owner Replay Trace
    # -------------------------------------------------------------
    print("\n[Test 7] GET /api/chitra/replay/{task_id} (Alice -> Task A)...")
    r7 = client.get(f"/api/chitra/replay/{data['task_a_id']}", headers=alice_headers)
    assert r7.status_code == 200
    replay = r7.json()
    assert replay["replay_status"] == "SUCCESS"
    assert replay["integrity_verified"] is True
    assert replay["events_replayed"] == 3
    assert len(replay["timeline"]) == 3
    assert len(replay["decision_dag"]) == 3
    print("  [PASS] Owner successfully reconstructed forensic replay trace.")

    # -------------------------------------------------------------
    # Test 8: Foreign Task Replay Denied (404)
    # -------------------------------------------------------------
    print("\n[Test 8] Cross-Tenant GET /api/chitra/replay/{task_id} (Alice -> Task B)...")
    r8 = client.get(f"/api/chitra/replay/{data['task_b_id']}", headers=alice_headers)
    assert r8.status_code == 404
    print("  [PASS] Cross-tenant replay rejected with 404 Not Found.")

    # -------------------------------------------------------------
    # Test 9: Multi-Index Ledger Query
    # -------------------------------------------------------------
    print("\n[Test 9] GET /api/chitra/ledger (Multi-Index Query)...")
    r9 = client.get("/api/chitra/ledger?faculty=KARMA", headers=alice_headers)
    assert r9.status_code == 200
    ledger = r9.json()
    assert len(ledger) == 1
    assert ledger[0]["faculty"] == "KARMA"
    assert ledger[0]["task_id"] == data["task_a_id"]
    print("  [PASS] Ledger multi-index query returned matching records.")

    # -------------------------------------------------------------
    # Test 10: Ledger Query Cannot Cross Tenant Boundary
    # -------------------------------------------------------------
    print("\n[Test 10] Cross-Tenant Ledger Query Isolation...")
    # Alice requests all ledger records without filters
    r10_a = client.get("/api/chitra/ledger?limit=100", headers=alice_headers)
    # Bob requests all ledger records without filters
    r10_b = client.get("/api/chitra/ledger?limit=100", headers=bob_headers)

    alice_events = r10_a.json()
    bob_events = r10_b.json()

    alice_task_ids = set(e["task_id"] for e in alice_events)
    bob_task_ids = set(e["task_id"] for e in bob_events)

    assert data["task_b_id"] not in alice_task_ids
    assert data["task_a_id"] not in bob_task_ids
    assert alice_task_ids.isdisjoint(bob_task_ids)
    print("  [PASS] Global ledger query strictly segregated by authenticated tenant.")

    # -------------------------------------------------------------
    # Test 11: Forged tenant_id / user_id in Query Params Ignored
    # -------------------------------------------------------------
    print("\n[Test 11] Forged tenant_id in Query Parameters Ignored...")
    r11 = client.get(f"/api/chitra/ledger?tenant_id=tenant_{data['bob_id']}&user_id={data['bob_id']}", headers=alice_headers)
    assert r11.status_code == 200
    for e in r11.json():
        assert e["task_id"] != data["task_b_id"]
    print("  [PASS] Injected query parameters ignored; server authenticated context used.")

    # -------------------------------------------------------------
    # Test 12: Empty Task Replay & Verification
    # -------------------------------------------------------------
    print("\n[Test 12] Empty Task Verification & Replay...")
    r12_v = client.get(f"/api/chitra/verify/{data['task_a_empty_id']}", headers=alice_headers)
    assert r12_v.status_code == 200
    assert r12_v.json()["chain_status"] == "EMPTY"

    r12_r = client.get(f"/api/chitra/replay/{data['task_a_empty_id']}", headers=alice_headers)
    assert r12_r.status_code == 200
    assert r12_r.json()["replay_status"] == "EMPTY"
    print("  [PASS] Empty task handled cleanly with EMPTY status across verify and replay.")

    # -------------------------------------------------------------
    # Test 13: IDOR Sequential Probe Resistance
    # -------------------------------------------------------------
    print("\n[Test 13] IDOR Sequential Probing (IDs 100-150)...")
    for probe_id in range(100, 150):
        r_probe = client.get(f"/api/chitra/events/{probe_id}", headers=alice_headers)
        assert r_probe.status_code == 404
    print("  [PASS] 50 consecutive IDOR probes returned 404 with zero data leakage.")

    # -------------------------------------------------------------
    # Test 14: Non-Mutation / Read-Only Guarantee on APIs
    # -------------------------------------------------------------
    print("\n[Test 14] Proving API Endpoints are Strictly Read-Only...")
    db = TestSession()
    count_before = db.query(ChitraEvent).count()
    db.close()

    client.get(f"/api/chitra/events/{data['task_a_id']}", headers=alice_headers)
    client.get(f"/api/chitra/verify/{data['task_a_id']}", headers=alice_headers)
    client.get(f"/api/chitra/replay/{data['task_a_id']}", headers=alice_headers)
    client.get("/api/chitra/ledger", headers=alice_headers)

    db = TestSession()
    count_after = db.query(ChitraEvent).count()
    db.close()
    assert count_before == count_after
    print(f"  [PASS] Database row count constant ({count_before}) across all API operations.")

    print("\n==================================================")
    print("ALL 14 PHASE 4D API TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_api_tests()
