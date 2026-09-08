"""
Learning Pattern Database Model (Whitesheet F14 & F15).
Defines persistent PostgreSQL schema for extracted learning patterns and candidate lifecycles.
"""
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from app.db.database import Base


class LearningPattern(Base):
    """
    PostgreSQL persistent representation of an F14/F15 learning candidate pattern.
    Guarantees pattern survival across process restarts with strict tenant isolation.
    """
    __tablename__ = "learning_patterns"

    id = Column(Integer, primary_key=True, index=True)
    pattern_id = Column(String(128), unique=True, nullable=False, index=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    pattern_type = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(32), default="CANDIDATE", nullable=False, index=True)
    fingerprint = Column(String(128), nullable=True, index=True)
    confidence = Column(Float, default=0.5, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    le_score = Column(Float, default=0.0, nullable=False)
    constitutional_approved = Column(Boolean, default=False, nullable=False)
    shadow_passed = Column(Boolean, default=False, nullable=False)
    regression_passed = Column(Boolean, default=False, nullable=False)
    action_template = Column(JSON, nullable=False, default=dict)
    evidence = Column(JSON, nullable=False, default=dict)
    source_episode_ids = Column(JSON, nullable=False, default=list)
    metadata_payload = Column(JSON, nullable=False, default=dict)
    promoted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
