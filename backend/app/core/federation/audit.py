"""
FEDERATED CHITRA AUDIT INTEGRATION (Whitesheet §18.6)
Provides authoritative cryptographic audit chaining and cross-node provenance linkage
for all incoming, outgoing, and security-rejected federation wire events.
"""
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from datetime import datetime, timezone
import hashlib
from pydantic import BaseModel, Field

from app.core.federation.models import FederationMessage, NodeIdentity
from app.core.chitra.crypto import (
    GENESIS_HASH,
    generate_ulid,
    canonical_json,
    compute_sha256,
    compute_content_hash,
    compute_chained_hash,
    sign_event,
    verify_event_signature
)


class FederationAuditEventType(str, Enum):
    FEDERATION_INCOMING = "FEDERATION_INCOMING"
    FEDERATION_OUTGOING = "FEDERATION_OUTGOING"
    FEDERATION_SECURITY_REJECTION = "FEDERATION_SECURITY_REJECTION"
    FEDERATION_HANDSHAKE = "FEDERATION_HANDSHAKE"
    FEDERATION_SYNC = "FEDERATION_SYNC"
    FEDERATION_GOVERNANCE = "FEDERATION_GOVERNANCE"


class FederatedAuditEvent(BaseModel):
    """
    Immutable cryptographic CHITRA audit event representing a federated cross-node interaction.
    Maintains dual linkage:
    1. Local CHITRA audit chain: prev_event_hash -> this_event_hash
    2. Remote cryptographic linkage: remote_event_hash -> local audit entry
    """
    event_id: str
    task_id: int = 0
    session_id: Optional[str] = None
    timestamp: str
    faculty: str = "FEDERATION"  # Strictly identified as FEDERATION (§18.6)
    event_type: str
    input_hash: str
    decision: Dict[str, Any]
    evidence: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    outcome: Optional[Dict[str, Any]] = None
    constitutional_review: str = "passed"
    
    # Dual Cryptographic Linkage
    remote_event_hash: Optional[str] = None  # Linkage to remote node's message digest or audit hash
    prev_event_hash: str
    this_event_hash: str
    signature: str

    # Complete Provenance
    source_node_id: str
    target_node_id: str
    source_tenant_id: str
    local_tenant_id: str
    federation_message_id: str
    provenance: Dict[str, Any] = Field(default_factory=dict)


class FederatedChitraAuditService:
    """
    Service for creating, cryptographically chaining, and verifying federated CHITRA audit events.
    """

    @classmethod
    def create_incoming_audit_event(
        cls,
        incoming_message: FederationMessage,
        local_identity: NodeIdentity,
        local_tenant_id: str,
        prev_event_hash: str = GENESIS_HASH,
        task_id: int = 0,
        session_id: Optional[str] = None,
        remote_event_hash: Optional[str] = None,
        constitutional_verdict: str = "passed",
        secret_key: Optional[str] = None
    ) -> FederatedAuditEvent:
        """
        Creates, chains, and signs a local CHITRA audit record for an incoming federation event.
        """
        cls._validate_message_fields(incoming_message, local_tenant_id)

        # Compute remote message digest if not explicitly passed
        remote_hash = remote_event_hash or compute_sha256(canonical_json(incoming_message.model_dump()))
        event_id = generate_ulid(prefix="evt_fed_in_")
        now_ts = datetime.now(timezone.utc).isoformat()
        input_hash = compute_sha256(canonical_json(incoming_message.payload))

        decision_data = {
            "federation_message_id": incoming_message.message_id,
            "payload_type": incoming_message.payload_type.value,
            "source_node_id": incoming_message.source_node_id,
            "target_node_id": incoming_message.target_node_id,
            "source_tenant_id": incoming_message.tenant_id,
            "local_tenant_id": local_tenant_id,
            "remote_event_hash": remote_hash,
            "signature_verified": True
        }

        provenance_data = {
            "source_node_id": incoming_message.source_node_id,
            "source_tenant_id": incoming_message.tenant_id,
            "target_node_id": local_identity.node_id,
            "local_tenant_id": local_tenant_id,
            "federation_message_id": incoming_message.message_id,
            "remote_event_hash": remote_hash,
            "origin_timestamp": incoming_message.timestamp
        }

        raw_event = {
            "event_id": event_id,
            "task_id": task_id,
            "session_id": session_id or f"ses_fed_{incoming_message.message_id}",
            "timestamp": now_ts,
            "faculty": "FEDERATION",
            "event_type": FederationAuditEventType.FEDERATION_INCOMING.value,
            "input_hash": input_hash,
            "decision": decision_data,
            "evidence": [remote_hash],
            "confidence": 1.0,
            "outcome": {"status": "ACCEPTED", "message": "Incoming federation event ingested and audited."},
            "constitutional_review": constitutional_verdict,
            "remote_event_hash": remote_hash,
            "prev_event_hash": prev_event_hash or GENESIS_HASH,
            "source_node_id": incoming_message.source_node_id,
            "target_node_id": incoming_message.target_node_id,
            "source_tenant_id": incoming_message.tenant_id,
            "local_tenant_id": local_tenant_id,
            "federation_message_id": incoming_message.message_id,
            "provenance": provenance_data
        }

        content_hash = compute_content_hash(raw_event)
        this_event_hash = compute_chained_hash(raw_event["prev_event_hash"], content_hash)
        signature = sign_event(this_event_hash, secret_key=secret_key)

        return FederatedAuditEvent(
            **raw_event,
            this_event_hash=this_event_hash,
            signature=signature
        )

    @classmethod
    def create_outgoing_audit_event(
        cls,
        outgoing_message: FederationMessage,
        local_identity: NodeIdentity,
        local_tenant_id: str,
        prev_event_hash: str = GENESIS_HASH,
        task_id: int = 0,
        session_id: Optional[str] = None,
        secret_key: Optional[str] = None
    ) -> FederatedAuditEvent:
        """
        Creates, chains, and signs a local CHITRA audit record for an outgoing federation event.
        """
        cls._validate_message_fields(outgoing_message, local_tenant_id)

        local_msg_hash = compute_sha256(canonical_json(outgoing_message.model_dump()))
        event_id = generate_ulid(prefix="evt_fed_out_")
        now_ts = datetime.now(timezone.utc).isoformat()
        input_hash = compute_sha256(canonical_json(outgoing_message.payload))

        decision_data = {
            "federation_message_id": outgoing_message.message_id,
            "payload_type": outgoing_message.payload_type.value,
            "source_node_id": local_identity.node_id,
            "target_node_id": outgoing_message.target_node_id,
            "source_tenant_id": local_tenant_id,
            "target_tenant_id": outgoing_message.tenant_id,
            "outgoing_message_hash": local_msg_hash
        }

        provenance_data = {
            "source_node_id": local_identity.node_id,
            "source_tenant_id": local_tenant_id,
            "target_node_id": outgoing_message.target_node_id,
            "target_tenant_id": outgoing_message.tenant_id,
            "federation_message_id": outgoing_message.message_id,
            "outgoing_message_hash": local_msg_hash,
            "origin_timestamp": outgoing_message.timestamp
        }

        raw_event = {
            "event_id": event_id,
            "task_id": task_id,
            "session_id": session_id or f"ses_fed_{outgoing_message.message_id}",
            "timestamp": now_ts,
            "faculty": "FEDERATION",
            "event_type": FederationAuditEventType.FEDERATION_OUTGOING.value,
            "input_hash": input_hash,
            "decision": decision_data,
            "evidence": [local_msg_hash],
            "confidence": 1.0,
            "outcome": {"status": "DISPATCHED", "message": "Outgoing federation event dispatched."},
            "constitutional_review": "passed",
            "remote_event_hash": local_msg_hash,
            "prev_event_hash": prev_event_hash or GENESIS_HASH,
            "source_node_id": local_identity.node_id,
            "target_node_id": outgoing_message.target_node_id,
            "source_tenant_id": local_tenant_id,
            "local_tenant_id": local_tenant_id,
            "federation_message_id": outgoing_message.message_id,
            "provenance": provenance_data
        }

        content_hash = compute_content_hash(raw_event)
        this_event_hash = compute_chained_hash(raw_event["prev_event_hash"], content_hash)
        signature = sign_event(this_event_hash, secret_key=secret_key)

        return FederatedAuditEvent(
            **raw_event,
            this_event_hash=this_event_hash,
            signature=signature
        )

    @classmethod
    def create_rejection_audit_event(
        cls,
        incoming_message: FederationMessage,
        local_identity: NodeIdentity,
        local_tenant_id: str,
        rejection_reason: str,
        prev_event_hash: str = GENESIS_HASH,
        task_id: int = 0,
        session_id: Optional[str] = None,
        secret_key: Optional[str] = None
    ) -> FederatedAuditEvent:
        """
        Creates a local CHITRA audit event recording a rejected/unauthorized federation attempt.
        """
        event_id = generate_ulid(prefix="evt_fed_rej_")
        now_ts = datetime.now(timezone.utc).isoformat()
        input_hash = compute_sha256(canonical_json(incoming_message.payload if incoming_message else {}))
        msg_id = incoming_message.message_id if incoming_message else "UNKNOWN_MSG"
        src_node = incoming_message.source_node_id if incoming_message else "UNKNOWN_NODE"
        src_tenant = incoming_message.tenant_id if incoming_message else "UNKNOWN_TENANT"

        decision_data = {
            "rejection_reason": rejection_reason,
            "federation_message_id": msg_id,
            "source_node_id": src_node,
            "source_tenant_id": src_tenant,
            "local_tenant_id": local_tenant_id,
            "action_taken": "BLOCKED_BY_FEDERATION_GOVERNANCE"
        }

        provenance_data = {
            "source_node_id": src_node,
            "source_tenant_id": src_tenant,
            "target_node_id": local_identity.node_id,
            "local_tenant_id": local_tenant_id,
            "federation_message_id": msg_id,
            "rejection_reason": rejection_reason
        }

        raw_event = {
            "event_id": event_id,
            "task_id": task_id,
            "session_id": session_id or f"ses_fed_rej_{msg_id}",
            "timestamp": now_ts,
            "faculty": "FEDERATION",
            "event_type": FederationAuditEventType.FEDERATION_SECURITY_REJECTION.value,
            "input_hash": input_hash,
            "decision": decision_data,
            "evidence": [compute_sha256(rejection_reason)],
            "confidence": 1.0,
            "outcome": {"status": "REJECTED", "reason": rejection_reason},
            "constitutional_review": "blocked",
            "remote_event_hash": None,
            "prev_event_hash": prev_event_hash or GENESIS_HASH,
            "source_node_id": src_node,
            "target_node_id": local_identity.node_id,
            "source_tenant_id": src_tenant,
            "local_tenant_id": local_tenant_id,
            "federation_message_id": msg_id,
            "provenance": provenance_data
        }

        content_hash = compute_content_hash(raw_event)
        this_event_hash = compute_chained_hash(raw_event["prev_event_hash"], content_hash)
        signature = sign_event(this_event_hash, secret_key=secret_key)

        return FederatedAuditEvent(
            **raw_event,
            this_event_hash=this_event_hash,
            signature=signature
        )

    @classmethod
    def verify_audit_event(
        cls,
        event: FederatedAuditEvent,
        expected_prev_event_hash: Optional[str] = None,
        secret_key: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Cryptographically verifies a FederatedAuditEvent:
        1. Validates faculty == 'FEDERATION'.
        2. Recalculates canonical content hash.
        3. Recalculates chained event hash: SHA256(prev_event_hash + ':' + content_hash).
        4. Validates this_event_hash matches computed chained hash.
        5. Validates HMAC signature.
        6. Verifies prev_event_hash matches expected_prev_event_hash if provided.
        """
        # 1. Faculty check
        if event.faculty != "FEDERATION":
            return False, f"Invalid faculty '{event.faculty}': expected 'FEDERATION'."

        # 2. Previous hash linkage check
        if expected_prev_event_hash is not None and event.prev_event_hash != expected_prev_event_hash:
            return False, f"Chain broken: prev_event_hash '{event.prev_event_hash}' != expected '{expected_prev_event_hash}'."

        # 3. Content hash recalculation
        event_dict = event.model_dump()
        recomputed_content_hash = compute_content_hash(event_dict)

        # 4. Chained hash recalculation
        recomputed_event_hash = compute_chained_hash(event.prev_event_hash, recomputed_content_hash)
        if event.this_event_hash != recomputed_event_hash:
            return False, f"Hash mismatch: event claims '{event.this_event_hash}', computed '{recomputed_event_hash}'."

        # 5. Signature verification
        is_sig_valid = verify_event_signature(event.this_event_hash, event.signature, secret_key=secret_key)
        if not is_sig_valid:
            return False, "Cryptographic HMAC signature verification failed."

        return True, "Audit event verified clean."

    @classmethod
    def _validate_message_fields(cls, message: FederationMessage, local_tenant_id: str) -> None:
        if not message:
            raise ValueError("message is required for audit event creation (FAIL-CLOSED).")
        if not message.message_id or not message.message_id.strip():
            raise ValueError("federation_message_id cannot be null or empty (FAIL-CLOSED).")
        if not message.source_node_id or not message.source_node_id.strip():
            raise ValueError("source_node_id cannot be null or empty (FAIL-CLOSED).")
        if not message.tenant_id or not message.tenant_id.strip():
            raise ValueError("source tenant_id cannot be null or empty (FAIL-CLOSED).")
        if not local_tenant_id or not local_tenant_id.strip():
            raise ValueError("local_tenant_id cannot be null or empty (FAIL-CLOSED).")
