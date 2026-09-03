"""
FEDERATION DATA MODELS (Whitesheet §18.0 - §18.6)
Strictly defines node trust tiers, cryptographic node identity, and canonical federation message envelopes.
"""
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator


class TrustTier(str, Enum):
    """
    Cryptographic trust tiers for nodes in the federation mesh (§18.1).
    """
    UNTRUSTED = "UNTRUSTED"
    VERIFIED = "VERIFIED"
    FEDERATED = "FEDERATED"
    SOVEREIGN = "SOVEREIGN"


class NodeStatus(str, Enum):
    """
    Operational status of a federation node.
    """
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    REVOKED = "REVOKED"
    SUSPENDED = "SUSPENDED"


class FederationPayloadType(str, Enum):
    """
    Supported cross-node federation payload types (§18.2).
    """
    PATTERN_SYNC = "PATTERN_SYNC"
    KNOWLEDGE_SYNC = "KNOWLEDGE_SYNC"
    TASK_DISPATCH = "TASK_DISPATCH"
    HEARTBEAT = "HEARTBEAT"
    HANDSHAKE = "HANDSHAKE"
    REVOCATION = "REVOCATION"


class NodeIdentity(BaseModel):
    """
    Public cryptographic identity of a federation node (§18.1).
    Private keys are NEVER included in this model.
    """
    node_id: str = Field(..., min_length=4, description="Unique, immutable identifier of the node.")
    public_key: str = Field(..., min_length=32, description="Hex-encoded ECDSA public key.")
    trust_tier: TrustTier = Field(default=TrustTier.UNTRUSTED)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: NodeStatus = Field(default=NodeStatus.ACTIVE)
    name: Optional[str] = None
    endpoint: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("node_id cannot be null or empty (FAIL-CLOSED).")
        return v.strip()

    @field_validator("public_key")
    @classmethod
    def validate_public_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("public_key cannot be null or empty (FAIL-CLOSED).")
        return v.strip()


class FederationMessage(BaseModel):
    """
    Canonical wire envelope for inter-node communication (§18.2).
    """
    message_id: str = Field(..., min_length=4, description="Unique ULID/UUID of the message.")
    source_node_id: str = Field(..., min_length=4, description="Node ID of the sender.")
    target_node_id: str = Field(..., min_length=4, description="Node ID of the intended recipient or 'BROADCAST'.")
    tenant_id: str = Field(..., min_length=1, description="Authenticated tenant scope (§18.5).")
    payload_type: FederationPayloadType = Field(..., description="Type of federated operation.")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Structured payload data.")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    nonce: str = Field(..., min_length=8, description="Cryptographic nonce for replay protection.")
    signature: Optional[str] = Field(default=None, description="Hex-encoded ECDSA signature over canonical payload.")

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("tenant_id is required for all federation messages (AUTHENTICATED_TENANT_REQUIRED).")
        return v.strip()

    @field_validator("source_node_id", "target_node_id", "message_id", "nonce")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be null or empty (FAIL-CLOSED).")
        return v.strip()
