"""
FEDERATION RUNTIME ENVIRONMENT & NODE LIFECYCLE (Whitesheet §18.1 - §18.6)
Manages local instance node identity, signing keys, trust registry, and pipeline coordinator.
Configurable via standard environment variables:
- BRAHMA_NODE_ID
- BRAHMA_NODE_NAME
- BRAHMA_NODE_ENDPOINT
- BRAHMA_TENANT_ID
- BRAHMA_NODE_PRIVATE_KEY
"""
import os
import secrets
import logging
from typing import Optional
from ecdsa import SigningKey

from app.core.federation.models import NodeIdentity, TrustTier, NodeStatus
from app.core.federation.identity import NodeIdentityManager
from app.core.federation.trust import NodeTrustRegistry
from app.core.federation.replay import FederationReplayGuard
from app.core.federation.sync import FederatedSyncStore
from app.core.federation.orchestrator import FederationPipelineCoordinator
from app.core.chitra.crypto import generate_ulid

logger = logging.getLogger(__name__)


class FederationRuntime:
    """
    Singleton runtime container for a BRAHMA node's cryptographic and federation state.
    """

    def __init__(
        self,
        node_id: Optional[str] = None,
        name: Optional[str] = None,
        endpoint: Optional[str] = None,
        tenant_id: Optional[str] = None,
        signing_key: Optional[SigningKey] = None,
        trust_tier: TrustTier = TrustTier.FEDERATED
    ):
        env_node_id = os.getenv("BRAHMA_NODE_ID")
        env_name = os.getenv("BRAHMA_NODE_NAME")
        env_endpoint = os.getenv("BRAHMA_NODE_ENDPOINT")
        env_tenant = os.getenv("BRAHMA_TENANT_ID", "tenant_global")

        self.tenant_id = tenant_id or env_tenant

        # Initialize or load signing key
        if signing_key is not None:
            self.signing_key = signing_key
            self.public_key_hex = signing_key.verifying_key.to_string().hex()
        else:
            self.signing_key, self.public_key_hex = NodeIdentityManager.generate_keypair()

        self.node_id = node_id or env_node_id or generate_ulid(prefix="node_")
        self.name = name or env_name or f"BrahmaNode_{self.node_id[:8]}"
        self.endpoint = endpoint or env_endpoint or "http://127.0.0.1:8000"

        self.local_identity = NodeIdentity(
            node_id=self.node_id,
            public_key=self.public_key_hex,
            tenant_id=self.tenant_id,
            trust_tier=trust_tier,
            status=NodeStatus.ACTIVE,
            name=self.name,
            endpoint=self.endpoint,
            metadata={"runtime": "FastAPI", "version": "0.1.0"}
        )

        self.trust_registry = NodeTrustRegistry(tenant_id=self.tenant_id)
        self.replay_guard = FederationReplayGuard()
        self.sync_store = FederatedSyncStore()

        self.coordinator = FederationPipelineCoordinator(
            local_identity=self.local_identity,
            local_signing_key=self.signing_key,
            trust_registry=self.trust_registry,
            replay_guard=self.replay_guard,
            sync_store=self.sync_store
        )
        logger.info(f"Initialized FederationRuntime for node '{self.node_id}' ({self.name}) at '{self.endpoint}'")


_GLOBAL_FEDERATION_RUNTIME: Optional[FederationRuntime] = None


def get_federation_runtime() -> FederationRuntime:
    """Retrieves or initializes the global singleton FederationRuntime."""
    global _GLOBAL_FEDERATION_RUNTIME
    if _GLOBAL_FEDERATION_RUNTIME is None:
        _GLOBAL_FEDERATION_RUNTIME = FederationRuntime()
    return _GLOBAL_FEDERATION_RUNTIME


def reset_federation_runtime(new_runtime: Optional[FederationRuntime] = None) -> FederationRuntime:
    """Overrides or resets the global FederationRuntime for testing or multi-instance configuration."""
    global _GLOBAL_FEDERATION_RUNTIME
    _GLOBAL_FEDERATION_RUNTIME = new_runtime or FederationRuntime()
    return _GLOBAL_FEDERATION_RUNTIME
