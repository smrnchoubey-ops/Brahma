from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any

app = FastAPI(title="BRAHMA COS Backend", version="0.1.0")

from datetime import datetime

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TaskRequest(BaseModel):
    title: str
    prompt: str

from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException
from app.db.database import get_db
from app.models.task import Task
from datetime import datetime
from app.api.auth import router as auth_router, get_current_user
from app.api.routes.upload import router as upload_router

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(upload_router)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "BRAHMA COS API is running"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/tasks/")
def get_all_tasks(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    tasks = db.query(Task).filter(Task.user_id == current_user.id).all()
    return tasks

from fastapi import BackgroundTasks
from agents.graph import brahma_app
from app.db.database import SessionLocal

def run_agent_workflow(task_id: int, intent: str):
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
            
        task.status = "RUNNING"
        db.commit()
        
        initial_state = {
            "task_id": task_id,
            "trace_id": f"trace_{task_id}",
            "intent": intent,
            "errors": []
        }
        
        final_state = brahma_app.invoke(initial_state)
        
        # Update Task based on final state
        task.plan = final_state.get("plan")
        task.risk_report = final_state.get("risk_report")
        task.policy_verdict = final_state.get("policy_verdict")
        task.execution_result = final_state.get("execution_result")
        
        # Set final status
        status = final_state.get("status", "")
        if "FAILED" in status or final_state.get("errors"):
            task.status = "FAILED"
        elif status == "MARYADA_BLOCKED":
            verdict = final_state.get("policy_verdict", {})
            if verdict.get("requires_human"):
                task.status = "HUMAN_REVIEW"
            else:
                task.status = "BLOCKED"
        elif status == "RACHIT_EXECUTED":
            task.status = "COMPLETED"
        elif status == "RACHIT_BLOCKED":
            task.status = "BLOCKED"
        elif status == "RACHIT_STUBBED":
            task.status = "COMPLETED"
        else:
            task.status = "UNKNOWN"
            
        if task.risk_report and isinstance(task.risk_report, dict):
            task.risk_level = task.risk_report.get("risk_level", task.risk_level)
            
        db.commit()
    except Exception as e:
        db.rollback()
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "FAILED"
            task.execution_result = {"error": str(e), "message": "Workflow failed due to internal exception"}
            db.commit()
            
            from app.services.audit_service import log_audit_event
            log_audit_event(task_id, "SYSTEM", "Workflow Crash", "FAILED", {"error": str(e)})
        print(f"Exception in workflow for task {task_id}: {e}")
        raise e
    finally:
        db.close()

@app.post("/tasks/")
def create_task(request: TaskRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    from datetime import datetime, timedelta
    try:
        # Idempotency check: duplicate prompt in last 5 minutes
        five_mins_ago = datetime.utcnow() - timedelta(minutes=5)
        duplicate = db.query(Task).filter(
            Task.user_id == current_user.id,
            Task.prompt == request.prompt,
            Task.created_at >= five_mins_ago
        ).first()
        
        if duplicate:
            raise HTTPException(status_code=429, detail="Duplicate task submitted recently. Please wait before submitting the exact same intent.")

        new_task = Task(
            title=request.title or "Untitled Task",
            prompt=request.prompt,
            status="PENDING",
            risk_level="UNKNOWN",
            user_id=current_user.id
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        
        background_tasks.add_task(run_agent_workflow, new_task.id, request.prompt)
        
        return {
            "status": "success",
            "task_id": new_task.id,
            "message": f"Task '{request.title}' received and processing started."
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@app.get("/api/metrics")
def get_metrics(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    total = db.query(Task).count()
    running = db.query(Task).filter(Task.status == "RUNNING").count()
    completed = db.query(Task).filter(Task.status == "COMPLETED").count()
    failed = db.query(Task).filter(Task.status == "FAILED").count()
    blocked = db.query(Task).filter(Task.status == "BLOCKED").count()
    human_review = db.query(Task).filter(Task.status == "HUMAN_REVIEW").count()
    
    return {
        "total": total,
        "running": running,
        "completed": completed,
        "failed": failed,
        "blocked": blocked,
        "human_review": human_review,
        "system_health": "Healthy"
    }

@app.get("/api/agents")
def get_agents(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    return [
        {"name": "KARMA", "role": "Orchestrator", "status": "Implemented & Verified"},
        {"name": "PRAGYA", "role": "Planner", "status": "Implemented & Verified"},
        {"name": "MURPHY", "role": "Red-Teamer", "status": "Implemented & Verified"},
        {"name": "MARYADA", "role": "Governance Guard", "status": "Implemented & Verified"},
        {"name": "RACHIT", "role": "Executor", "status": "Implemented & Verified"},
        {"name": "KOSH", "role": "Vector DB / Memory", "status": "Implemented But Not Verified"},
        {"name": "SMRITI", "role": "Memory Core", "status": "Conceptual / Planned"},
        {"name": "NIYANTRA", "role": "Control Plane", "status": "Conceptual / Planned"},
        {"name": "LISA", "role": "Analytics", "status": "Conceptual / Planned"}
    ]

from app.models.audit import Audit

@app.get("/api/audit")
def get_audit_ledger(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    # Read the immutable audit ledger
    audit_events = db.query(Audit).order_by(Audit.created_at.desc()).limit(50).all()
    
    formatted_events = []
    for evt in audit_events:
        formatted_events.append({
            "timestamp": evt.created_at.isoformat() if evt.created_at else None,
            "task_id": evt.task_id,
            "agent": evt.agent,
            "event": evt.event_type,
            "status": evt.status,
            "payload_snapshot": evt.payload_snapshot,
            "action": evt.event_type
        })
        
    return formatted_events

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
