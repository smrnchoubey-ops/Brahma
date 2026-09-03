"""
FEDERATION SYSTEM Phase 18A Test Suite: Data Models & Cryptographic Node Identity
Strictly validates Whitesheet §18.0 - §18.6 Phase 18A specifications.
"""
import pytest
import json

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
from app.core.learning.models import PatternStatus  # Phase 17 boundary check


# -------------------------------------------------------------
# 1. TRUST TIERS & DATA MODELS (1-4)
# -------------------------------------------------------------

def test_1_trust_tier_values():
    assert TrustTier.UNTRUSTED.value == "UNTRUSTED"
    assert TrustTier.VERIFIED.value == "VERIFIED"
    assert TrustTier.FEDERATED.value == "FEDERATED"
    assert TrustTier.SOVEREIGN.value == "SOVEREIGN"


def test_2_node_identity_generation():
    identity, sk = NodeIdentityManager.create_node_identity(
        name="AlphaNode",
        trust_tier=TrustTier.VERIFIED
    )
    assert identity.node_id.startswith("node_")
    assert len(identity.public_key) == 128  # 64 bytes in hex
    assert identity.trust_tier == TrustTier.VERIFIED
    assert identity.status == NodeStatus.ACTIVE
    assert identity.name == "AlphaNode"


def test_3_unique_node_ids():
    id1, _ = NodeIdentityManager.create_node_identity()
    id2, _ = NodeIdentityManager.create_node_identity()
    assert id1.node_id != id2.node_id
    assert id1.public_key != id2.public_key


def test_4_keypair_generation():
    sk, pk_hex = NodeIdentityManager.generate_keypair()
    assert len(pk_hex) == 128
    assert bytes.fromhex(pk_hex) is not None


# -------------------------------------------------------------
# 2. CANONICAL SERIALIZATION & SIGNING (5-9)
# -------------------------------------------------------------

def test_5_message_signing():
    identity, sk = NodeIdentityManager.create_node_identity()
    msg = FederationMessage(
        message_id="msg_101",
        source_node_id=identity.node_id,
        target_node_id="node_target_1",
        tenant_id="tenant_alice",
        payload_type=FederationPayloadType.PATTERN_SYNC,
        payload={"pattern_id": "pat_001", "version": 1},
        timestamp="2026-09-03T12:00:00Z",
        nonce="nonce_secure_12345"
    )
    signed_msg = NodeIdentityManager.sign_message(sk, msg)
    assert signed_msg.signature is not None
    assert len(signed_msg.signature) > 0


def test_6_valid_signature_verification():
    identity, sk = NodeIdentityManager.create_node_identity()
    msg = FederationMessage(
        message_id="msg_102",
        source_node_id=identity.node_id,
        target_node_id="node_target_2",
        tenant_id="tenant_alice",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={"status": "OK"},
        timestamp="2026-09-03T12:05:00Z",
        nonce="nonce_secure_67890"
    )
    signed_msg = NodeIdentityManager.sign_message(sk, msg)
    is_valid = NodeIdentityManager.verify_message_signature(identity.public_key, signed_msg)
    assert is_valid is True


def test_7_tampered_payload_rejection():
    identity, sk = NodeIdentityManager.create_node_identity()
    msg = FederationMessage(
        message_id="msg_103",
        source_node_id=identity.node_id,
        target_node_id="node_target_3",
        tenant_id="tenant_alice",
        payload_type=FederationPayloadType.TASK_DISPATCH,
        payload={"action": "calculate 10+20"},
        timestamp="2026-09-03T12:10:00Z",
        nonce="nonce_secure_11223"
    )
    signed_msg = NodeIdentityManager.sign_message(sk, msg)

    # Tamper payload
    tampered_msg = signed_msg.model_copy(update={"payload": {"action": "rm -rf /critical"}})
    is_valid = NodeIdentityManager.verify_message_signature(identity.public_key, tampered_msg)
    assert is_valid is False


def test_8_invalid_signature_rejection():
    identity, sk = NodeIdentityManager.create_node_identity()
    msg = FederationMessage(
        message_id="msg_104",
        source_node_id=identity.node_id,
        target_node_id="node_target_4",
        tenant_id="tenant_alice",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={"status": "OK"},
        timestamp="2026-09-03T12:15:00Z",
        nonce="nonce_secure_44556",
        signature="deadbeef0102030405060708"
    )
    is_valid = NodeIdentityManager.verify_message_signature(identity.public_key, msg)
    assert is_valid is False


def test_9_canonical_serialization_determinism():
    msg1 = FederationMessage(
        message_id="msg_105",
        source_node_id="node_1",
        target_node_id="node_2",
        tenant_id="tenant_alice",
        payload_type=FederationPayloadType.PATTERN_SYNC,
        payload={"z_key": 10, "a_key": 20, "m_key": {"sub_z": 1, "sub_a": 2}},
        timestamp="2026-09-03T12:20:00Z",
        nonce="nonce_det_123"
    )
    msg2 = FederationMessage(
        message_id="msg_105",
        source_node_id="node_1",
        target_node_id="node_2",
        tenant_id="tenant_alice",
        payload_type=FederationPayloadType.PATTERN_SYNC,
        payload={"a_key": 20, "m_key": {"sub_a": 2, "sub_z": 1}, "z_key": 10},
        timestamp="2026-09-03T12:20:00Z",
        nonce="nonce_det_123"
    )
    bytes1 = canonical_message_bytes(msg1)
    bytes2 = canonical_message_bytes(msg2)
    assert bytes1 == bytes2


# -------------------------------------------------------------
# 3. FAIL-CLOSED SECURITY & BOUNDARIES (10-15)
# -------------------------------------------------------------

def test_10_missing_tenant_id_rejection():
    with pytest.raises(ValueError):
        FederationMessage(
            message_id="msg_bad_tenant",
            source_node_id="node_1",
            target_node_id="node_2",
            tenant_id="",
            payload_type=FederationPayloadType.HEARTBEAT,
            nonce="nonce_123"
        )


def test_11_missing_node_id_rejection():
    with pytest.raises(ValueError):
        NodeIdentity(
            node_id="",
            public_key="00" * 64
        )


def test_12_malformed_identity_rejection():
    bad_identity = NodeIdentity(
        node_id="node_bad",
        public_key="not_a_valid_hex_public_key_with_sufficient_length"
    )
    assert NodeIdentityManager.verify_node_identity(bad_identity) is False


def test_13_private_key_not_exposed_in_public_identity():
    identity, sk = NodeIdentityManager.create_node_identity()
    serialized = identity.model_dump()
    assert "private_key" not in serialized
    assert "signing_key" not in serialized
    assert not hasattr(identity, "signing_key")


def test_14_federation_message_schema_validation():
    msg = FederationMessage(
        message_id="msg_schema_ok",
        source_node_id="node_src",
        target_node_id="node_tgt",
        tenant_id="tenant_alice",
        payload_type=FederationPayloadType.HANDSHAKE,
        payload={"node_name": "TestNode"},
        timestamp="2026-09-03T12:30:00Z",
        nonce="nonce_rand_998877"
    )
    assert msg.source_node_id == "node_src"
    assert msg.payload_type == FederationPayloadType.HANDSHAKE
    assert msg.payload["node_name"] == "TestNode"


def test_15_phase17_boundary_protection():
    # Strictly ensures Phase 17 Learning models remain intact and unmodified
    assert PatternStatus.PROMOTED.value == "PROMOTED"
    assert PatternStatus.ROLLED_BACK.value == "ROLLED_BACK"


def run_all_15_phase18a_tests():
    print("==================================================")
    print("FEDERATION SYSTEM PHASE 18A: 15-SCENARIO SUITE")
    print("DATA MODELS & CRYPTOGRAPHIC NODE IDENTITY (§18.0-18.6)")
    print("==================================================")

    test_1_trust_tier_values()
    print("  [PASS 1/15] [REAL] TrustTier values (§18.1).")

    test_2_node_identity_generation()
    print("  [PASS 2/15] [REAL] Node identity generation with ECDSA NIST256p (§18.1).")

    test_3_unique_node_ids()
    print("  [PASS 3/15] [REAL] Collision-free unique node IDs.")

    test_4_keypair_generation()
    print("  [PASS 4/15] [REAL] Keypair generation & public key hex encoding.")

    test_5_message_signing()
    print("  [PASS 5/15] [REAL] Canonical message signing (§18.2).")

    test_6_valid_signature_verification()
    print("  [PASS 6/15] [REAL] Valid signature verification (§18.2).")

    test_7_tampered_payload_rejection()
    print("  [PASS 7/15] [REAL] Tampered payload rejection fails closed.")

    test_8_invalid_signature_rejection()
    print("  [PASS 8/15] [REAL] Invalid signature rejection fails closed.")

    test_9_canonical_serialization_determinism()
    print("  [PASS 9/15] [REAL] Canonical serialization determinism.")

    test_10_missing_tenant_id_rejection()
    print("  [PASS 10/15] [REAL] Missing tenant ID rejection fails closed.")

    test_11_missing_node_id_rejection()
    print("  [PASS 11/15] [REAL] Missing node ID rejection fails closed.")

    test_12_malformed_identity_rejection()
    print("  [PASS 12/15] [REAL] Malformed public key identity rejection.")

    test_13_private_key_not_exposed_in_public_identity()
    print("  [PASS 13/15] [REAL] Private key containment in NodeIdentity.")

    test_14_federation_message_schema_validation()
    print("  [PASS 14/15] [REAL] FederationMessage schema validation.")

    test_15_phase17_boundary_protection()
    print("  [PASS 15/15] [REAL] Phase 17 boundary protection.")

    print("\n==================================================")
    print("ALL 15 PHASE 18A TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_15_phase18a_tests()
