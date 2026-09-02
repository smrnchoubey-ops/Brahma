import os
import sys
from dotenv import load_dotenv

# Ensure backend is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from agents.graph import brahma_app
from app.core.llm import print_llm_config

from app.db.database import SessionLocal
from app.models.task import Task
from app.models.user import User

def main():
    print_llm_config()
    
    print("\n--- CREATING TEST TASK IN DB ---")
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            user = User(username="testuser", hashed_password="pw")
            db.add(user)
            db.commit()
            db.refresh(user)
            
        test_intent = "We need to set up a secure data room for the upcoming Series A diligence. Include NDA generation, document indexing, and access controls for external auditors."
        task = Task(title="Test Graph Task", prompt=test_intent, user_id=user.id)
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
        print(f"Created real task in DB with ID: {task_id}")
    finally:
        db.close()
    
    print("\n--- RUNNING GRAPH ---")
    
    initial_state = {
        "task_id": task_id,
        "trace_id": f"trace-{task_id}",
        "intent": test_intent,
        "current_agent": "system",
        "status": "INIT",
        "errors": []
    }
    
    final_state = brahma_app.invoke(initial_state)
    
    print("\n--- FINAL STATE ---")
    print(f"Final Agent: {final_state.get('current_agent')}")
    print(f"Status     : {final_state.get('status')}")
    print(f"Errors     : {final_state.get('errors')}")
    
    if final_state.get("plan"):
        print(f"\nPlan Summary: {final_state['plan'].get('summary')}")
    if final_state.get("risk_report"):
        print(f"Risk Level  : {final_state['risk_report'].get('risk_level')}")
    if final_state.get("policy_verdict"):
        print(f"Verdict     : {'APPROVED' if final_state['policy_verdict'].get('approved') else 'BLOCKED'}")
        
    print("\nDone.")

if __name__ == "__main__":
    main()
