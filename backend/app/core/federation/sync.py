"""
FEDERATION SYNCHRONIZATION SERVICE (Whitesheet §18.3, §18.5)
Coordinates distributed, tenant-scoped synchronization of PROMOTED F15 learning patterns
and curated KOSH memory chunks between authenticated federation nodes.
"""
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
import secrets

from ecdsa import SigningKey

from app.core.federation.models import (
    NodeIdentity,
    FederationMessage,
    FederationPayloadType,
    TrustTier,
    NodeStatus
)
from app.core.federation.identity import NodeIdentityManager
from app.core.federation.trust import NodeTrustRegistry
from app.core.learning.models import LearningCandidate, PatternStatus
from app.core.kosh.memory_tiers import KoshChunk, MemoryTier
from app.core.chitra.crypto import generate_ulid


class SyncPayloadError(Exception):
    """Raised when an invalid or unpromoted sync item is packaged or ingested."""
    pass


class FederatedSyncStore:
    """
    In-memory isolated storage for ingested cross-node patterns and memory chunks in staging state.
    """

    def __init__(self):
        self._ingested_messages: Dict[str, Dict[str, Any]] = {}
        self._synced_patterns: Dict[str, Dict[str, Any]] = {}
        self._synced_chunks: Dict[str, Dict[str, Any]] = {}

    def is_message_ingested(self, message_id: str) -> bool:
        return message_id in self._ingested_messages

    def store_pattern(self, message_id: str, pattern_id: str, record: Dict[str, Any]) -> None:
        self._ingested_messages[message_id] = record
        self._synced_patterns[pattern_id] = record

    def store_chunk(self, message_id: str, chunk_id: str, record: Dict[str, Any]) -> None:
        self._ingested_messages[message_id] = record
        self._synced_chunks[chunk_id] = record

    def get_pattern(self, pattern_id: str) -> Optional[Dict[str, Any]]:
        return self._synced_patterns.get(pattern_id)

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        return self._synced_chunks.get(chunk_id)

    def list_synced_patterns(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not tenant_id:
            return list(self._synced_patterns.values())
        return [p for p in self._synced_patterns.values() if p.get("target_tenant_id") == tenant_id]

    def list_synced_chunks(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not tenant_id:
            return list(self._synced_chunks.values())
        return [c for c in self._synced_chunks.values() if c.get("target_tenant_id") == tenant_id]


class FederatedSyncService:
    """
    Service coordinating cross-node pattern and memory synchronization.
    """

    @classmethod
    def create_pattern_sync_message(
        cls,
        source_identity: NodeIdentity,
        source_signing_key: SigningKey,
        target_node_id: str,
        tenant_id: str,
        pattern: LearningCandidate,
        allowed_target_tenants: Optional[List[str]] = None
    ) -> FederationMessage:
        """
        Constructs and signs a PATTERN_SYNC FederationMessage.
        Fails closed if the pattern is not in PROMOTED status (§18.3).
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Tenant ID is required for pattern synchronization (AUTHENTICATED_TENANT_REQUIRED).")

        if pattern.status != PatternStatus.PROMOTED:
            raise SyncPayloadError(
                f"Cannot synchronize pattern '{pattern.pattern_id}' in status '{pattern.status.value}'. "
                f"Only PROMOTED patterns may be synchronized across federation nodes (FAIL-CLOSED)."
            )

        if pattern.tenant_id != tenant_id:
            raise SyncPayloadError(
                f"Pattern tenant '{pattern.tenant_id}' does not match message tenant '{tenant_id}'."
            )

        allowed_tenants = allowed_target_tenants or [tenant_id]

        payload = {
            "sync_type": "PATTERN",
            "pattern": pattern.model_dump(),
            "allowed_target_tenants": allowed_tenants,
            "origin_node_id": source_identity.node_id,
            "origin_timestamp": datetime.now(timezone.utc).isoformat()
        }

        unsigned_msg = FederationMessage(
            message_id=generate_ulid(prefix="msg_sync_pat_"),
            source_node_id=source_identity.node_id,
            target_node_id=target_node_id,
            tenant_id=tenant_id,
            payload_type=FederationPayloadType.PATTERN_SYNC,
            payload=payload,
            nonce=secrets.token_hex(16)
        )

        return NodeIdentityManager.sign_message(source_signing_key, unsigned_msg)

    @classmethod
    def create_memory_sync_message(
        cls,
        source_identity: NodeIdentity,
        source_signing_key: SigningKey,
        target_node_id: str,
        tenant_id: str,
        chunk: KoshChunk,
        allowed_target_tenants: Optional[List[str]] = None
    ) -> FederationMessage:
        """
        Constructs and signs a KNOWLEDGE_SYNC FederationMessage for a curated KOSH memory chunk (§18.3).
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Tenant ID is required for memory synchronization (AUTHENTICATED_TENANT_REQUIRED).")

        if not chunk.content or not chunk.content.strip():
            raise SyncPayloadError("Cannot synchronize empty KOSH memory chunk (FAIL-CLOSED).")

        if chunk.tenant_id != tenant_id:
            raise SyncPayloadError(
                f"Chunk tenant '{chunk.tenant_id}' does not match message tenant '{tenant_id}'."
            )

        allowed_tenants = allowed_target_tenants or [tenant_id]

        payload = {
            "sync_type": "KNOWLEDGE",
            "chunk": chunk.model_dump(),
            "allowed_target_tenants": allowed_tenants,
            "origin_node_id": source_identity.node_id,
            "origin_timestamp": datetime.now(timezone.utc).isoformat()
        }

        unsigned_msg = FederationMessage(
            message_id=generate_ulid(prefix="msg_sync_mem_"),
            source_node_id=source_identity.node_id,
            target_node_id=target_node_id,
            tenant_id=tenant_id,
            payload_type=FederationPayloadType.KNOWLEDGE_SYNC,
            payload=payload,
            nonce=secrets.token_hex(16)
        )

        return NodeIdentityManager.sign_message(source_signing_key, unsigned_msg)

    @classmethod
    def verify_and_ingest_sync_message(
        cls,
        local_identity: NodeIdentity,
        trust_registry: NodeTrustRegistry,
        incoming_message: FederationMessage,
        local_tenant_id: str,
        sync_store: Optional[FederatedSyncStore] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Validates, authenticates, and ingests an incoming synchronization message.
        Enforces:
        1. Valid payload type (PATTERN_SYNC or KNOWLEDGE_SYNC).
        2. Recipient addressing (local node ID or BROADCAST).
        3. Sender verification via NodeTrustRegistry (must be ACTIVE and at least VERIFIED).
        4. Cryptographic signature verification over canonical message bytes.
        5. Tenant policy enforcement (same tenant OR explicitly authorized in allowed_target_tenants).
        6. Payload integrity & provenance preservation.
        7. Ingested items are placed in STAGED_FOR_LOCAL_EVALUATION state (not auto-promoted).
        8. Idempotency protection if sync_store is provided.
        """
        # 1. Check payload type
        if incoming_message.payload_type not in [FederationPayloadType.PATTERN_SYNC, FederationPayloadType.KNOWLEDGE_SYNC]:
            return False, f"Unsupported payload type '{incoming_message.payload_type.value}' for synchronization.", None

        # 2. Target node check
        if incoming_message.target_node_id not in [local_identity.node_id, "BROADCAST"]:
            return False, f"Message target '{incoming_message.target_node_id}' does not match local node '{local_identity.node_id}'.", None

        # 3. Trust registry validation
        sender_node = trust_registry.get_node(incoming_message.source_node_id)
        if not sender_node:
            return False, f"Unauthorized sender node '{incoming_message.source_node_id}': not in TrustRegistry.", None

        if sender_node.status != NodeStatus.ACTIVE:
            return False, f"Sender node '{incoming_message.source_node_id}' is inactive ('{sender_node.status.value}').", None

        if not trust_registry.is_node_trusted(sender_node.node_id, minimum_tier=TrustTier.VERIFIED):
            return False, f"Sender node '{incoming_message.source_node_id}' has insufficient trust tier '{sender_node.trust_tier.value}'.", None

        # 4. Cryptographic signature check
        is_valid_sig = NodeIdentityManager.verify_message_signature(
            public_key_hex=sender_node.public_key,
            message=incoming_message
        )
        if not is_valid_sig:
            return False, "Cryptographic signature verification failed on sync message.", None

        # 5. Tenant isolation check (§18.5)
        allowed_targets = incoming_message.payload.get("allowed_target_tenants", [incoming_message.tenant_id])
        if incoming_message.tenant_id != local_tenant_id and local_tenant_id not in allowed_targets:
            return False, (
                f"Cross-tenant synchronization rejected. Source tenant '{incoming_message.tenant_id}' "
                f"not permitted for local tenant '{local_tenant_id}'."
            ), None

        # 6. Idempotency check
        if sync_store and sync_store.is_message_ingested(incoming_message.message_id):
            return True, "Message already ingested (idempotent).", sync_store._ingested_messages[incoming_message.message_id]

        # 7. Payload validation and provenance assembly
        now_ts = datetime.now(timezone.utc).isoformat()

        if incoming_message.payload_type == FederationPayloadType.PATTERN_SYNC:
            pat_data = incoming_message.payload.get("pattern")
            if not pat_data or not isinstance(pat_data, dict):
                return False, "Malformed pattern payload: missing 'pattern' dictionary.", None

            # Verify pattern was promoted
            if pat_data.get("status") != PatternStatus.PROMOTED.value:
                return False, f"Rejected sync: remote pattern status is '{pat_data.get('status')}', expected PROMOTED.", None

            ingested_record = {
                "sync_type": "PATTERN",
                "message_id": incoming_message.message_id,
                "source_node_id": incoming_message.source_node_id,
                "source_tenant_id": incoming_message.tenant_id,
                "target_tenant_id": local_tenant_id,
                "entity_id": pat_data.get("pattern_id"),
                "data": pat_data,
                "federated_status": "STAGED_FOR_LOCAL_EVALUATION",
                "synced_at": now_ts,
                "provenance": {
                    "source_node": incoming_message.source_node_id,
                    "source_tenant": incoming_message.tenant_id,
                    "origin_timestamp": incoming_message.payload.get("origin_timestamp"),
                    "signature_verified": True
                }
            }

            if sync_store:
                sync_store.store_pattern(incoming_message.message_id, pat_data.get("pattern_id"), ingested_record)

            return True, "Pattern successfully ingested in STAGED status.", ingested_record

        elif incoming_message.payload_type == FederationPayloadType.KNOWLEDGE_SYNC:
            chunk_data = incoming_message.payload.get("chunk")
            if not chunk_data or not isinstance(chunk_data, dict):
                return False, "Malformed memory payload: missing 'chunk' dictionary.", None

            if not chunk_data.get("content"):
                return False, "Rejected sync: empty memory chunk content.", None

            ingested_record = {
                "sync_type": "KNOWLEDGE",
                "message_id": incoming_message.message_id,
                "source_node_id": incoming_message.source_node_id,
                "source_tenant_id": incoming_message.tenant_id,
                "target_tenant_id": local_tenant_id,
                "entity_id": chunk_data.get("chunk_id"),
                "data": chunk_data,
                "federated_status": "STAGED_FOR_LOCAL_EVALUATION",
                "synced_at": now_ts,
                "provenance": {
                    "source_node": incoming_message.source_node_id,
                    "source_tenant": incoming_message.tenant_id,
                    "origin_timestamp": incoming_message.payload.get("origin_timestamp"),
                    "signature_verified": True
                }
            }

            if sync_store:
                sync_store.store_chunk(incoming_message.message_id, chunk_data.get("chunk_id"), ingested_record)

            return True, "Memory chunk successfully ingested in STAGED status.", ingested_record

        return False, "Unknown synchronization error.", None
