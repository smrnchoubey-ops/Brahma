import os
import sys
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import text

from main import app
from app.db.database import SessionLocal, engine
from app.models.user import User
from app.models.task import Task
from app.models.learning_pattern import LearningPattern
from app.core.security import create_access_token, get_password_hash

def mock_brahma_invoke(state):
    """Deterministic agent execution result without external LLM network dependency."""
    return {
        "status": "RACHIT_EXECUTED",
        "plan": {"summary": "Execute code analysis", "tool": "code_analyzer"},
        "risk_report": {"risk_level": "LOW", "recommendation": "Proceed"},
        "policy_verdict": {"approved": True, "justification": "Safe deterministic execution"},
        "execution_result": {
            "status": "SUCCESS",
            "tool": "code_analyzer",
            "duration_ms": 115.0,
            "output": "Code analysis completed with 0 errors"
        }
    }

def main():
    print("==================================================================")
    print("GAP #6 LIVE EVIDENCE: REAL TASK COMPLETION & F14 AUTO-TRIGGER")
    print("==================================================================")

    # 1. Setup isolated test user in PostgreSQL
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "user_gap6_test").first()
        if not user:
            user = User(
                username="user_gap6_test",
                hashed_password=get_password_hash("password123")
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        user_id = user.id
        tenant_id = f"tenant_{user_id}"

        # Clean up any previous test tasks and learning patterns for this tenant
        db.query(Task).filter(Task.user_id == user_id).delete()
        db.query(LearningPattern).filter(LearningPattern.tenant_id == tenant_id).delete()
        db.commit()

        # Initial baseline check
        pattern_count_0 = db.query(LearningPattern).filter(LearningPattern.tenant_id == tenant_id).count()
        print(f"[*] Initial state for {tenant_id}: {pattern_count_0} patterns in PostgreSQL learning_patterns table.")

    # Generate auth token
    token = create_access_token(data={"sub": "user_gap6_test", "id": user_id})
    headers = {"Authorization": f"Bearer {token}"}

    client = TestClient(app)

    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke):
        # -------------------------------------------------------------
        # STEP 1: Submit Task 1 via real API
        # -------------------------------------------------------------
        print("\n--- [STEP 1] Submitting Task 1 via API (POST /tasks/) ---")
        t0 = time.time()
        resp1 = client.post(
            "/tasks/",
            json={"title": "Analyze Code 1", "prompt": "Review code quality and security for repo 1"},
            headers=headers
        )
        t1 = time.time()
        duration1 = (t1 - t0) * 1000.0

        print(f"[*] Task 1 Response Status: {resp1.status_code} (in {duration1:.2f} ms)")
        print(f"[*] Task 1 Response JSON: {resp1.json()}")
        assert resp1.status_code == 200
        task1_id = resp1.json()["task_id"]

        # Allow background thread worker to complete
        time.sleep(0.3)

        with SessionLocal() as db:
            t1_record = db.query(Task).filter(Task.id == task1_id).first()
            print(f"[*] Task 1 DB status: {t1_record.status}")
            p_count_1 = db.query(LearningPattern).filter(LearningPattern.tenant_id == tenant_id).count()
            print(f"[*] PostgreSQL learning_patterns count after Task 1: {p_count_1} (Expected: 0, since completed episodes < 3)")
            assert p_count_1 == 0

        # -------------------------------------------------------------
        # STEP 2: Submit Task 2 via real API
        # -------------------------------------------------------------
        print("\n--- [STEP 2] Submitting Task 2 via API (POST /tasks/) ---")
        t0 = time.time()
        resp2 = client.post(
            "/tasks/",
            json={"title": "Analyze Code 2", "prompt": "Review code quality and security for repo 2"},
            headers=headers
        )
        t1 = time.time()
        duration2 = (t1 - t0) * 1000.0

        print(f"[*] Task 2 Response Status: {resp2.status_code} (in {duration2:.2f} ms)")
        print(f"[*] Task 2 Response JSON: {resp2.json()}")
        assert resp2.status_code == 200
        task2_id = resp2.json()["task_id"]

        # Allow background thread worker to complete
        time.sleep(0.3)

        with SessionLocal() as db:
            t2_record = db.query(Task).filter(Task.id == task2_id).first()
            print(f"[*] Task 2 DB status: {t2_record.status}")
            p_count_2 = db.query(LearningPattern).filter(LearningPattern.tenant_id == tenant_id).count()
            print(f"[*] PostgreSQL learning_patterns count after Task 2: {p_count_2} (Expected: 0, since completed episodes < 3)")
            assert p_count_2 == 0

        # -------------------------------------------------------------
        # STEP 3: Submit Task 3 via real API (Threshold k_min=3 met)
        # -------------------------------------------------------------
        print("\n--- [STEP 3] Submitting Task 3 via API (POST /tasks/) ---")
        t0 = time.time()
        resp3 = client.post(
            "/tasks/",
            json={"title": "Analyze Code 3", "prompt": "Review code quality and security for repo 3"},
            headers=headers
        )
        t1 = time.time()
        duration3 = (t1 - t0) * 1000.0

        print(f"[*] Task 3 Response Status: {resp3.status_code} (in {duration3:.2f} ms)")
        print(f"[*] Task 3 Response JSON: {resp3.json()}")
        assert resp3.status_code == 200
        task3_id = resp3.json()["task_id"]

        # Allow background thread worker to complete F14 extraction & persistence
        time.sleep(0.5)

        with SessionLocal() as db:
            t3_record = db.query(Task).filter(Task.id == task3_id).first()
            print(f"[*] Task 3 DB status: {t3_record.status}")
            p_count_3 = db.query(LearningPattern).filter(LearningPattern.tenant_id == tenant_id).count()
            print(f"[*] PostgreSQL learning_patterns count after Task 3: {p_count_3} (Expected: 1, auto-created by F14 trigger)")
            assert p_count_3 >= 1

            pattern = db.query(LearningPattern).filter(LearningPattern.tenant_id == tenant_id).first()
            print("\n--- REAL POSTGRESQL ROW DETAILS IN learning_patterns ---")
            print(f"  Pattern ID:              {pattern.pattern_id}")
            print(f"  Tenant ID:               {pattern.tenant_id}")
            print(f"  Status:                  {pattern.status}")
            print(f"  Pattern Type:            {pattern.pattern_type}")
            print(f"  Name:                    {pattern.name}")
            print(f"  Fingerprint:             {pattern.fingerprint}")
            print(f"  Confidence:              {pattern.confidence}")
            print(f"  Constitutional Approved: {pattern.constitutional_approved}")
            print(f"  Shadow Passed:           {pattern.shadow_passed}")
            print(f"  Source Episode IDs:      {pattern.source_episode_ids}")
            print(f"  Created At:              {pattern.created_at}")

            assert pattern.status == "CANDIDATE"
            assert pattern.constitutional_approved is False

    # -------------------------------------------------------------
    # STEP 4: NEGATIVE TEST — Fail-Open Safety Verification
    # -------------------------------------------------------------
    print("\n--- [STEP 4] NEGATIVE TEST: Fail-Open Verification ---")
    import main as app_main
    original_worker = app_main._trigger_f14_pattern_extraction_worker
    
    def buggy_worker(*args, **kwargs):
        raise RuntimeError("Simulated internal F14 extraction failure")
    
    app_main._trigger_f14_pattern_extraction_worker = buggy_worker

    try:
        with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke):
            resp_neg = client.post(
                "/tasks/",
                json={"title": "Analyze Code 4 (Fail-Open Test)", "prompt": "Review code quality and security for repo 4"},
                headers=headers
            )
            print(f"[*] Negative Test Task Response Status: {resp_neg.status_code}")
            print(f"[*] Negative Test Task Response JSON: {resp_neg.json()}")
            assert resp_neg.status_code == 200
            neg_task_id = resp_neg.json()["task_id"]

            time.sleep(0.3)

            with SessionLocal() as db:
                neg_task = db.query(Task).filter(Task.id == neg_task_id).first()
                print(f"[*] Negative Test Task DB Status: {neg_task.status}")
                assert neg_task.status == "COMPLETED"
                print("  [PASS] Task completed successfully despite F14 background failure (Strictly Fail-Open).")
    finally:
        app_main._trigger_f14_pattern_extraction_worker = original_worker

    print("\n==================================================================")
    print("ALL LIVE EVIDENCE TESTS PASSED SUCCESSFULLY!")
    print("==================================================================")

if __name__ == "__main__":
    main()
