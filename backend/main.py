import os
import threading
import logging
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
from app.core.runtime_mode import OperationalMode
from app.api.auth import router as auth_router, get_current_user
from app.api.routes.upload import router as upload_router
from app.api.routes.chitra import router as chitra_router
from app.api.routes.manush import router as manush_router
from agents.graph import brahma_app

logger = logging.getLogger(__name__)

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
    mode: Optional[str] = "REACTIVE"

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(upload_router)
app.include_router(chitra_router)
app.include_router(manush_router)


@app.on_event("startup")
def on_startup_disaster_recovery():
    """
    Automatic Cold-Start / Disaster Recovery reconciliation on service startup.
    Conforms to Whitesheet §14 & Appendix I (RB-1 Cold Start, RB-2 Failure Recovery).
    Reconciles orphaned RUNNING tasks left in-flight by unexpected termination/crash.
    """
    try:
        from app.db.database import SessionLocal
        from app.core.disaster_recovery import DisasterRecoveryEngine
        with SessionLocal() as db:
            report = DisasterRecoveryEngine.execute_recovery_drill(db=db)
            if report.tasks_reconciled > 0:
                logger.info(
                    f"[COLD-START DR] Reconciled {report.tasks_reconciled} orphaned task(s) "
                    f"(drill_id={report.drill_id}, duplicates_prevented={report.duplicate_executions_prevented})"
                )
    except Exception as e:
        logger.error(f"[COLD-START DR] Failed to execute cold-start disaster recovery: {e}")


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


def _trigger_f14_pattern_extraction_worker(tenant_id: str, user_id: int, current_task_id: int):
    """
    Non-blocking background worker for F14 pattern extraction upon task completion.
    Queries recent completed tasks for this tenant/user.
    If >= 3 completed episodes exist, extracts and persists a candidate pattern.
    Fail-open: any exception is logged and suppressed so task execution is never impacted.
    """
    try:
        from app.db.database import SessionLocal
        from app.models.task import Task
        from app.core.learning.service import LearningService
        from app.core.learning.models import PatternType
        from app.core.learning.stewardship import F15EvolutionarySteward

        with SessionLocal() as db:
            completed_tasks = (
                db.query(Task)
                .filter(Task.user_id == user_id, Task.status == "COMPLETED")
                .order_by(Task.id.desc())
                .limit(10)
                .all()
            )

            if len(completed_tasks) < 3:
                return

            episodes = []
            for t in completed_tasks:
                ep_tool = "generic_executor"
                duration_ms = 100.0
                if t.execution_result and isinstance(t.execution_result, dict):
                    ep_tool = t.execution_result.get("tool", t.execution_result.get("tool_name", "generic_executor"))
                    duration_ms = float(t.execution_result.get("duration_ms", 100.0))
                elif t.plan and isinstance(t.plan, dict):
                    ep_tool = t.plan.get("tool", "generic_executor")

                episodes.append({
                    "task_id": t.id,
                    "event_id": f"evt_task_{t.id}",
                    "status": "SUCCESS",
                    "duration_ms": duration_ms,
                    "tool": ep_tool,
                    "tenant_id": tenant_id
                })

            candidate = LearningService.extract_pattern(
                tenant_id=tenant_id,
                episodes=episodes,
                pattern_type=PatternType.PLAN_OPTIMIZATION,
                name=f"AutoPattern_{tenant_id}",
                description=f"Automatically extracted from {len(episodes)} completed tasks."
            )

            F15EvolutionarySteward._persist_candidate(candidate=candidate, db_session=db)
            logger.info(f"F14 auto-extraction successfully created candidate pattern '{candidate.pattern_id}' for tenant '{tenant_id}'")
    except Exception as e:
        logger.warning(
            f"F14 background pattern extraction failed for tenant '{tenant_id}' (fail-open): {e}",
            exc_info=True
        )


def _trigger_f14_pattern_extraction_async(tenant_id: str, user_id: int, current_task_id: int):
    """Dispatches F14 pattern extraction to a background thread to ensure zero latency impact on task completion."""
    thread = threading.Thread(
        target=_trigger_f14_pattern_extraction_worker,
        args=(tenant_id, user_id, current_task_id),
        daemon=True,
        name=f"F14-Extractor-{tenant_id}-{current_task_id}"
    )
    thread.start()


def run_agent_workflow(task_id: int, intent: str, mode: Optional[str] = None, db_session: Optional[Session] = None):
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

        # Operational Mode validation & resolution (Whitesheet §3.3)
        raw_mode = mode or getattr(task, "mode", None) or "REACTIVE"
        try:
            op_mode = OperationalMode.validate_mode(raw_mode)
        except ValueError as ve:
            task.status = "FAILED"
            task.execution_result = {"error": str(ve), "message": "Invalid operational mode"}
            db.commit()
            return

        # Whitesheet §3.3: Mode selection is itself a decision logged in CHITRA with justification
        from app.services.audit_service import log_audit_event
        mode_meta = OperationalMode.get_mode_metadata(op_mode)
        log_audit_event(
            task_id,
            "RUNTIME",
            "Mode Selection",
            "SELECTED",
            {
                "mode": op_mode.value,
                "is_autonomous": mode_meta["is_autonomous"],
                "retention_tier": mode_meta["retention_tier"],
                "justification": f"Selected {op_mode.value} runtime mode for task: {mode_meta['description']}"
            }
        )
        
        initial_state = {
            "task_id": task_id,
            "user_id": task.user_id,
            "tenant_id": f"tenant_{task.user_id}",
            "session_id": f"ses_{task_id}",
            "trace_id": f"trace_{task_id}",
            "intent": intent,
            "mode": op_mode.value,
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

        # F14 Learning Trigger: automatically initiate pattern extraction if task completed
        if task.status == "COMPLETED":
            try:
                _trigger_f14_pattern_extraction_async(
                    tenant_id=f"tenant_{task.user_id}",
                    user_id=task.user_id,
                    current_task_id=task.id
                )
            except Exception as e:
                # Fail-open: learning trigger must never impact task completion
                logger.warning(f"Failed to dispatch F14 pattern extraction trigger (fail-open): {e}")
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
        # Validate operational mode fail-safe (Whitesheet §3.3)
        try:
            validated_mode = OperationalMode.validate_mode(request.mode)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))

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
            mode=validated_mode.value,
            status="PENDING",
            risk_level="UNKNOWN",
            user_id=current_user.id
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        
        background_tasks.add_task(run_agent_workflow, new_task.id, request.prompt, validated_mode.value)
        
        return {
            "status": "success",
            "task_id": new_task.id,
            "mode": validated_mode.value,
            "message": f"Task '{request.title}' received in {validated_mode.value} mode and processing started."
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

