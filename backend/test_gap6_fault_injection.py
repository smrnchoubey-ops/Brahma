import logging
import io
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app, logger as main_logger
from app.db.database import SessionLocal
from app.models.user import User
from app.models.task import Task
from app.models.learning_pattern import LearningPattern
from app.core.security import create_access_token, get_password_hash
from app.core.learning.service import LearningService

def mock_brahma_invoke(state):
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
    print("REAL FAULT INJECTION & FAIL-OPEN LOG VERIFICATION")
    print("==================================================================")

    # Setup logger to capture warning messages
    log_capture_string = io.StringIO()
    ch = logging.StreamHandler(log_capture_string)
    ch.setLevel(logging.WARNING)
    formatter = logging.Formatter('%(levelname)s [%(name)s]: %(message)s')
    ch.setFormatter(formatter)
    
    # Attach to main logger and root logger
    logging.getLogger().addHandler(ch)
    main_logger.addHandler(ch)
    main_logger.setLevel(logging.DEBUG)

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "user_gap6_fault_test").first()
        if not user:
            user = User(
                username="user_gap6_fault_test",
                hashed_password=get_password_hash("password123")
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        user_id = user.id
        tenant_id = f"tenant_{user_id}"

        # Clean previous tasks/patterns for this tenant
        db.query(Task).filter(Task.user_id == user_id).delete()
        db.query(LearningPattern).filter(LearningPattern.tenant_id == tenant_id).delete()
        db.commit()

        # Seed 2 completed tasks so that the next task completion triggers extraction (3 total)
        for i in range(1, 3):
            t = Task(
                title=f"Prior Task {i}",
                prompt=f"Prior prompt {i}",
                status="COMPLETED",
                user_id=user_id,
                execution_result={"tool": "code_analyzer", "duration_ms": 100.0}
            )
            db.add(t)
        db.commit()

    token = create_access_token(data={"sub": "user_gap6_fault_test", "id": user_id})
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)

    print("\n[1] Injecting fault into LearningService.extract_pattern...")
    
    def faulty_extract_pattern(*args, **kwargs):
        raise RuntimeError("CRITICAL_SIMULATED_FAULT: LearningService extraction algorithm crashed due to corrupted vector state!")

    with patch.object(LearningService, "extract_pattern", side_effect=faulty_extract_pattern):
        with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke):
            print("\n[2] Submitting 3rd task via API (POST /tasks/) with fault injection active...")
            resp = client.post(
                "/tasks/",
                json={"title": "Task Under Extraction Fault", "prompt": "Execute task that will trigger faulty extractor"},
                headers=headers
            )
            
            print(f"\n[3] HTTP Response Verification:")
            print(f"  HTTP Status Code:   {resp.status_code} (Expected: 200 OK)")
            print(f"  Response Body:      {resp.json()}")
            assert resp.status_code == 200
            task_id = resp.json()["task_id"]

            # Small sleep purely in test harness to give background thread time to log
            import time
            time.sleep(0.5)

            with SessionLocal() as db:
                db_task = db.query(Task).filter(Task.id == task_id).first()
                print(f"\n[4] Database Task Record Verification:")
                print(f"  Task ID:            {db_task.id}")
                print(f"  Task Status:        {db_task.status} (Expected: COMPLETED)")
                print(f"  Task User ID:       {db_task.user_id}")
                assert db_task.status == "COMPLETED"

    print("\n[5] Captured Background Logger Output:")
    log_output = log_capture_string.getvalue()
    print("------------------------------------------------------------------")
    print(log_output.strip())
    print("------------------------------------------------------------------")

    assert "F14 background pattern extraction failed for tenant" in log_output
    assert "CRITICAL_SIMULATED_FAULT" in log_output
    print("\n[PASS] Verified: Background extraction error was caught and logged cleanly, task returned HTTP 200 and completed with zero degradation.")

if __name__ == "__main__":
    main()
