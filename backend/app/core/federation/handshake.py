"""
PEER HANDSHAKE SERVICE (Whitesheet §18.1, §18.2)
Cryptographic mutual peer handshake establishing identity, trust tier eligibility, and tenant isolation.
"""
from typing import Tuple, Optional, Dict, Any
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
from app.core.chitra.crypto import generate_ulid


class NodeHandshakeService:
    """
    Coordinates cryptographic handshakes between local and remote federation nodes.
    """

    @classmethod
    def initiate_handshake_request(
        cls,
        local_identity: NodeIdentity,
        local_signing_key: SigningKey,
        target_node_id: str,
        tenant_id: str,
        challenge_nonce: Optional[str] = None
    ) -> FederationMessage:
        """
        Constructs and cryptographically signs a HANDSHAKE request message.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Tenant ID is required for handshake initiation (AUTHENTICATED_TENANT_REQUIRED).")

        if not target_node_id or not target_node_id.strip():
            raise ValueError("Target node ID is required for handshake initiation (FAIL-CLOSED).")

        nonce = challenge_nonce or secrets.token_hex(16)
        payload = {
            "handshake_version": "1.0",
            "source_node_name": local_identity.name,
            "claimed_trust_tier": local_identity.trust_tier.value,
            "public_key": local_identity.public_key,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        unsigned_msg = FederationMessage(
            message_id=generate_ulid(prefix="msg_hs_"),
            source_node_id=local_identity.node_id,
            target_node_id=target_node_id,
            tenant_id=tenant_id,
            payload_type=FederationPayloadType.HANDSHAKE,
            payload=payload,
            nonce=nonce
        )

        # Cryptographically sign using local node's private key
        return NodeIdentityManager.sign_message(local_signing_key, unsigned_msg)

    @classmethod
    def verify_and_process_handshake(
        cls,
        local_identity: NodeIdentity,
        local_signing_key: SigningKey,
        trust_registry: NodeTrustRegistry,
        incoming_message: FederationMessage,
        expected_tenant_id: str
    ) -> Tuple[bool, str, Optional[FederationMessage]]:
        """
        Validates an incoming handshake request:
        1. Validates schema and payload type == HANDSHAKE.
        2. Enforces strict tenant isolation: incoming.tenant_id == expected_tenant_id.
        3. Enforces recipient address: target_node_id == local_identity.node_id or 'BROADCAST'.
        4. Looks up sender in NodeTrustRegistry.
        5. Asserts sender node status == ACTIVE (rejects REVOKED/SUSPENDED).
        6. Cryptographically verifies message signature against sender's registered public key.
        7. Produces signed response message on success.
        """
        # 1. Payload type check
        if incoming_message.payload_type != FederationPayloadType.HANDSHAKE:
            return False, f"Invalid payload type '{incoming_message.payload_type.value}'. Expected HANDSHAKE.", None

        # 2. Tenant isolation check (§18.5)
        if not incoming_message.tenant_id or incoming_message.tenant_id != expected_tenant_id:
            return False, f"Cross-tenant handshake rejected. Scope '{incoming_message.tenant_id}' != '{expected_tenant_id}'.", None

        # 3. Target node check
        if incoming_message.target_node_id not in [local_identity.node_id, "BROADCAST"]:
            return False, f"Message target '{incoming_message.target_node_id}' does not match local node '{local_identity.node_id}'.", None

        # 4. Registry lookup
        sender_node = trust_registry.get_node(incoming_message.source_node_id)
        if not sender_node:
            return False, f"Unknown sender node '{incoming_message.source_node_id}' not found in TrustRegistry.", None

        # 5. Node status check
        if sender_node.status != NodeStatus.ACTIVE:
            return False, f"Sender node '{incoming_message.source_node_id}' is in inactive state '{sender_node.status.value}'.", None

        # 6. Cryptographic signature verification
        is_sig_valid = NodeIdentityManager.verify_message_signature(
            public_key_hex=sender_node.public_key,
            message=incoming_message
        )
        if not is_sig_valid:
            return False, "Cryptographic signature verification failed for incoming handshake.", None

        # 7. Handshake successful: create signed response message
        response_payload = {
            "handshake_status": "ACCEPTED",
            "responding_node_id": local_identity.node_id,
            "responding_node_name": local_identity.name,
            "verified_sender_tier": sender_node.trust_tier.value,
            "session_token": secrets.token_hex(24),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        unsigned_resp = FederationMessage(
            message_id=generate_ulid(prefix="msg_hs_ack_"),
            source_node_id=local_identity.node_id,
            target_node_id=incoming_message.source_node_id,
            tenant_id=expected_tenant_id,
            payload_type=FederationPayloadType.HANDSHAKE,
            payload=response_payload,
            nonce=secrets.token_hex(16)
        )

        signed_resp = NodeIdentityManager.sign_message(local_signing_key, unsigned_resp)
        return True, "Handshake verified and accepted.", signed_resp
