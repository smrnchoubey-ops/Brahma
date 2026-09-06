import os
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db, SessionLocal
from app.models.task import Task
from app.models.audit import Audit
from app.api.auth import router as auth_router, get_current_user
from app.api.routes.upload import router as upload_router
from app.api.routes.chitra import router as chitra_router
from app.api.routes.manush import router as manush_router
from agents.graph import brahma_app

app = FastAPI(title="BRAHMA COS Backend", version="0.1.0")

allowed_origins_raw = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000,https://brahma-cos.vercel.app,https://brahma-cos.onrender.com"
)
allowed_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TaskRequest(BaseModel):
    title: str
    prompt: str

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(upload_router)
app.include_router(chitra_router)
app.include_router(manush_router)


@app.get("/")
def read_root():
    return {"status": "ok", "message": "BRAHMA COS API is running"}

@app.get("/health")
def health(db: Session = Depends(get_db)):
    health_status = {
        "status": "healthy",
        "database": "connected",
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["database"] = f"disconnected: {str(e)}"
        raise HTTPException(status_code=503, detail=health_status)
        
    return health_status

@app.get("/tasks/")
def get_all_tasks(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    tasks = db.query(Task).filter(Task.user_id == current_user.id).all()
    return tasks

def run_agent_workflow(task_id: int, intent: str, db_session: Optional[Session] = None):
    should_close = False
    if db_session is None:
        db = SessionLocal()
        should_close = True
    else:
        db = db_session

    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
            
        task.status = "RUNNING"
        db.commit()
        
        initial_state = {
            "task_id": task_id,
            "user_id": task.user_id,
            "tenant_id": f"tenant_{task.user_id}",
            "session_id": f"ses_{task_id}",
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
        if should_close:
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
    user_tasks = db.query(Task).filter(Task.user_id == current_user.id)
    total = user_tasks.count()
    running = user_tasks.filter(Task.status == "RUNNING").count()
    completed = user_tasks.filter(Task.status == "COMPLETED").count()
    failed = user_tasks.filter(Task.status == "FAILED").count()
    blocked = user_tasks.filter(Task.status == "BLOCKED").count()
    human_review = user_tasks.filter(Task.status == "HUMAN_REVIEW").count()
    
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

from app.models.chitra import ChitraEvent

@app.get("/api/audit")
def get_audit_ledger(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    # Read the canonical CHITRA audit ledger scoped to current user's tasks
    chitra_events = (
        db.query(ChitraEvent)
        .join(Task, ChitraEvent.task_id == Task.id)
        .filter(Task.user_id == current_user.id)
        .order_by(ChitraEvent.id.desc())
        .limit(50)
        .all()
    )
    
    if chitra_events:
        formatted_events = []
        for evt in chitra_events:
            ts_str = evt.timestamp.isoformat() if isinstance(evt.timestamp, datetime) else str(evt.timestamp)
            formatted_events.append({
                "timestamp": ts_str,
                "event_id": evt.event_id,
                "task_id": evt.task_id,
                "agent": evt.faculty,
                "faculty": evt.faculty,
                "event": evt.event_type,
                "event_type": evt.event_type,
                "status": "APPROVED" if evt.constitutional_review == "passed" else "BLOCKED",
                "constitutional_review": evt.constitutional_review,
                "payload_snapshot": evt.decision,
                "hash": evt.this_event_hash,
                "action": evt.event_type
            })
        return formatted_events

    # Backward compatibility fallback for legacy audit table fixtures
    legacy_events = (
        db.query(Audit)
        .join(Task, Audit.task_id == Task.id)
        .filter(Task.user_id == current_user.id)
        .order_by(Audit.created_at.desc())
        .limit(50)
        .all()
    )
    formatted_legacy = []
    for evt in legacy_events:
        formatted_legacy.append({
            "timestamp": evt.created_at.isoformat() if evt.created_at else None,
            "task_id": evt.task_id,
            "agent": evt.agent,
            "event": evt.event_type,
            "status": evt.status,
            "payload_snapshot": evt.payload_snapshot,
            "action": evt.event_type
        })
    return formatted_legacy

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

