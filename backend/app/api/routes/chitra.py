"""
CHITRA REST API Endpoints
Conforms to BRAHMA COS Whitesheet §8.4, §8.5 & §20.7.

Provides tenant-isolated audit event inspection, cryptographic chain verification,
forensic replay, and multi-index ledger querying.
"""
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.db.database import get_db
from app.models.task import Task
from app.models.chitra import ChitraEvent
from app.core.tenant import TenantContext, get_current_tenant
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier, ChitraVerificationResult
from app.services.replay_service import chitra_replay_engine, ChitraReplayTrace

router = APIRouter(prefix="/api/chitra", tags=["CHITRA Cryptographic Ledger"])


def _verify_task_ownership(db: Session, task_id: int, user_id: int) -> Task:
    """Resource-hiding task ownership verification: returns 404 for non-existent or foreign tasks."""
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found."
        )
    return task


@router.get("/events/{task_id}", response_model=List[Dict[str, Any]])
def get_task_events(
    task_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Returns the complete chronological array of canonical CHITRA event records for a task.
    Enforces strict tenant isolation and resource-hiding 404s for foreign tasks.
    """
    _verify_task_ownership(db, task_id, tenant.user_id)
    events = chitra_repository.get_events_for_task(db, task_id, user_id=tenant.user_id)
    
    formatted_events = []
    for evt in events:
        ts_str = evt.timestamp.isoformat() if isinstance(evt.timestamp, datetime) else str(evt.timestamp)
        if isinstance(evt.timestamp, datetime) and evt.timestamp.tzinfo is None:
            ts_str = evt.timestamp.replace(tzinfo=timezone.utc).isoformat()

        formatted_events.append({
            "event_id": evt.event_id,
            "task_id": evt.task_id,
            "session_id": evt.session_id,
            "timestamp": ts_str,
            "faculty": evt.faculty,
            "event_type": evt.event_type,
            "input_hash": evt.input_hash,
            "decision": evt.decision,
            "evidence": evt.evidence or [],
            "confidence": float(evt.confidence),
            "outcome": evt.outcome,
            "constitutional_review": evt.constitutional_review,
            "prev_event_hash": evt.prev_event_hash,
            "this_event_hash": evt.this_event_hash,
            "signature": evt.signature,
        })
    return formatted_events


@router.get("/verify/{task_id}", response_model=Dict[str, Any])
def verify_task_chain(
    task_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Invokes the independent read-only CHITRA Integrity Verifier on a task's hash chain.
    Returns the complete mathematical and cryptographic proof of unbroken chain and signatures.
    """
    _verify_task_ownership(db, task_id, tenant.user_id)
    result: ChitraVerificationResult = chitra_verifier.verify_task_chain(db, task_id, user_id=tenant.user_id)
    return result.to_dict()


@router.get("/replay/{task_id}", response_model=Dict[str, Any])
def replay_task_trace(
    task_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Forensically reconstructs the complete execution trace, causal decision DAG, timeline frames,
    and confidence curve from verified CHITRA records. Refuses replay if the ledger is corrupted.
    """
    _verify_task_ownership(db, task_id, tenant.user_id)
    trace: ChitraReplayTrace = chitra_replay_engine.replay_task(db, task_id, user_id=tenant.user_id)
    return trace.to_dict()


@router.get("/ledger", response_model=List[Dict[str, Any]])
def query_ledger(
    task_id: Optional[int] = Query(None, description="Filter by task ID"),
    faculty: Optional[str] = Query(None, description="Filter by faculty (KARMA, PRAGYA, etc.)"),
    event_type: Optional[str] = Query(None, description="Filter by event category"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return"),
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Multi-index filtered query across the tenant's CHITRA ledger (Whitesheet §8.4).
    Strictly scoped to records belonging to the authenticated tenant.
    """
    events = chitra_repository.query_ledger(
        db=db,
        user_id=tenant.user_id,
        task_id=task_id,
        faculty=faculty,
        event_type=event_type,
        limit=limit
    )

    results = []
    for evt in events:
        ts_str = evt.timestamp.isoformat() if isinstance(evt.timestamp, datetime) else str(evt.timestamp)
        if isinstance(evt.timestamp, datetime) and evt.timestamp.tzinfo is None:
            ts_str = evt.timestamp.replace(tzinfo=timezone.utc).isoformat()

        results.append({
            "event_id": evt.event_id,
            "task_id": evt.task_id,
            "session_id": evt.session_id,
            "timestamp": ts_str,
            "faculty": evt.faculty,
            "event_type": evt.event_type,
            "input_hash": evt.input_hash,
            "decision": evt.decision,
            "evidence": evt.evidence or [],
            "confidence": float(evt.confidence),
            "outcome": evt.outcome,
            "constitutional_review": evt.constitutional_review,
            "prev_event_hash": evt.prev_event_hash,
            "this_event_hash": evt.this_event_hash,
            "signature": evt.signature,
        })
    return results
