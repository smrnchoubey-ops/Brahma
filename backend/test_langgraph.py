import os
import sys
import json
from unittest.mock import patch
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from agents.graph import brahma_app
from app.db.database import SessionLocal
from app.models.task import Task
from app.models.user import User

def get_real_task_id(intent: str, title: str) -> int:
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            user = User(username="testuser", hashed_password="pw")
            db.add(user)
            db.commit()
            db.refresh(user)
            
        task = Task(title=title, prompt=intent, user_id=user.id)
        db.add(task)
        db.commit()
        db.refresh(task)
        return task.id
    finally:
        db.close()

def print_path(state):
    print("\n--- Actual State Output ---")
    print("Errors:", state.get("errors", []))
    print("Risk Report:", str(state.get("risk_report", "None"))[:100] + "..." if state.get("risk_report") else "None")
    print("Policy Verdict:", json.dumps(state.get("policy_verdict", {}), indent=2))
    print("Execution Result:", state.get("execution_result"))
    print("-" * 30)

def test_success_path():
    print("\n" + "="*50)
    print("TEST: SUCCESS PATH")
    print("="*50)
    
    intent = "Read a publicly available news article and summarize it in three bullets."
    real_task_id = get_real_task_id(intent, "Test LangGraph Success")
    
    initial_state = {
        "task_id": real_task_id,
        "trace_id": f"trace_success_{real_task_id}",
        "intent": intent,
        "errors": []
    }
    
    final_state = brahma_app.invoke(initial_state)
    print_path(final_state)

def test_failure_path():
    print("\n" + "="*50)
    print("TEST: FAILURE PATH (PRAGYA fails)")
    print("="*50)
    
    intent = "Any intent."
    real_task_id = get_real_task_id(intent, "Test LangGraph Failure")
    
    initial_state = {
        "task_id": real_task_id,
        "trace_id": f"trace_failure_{real_task_id}",
        "intent": intent,
        "errors": []
    }
    
    # Force LLM failure by invalidating the key
    original_key = os.environ.get("OPENROUTER_API_KEY")
    os.environ["OPENROUTER_API_KEY"] = "invalid_key_to_force_failure"
    
    try:
        final_state = brahma_app.invoke(initial_state)
        print_path(final_state)
    finally:
        if original_key:
            os.environ["OPENROUTER_API_KEY"] = original_key
        else:
            del os.environ["OPENROUTER_API_KEY"]

if __name__ == "__main__":
    test_success_path()
    test_failure_path()
