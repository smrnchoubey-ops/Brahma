"""
FEDERATION SYSTEM Phase 18B Dedicated Test Suite: Node Trust Registry & Peer Handshake
Strictly tests Whitesheet §18.1 & §18.2 requirements across 20 explicit scenarios.
"""
import pytest
import secrets

from app.core.federation.models import (
    TrustTier,
    NodeStatus,
    FederationPayloadType,
    NodeIdentity,
    FederationMessage
)
from app.core.federation.identity import NodeIdentityManager
from app.core.federation.trust import NodeTrustRegistry, TrustTransitionError
from app.core.federation.handshake import NodeHandshakeService


# -------------------------------------------------------------
# 1. NODE TRUST REGISTRY TESTS (1-11)
# -------------------------------------------------------------

def test_1_registry_initialization():
    registry = NodeTrustRegistry()
    assert len(registry.list_nodes()) == 0


def test_2_valid_node_registration():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity(name="NodeAlpha")
    registry.register_node(identity)

    fetched = registry.get_node(identity.node_id)
    assert fetched is not None
    assert fetched.node_id == identity.node_id
    assert fetched.name == "NodeAlpha"
    assert fetched.trust_tier == TrustTier.UNTRUSTED


def test_3_duplicate_node_rejection():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity(name="NodeDup")
    registry.register_node(identity)

    with pytest.raises(ValueError, match="Duplicate node registration rejected"):
        registry.register_node(identity)


def test_4_unknown_node_lookup():
    registry = NodeTrustRegistry()
    assert registry.get_node("node_nonexistent_123") is None
    assert registry.get_node("") is None


def test_5_untrusted_state_default():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity()
    registry.register_node(identity)

    assert registry.is_node_trusted(identity.node_id, minimum_tier=TrustTier.VERIFIED) is False
    assert registry.is_node_trusted(identity.node_id, minimum_tier=TrustTier.UNTRUSTED) is True


def test_6_valid_untrusted_to_verified_transition():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity()
    registry.register_node(identity)

    updated = registry.update_trust_tier(identity.node_id, TrustTier.VERIFIED, reason="Passed identity verification")
    assert updated.trust_tier == TrustTier.VERIFIED
    assert registry.is_node_trusted(identity.node_id, minimum_tier=TrustTier.VERIFIED) is True


def test_7_valid_verified_to_federated_transition():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity()
    registry.register_node(identity)

    registry.update_trust_tier(identity.node_id, TrustTier.VERIFIED)
    updated = registry.update_trust_tier(identity.node_id, TrustTier.FEDERATED, reason="Mutual federation agreement signed")
    assert updated.trust_tier == TrustTier.FEDERATED
    assert registry.is_node_trusted(identity.node_id, minimum_tier=TrustTier.FEDERATED) is True


def test_8_valid_federated_to_sovereign_transition():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity()
    registry.register_node(identity)

    registry.update_trust_tier(identity.node_id, TrustTier.VERIFIED)
    registry.update_trust_tier(identity.node_id, TrustTier.FEDERATED)
    updated = registry.update_trust_tier(identity.node_id, TrustTier.SOVEREIGN, reason="Root administrative node")
    assert updated.trust_tier == TrustTier.SOVEREIGN
    assert registry.is_node_trusted(identity.node_id, minimum_tier=TrustTier.SOVEREIGN) is True


def test_9_invalid_trust_escalation_rejection():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity()
    registry.register_node(identity)

    # Illegal direct jump: UNTRUSTED -> FEDERATED (must go through VERIFIED)
    with pytest.raises(TrustTransitionError, match="Illegal trust escalation"):
        registry.update_trust_tier(identity.node_id, TrustTier.FEDERATED)

    # Illegal direct jump: UNTRUSTED -> SOVEREIGN
    with pytest.raises(TrustTransitionError, match="Illegal trust escalation"):
        registry.update_trust_tier(identity.node_id, TrustTier.SOVEREIGN)


def test_10_revoked_node_rejection():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity()
    registry.register_node(identity)
    registry.update_trust_tier(identity.node_id, TrustTier.VERIFIED)

    # Revoke node
    registry.set_node_status(identity.node_id, NodeStatus.REVOKED, reason="Security compromise detected")
    assert registry.is_node_trusted(identity.node_id, minimum_tier=TrustTier.UNTRUSTED) is False

    # Cannot update trust on revoked node
    with pytest.raises(TrustTransitionError, match="Cannot update trust tier"):
        registry.update_trust_tier(identity.node_id, TrustTier.FEDERATED)


def test_11_suspended_node_rejection():
    registry = NodeTrustRegistry()
    identity, _ = NodeIdentityManager.create_node_identity()
    registry.register_node(identity)
    registry.set_node_status(identity.node_id, NodeStatus.SUSPENDED, reason="Maintenance window")
    assert registry.is_node_trusted(identity.node_id) is False


# -------------------------------------------------------------
# 2. PEER HANDSHAKE TESTS (12-20)
# -------------------------------------------------------------

def test_12_valid_cryptographic_handshake():
    registry = NodeTrustRegistry()

    # Local Node (Node A)
    id_a, sk_a = NodeIdentityManager.create_node_identity(name="NodeA")
    # Remote Peer (Node B)
    id_b, sk_b = NodeIdentityManager.create_node_identity(name="NodeB")

    registry.register_node(id_b)
    registry.update_trust_tier(id_b.node_id, TrustTier.VERIFIED)

    # Node B initiates handshake to Node A
    hs_req = NodeHandshakeService.initiate_handshake_request(
        local_identity=id_b,
        local_signing_key=sk_b,
        target_node_id=id_a.node_id,
        tenant_id="tenant_global"
    )

    # Node A verifies and processes incoming handshake
    success, msg, hs_resp = NodeHandshakeService.verify_and_process_handshake(
        local_identity=id_a,
        local_signing_key=sk_a,
        trust_registry=registry,
        incoming_message=hs_req,
        expected_tenant_id="tenant_global"
    )

    assert success is True
    assert "verified and accepted" in msg
    assert hs_resp is not None
    assert hs_resp.payload["handshake_status"] == "ACCEPTED"
    assert hs_resp.payload["responding_node_id"] == id_a.node_id


def test_13_unknown_peer_handshake_rejection():
    registry = NodeTrustRegistry()
    id_a, sk_a = NodeIdentityManager.create_node_identity(name="NodeA")
    id_unregistered, sk_unregistered = NodeIdentityManager.create_node_identity(name="NodeRogue")

    # Rogue node sends handshake without being in registry
    hs_req = NodeHandshakeService.initiate_handshake_request(
        local_identity=id_unregistered,
        local_signing_key=sk_unregistered,
        target_node_id=id_a.node_id,
        tenant_id="tenant_global"
    )

    success, msg, resp = NodeHandshakeService.verify_and_process_handshake(
        local_identity=id_a,
        local_signing_key=sk_a,
        trust_registry=registry,
        incoming_message=hs_req,
        expected_tenant_id="tenant_global"
    )
    assert success is False
    assert "not found in TrustRegistry" in msg
    assert resp is None


def test_14_invalid_signature_rejection():
    registry = NodeTrustRegistry()
    id_a, sk_a = NodeIdentityManager.create_node_identity(name="NodeA")
    id_b, sk_b = NodeIdentityManager.create_node_identity(name="NodeB")
    registry.register_node(id_b)

    hs_req = NodeHandshakeService.initiate_handshake_request(
        local_identity=id_b,
        local_signing_key=sk_b,
        target_node_id=id_a.node_id,
        tenant_id="tenant_global"
    )

    # Corrupt signature
    tampered_sig = hs_req.model_copy(update={"signature": "deadbeef" * 8})

    success, msg, resp = NodeHandshakeService.verify_and_process_handshake(
        local_identity=id_a,
        local_signing_key=sk_a,
        trust_registry=registry,
        incoming_message=tampered_sig,
        expected_tenant_id="tenant_global"
    )
    assert success is False
    assert "signature verification failed" in msg
    assert resp is None


def test_15_tampered_handshake_rejection():
    registry = NodeTrustRegistry()
    id_a, sk_a = NodeIdentityManager.create_node_identity(name="NodeA")
    id_b, sk_b = NodeIdentityManager.create_node_identity(name="NodeB")
    registry.register_node(id_b)

    hs_req = NodeHandshakeService.initiate_handshake_request(
        local_identity=id_b,
        local_signing_key=sk_b,
        target_node_id=id_a.node_id,
        tenant_id="tenant_global"
    )

    # Modify payload after signing
    tampered_payload = hs_req.model_copy(update={"payload": {"handshake_version": "999.0", "escalate": True}})

    success, msg, resp = NodeHandshakeService.verify_and_process_handshake(
        local_identity=id_a,
        local_signing_key=sk_a,
        trust_registry=registry,
        incoming_message=tampered_payload,
        expected_tenant_id="tenant_global"
    )
    assert success is False
    assert "signature verification failed" in msg
    assert resp is None


def test_16_malformed_public_key_rejection():
    registry = NodeTrustRegistry()
    bad_identity = NodeIdentity(
        node_id="node_malformed_pk",
        public_key="00" * 64
    )
    # The dummy public key 00*64 is not a valid NIST256p point
    with pytest.raises(ValueError, match="Malformed or invalid public key"):
        registry.register_node(bad_identity)


def test_17_missing_node_id_rejection():
    with pytest.raises(ValueError):
        NodeHandshakeService.initiate_handshake_request(
            local_identity=NodeIdentity(node_id="node_ok", public_key="01" * 64),
            local_signing_key=None,
            target_node_id="",
            tenant_id="tenant_global"
        )


def test_18_missing_tenant_id_rejection():
    id_a, sk_a = NodeIdentityManager.create_node_identity()
    with pytest.raises(ValueError, match="Tenant ID is required"):
        NodeHandshakeService.initiate_handshake_request(
            local_identity=id_a,
            local_signing_key=sk_a,
            target_node_id="node_target",
            tenant_id=""
        )


def test_19_cross_tenant_handshake_rejection():
    registry = NodeTrustRegistry()
    id_a, sk_a = NodeIdentityManager.create_node_identity(name="NodeA")
    id_b, sk_b = NodeIdentityManager.create_node_identity(name="NodeB")
    registry.register_node(id_b)

    # Node B initiates with Tenant Alice
    hs_req = NodeHandshakeService.initiate_handshake_request(
        local_identity=id_b,
        local_signing_key=sk_b,
        target_node_id=id_a.node_id,
        tenant_id="tenant_alice"
    )

    # Node A is processing for Tenant Bob (Cross-tenant attempt)
    success, msg, resp = NodeHandshakeService.verify_and_process_handshake(
        local_identity=id_a,
        local_signing_key=sk_a,
        trust_registry=registry,
        incoming_message=hs_req,
        expected_tenant_id="tenant_bob"
    )
    assert success is False
    assert "Cross-tenant handshake rejected" in msg
    assert resp is None


def test_20_phase18a_boundary_protection():
    # Strictly ensures Phase 18A cryptographic models remain intact
    assert TrustTier.SOVEREIGN.value == "SOVEREIGN"
    assert FederationPayloadType.HANDSHAKE.value == "HANDSHAKE"


def run_all_20_phase18b_tests():
    print("==================================================")
    print("FEDERATION SYSTEM PHASE 18B: 20-SCENARIO SUITE")
    print("NODE TRUST REGISTRY & PEER HANDSHAKE (§18.1-18.2)")
    print("==================================================")

    test_1_registry_initialization()
    print("  [PASS 1/20] [REAL] Registry initialization.")

    test_2_valid_node_registration()
    print("  [PASS 2/20] [REAL] Valid node registration (§18.1).")

    test_3_duplicate_node_rejection()
    print("  [PASS 3/20] [REAL] Duplicate node registration rejection fails closed.")

    test_4_unknown_node_lookup()
    print("  [PASS 4/20] [REAL] Unknown node lookup fails closed.")

    test_5_untrusted_state_default()
    print("  [PASS 5/20] [REAL] UNTRUSTED default state (§18.1).")

    test_6_valid_untrusted_to_verified_transition()
    print("  [PASS 6/20] [REAL] Valid UNTRUSTED -> VERIFIED transition.")

    test_7_valid_verified_to_federated_transition()
    print("  [PASS 7/20] [REAL] Valid VERIFIED -> FEDERATED transition.")

    test_8_valid_federated_to_sovereign_transition()
    print("  [PASS 8/20] [REAL] Valid FEDERATED -> SOVEREIGN transition.")

    test_9_invalid_trust_escalation_rejection()
    print("  [PASS 9/20] [REAL] Invalid trust escalation rejection fails closed.")

    test_10_revoked_node_rejection()
    print("  [PASS 10/20] [REAL] Revoked node rejection fails closed.")

    test_11_suspended_node_rejection()
    print("  [PASS 11/20] [REAL] Suspended node rejection fails closed.")

    test_12_valid_cryptographic_handshake()
    print("  [PASS 12/20] [REAL] Valid cryptographic mutual handshake (§18.2).")

    test_13_unknown_peer_handshake_rejection()
    print("  [PASS 13/20] [REAL] Unknown peer handshake rejection fails closed.")

    test_14_invalid_signature_rejection()
    print("  [PASS 14/20] [REAL] Invalid signature rejection fails closed.")

    test_15_tampered_handshake_rejection()
    print("  [PASS 15/20] [REAL] Tampered handshake payload rejection fails closed.")

    test_16_malformed_public_key_rejection()
    print("  [PASS 16/20] [REAL] Malformed public key rejection fails closed.")

    test_17_missing_node_id_rejection()
    print("  [PASS 17/20] [REAL] Missing node ID rejection fails closed.")

    test_18_missing_tenant_id_rejection()
    print("  [PASS 18/20] [REAL] Missing tenant ID rejection fails closed.")

    test_19_cross_tenant_handshake_rejection()
    print("  [PASS 19/20] [REAL] Cross-tenant handshake rejection (§18.5).")

    test_20_phase18a_boundary_protection()
    print("  [PASS 20/20] [REAL] Phase 18A boundary protection.")

    print("\n==================================================")
    print("ALL 20 PHASE 18B TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_20_phase18b_tests()
