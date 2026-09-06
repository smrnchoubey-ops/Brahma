"""
CHITRA Integrity Verification Service
Conforms to BRAHMA COS Whitesheet §8.0, §8.3, §8.8 & §20.7.

Features:
- Pure Cryptographic DAG Traversal: Traces from GENESIS_HASH -> prev_hash -> this_hash without relying on DB IDs.
- Temporal Monotonicity Auditing: Validates timestamp progression and envelope consistency.
- Exact Failure Attribution: Accurate events_checked counting (inspected count including failing node).
- Fork & Orphan Detection: Detects unchained or branching events for a task.
"""
from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session

from app.models.chitra import ChitraEvent
from app.models.task import Task
from app.core.chitra.crypto import (
    GENESIS_HASH,
    compute_content_hash,
    compute_chained_hash,
    verify_event_signature
)


@dataclass
class ChitraVerificationResult:
    """Structured cryptographic integrity report for a task's event chain."""
    valid: bool
    task_id: int
    events_checked: int
    chain_status: str  # "VERIFIED" | "CORRUPTED" | "EMPTY"
    first_corrupted_event_id: Optional[str] = None
    failure_type: Optional[str] = None  # CHAIN_LINK_BROKEN | CONTENT_HASH_MISMATCH | INVALID_SIGNATURE | FORK_COLLISION | ORPHAN_EVENTS | TIMESTAMP_ANACHRONISM | EMPTY_CHAIN
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    signature_status: str = "UNCHECKED"  # "VALID" | "INVALID" | "UNCHECKED"
    details: Optional[Dict[str, Any]] = None
    genesis_hash: str = GENESIS_HASH
    latest_event_hash: Optional[str] = None
    verified_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if not d["verified_at"]:
            d["verified_at"] = datetime.now(timezone.utc).isoformat()
        return d


class ChitraIntegrityVerifier:
    """
    Independent, read-only verifier for the CHITRA cryptographic ledger.
    Determines chain continuity purely through cryptographic pointers (GENESIS -> prev_hash -> this_hash).
    """

    def verify_task_chain(self, db: Session, task_id: int, user_id: Optional[int] = None, secret_key: Optional[str] = None) -> ChitraVerificationResult:
        """
        Performs topological DAG traversal and mathematical verification of a task's ledger.
        Enforces tenant authorization if user_id is provided.
        """
        verified_time = datetime.now(timezone.utc).isoformat()

        # Tenant Authorization Check
        if user_id is not None:
            task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
            if not task:
                return ChitraVerificationResult(
                    valid=False,
                    task_id=task_id,
                    events_checked=0,
                    chain_status="ACCESS_DENIED",
                    failure_type="UNAUTHORIZED_TENANT",
                    details={"reason": f"Access Denied: Task {task_id} does not exist or does not belong to tenant {user_id}."},
                    verified_at=verified_time
                )

        all_events = db.query(ChitraEvent).filter(ChitraEvent.task_id == task_id).all()

        if not all_events:
            task_exists = db.query(Task).filter(Task.id == task_id).first() is not None
            return ChitraVerificationResult(
                valid=True,
                task_id=task_id,
                events_checked=0,
                chain_status="EMPTY",
                details={"task_exists": task_exists, "message": "No CHITRA events recorded for this task yet."},
                verified_at=verified_time
            )

        # Index events by prev_event_hash to perform cryptographic pointer traversal
        prev_hash_map: Dict[str, List[ChitraEvent]] = {}
        for event in all_events:
            prev_hash_map.setdefault(event.prev_event_hash, []).append(event)

        # Check for multiple Genesis roots (Fork from Genesis)
        genesis_events = prev_hash_map.get(GENESIS_HASH, [])
        if len(genesis_events) == 0:
            # Missing genesis event
            first_event = all_events[0]
            return ChitraVerificationResult(
                valid=False,
                task_id=task_id,
                events_checked=1,
                chain_status="CORRUPTED",
                first_corrupted_event_id=first_event.event_id,
                failure_type="CHAIN_LINK_BROKEN",
                expected_hash=GENESIS_HASH,
                actual_hash=first_event.prev_event_hash,
                details={"reason": f"No event chains from GENESIS_HASH. First found prev_hash: {first_event.prev_event_hash}"},
                verified_at=verified_time
            )
        elif len(genesis_events) > 1:
            return ChitraVerificationResult(
                valid=False,
                task_id=task_id,
                events_checked=2,
                chain_status="CORRUPTED",
                first_corrupted_event_id=genesis_events[1].event_id,
                failure_type="FORK_COLLISION",
                expected_hash=GENESIS_HASH,
                actual_hash=GENESIS_HASH,
                details={"reason": f"Multiple root events ({len(genesis_events)}) claim GENESIS_HASH parentage."},
                verified_at=verified_time
            )

        # Traverse the cryptographic DAG chain from GENESIS
        current_hash = GENESIS_HASH
        traversed_events: List[ChitraEvent] = []
        visited_ids: Set[str] = set()
        prev_timestamp: Optional[datetime] = None

        while current_hash in prev_hash_map:
            siblings = prev_hash_map[current_hash]
            
            # Detect sibling fork (multiple events claiming the same parent hash)
            if len(siblings) > 1:
                return ChitraVerificationResult(
                    valid=False,
                    task_id=task_id,
                    events_checked=len(traversed_events) + 2,
                    chain_status="CORRUPTED",
                    first_corrupted_event_id=siblings[1].event_id,
                    failure_type="FORK_COLLISION",
                    expected_hash=current_hash,
                    actual_hash=current_hash,
                    details={"reason": f"Fork detected: {len(siblings)} events point to parent {current_hash}."},
                    verified_at=verified_time
                )

            event = siblings[0]
            event_idx = len(traversed_events)
            events_inspected_so_far = event_idx + 1

            # Detect cycle
            if event.event_id in visited_ids:
                return ChitraVerificationResult(
                    valid=False,
                    task_id=task_id,
                    events_checked=events_inspected_so_far,
                    chain_status="CORRUPTED",
                    first_corrupted_event_id=event.event_id,
                    failure_type="CHAIN_LINK_BROKEN",
                    details={"reason": "Infinite cycle detected in cryptographic pointer graph."},
                    verified_at=verified_time
                )

            visited_ids.add(event.event_id)

            # Check 1: Content Hash & Chained Hash Integrity
            timestamp_str = event.timestamp.isoformat() if isinstance(event.timestamp, datetime) else str(event.timestamp)
            if isinstance(event.timestamp, datetime) and event.timestamp.tzinfo is None:
                timestamp_str = event.timestamp.replace(tzinfo=timezone.utc).isoformat()

            envelope = {
                "event_id": event.event_id,
                "timestamp": timestamp_str,
                "session_id": event.session_id,
                "task_id": event.task_id,
                "faculty": event.faculty,
                "event_type": event.event_type,
                "input_hash": event.input_hash,
                "decision": event.decision,
                "evidence": event.evidence or [],
                "confidence": float(event.confidence),
                "outcome": event.outcome,
                "constitutional_review": event.constitutional_review,
                "prev_event_hash": event.prev_event_hash,
            }

            content_hash = compute_content_hash(envelope)
            recomputed_this_hash = compute_chained_hash(event.prev_event_hash, content_hash)

            if recomputed_this_hash != event.this_event_hash:
                return ChitraVerificationResult(
                    valid=False,
                    task_id=task_id,
                    events_checked=events_inspected_so_far,
                    chain_status="CORRUPTED",
                    first_corrupted_event_id=event.event_id,
                    failure_type="CONTENT_HASH_MISMATCH",
                    expected_hash=recomputed_this_hash,
                    actual_hash=event.this_event_hash,
                    signature_status="UNCHECKED",
                    details={
                        "event_index": event_idx,
                        "faculty": event.faculty,
                        "event_type": event.event_type,
                        "reason": f"Payload or envelope hash mismatch at {event.event_id}. Recomputed: {recomputed_this_hash}, Stored: {event.this_event_hash}"
                    },
                    latest_event_hash=current_hash,
                    verified_at=verified_time
                )

            # Check 2: HMAC Authority Signature Verification
            sig_valid = verify_event_signature(event.this_event_hash, event.signature, secret_key=secret_key)
            if not sig_valid:
                return ChitraVerificationResult(
                    valid=False,
                    task_id=task_id,
                    events_checked=events_inspected_so_far,
                    chain_status="CORRUPTED",
                    first_corrupted_event_id=event.event_id,
                    failure_type="INVALID_SIGNATURE",
                    expected_hash=event.this_event_hash,
                    actual_hash=event.this_event_hash,
                    signature_status="INVALID",
                    details={
                        "event_index": event_idx,
                        "faculty": event.faculty,
                        "event_type": event.event_type,
                        "reason": f"HMAC signature for {event.event_id} failed verification against CHITRA_SIGNING_KEY."
                    },
                    latest_event_hash=current_hash,
                    verified_at=verified_time
                )

            # Check 3: Timestamp monotonicity
            current_event_ts = event.timestamp if isinstance(event.timestamp, datetime) else datetime.fromisoformat(event.timestamp)
            if prev_timestamp and current_event_ts < prev_timestamp:
                return ChitraVerificationResult(
                    valid=False,
                    task_id=task_id,
                    events_checked=events_inspected_so_far,
                    chain_status="CORRUPTED",
                    first_corrupted_event_id=event.event_id,
                    failure_type="TIMESTAMP_ANACHRONISM",
                    details={"reason": f"Event {event.event_id} has timestamp {current_event_ts} earlier than predecessor {prev_timestamp}"},
                    verified_at=verified_time
                )

            prev_timestamp = current_event_ts
            traversed_events.append(event)
            current_hash = event.this_event_hash

        # Check 4: Orphan detection (events exist in DB for task_id but are disconnected from main chain)
        if len(traversed_events) < len(all_events):
            orphan_events = [e for e in all_events if e.event_id not in visited_ids]
            first_orphan = orphan_events[0]
            return ChitraVerificationResult(
                valid=False,
                task_id=task_id,
                events_checked=len(traversed_events) + 1,
                chain_status="CORRUPTED",
                first_corrupted_event_id=first_orphan.event_id,
                failure_type="ORPHAN_EVENTS",
                expected_hash=current_hash,
                actual_hash=first_orphan.prev_event_hash,
                details={
                    "total_in_db": len(all_events),
                    "chained_count": len(traversed_events),
                    "orphan_count": len(orphan_events),
                    "reason": f"Found {len(orphan_events)} orphan events disconnected from canonical chain."
                },
                latest_event_hash=current_hash,
                verified_at=verified_time
            )

        return ChitraVerificationResult(
            valid=True,
            task_id=task_id,
            events_checked=len(traversed_events),
            chain_status="VERIFIED",
            signature_status="VALID",
            latest_event_hash=current_hash,
            details={
                "first_event_id": traversed_events[0].event_id,
                "latest_event_id": traversed_events[-1].event_id,
                "faculties_involved": list(set(e.faculty for e in traversed_events)),
                "unbroken_chain": True
            },
            verified_at=verified_time
        )


chitra_verifier = ChitraIntegrityVerifier()
