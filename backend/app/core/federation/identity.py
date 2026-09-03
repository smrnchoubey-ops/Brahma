"""
CRYPTOGRAPHIC NODE IDENTITY & CANONICAL SERIALIZATION (Whitesheet §18.1, §18.2)
Implements ECDSA keypair management, canonical message serialization, signing, and verification.
"""
from typing import Tuple, Optional, Dict, Any
import json
import hashlib
import secrets
from datetime import datetime, timezone

import ecdsa.util
from ecdsa import SigningKey, VerifyingKey, NIST256p, BadSignatureError

from app.core.federation.models import NodeIdentity, FederationMessage, TrustTier, NodeStatus
from app.core.chitra.crypto import generate_ulid


def canonical_message_bytes(message: FederationMessage) -> bytes:
    """
    Serializes a FederationMessage into deterministic canonical UTF-8 bytes for signing/verification.
    Strictly excludes the `signature` field to ensure reproducible digest generation.
    """
    signing_dict = {
        "message_id": message.message_id,
        "source_node_id": message.source_node_id,
        "target_node_id": message.target_node_id,
        "tenant_id": message.tenant_id,
        "payload_type": message.payload_type.value,
        "payload": message.payload,
        "timestamp": message.timestamp,
        "nonce": message.nonce
    }
    canonical_json_str = json.dumps(
        signing_dict,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False
    )
    return canonical_json_str.encode('utf-8')


class NodeIdentityManager:
    """
    Cryptographic manager for generating node identities, signing messages, and verifying peer signatures.
    """

    @classmethod
    def generate_keypair(cls) -> Tuple[SigningKey, str]:
        """
        Generates an ECDSA (NIST256p) keypair.
        Returns:
            (SigningKey object, hex-encoded public key string)
        """
        signing_key = SigningKey.generate(curve=NIST256p, hashfunc=hashlib.sha256)
        verifying_key = signing_key.verifying_key
        public_key_hex = verifying_key.to_string().hex()
        return signing_key, public_key_hex

    @classmethod
    def create_node_identity(
        cls,
        name: Optional[str] = None,
        trust_tier: TrustTier = TrustTier.UNTRUSTED,
        endpoint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[NodeIdentity, SigningKey]:
        """
        Generates a unique node_id, creates an ECDSA keypair, and constructs a public NodeIdentity.
        Returns:
            (NodeIdentity [public only], SigningKey [private key])
        """
        signing_key, public_key_hex = cls.generate_keypair()
        node_id = generate_ulid(prefix="node_")

        identity = NodeIdentity(
            node_id=node_id,
            public_key=public_key_hex,
            trust_tier=trust_tier,
            status=NodeStatus.ACTIVE,
            name=name or f"BrahmaNode_{node_id[:8]}",
            endpoint=endpoint,
            metadata=metadata or {}
        )
        return identity, signing_key

    @classmethod
    def sign_message(
        cls,
        signing_key: SigningKey,
        message: FederationMessage
    ) -> FederationMessage:
        """
        Signs the canonical bytes of a FederationMessage using the node's private SigningKey.
        Returns a new FederationMessage instance with the `signature` field populated with hex signature.
        """
        canonical_bytes = canonical_message_bytes(message)
        signature_bytes = signing_key.sign_deterministic(
            canonical_bytes,
            hashfunc=hashlib.sha256,
            sigencode=ecdsa.util.sigencode_der if hasattr(ecdsa.util, 'sigencode_der') else None
        )
        signature_hex = signature_bytes.hex()
        
        # Return updated message with signature attached
        return message.model_copy(update={"signature": signature_hex})

    @classmethod
    def verify_message_signature(
        cls,
        public_key_hex: str,
        message: FederationMessage
    ) -> bool:
        """
        Verifies the signature on a FederationMessage against the sender's public key.
        Fails closed (returns False) on missing signature, malformed public key, or signature mismatch.
        """
        if not message.signature or not message.signature.strip():
            return False

        if not public_key_hex or not public_key_hex.strip():
            return False

        try:
            vk_bytes = bytes.fromhex(public_key_hex.strip())
            verifying_key = VerifyingKey.from_string(vk_bytes, curve=NIST256p, hashfunc=hashlib.sha256)
            signature_bytes = bytes.fromhex(message.signature.strip())
            canonical_bytes = canonical_message_bytes(message)

            is_valid = verifying_key.verify(
                signature_bytes,
                canonical_bytes,
                sigdecode=ecdsa.util.sigdecode_der if hasattr(ecdsa.util, 'sigdecode_der') else None
            )
            return bool(is_valid)
        except (BadSignatureError, ValueError, Exception):
            return False

    @classmethod
    def verify_node_identity(cls, identity: NodeIdentity) -> bool:
        """
        Validates the structure and cryptographic validity of a NodeIdentity.
        """
        if not identity.node_id or not identity.public_key:
            return False
        try:
            vk_bytes = bytes.fromhex(identity.public_key.strip())
            VerifyingKey.from_string(vk_bytes, curve=NIST256p, hashfunc=hashlib.sha256)
            return True
        except Exception:
            return False
