"""
Federation Node Database Model (Whitesheet §18 & §23 - Gap #8).
Defines persistent PostgreSQL schema for Federation node registry state and cryptographic standing.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.db.database import Base


class FederationNode(Base):
    """
    PostgreSQL persistent representation of a Federation node identity and trust standing.
    Guarantees registry survival across process restarts with strict tenant isolation.
    """
    __tablename__ = "federation_nodes"

    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(String(128), unique=True, nullable=False, index=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    public_key = Column(Text, nullable=False)
    trust_tier = Column(String(32), default="UNTRUSTED", nullable=False, index=True)
    status = Column(String(32), default="ACTIVE", nullable=False, index=True)
    name = Column(String(255), nullable=True)
    endpoint = Column(String(255), nullable=True)
    node_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_node_identity(self):
        """Converts PostgreSQL FederationNode model to canonical NodeIdentity domain model."""
        from app.core.federation.models import NodeIdentity, TrustTier, NodeStatus
        return NodeIdentity(
            node_id=self.node_id,
            public_key=self.public_key,
            tenant_id=self.tenant_id,
            trust_tier=TrustTier(self.trust_tier),
            status=NodeStatus(self.status),
            name=self.name,
            endpoint=self.endpoint,
            metadata=self.node_metadata or {},
            created_at=self.created_at.isoformat() if self.created_at else datetime.now(timezone.utc).isoformat()
        )
