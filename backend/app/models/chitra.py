from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from app.db.database import Base


class ChitraEvent(Base):
    """
    CHITRA Immutable Cryptographic Ledger Event Record.
    Strictly conforms to BRAHMA COS Whitesheet §8.2 and Appendix C.1.
    """
    __tablename__ = "chitra_events"

    id = Column(Integer, primary_key=True, index=True)
    
    # Monotonic ULID (Whitesheet §8.2: evt-<ULID>) with strict unique index
    event_id = Column(String(36), unique=True, index=True, nullable=False)
    
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False)
    session_id = Column(String(64), index=True, nullable=True)
    timestamp = Column(DateTime(timezone=True), index=True, nullable=False)
    
    # Faculty / Agent origin (e.g. F9, KARMA, MARYADA, PRAGYA, RACHIT, KOSH, SYSTEM)
    faculty = Column(String(64), index=True, nullable=False)
    
    # Event category (perception | retrieval | verification | decision | gate | route | invocation | validation | learning | escalation)
    event_type = Column(String(64), index=True, nullable=False)
    
    # SHA-256 hash of canonical input data
    input_hash = Column(String(71), nullable=False)
    
    # Structured decision / execution snapshot
    decision = Column(JSON, nullable=True)
    
    # Upstream causal event IDs (e.g. ["evt_01J..."])
    evidence = Column(JSON, nullable=True)
    
    # Confidence score (0.0 to 1.0)
    confidence = Column(Float, default=1.0, index=True, nullable=False)
    
    # Result outcome object
    outcome = Column(JSON, nullable=True)
    
    # Constitutional governance verdict (passed | pending | failed | n/a)
    constitutional_review = Column(String(32), default="passed", index=True, nullable=False)
    
    # Cryptographic Hash Chaining (§8.3)
    prev_event_hash = Column(String(71), nullable=False)
    this_event_hash = Column(String(71), unique=True, index=True, nullable=False)
    
    # HMAC-SHA256 Authority Signature
    signature = Column(String(79), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Concurrency safeguard: prevents two events for the same task from claiming the same parent hash (fork prevention)
    __table_args__ = (
        UniqueConstraint("task_id", "prev_event_hash", name="uq_chitra_task_prev_hash"),
    )
