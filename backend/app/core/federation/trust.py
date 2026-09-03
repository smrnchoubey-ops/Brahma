"""
FEDERATION NODE TRUST REGISTRY (Whitesheet §18.1)
Deterministic in-memory registry governing node registration, trust tiers, and lifecycle state.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from app.core.federation.models import NodeIdentity, TrustTier, NodeStatus
from app.core.federation.identity import NodeIdentityManager


class TrustTransitionError(Exception):
    """Raised when an invalid or unauthorized trust tier escalation is attempted."""
    pass


class NodeTrustRegistry:
    """
    Authoritative in-memory registry of known federation nodes, managing trust standing and status.
    """

    # Allowed sequential progression: UNTRUSTED -> VERIFIED -> FEDERATED -> SOVEREIGN
    ALLOWED_FORWARD_TRANSITIONS = {
        TrustTier.UNTRUSTED: {TrustTier.VERIFIED},
        TrustTier.VERIFIED: {TrustTier.FEDERATED, TrustTier.UNTRUSTED},
        TrustTier.FEDERATED: {TrustTier.SOVEREIGN, TrustTier.VERIFIED, TrustTier.UNTRUSTED},
        TrustTier.SOVEREIGN: {TrustTier.FEDERATED, TrustTier.VERIFIED, TrustTier.UNTRUSTED}
    }

    def __init__(self):
        self._nodes: Dict[str, NodeIdentity] = {}

    def register_node(self, identity: NodeIdentity) -> None:
        """
        Registers a new node identity.
        Fails closed on duplicate registrations, missing fields, or malformed public keys.
        """
        if not identity or not isinstance(identity, NodeIdentity):
            raise ValueError("Node identity must be a valid NodeIdentity instance (FAIL-CLOSED).")

        if identity.node_id in self._nodes:
            raise ValueError(f"Duplicate node registration rejected for node_id: '{identity.node_id}'.")

        # Cryptographic verification of public key format
        if not NodeIdentityManager.verify_node_identity(identity):
            raise ValueError(f"Malformed or invalid public key in NodeIdentity for node_id: '{identity.node_id}'.")

        self._nodes[identity.node_id] = identity.model_copy()

    def get_node(self, node_id: str) -> Optional[NodeIdentity]:
        """
        Retrieves a registered node by node_id. Returns None if unknown.
        """
        if not node_id or not node_id.strip():
            return None
        node = self._nodes.get(node_id.strip())
        return node.model_copy() if node else None

    def list_nodes(self, trust_tier: Optional[TrustTier] = None, status: Optional[NodeStatus] = None) -> List[NodeIdentity]:
        """
        Lists registered nodes filtered by optional trust_tier and status.
        """
        results = []
        for node in self._nodes.values():
            if trust_tier and node.trust_tier != trust_tier:
                continue
            if status and node.status != status:
                continue
            results.append(node.model_copy())
        return results

    def update_trust_tier(self, node_id: str, new_tier: TrustTier, reason: Optional[str] = None) -> NodeIdentity:
        """
        Updates a node's trust tier according to the strict transition state machine.
        Rejects illegal jumps (e.g. UNTRUSTED -> FEDERATED/SOVEREIGN).
        """
        node = self._nodes.get(node_id)
        if not node:
            raise KeyError(f"Cannot update trust tier: node_id '{node_id}' is not registered.")

        if node.status in [NodeStatus.REVOKED, NodeStatus.SUSPENDED]:
            raise TrustTransitionError(f"Cannot update trust tier for node '{node_id}' in status '{node.status.value}'.")

        current_tier = node.trust_tier
        if current_tier == new_tier:
            return node.model_copy()

        allowed = self.ALLOWED_FORWARD_TRANSITIONS.get(current_tier, set())
        if new_tier not in allowed:
            raise TrustTransitionError(
                f"Illegal trust escalation from '{current_tier.value}' to '{new_tier.value}' "
                f"for node '{node_id}'. Transitions must follow sequential progression."
            )

        updated_metadata = dict(node.metadata)
        updated_metadata["last_trust_change"] = {
            "from": current_tier.value,
            "to": new_tier.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason or "Administrative update"
        }

        updated_node = node.model_copy(update={
            "trust_tier": new_tier,
            "metadata": updated_metadata
        })
        self._nodes[node_id] = updated_node
        return updated_node.model_copy()

    def set_node_status(self, node_id: str, new_status: NodeStatus, reason: Optional[str] = None) -> NodeIdentity:
        """
        Updates the operational status of a node (e.g. SUSPENDED or REVOKED).
        """
        node = self._nodes.get(node_id)
        if not node:
            raise KeyError(f"Cannot update status: node_id '{node_id}' is not registered.")

        updated_metadata = dict(node.metadata)
        updated_metadata["last_status_change"] = {
            "from": node.status.value,
            "to": new_status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason or "Administrative status change"
        }

        updated_node = node.model_copy(update={
            "status": new_status,
            "metadata": updated_metadata
        })
        self._nodes[node_id] = updated_node
        return updated_node.model_copy()

    def is_node_trusted(self, node_id: str, minimum_tier: TrustTier = TrustTier.VERIFIED) -> bool:
        """
        Returns True only if the node is registered, ACTIVE, and meets or exceeds the minimum trust tier.
        """
        node = self._nodes.get(node_id)
        if not node or node.status != NodeStatus.ACTIVE:
            return False

        tier_weights = {
            TrustTier.UNTRUSTED: 0,
            TrustTier.VERIFIED: 1,
            TrustTier.FEDERATED: 2,
            TrustTier.SOVEREIGN: 3
        }
        return tier_weights.get(node.trust_tier, 0) >= tier_weights.get(minimum_tier, 1)
