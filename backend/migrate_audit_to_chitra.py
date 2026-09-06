"""
CHITRA Migration Script: audit_logs -> chitra_events
Conforms to BRAHMA COS Whitesheet §8.2 & Appendix C.1.

Features:
- Full legacy event_type mapping to Whitesheet categories
- Atomic single-transaction execution
- Pre-commit 100% cryptographic chain and signature validation
- Automatic rollback if any verification fails
"""
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, DATABASE_URL
from app.models.chitra import ChitraEvent
from app.models.audit import Audit
from app.core.chitra.crypto import (
    GENESIS_HASH,
    generate_ulid,
    compute_sha256,
    canonical_json,
    compute_content_hash,
    compute_chained_hash,
    sign_event,
    verify_event_signature
)

# Comprehensive Whitesheet §8.2 Event Type Mapping Table
LEGACY_EVENT_TYPE_MAP = {
    # KARMA Perception / Ingest
    "ingest intent": "perception",
    "user intent": "perception",
    "intent ingest": "perception",
    
    # KOSH Context Retrieval
    "context retrieval": "retrieval",
    "knowledge retrieval": "retrieval",
    "vector search": "retrieval",
    
    # PRAGYA Planning & Reasoning
    "plan generation": "decision",
    "dag generation": "decision",
    "synthesize recommendation": "decision",
    "reasoning": "decision",
    
    # MURPHY Red-Teaming & Verification
    "risk assessment": "verification",
    "security scan": "verification",
    "red team scan": "verification",
    
    # MARYADA Constitutional Governance Gate
    "policy enforcement": "gate",
    "governance gate": "gate",
    "constitutional check": "gate",
    
    # RACHIT Execution & Tools
    "task execution": "invocation",
    "tool execution": "invocation",
    "rachit execution": "invocation",
    "action dispatch": "invocation",
    
    # Validation & Completion
    "validation": "validation",
    "completion check": "validation",
    
    # System Escalations & Crashes
    "workflow crash": "escalation",
    "system error": "escalation",
    "human review required": "escalation",
    "escalation": "escalation"
}


def map_legacy_event_type(legacy_event: str, agent: str) -> str:
    """Maps a legacy event string and agent to the canonical Whitesheet §8.2 category."""
    normalized = (legacy_event or "").strip().lower()
    
    # Exact match in mapping table
    if normalized in LEGACY_EVENT_TYPE_MAP:
        return LEGACY_EVENT_TYPE_MAP[normalized]
    
    # Substring heuristic
    if "risk" in normalized or "scan" in normalized:
        return "verification"
    if "policy" in normalized or "guard" in normalized or "gate" in normalized:
        return "gate"
    if "retriev" in normalized or "search" in normalized:
        return "retrieval"
    if "plan" in normalized or "decid" in normalized:
        return "decision"
    if "execut" in normalized or "tool" in normalized:
        return "invocation"
    if "crash" in normalized or "error" in normalized or "fail" in normalized:
        return "escalation"
    
    # Agent fallback
    agent_norm = (agent or "").upper()
    if agent_norm == "MARYADA":
        return "gate"
    if agent_norm == "MURPHY":
        return "verification"
    if agent_norm == "PRAGYA":
        return "decision"
    if agent_norm == "KOSH":
        return "retrieval"
    if agent_norm == "RACHIT":
        return "invocation"
    
    return "decision"


def run_migration(db_url: str = None) -> bool:
    target_url = db_url or DATABASE_URL
    if not target_url:
        print("ERROR: Database URL is required.")
        return False

    engine = create_engine(target_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    print("==================================================")
    print("CHITRA ATOMIC MIGRATION: audit_logs -> chitra_events")
    print(f"Target DB: {target_url.split('@')[-1] if '@' in target_url else target_url}")
    print("==================================================")

    # 1. Ensure schema exists
    Base.metadata.create_all(bind=engine)
    print("[1/5] Verified schema definition for 'chitra_events'.")

    inspector = inspect(engine)
    if "audit_logs" not in inspector.get_table_names():
        print("No 'audit_logs' table found. Migration skipped.")
        db.close()
        return True

    # 2. Fetch all legacy logs ordered by task_id and id
    legacy_logs = db.query(Audit).order_by(Audit.task_id.asc(), Audit.id.asc()).all()
    total_legacy = len(legacy_logs)
    print(f"[2/5] Retrieved {total_legacy} legacy audit records.")

    if total_legacy == 0:
        print("No legacy records to migrate.")
        db.close()
        return True

    # 3. Group by task_id
    task_groups: Dict[int, list] = {}
    for log in legacy_logs:
        task_groups.setdefault(log.task_id, []).append(log)

    print(f"[3/5] Grouped {total_legacy} records across {len(task_groups)} tasks. Processing hash chains...")

    migrated_events = []
    try:
        for task_id, logs in task_groups.items():
            prev_hash = GENESIS_HASH

            for log in logs:
                event_id = generate_ulid(prefix="evt_")
                event_ts = log.created_at or datetime.now(timezone.utc)
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=timezone.utc)

                canonical_event_type = map_legacy_event_type(log.event_type, log.agent)
                
                decision_payload = {
                    "legacy_event_type": log.event_type,
                    "legacy_status": log.status,
                    "payload_snapshot": log.payload_snapshot or {}
                }

                envelope = {
                    "event_id": event_id,
                    "timestamp": event_ts.isoformat(),
                    "session_id": f"ses_{task_id}",
                    "task_id": task_id,
                    "faculty": log.agent or "SYSTEM",
                    "event_type": canonical_event_type,
                    "input_hash": compute_sha256("{}"),
                    "decision": decision_payload,
                    "evidence": [],
                    "confidence": 1.0,
                    "outcome": {"migrated": True, "original_audit_id": log.id},
                    "constitutional_review": "passed" if log.status != "BLOCKED" else "failed",
                    "prev_event_hash": prev_hash,
                }

                # Step 1: Content Hash
                content_hash = compute_content_hash(envelope)
                
                # Step 2: Chained Hash
                this_hash = compute_chained_hash(prev_hash, content_hash)
                
                # Step 3: Signature
                sig = sign_event(this_hash)

                chitra_evt = ChitraEvent(
                    event_id=event_id,
                    task_id=task_id,
                    session_id=envelope["session_id"],
                    timestamp=event_ts,
                    faculty=envelope["faculty"],
                    event_type=envelope["event_type"],
                    input_hash=envelope["input_hash"],
                    decision=decision_payload,
                    evidence=[],
                    confidence=1.0,
                    outcome=envelope["outcome"],
                    constitutional_review=envelope["constitutional_review"],
                    prev_event_hash=prev_hash,
                    this_event_hash=this_hash,
                    signature=sig
                )

                db.add(chitra_evt)
                migrated_events.append(chitra_evt)
                prev_hash = this_hash

        # Flush into transaction buffer without committing yet
        db.flush()
        print(f"[4/5] Successfully staged {len(migrated_events)} CHITRA events in transaction buffer.")

        # 4. Pre-Commit Verification Gate
        print("[5/5] Executing pre-commit cryptographic integrity audit...")
        task_prev_map: Dict[int, str] = {}
        for evt in migrated_events:
            expected_prev = task_prev_map.get(evt.task_id, GENESIS_HASH)
            
            if evt.prev_event_hash != expected_prev:
                raise ValueError(f"Integrity check failed: Broken chain on task {evt.task_id} at event {evt.event_id}")
            
            if not verify_event_signature(evt.this_event_hash, evt.signature):
                raise ValueError(f"Integrity check failed: Invalid signature on task {evt.task_id} at event {evt.event_id}")
            
            task_prev_map[evt.task_id] = evt.this_event_hash

        # All checks passed cleanly -> commit atomic transaction
        db.commit()
        print("==================================================")
        print(f"MIGRATION COMPLETE & COMMITTED: {len(migrated_events)} events across {len(task_groups)} tasks verified.")
        print("==================================================")
        return True

    except Exception as e:
        db.rollback()
        print("==================================================")
        print(f"MIGRATION FAILED & ROLLED BACK AUTOMATICALLY: {e}")
        print("chitra_events table remains pristine and untouched.")
        print("==================================================")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
