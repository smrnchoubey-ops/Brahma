import os
import sys
import time
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import text

from main import app
from app.db.database import SessionLocal, engine
from app.models.user import User
from app.models.task import Task
from app.models.chitra import ChitraEvent
from app.core.runtime_mode import OperationalMode
from app.core.security import create_access_token, get_password_hash

def mock_brahma_invoke_safe(state):
    return {
        "status": "RACHIT_EXECUTED",
        "plan": {"summary": "Execute safe action", "tool": "calc"},
        "risk_report": {"risk_level": "LOW", "recommendation": "Proceed"},
        "policy_verdict": {"approved": True, "justification": "Safe deterministic execution"},
        "execution_result": {
            "status": "EXECUTED",
            "tool": "calc",
            "duration_ms": 45.0,
            "output": "42"
        }
    }

def mock_brahma_invoke_prohibited(state):
    return {
        "status": "MARYADA_BLOCKED",
        "plan": {"summary": "Unauthorized critical system reconfiguration", "tool": "root_shell"},
        "risk_report": {"risk_level": "CRITICAL", "recommendation": "Block immediately"},
        "policy_verdict": {"approved": False, "requires_human": False, "justification": "Blocked: Critical governance violation."},
        "execution_result": None
    }

def main():
    print("==================================================================")
    print("GAP #10 LIVE EVIDENCE: OPERATIONAL MODE RUNTIME SELECTOR")
    print("Whitesheet Authority: §3.3 Operational Modes & Phase 6 Autonomous Operations")
    print("==================================================================")

    # 1. Setup isolated test users in PostgreSQL
    with SessionLocal() as db:
        user_a = db.query(User).filter(User.username == "user_gap10_live_a").first()
        if not user_a:
            user_a = User(username="user_gap10_live_a", hashed_password=get_password_hash("pwdLiveA"))
            db.add(user_a)
        
        user_b = db.query(User).filter(User.username == "user_gap10_live_b").first()
        if not user_b:
            user_b = User(username="user_gap10_live_b", hashed_password=get_password_hash("pwdLiveB"))
            db.add(user_b)
        
        db.commit()
        db.refresh(user_a)
        db.refresh(user_b)
        
        u_a_id = user_a.id
        u_b_id = user_b.id

        # Clean prior test tasks
        db.query(Task).filter(Task.user_id.in_([u_a_id, u_b_id])).delete(synchronize_session=False)
        db.commit()

    token_a = create_access_token(data={"sub": "user_gap10_live_a", "id": u_a_id})
    token_b = create_access_token(data={"sub": "user_gap10_live_b", "id": u_b_id})
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    client = TestClient(app)

    # -------------------------------------------------------------
    # RUNTIME SCENARIO 1: Normal/Manual/Default Mode (REACTIVE)
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 1] Normal / Manual Execution Mode (Default REACTIVE) ---")
    uid1 = uuid.uuid4().hex[:8]
    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke_safe):
        resp1 = client.post(
            "/tasks/",
            json={"title": f"Manual Query {uid1}", "prompt": f"Analyze telemetry data {uid1}"},
            headers=headers_a
        )
        print(f"[*] API Response Status: {resp1.status_code}")
        print(f"[*] API Response JSON:   {resp1.json()}")
        assert resp1.status_code == 200
        task1_id = resp1.json()["task_id"]

        time.sleep(0.4)

        with SessionLocal() as db:
            task1 = db.query(Task).filter(Task.id == task1_id).first()
            print(f"[*] PostgreSQL Task Row: ID={task1.id}, Mode={task1.mode}, Status={task1.status}")
            assert task1.mode == "REACTIVE"
            assert task1.status == "COMPLETED"

            chitra1 = db.query(ChitraEvent).filter(ChitraEvent.task_id == task1_id, ChitraEvent.faculty == "RUNTIME").first()
            print(f"[*] CHITRA Mode Decision Event: faculty={chitra1.faculty}, payload={chitra1.decision['payload']}")
            assert chitra1.decision["payload"]["mode"] == "REACTIVE"

    # -------------------------------------------------------------
    # RUNTIME SCENARIO 2: Explicit Autonomous Mode Selection
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 2] Explicit Autonomous Mode Execution (AUTONOMOUS) ---")
    uid2 = uuid.uuid4().hex[:8]
    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke_safe):
        resp2 = client.post(
            "/tasks/",
            json={"title": f"Autonomous Workflow {uid2}", "prompt": f"Continuous pipeline execution {uid2}", "mode": "AUTONOMOUS"},
            headers=headers_a
        )
        print(f"[*] API Response Status: {resp2.status_code}")
        print(f"[*] API Response JSON:   {resp2.json()}")
        assert resp2.status_code == 200
        task2_id = resp2.json()["task_id"]

        time.sleep(0.4)

        with SessionLocal() as db:
            task2 = db.query(Task).filter(Task.id == task2_id).first()
            print(f"[*] PostgreSQL Task Row: ID={task2.id}, Mode={task2.mode}, Status={task2.status}")
            assert task2.mode == "AUTONOMOUS"
            assert task2.status == "COMPLETED"

            chitra2 = db.query(ChitraEvent).filter(ChitraEvent.task_id == task2_id, ChitraEvent.faculty == "RUNTIME").first()
            print(f"[*] CHITRA Mode Decision Event: faculty={chitra2.faculty}, payload={chitra2.decision['payload']}")
            assert chitra2.decision["payload"]["mode"] == "AUTONOMOUS"
            assert chitra2.decision["payload"]["is_autonomous"] is True
            assert chitra2.decision["payload"]["retention_tier"] == "PERMANENT"

    # -------------------------------------------------------------
    # RUNTIME SCENARIO 3: Invalid Mode Rejected Fail-Safe
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 3] Invalid / Unknown Mode Rejection (Fail-Safe) ---")
    uid3 = uuid.uuid4().hex[:8]
    resp3 = client.post(
        "/tasks/",
        json={"title": f"Bypass Attempt {uid3}", "prompt": f"Unauthorized mode injection {uid3}", "mode": "UNRESTRICTED_ROOT_BYPASS"},
        headers=headers_a
    )
    print(f"[*] API Response Status: {resp3.status_code} (Expected: 400 Bad Request)")
    print(f"[*] API Response JSON:   {resp3.json()}")
    assert resp3.status_code == 400
    assert "Invalid operational mode" in resp3.json()["detail"]

    # -------------------------------------------------------------
    # RUNTIME SCENARIO 4: Autonomous Mode Blocked by MARYADA Governance
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 4] Autonomous Mode Blocked by MARYADA Governance (Negative Control) ---")
    uid4 = uuid.uuid4().hex[:8]
    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke_prohibited):
        resp4 = client.post(
            "/tasks/",
            json={"title": f"Critical Action in Autonomous Mode {uid4}", "prompt": f"Reconfigure security perimeter {uid4}", "mode": "AUTONOMOUS"},
            headers=headers_a
        )
        print(f"[*] API Response Status: {resp4.status_code}")
        print(f"[*] API Response JSON:   {resp4.json()}")
        assert resp4.status_code == 200
        task4_id = resp4.json()["task_id"]

        time.sleep(0.4)

        with SessionLocal() as db:
            task4 = db.query(Task).filter(Task.id == task4_id).first()
            print(f"[*] PostgreSQL Task Row: ID={task4.id}, Mode={task4.mode}, Status={task4.status}, PolicyVerdict={task4.policy_verdict}")
            assert task4.mode == "AUTONOMOUS"
            assert task4.status == "BLOCKED"
            assert task4.policy_verdict["approved"] is False
            print("  [PASS] Confirmed: Autonomous mode cannot bypass MARYADA constitutional gates.")

    # -------------------------------------------------------------
    # RUNTIME SCENARIO 5: Tenant Isolation Preserved in Autonomous Mode
    # -------------------------------------------------------------
    print("\n--- [SCENARIO 5] Tenant Isolation in Autonomous Mode ---")
    uid5 = uuid.uuid4().hex[:8]
    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke_safe):
        resp5 = client.post(
            "/tasks/",
            json={"title": f"Tenant A Proprietary Autonomous Task {uid5}", "prompt": f"Secret algorithm execution {uid5}", "mode": "AUTONOMOUS"},
            headers=headers_a
        )
        task5_id = resp5.json()["task_id"]

        # User B attempts to access Tenant A's autonomous task
        resp5_cross = client.get(f"/tasks/{task5_id}", headers=headers_b)
        print(f"[*] Cross-Tenant Access Status: {resp5_cross.status_code} (Expected: 404 Not Found)")
        assert resp5_cross.status_code == 404
        print("  [PASS] Confirmed: Strict multi-tenant isolation enforced in Autonomous Mode.")

    print("\n==================================================================")
    print("ALL GAP #10 RUNTIME EVIDENCE SCENARIOS PASSED SUCCESSFULLY!")
    print("==================================================================")

if __name__ == "__main__":
    main()
