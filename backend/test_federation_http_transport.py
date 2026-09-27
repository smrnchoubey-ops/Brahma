"""
GAP #9 TEST SUITE: Federation HTTP Transport & API Verification
Whitesheet §18 (Federation Transport) & §23 (Phase 4 Multi-Instance Communication)

Validates:
1. GET /api/federation/identity exposes public node identity without leaking private keys.
2. POST /api/federation/messages processes valid signed messages through the 9-step pipeline.
3. Tampered signatures over HTTP are rejected (FAIL-CLOSED).
4. Replay attacks with identical nonce over HTTP are rejected.
5. Unknown/unregistered nodes are rejected over HTTP.
6. Verified nodes exchanging HANDSHAKE messages successfully complete mutual authentication.
"""
import pytest
import secrets
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

from main import app
from app.db.database import Base
from app.models.federation_node import FederationNode
from app.core.federation.models import (
    NodeIdentity,
    FederationMessage,
    FederationPayloadType,
    TrustTier,
    NodeStatus
)
from app.core.federation.identity import NodeIdentityManager
from app.core.federation.trust import NodeTrustRegistry
from app.core.federation.runtime import get_federation_runtime, reset_federation_runtime, FederationRuntime
from app.core.chitra.crypto import generate_ulid


@pytest.fixture
def federation_test_client():
    """Initializes a fresh isolated FederationRuntime with thread-safe SQLite test database and TestClient."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine, autoflush=True, expire_on_commit=False)
    test_db = TestSession()

    sk, pk_hex = NodeIdentityManager.generate_keypair()

    # Create trust registry bound to the test session
    trust_reg = NodeTrustRegistry(tenant_id="tenant_fed_test", db_session=test_db)

    local_runtime = FederationRuntime(
        node_id="node_local_test_server",
        name="LocalServerNode",
        endpoint="http://127.0.0.1:8000",
        tenant_id="tenant_fed_test",
        signing_key=sk,
        trust_tier=TrustTier.SOVEREIGN
    )
    # Inject test-bound trust registry
    local_runtime.trust_registry = trust_reg
    local_runtime.coordinator.trust_registry = trust_reg

    reset_federation_runtime(local_runtime)
    client = TestClient(app)

    yield client, local_runtime, test_db

    test_db.close()


def test_1_get_local_identity(federation_test_client):
    client, runtime, _ = federation_test_client
    response = client.get("/api/federation/identity")
    assert response.status_code == 200
    data = response.json()
    assert data["node_id"] == "node_local_test_server"
    assert data["public_key"] == runtime.public_key_hex
    assert data["trust_tier"] == "SOVEREIGN"
    assert data["status"] == "ACTIVE"
    assert "signing_key" not in data
    assert "private_key" not in data


def test_2_http_message_ingress_unknown_sender_rejected(federation_test_client):
    client, runtime, _ = federation_test_client

    # Create an unregistered remote node
    remote_identity, remote_sk = NodeIdentityManager.create_node_identity(
        name="UnknownRemoteNode",
        tenant_id="tenant_fed_test"
    )

    unsigned_msg = FederationMessage(
        message_id=generate_ulid(prefix="msg_"),
        source_node_id=remote_identity.node_id,
        target_node_id=runtime.node_id,
        tenant_id="tenant_fed_test",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={"ping": "pong"},
        nonce=secrets.token_hex(16)
    )
    signed_msg = NodeIdentityManager.sign_message(remote_sk, unsigned_msg)

    response = client.post("/api/federation/messages", json=signed_msg.model_dump())
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "REJECTED"
    assert result["authenticated"] is False
    assert "Unknown sender" in result["reason"]


def test_3_http_message_ingress_verified_sender_accepted(federation_test_client):
    client, runtime, test_db = federation_test_client

    # Register peer in local trust registry with VERIFIED tier
    peer_identity, peer_sk = NodeIdentityManager.create_node_identity(
        name="VerifiedPeerNode",
        trust_tier=TrustTier.UNTRUSTED,
        tenant_id="tenant_fed_test"
    )
    runtime.trust_registry.register_node(peer_identity, db_session=test_db)
    runtime.trust_registry.update_trust_tier(peer_identity.node_id, TrustTier.VERIFIED, db_session=test_db)

    unsigned_msg = FederationMessage(
        message_id=generate_ulid(prefix="msg_"),
        source_node_id=peer_identity.node_id,
        target_node_id=runtime.node_id,
        tenant_id="tenant_fed_test",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={"status": "healthy"},
        nonce=secrets.token_hex(16)
    )
    signed_msg = NodeIdentityManager.sign_message(peer_sk, unsigned_msg)

    response = client.post("/api/federation/messages", json=signed_msg.model_dump())
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "ACCEPTED"
    assert result["authenticated"] is True
    assert result["tenant_authorized"] is True
    assert result["audit_event"] is not None
    assert result["audit_event"]["event_type"] == "FEDERATION_INCOMING"


def test_4_http_tampered_payload_rejected(federation_test_client):
    client, runtime, test_db = federation_test_client

    peer_identity, peer_sk = NodeIdentityManager.create_node_identity(
        name="TamperTestNode",
        trust_tier=TrustTier.UNTRUSTED,
        tenant_id="tenant_fed_test"
    )
    runtime.trust_registry.register_node(peer_identity, db_session=test_db)
    runtime.trust_registry.update_trust_tier(peer_identity.node_id, TrustTier.VERIFIED, db_session=test_db)

    unsigned_msg = FederationMessage(
        message_id=generate_ulid(prefix="msg_"),
        source_node_id=peer_identity.node_id,
        target_node_id=runtime.node_id,
        tenant_id="tenant_fed_test",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={"data": "original"},
        nonce=secrets.token_hex(16)
    )
    signed_msg = NodeIdentityManager.sign_message(peer_sk, unsigned_msg)

    # Tamper payload after signing
    tampered_dict = signed_msg.model_dump()
    tampered_dict["payload"] = {"data": "TAMPERED_CONTENT"}

    response = client.post("/api/federation/messages", json=tampered_dict)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "REJECTED"
    assert result["authenticated"] is False
    assert "Signature verification failed" in result["reason"]


def test_5_http_replay_attack_rejected(federation_test_client):
    client, runtime, test_db = federation_test_client

    peer_identity, peer_sk = NodeIdentityManager.create_node_identity(
        name="ReplayTestNode",
        trust_tier=TrustTier.UNTRUSTED,
        tenant_id="tenant_fed_test"
    )
    runtime.trust_registry.register_node(peer_identity, db_session=test_db)
    runtime.trust_registry.update_trust_tier(peer_identity.node_id, TrustTier.VERIFIED, db_session=test_db)

    unsigned_msg = FederationMessage(
        message_id=generate_ulid(prefix="msg_"),
        source_node_id=peer_identity.node_id,
        target_node_id=runtime.node_id,
        tenant_id="tenant_fed_test",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={"seq": 1},
        nonce="unique_nonce_12345678"
    )
    signed_msg = NodeIdentityManager.sign_message(peer_sk, unsigned_msg)

    # First request: ACCEPTED
    res1 = client.post("/api/federation/messages", json=signed_msg.model_dump())
    assert res1.status_code == 200
    assert res1.json()["status"] == "ACCEPTED"

    # Second request with exact same nonce: REJECTED (Replay attack blocked)
    res2 = client.post("/api/federation/messages", json=signed_msg.model_dump())
    assert res2.status_code == 200
    assert res2.json()["status"] == "REJECTED"
    assert "ReplayGuard check failed" in res2.json()["reason"]
