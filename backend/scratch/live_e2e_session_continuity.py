import sys
sys.path.insert(0, ".")
from app.db.database import SessionLocal, engine
from app.models.task import Task
from app.models.user import User
from agents.graph import brahma_app
from sqlalchemy import text

def demo_live_e2e_session_continuity():
    db = SessionLocal()
    try:
        # Create test user for session continuity
        user = db.query(User).filter(User.username == "user_session_e2e").first()
        if not user:
            user = User(username="user_session_e2e", hashed_password="pass", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        user_id = user.id
        tenant_id = f"tenant_{user_id}"
        session_id = "ses_e2e_continuity_100"

        # Task 1 (Turn 1)
        task1 = Task(title="Turn 1 Task", prompt="My secret passcode is SKYWALKER-99.", status="PENDING", risk_level="LOW", user_id=user_id)
        db.add(task1)
        db.commit()
        db.refresh(task1)

        state1 = {
            "task_id": task1.id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "trace_id": f"trace_{task1.id}",
            "intent": "My secret passcode is SKYWALKER-99.",
            "errors": []
        }
        res1 = brahma_app.invoke(state1)
        print("TURN 1 EXECUTION COMPLETE.")
        print("Turn 1 Status:", res1.get("status"))
        print("Turn 1 Memory Context loaded by SMRITI:", repr(res1.get("memory_context")))

        # Task 2 (Turn 2, same session_id)
        task2 = Task(title="Turn 2 Task", prompt="What is my secret passcode?", status="PENDING", risk_level="LOW", user_id=user_id)
        db.add(task2)
        db.commit()
        db.refresh(task2)

        state2 = {
            "task_id": task2.id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "trace_id": f"trace_{task2.id}",
            "intent": "What is my secret passcode?",
            "errors": []
        }
        res2 = brahma_app.invoke(state2)
        print("\nTURN 2 EXECUTION COMPLETE.")
        print("Turn 2 Status:", res2.get("status"))
        print("Turn 2 Memory Context loaded by SMRITI from Turn 1:")
        print("==================================================")
        print(res2.get("memory_context"))
        print("==================================================")

        # Inspect PostgreSQL memory table rows for this session
        print("\nPOSTGRESQL MEMORY TABLE ROWS FOR SESSION:", session_id)
        rows = db.execute(text("SELECT id, tenant_id, session_id, task_id, content, memory_type, created_at FROM memory WHERE session_id = :ses ORDER BY id ASC"), {"ses": session_id}).fetchall()
        for r in rows:
            print(dict(r._mapping))

    finally:
        db.close()

if __name__ == "__main__":
    demo_live_e2e_session_continuity()
