"""
CHITRA Forensic Replay Engine
Conforms to BRAHMA COS Whitesheet §8.5, §8.8 & §20.7.

Reconstructs deterministic execution traces, causal decision DAGs, and timeline frames
from mathematically verified CHITRA cryptographic ledgers.
"""
from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from sqlalchemy.orm import Session

from app.models.chitra import ChitraEvent
from app.models.task import Task
from app.core.chitra.crypto import GENESIS_HASH
from app.services.chitra_verifier import chitra_verifier, ChitraVerificationResult


@dataclass
class ChitraReplayFrame:
    """Individual chronological execution frame within a replayed task trace."""
    index: int
    event_id: str
    timestamp: str
    faculty: str
    event_type: str
    input_hash: str
    decision: Optional[Dict[str, Any]]
    evidence: List[str]
    confidence: float
    outcome: Optional[Any]
    constitutional_review: str
    prev_event_hash: str
    this_event_hash: str
    signature: str


@dataclass
class ChitraReplayTrace:
    """Complete forensic replay trace including timeline, causal DAG, and integrity proof."""
    task_id: int
    replay_status: str  # "SUCCESS" | "REFUSED_CORRUPTED" | "EMPTY" | "TASK_NOT_FOUND"
    integrity_verified: bool
    events_replayed: int
    genesis_hash: str = GENESIS_HASH
    latest_event_hash: Optional[str] = None
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    decision_dag: List[Dict[str, Any]] = field(default_factory=list)
    faculty_sequence: List[str] = field(default_factory=list)
    confidence_curve: List[Dict[str, Any]] = field(default_factory=list)
    verification_report: Optional[Dict[str, Any]] = None
    replayed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if not d["replayed_at"]:
            d["replayed_at"] = datetime.now(timezone.utc).isoformat()
        return d


class ChitraReplayEngine:
    """
    Read-only forensic replay engine for CHITRA.
    Enforces pre-replay integrity verification and refuses execution if the ledger is corrupted.
    """

    def replay_task(self, db: Session, task_id: int, user_id: Optional[int] = None) -> ChitraReplayTrace:
        """
        Replays a task's full reasoning trace from the cryptographic ledger.
        Enforces tenant authorization if user_id is provided.
        """
        replayed_time = datetime.now(timezone.utc).isoformat()

        # Step 1: Pre-Replay Integrity Verification & Tenant Authorization Gate
        verification_result: ChitraVerificationResult = chitra_verifier.verify_task_chain(db, task_id, user_id=user_id)

        if verification_result.chain_status == "ACCESS_DENIED":
            return ChitraReplayTrace(
                task_id=task_id,
                replay_status="ACCESS_DENIED",
                integrity_verified=False,
                events_replayed=0,
                genesis_hash=GENESIS_HASH,
                latest_event_hash=None,
                timeline=[],
                decision_dag=[],
                faculty_sequence=[],
                confidence_curve=[],
                verification_report=verification_result.to_dict(),
                replayed_at=replayed_time
            )

        if not verification_result.valid:
            # REFUSE REPLAY ON CORRUPTED LEDGER (Whitesheet §8.3 & §20.7)
            return ChitraReplayTrace(
                task_id=task_id,
                replay_status="REFUSED_CORRUPTED",
                integrity_verified=False,
                events_replayed=0,
                genesis_hash=GENESIS_HASH,
                latest_event_hash=verification_result.latest_event_hash,
                timeline=[],
                decision_dag=[],
                faculty_sequence=[],
                confidence_curve=[],
                verification_report=verification_result.to_dict(),
                replayed_at=replayed_time
            )

        if verification_result.chain_status == "EMPTY":
            return ChitraReplayTrace(
                task_id=task_id,
                replay_status="EMPTY",
                integrity_verified=True,
                events_replayed=0,
                genesis_hash=GENESIS_HASH,
                latest_event_hash=None,
                timeline=[],
                decision_dag=[],
                faculty_sequence=[],
                confidence_curve=[],
                verification_report=verification_result.to_dict(),
                replayed_at=replayed_time
            )

        # Step 2: Fetch all events for task and index by prev_event_hash
        all_events = db.query(ChitraEvent).filter(ChitraEvent.task_id == task_id).all()
        prev_hash_map: Dict[str, ChitraEvent] = {e.prev_event_hash: e for e in all_events}

        # Step 3: Pure Cryptographic Traversal from Genesis
        current_hash = GENESIS_HASH
        timeline_frames: List[ChitraReplayFrame] = []
        faculty_sequence: List[str] = []
        confidence_curve: List[Dict[str, Any]] = []
        decision_dag: List[Dict[str, Any]] = []
        visited_ids: Set[str] = set()

        index = 0
        while current_hash in prev_hash_map:
            event = prev_hash_map[current_hash]
            if event.event_id in visited_ids:
                break
            visited_ids.add(event.event_id)

            ts_str = event.timestamp.isoformat() if isinstance(event.timestamp, datetime) else str(event.timestamp)
            if isinstance(event.timestamp, datetime) and event.timestamp.tzinfo is None:
                ts_str = event.timestamp.replace(tzinfo=timezone.utc).isoformat()

            frame = ChitraReplayFrame(
                index=index,
                event_id=event.event_id,
                timestamp=ts_str,
                faculty=event.faculty,
                event_type=event.event_type,
                input_hash=event.input_hash,
                decision=event.decision,
                evidence=event.evidence or [],
                confidence=float(event.confidence),
                outcome=event.outcome,
                constitutional_review=event.constitutional_review,
                prev_event_hash=event.prev_event_hash,
                this_event_hash=event.this_event_hash,
                signature=event.signature
            )
            timeline_frames.append(frame)
            faculty_sequence.append(event.faculty)
            confidence_curve.append({
                "index": index,
                "event_id": event.event_id,
                "faculty": event.faculty,
                "confidence": float(event.confidence)
            })

            decision_dag.append({
                "event_id": event.event_id,
                "faculty": event.faculty,
                "event_type": event.event_type,
                "upstream_evidence": event.evidence or [],
                "parent_hash": event.prev_event_hash,
                "node_hash": event.this_event_hash
            })

            current_hash = event.this_event_hash
            index += 1

        return ChitraReplayTrace(
            task_id=task_id,
            replay_status="SUCCESS",
            integrity_verified=True,
            events_replayed=len(timeline_frames),
            genesis_hash=GENESIS_HASH,
            latest_event_hash=current_hash,
            timeline=[asdict(f) for f in timeline_frames],
            decision_dag=decision_dag,
            faculty_sequence=faculty_sequence,
            confidence_curve=confidence_curve,
            verification_report=verification_result.to_dict(),
            replayed_at=replayed_time
        )


chitra_replay_engine = ChitraReplayEngine()
