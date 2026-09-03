"""
FEDERATION SYSTEM Core Package (Whitesheet §18.0 - §18.6)
Phase 18A: Federation Data Models & Cryptographic Node Identity.
Phase 18B: Node Trust Registry & Peer Handshake.
Phase 18C: Distributed Pattern & Memory Synchronization.
Phase 18D: Conflict Resolution & Convergence.
Phase 18E: Cross-Node Constitutional Governance & Blast Radius.
Phase 18F: Federated CHITRA Audit Integration.
"""
from app.core.federation.models import (
    TrustTier,
    NodeStatus,
    FederationPayloadType,
    NodeIdentity,
    FederationMessage
)
from app.core.federation.identity import (
    NodeIdentityManager,
    canonical_message_bytes
)
from app.core.federation.trust import (
    NodeTrustRegistry,
    TrustTransitionError
)
from app.core.federation.handshake import (
    NodeHandshakeService
)
from app.core.federation.sync import (
    SyncPayloadError,
    FederatedSyncStore,
    FederatedSyncService
)
from app.core.federation.conflict import (
    VectorComparison,
    VersionVector,
    FederatedVersionedRecord,
    ConflictResolutionEngine
)
from app.core.federation.governance import (
    GovernanceDecision,
    FederatedGovernanceVerdict,
    FederatedGovernanceEngine
)
from app.core.federation.audit import (
    FederationAuditEventType,
    FederatedAuditEvent,
    FederatedChitraAuditService
)

__all__ = [
    "TrustTier",
    "NodeStatus",
    "FederationPayloadType",
    "NodeIdentity",
    "FederationMessage",
    "NodeIdentityManager",
    "canonical_message_bytes",
    "NodeTrustRegistry",
    "TrustTransitionError",
    "NodeHandshakeService",
    "SyncPayloadError",
    "FederatedSyncStore",
    "FederatedSyncService",
    "VectorComparison",
    "VersionVector",
    "FederatedVersionedRecord",
    "ConflictResolutionEngine",
    "GovernanceDecision",
    "FederatedGovernanceVerdict",
    "FederatedGovernanceEngine",
    "FederationAuditEventType",
    "FederatedAuditEvent",
    "FederatedChitraAuditService"
]
