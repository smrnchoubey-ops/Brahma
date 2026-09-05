from sqlalchemy import Column, Integer, String, Text, Float, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.db.database import Base


class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(64), nullable=False, index=True, default="global")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    provenance_source = Column(String(255), default="unspecified", nullable=False)
    source_uri = Column(String(512), nullable=True)
    confidence_score = Column(Float, default=1.0, nullable=False)
    epistemic_status = Column(String(64), default="VERIFIED", nullable=False, index=True)
    verification_details = Column(JSON, nullable=True)
    embedding = Column(Vector(768), nullable=True)
    lifecycle_state = Column(String(64), default="INGESTION", nullable=False, index=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    constitutional_verdict = Column(String(64), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    deprecated_at = Column(DateTime(timezone=True), nullable=True)
    deprecation_reason = Column(String(512), nullable=True)
    lifecycle_history = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())