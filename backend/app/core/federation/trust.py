"""
FEDERATION NODE TRUST REGISTRY (Whitesheet §18.1, §18.5, §23 Phase 4 - Gap #8)
Authoritative PostgreSQL-persisted registry governing node registration, trust tiers, lifecycle state,
and multi-tenant isolation.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from contextlib import contextmanager

from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.models.federation_node import FederationNode
from app.core.federation.models import NodeIdentity, TrustTier, NodeStatus
from app.core.federation.identity import NodeIdentityManager


class TrustTransitionError(Exception):
    """Raised when an invalid or unauthorized trust tier escalation is attempted."""
    pass


import secrets

class NodeTrustRegistry:
    """
    Authoritative PostgreSQL-persisted registry of known federation nodes,
    managing trust standing, lifecycle status, and tenant isolation.
    PostgreSQL is the authoritative source of truth.
    """

    # Allowed sequential progression: UNTRUSTED -> VERIFIED -> FEDERATED -> SOVEREIGN
    ALLOWED_FORWARD_TRANSITIONS = {
        TrustTier.UNTRUSTED: {TrustTier.VERIFIED},
        TrustTier.VERIFIED: {TrustTier.FEDERATED, TrustTier.UNTRUSTED},
        TrustTier.FEDERATED: {TrustTier.SOVEREIGN, TrustTier.VERIFIED, TrustTier.UNTRUSTED},
        TrustTier.SOVEREIGN: {TrustTier.FEDERATED, TrustTier.VERIFIED, TrustTier.UNTRUSTED}
    }

    def __init__(self, tenant_id: Optional[str] = None, db_session: Optional[Session] = None):
        self.tenant_id = tenant_id if tenant_id is not None else f"tenant_{secrets.token_hex(8)}"
        self._db_session = db_session
        self._nodes: Dict[str, NodeIdentity] = {}

    @contextmanager
    def _session_scope(self, db_session: Optional[Session] = None):
        """Context manager for database sessions, ensuring atomic transactions and fail-closed error handling."""
        if db_session is not None:
            yield db_session
        elif self._db_session is not None:
            yield self._db_session
        else:
            session = SessionLocal()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    def register_node(
        self,
        identity: NodeIdentity,
        tenant_id: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> None:
        """
        Registers a new node identity and persists it to PostgreSQL.
        Fails closed on duplicate registrations, missing fields, or malformed public keys.
        """
        if not identity or not isinstance(identity, NodeIdentity):
            raise ValueError("Node identity must be a valid NodeIdentity instance (FAIL-CLOSED).")

        # Cryptographic verification of public key format
        if not NodeIdentityManager.verify_node_identity(identity):
            raise ValueError(f"Malformed or invalid public key in NodeIdentity for node_id: '{identity.node_id}'.")

        effective_tenant = tenant_id or identity.tenant_id or self.tenant_id or "default"

        with self._session_scope(db_session) as session:
            # Check for duplicate node registration across database
            existing = session.query(FederationNode).filter(
                FederationNode.node_id == identity.node_id
            ).first()

            if existing:
                raise ValueError(f"Duplicate node registration rejected for node_id: '{identity.node_id}'.")

            tier_val = identity.trust_tier.value if isinstance(identity.trust_tier, TrustTier) else str(identity.trust_tier)
            status_val = identity.status.value if isinstance(identity.status, NodeStatus) else str(identity.status)

            db_node = FederationNode(
                node_id=identity.node_id,
                tenant_id=effective_tenant,
                public_key=identity.public_key,
                trust_tier=tier_val,
                status=status_val,
                name=identity.name,
                endpoint=identity.endpoint,
                node_metadata=identity.metadata or {}
            )
            session.add(db_node)
            session.flush()

            # Maintain in-memory mirror
            saved_identity = db_node.to_node_identity()
            self._nodes[identity.node_id] = saved_identity

    def get_node(
        self,
        node_id: str,
        tenant_id: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> Optional[NodeIdentity]:
        """
        Retrieves a registered node by node_id from PostgreSQL.
        Enforces tenant isolation if tenant_id or self.tenant_id is specified.
        Returns None if unknown or not accessible to the tenant.
        """
        if not node_id or not node_id.strip():
            return None

        clean_id = node_id.strip()
        effective_tenant = tenant_id if tenant_id is not None else self.tenant_id

        with self._session_scope(db_session) as session:
            query = session.query(FederationNode).filter(FederationNode.node_id == clean_id)
            if effective_tenant is not None and effective_tenant != "*":
                query = query.filter(FederationNode.tenant_id == effective_tenant)

            record = query.first()
            if not record:
                return None

            identity = record.to_node_identity()
            self._nodes[clean_id] = identity
            return identity

    def list_nodes(
        self,
        trust_tier: Optional[TrustTier] = None,
        status: Optional[NodeStatus] = None,
        tenant_id: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> List[NodeIdentity]:
        """
        Lists registered nodes from PostgreSQL filtered by optional trust_tier, status, and tenant_id.
        """
        effective_tenant = tenant_id if tenant_id is not None else self.tenant_id

        with self._session_scope(db_session) as session:
            query = session.query(FederationNode)
            if effective_tenant is not None and effective_tenant != "*":
                query = query.filter(FederationNode.tenant_id == effective_tenant)
            if trust_tier is not None:
                tier_val = trust_tier.value if isinstance(trust_tier, TrustTier) else str(trust_tier)
                query = query.filter(FederationNode.trust_tier == tier_val)
            if status is not None:
                status_val = status.value if isinstance(status, NodeStatus) else str(status)
                query = query.filter(FederationNode.status == status_val)

            records = query.order_by(FederationNode.id.asc()).all()
            results = [r.to_node_identity() for r in records]
            return results

    def update_trust_tier(
        self,
        node_id: str,
        new_tier: TrustTier,
        reason: Optional[str] = None,
        tenant_id: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> NodeIdentity:
        """
        Updates a node's trust tier in PostgreSQL according to the strict transition state machine.
        Rejects illegal jumps (e.g. UNTRUSTED -> FEDERATED/SOVEREIGN).
        """
        if not node_id or not node_id.strip():
            raise KeyError(f"Cannot update trust tier: node_id '{node_id}' is not registered.")

        clean_id = node_id.strip()
        effective_tenant = tenant_id if tenant_id is not None else self.tenant_id

        with self._session_scope(db_session) as session:
            query = session.query(FederationNode).filter(FederationNode.node_id == clean_id)
            if effective_tenant is not None and effective_tenant != "*":
                query = query.filter(FederationNode.tenant_id == effective_tenant)

            record = query.first()
            if not record:
                raise KeyError(f"Cannot update trust tier: node_id '{clean_id}' is not registered.")

            if record.status in [NodeStatus.REVOKED.value, NodeStatus.SUSPENDED.value]:
                raise TrustTransitionError(f"Cannot update trust tier for node '{clean_id}' in status '{record.status}'.")

            current_tier = TrustTier(record.trust_tier)
            target_tier = new_tier if isinstance(new_tier, TrustTier) else TrustTier(new_tier)

            if current_tier == target_tier:
                return record.to_node_identity()

            allowed = self.ALLOWED_FORWARD_TRANSITIONS.get(current_tier, set())
            if target_tier not in allowed:
                raise TrustTransitionError(
                    f"Illegal trust escalation from '{current_tier.value}' to '{target_tier.value}' "
                    f"for node '{clean_id}'. Transitions must follow sequential progression."
                )

            updated_metadata = dict(record.node_metadata or {})
            updated_metadata["last_trust_change"] = {
                "from": current_tier.value,
                "to": target_tier.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": reason or "Administrative update"
            }

            record.trust_tier = target_tier.value
            record.node_metadata = updated_metadata
            record.updated_at = datetime.now(timezone.utc)
            session.flush()

            saved_identity = record.to_node_identity()
            self._nodes[clean_id] = saved_identity
            return saved_identity

    def set_node_status(
        self,
        node_id: str,
        new_status: NodeStatus,
        reason: Optional[str] = None,
        tenant_id: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> NodeIdentity:
        """
        Updates the operational status of a node in PostgreSQL (e.g. SUSPENDED or REVOKED).
        """
        if not node_id or not node_id.strip():
            raise KeyError(f"Cannot update status: node_id '{node_id}' is not registered.")

        clean_id = node_id.strip()
        effective_tenant = tenant_id if tenant_id is not None else self.tenant_id

        with self._session_scope(db_session) as session:
            query = session.query(FederationNode).filter(FederationNode.node_id == clean_id)
            if effective_tenant is not None and effective_tenant != "*":
                query = query.filter(FederationNode.tenant_id == effective_tenant)

            record = query.first()
            if not record:
                raise KeyError(f"Cannot update status: node_id '{clean_id}' is not registered.")

            target_status = new_status if isinstance(new_status, NodeStatus) else NodeStatus(new_status)

            updated_metadata = dict(record.node_metadata or {})
            updated_metadata["last_status_change"] = {
                "from": record.status,
                "to": target_status.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": reason or "Administrative status change"
            }

            record.status = target_status.value
            record.node_metadata = updated_metadata
            record.updated_at = datetime.now(timezone.utc)
            session.flush()

            saved_identity = record.to_node_identity()
            self._nodes[clean_id] = saved_identity
            return saved_identity

    def is_node_trusted(
        self,
        node_id: str,
        minimum_tier: TrustTier = TrustTier.VERIFIED,
        tenant_id: Optional[str] = None,
        db_session: Optional[Session] = None
    ) -> bool:
        """
        Returns True only if the node is registered, ACTIVE, and meets or exceeds the minimum trust tier in PostgreSQL.
        """
        node = self.get_node(node_id, tenant_id=tenant_id, db_session=db_session)
        if not node or node.status != NodeStatus.ACTIVE:
            return False

        tier_weights = {
            TrustTier.UNTRUSTED: 0,
            TrustTier.VERIFIED: 1,
            TrustTier.FEDERATED: 2,
            TrustTier.SOVEREIGN: 3
        }
        return tier_weights.get(node.trust_tier, 0) >= tier_weights.get(minimum_tier, 1)
