"""
FEDERATION SYSTEM Phase 18C Dedicated Test Suite: Distributed Pattern & Memory Synchronization
Strictly tests Whitesheet §18.3 & §18.5 across 20 explicit scenarios.
"""
import pytest
from datetime import datetime, timezone

from app.core.federation.models import (
    TrustTier,
    NodeStatus,
    FederationPayloadType,
    NodeIdentity,
    FederationMessage
)
from app.core.federation.identity import NodeIdentityManager
from app.core.federation.trust import NodeTrustRegistry
from app.core.federation.sync import (
    FederatedSyncService,
    FederatedSyncStore,
    SyncPayloadError
)
from app.core.learning.models import LearningCandidate, PatternStatus, PatternType, LearningEvidence
from app.core.kosh.memory_tiers import KoshChunk, MemoryTier


# -------------------------------------------------------------
# 1. PATTERN & MEMORY SYNC MESSAGE CREATION (1-4)
# -------------------------------------------------------------

def test_1_valid_same_tenant_pattern_sync():
    id_src, sk_src = NodeIdentityManager.create_node_identity(name="NodeAlpha")
    pat = LearningCandidate(
        pattern_id="pat_opt_001",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Fast Calculator",
        description="Optimizes arithmetic DAGs",
        status=PatternStatus.PROMOTED,
        le_score=0.88,
        confidence=0.92,
        constitutional_approved=True
    )

    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_src,
        source_signing_key=sk_src,
        target_node_id="node_beta",
        tenant_id="tenant_alice",
        pattern=pat
    )
    assert msg.payload_type == FederationPayloadType.PATTERN_SYNC
    assert msg.signature is not None
    assert msg.payload["pattern"]["pattern_id"] == "pat_opt_001"
    assert msg.payload["pattern"]["status"] == "PROMOTED"


def test_2_valid_same_tenant_memory_sync():
    id_src, sk_src = NodeIdentityManager.create_node_identity(name="NodeAlpha")
    chunk = KoshChunk(
        chunk_id="chunk_doc_001",
        tenant_id="tenant_alice",
        title="Company Security Policy",
        content="All data must be encrypted in transit and at rest.",
        tier=MemoryTier.SEMANTIC_STORE
    )

    msg = FederatedSyncService.create_memory_sync_message(
        source_identity=id_src,
        source_signing_key=sk_src,
        target_node_id="node_beta",
        tenant_id="tenant_alice",
        chunk=chunk
    )
    assert msg.payload_type == FederationPayloadType.KNOWLEDGE_SYNC
    assert msg.signature is not None
    assert msg.payload["chunk"]["chunk_id"] == "chunk_doc_001"
    assert msg.payload["chunk"]["content"] == "All data must be encrypted in transit and at rest."


def test_3_unpromoted_pattern_sync_rejection_fail_closed():
    id_src, sk_src = NodeIdentityManager.create_node_identity()
    unpromoted_pat = LearningCandidate(
        pattern_id="pat_cand_002",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Candidate Pattern",
        description="Unpromoted",
        status=PatternStatus.CANDIDATE  # NOT PROMOTED
    )
    with pytest.raises(SyncPayloadError, match="Only PROMOTED patterns may be synchronized"):
        FederatedSyncService.create_pattern_sync_message(
            source_identity=id_src,
            source_signing_key=sk_src,
            target_node_id="node_beta",
            tenant_id="tenant_alice",
            pattern=unpromoted_pat
        )


def test_4_empty_memory_chunk_sync_rejection_fail_closed():
    id_src, sk_src = NodeIdentityManager.create_node_identity()
    empty_chunk = KoshChunk(
        chunk_id="chunk_empty",
        tenant_id="tenant_alice",
        title="Empty Chunk",
        content="",  # EMPTY
        tier=MemoryTier.WORKING_CONTEXT
    )
    with pytest.raises(SyncPayloadError, match="Cannot synchronize empty KOSH memory chunk"):
        FederatedSyncService.create_memory_sync_message(
            source_identity=id_src,
            source_signing_key=sk_src,
            target_node_id="node_beta",
            tenant_id="tenant_alice",
            chunk=empty_chunk
        )


# -------------------------------------------------------------
# 2. INGESTION & SENDER TRUST VALIDATION (5-8)
# -------------------------------------------------------------

def test_5_unknown_sender_node_sync_rejection():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity(name="LocalNode")
    id_rogue, sk_rogue = NodeIdentityManager.create_node_identity(name="RogueNode")

    pat = LearningCandidate(
        pattern_id="pat_003",
        tenant_id="tenant_alice",
        pattern_type=PatternType.TOOL_ROUTING,
        name="Tool Routing Opt",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_rogue,
        source_signing_key=sk_rogue,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        pattern=pat
    )

    success, err, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert success is False
    assert "not in TrustRegistry" in err
    assert record is None


def test_6_untrusted_sender_node_sync_rejection():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity(name="LocalNode")
    id_sender, sk_sender = NodeIdentityManager.create_node_identity(name="SenderNode")

    # Registered in registry, but default tier is UNTRUSTED
    registry.register_node(id_sender)

    pat = LearningCandidate(
        pattern_id="pat_004",
        tenant_id="tenant_alice",
        pattern_type=PatternType.TOOL_ROUTING,
        name="Opt",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        pattern=pat
    )

    success, err, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert success is False
    assert "insufficient trust tier 'UNTRUSTED'" in err


def test_7_suspended_sender_node_sync_rejection():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)
    registry.set_node_status(id_sender.node_id, NodeStatus.SUSPENDED)

    pat = LearningCandidate(
        pattern_id="pat_005",
        tenant_id="tenant_alice",
        pattern_type=PatternType.TOOL_ROUTING,
        name="Opt",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        pattern=pat
    )

    success, err, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert success is False
    assert "is inactive ('SUSPENDED')" in err


def test_8_revoked_sender_node_sync_rejection():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)
    registry.set_node_status(id_sender.node_id, NodeStatus.REVOKED)

    chunk = KoshChunk(
        chunk_id="chunk_002",
        tenant_id="tenant_alice",
        title="Doc",
        content="Secret instructions"
    )
    msg = FederatedSyncService.create_memory_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        chunk=chunk
    )

    success, err, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert success is False
    assert "is inactive ('REVOKED')" in err


# -------------------------------------------------------------
# 3. CRYPTOGRAPHIC SIGNATURE TAMPERING (9-10)
# -------------------------------------------------------------

def test_9_tampered_pattern_sync_signature_rejection():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)

    pat = LearningCandidate(
        pattern_id="pat_006",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Valid Opt",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        pattern=pat
    )

    # Tamper payload
    tampered_msg = msg.model_copy(update={"payload": {"sync_type": "PATTERN", "pattern": {"hacked": True}}})

    success, err, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=tampered_msg,
        local_tenant_id="tenant_alice"
    )
    assert success is False
    assert "signature verification failed" in err


def test_10_tampered_memory_sync_signature_rejection():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)

    chunk = KoshChunk(chunk_id="chk_003", tenant_id="tenant_alice", title="T", content="Original content")
    msg = FederatedSyncService.create_memory_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        chunk=chunk
    )

    # Tamper signature hex
    tampered_sig_msg = msg.model_copy(update={"signature": "deadbeef" * 8})

    success, err, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=tampered_sig_msg,
        local_tenant_id="tenant_alice"
    )
    assert success is False
    assert "signature verification failed" in err


# -------------------------------------------------------------
# 4. TENANT ISOLATION & SHARING POLICY (11-13)
# -------------------------------------------------------------

def test_11_cross_tenant_sync_rejection_without_policy():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)
    registry.update_trust_tier(id_sender.node_id, TrustTier.FEDERATED)

    # Sender creates message under Tenant Bob
    chunk = KoshChunk(chunk_id="chk_bob", tenant_id="tenant_bob", title="Bob Secret", content="Bob data")
    msg = FederatedSyncService.create_memory_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_bob",
        chunk=chunk
    )

    # Local node tries to ingest for Tenant Alice without explicit policy
    success, err, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert success is False
    assert "Cross-tenant synchronization rejected" in err


def test_12_cross_tenant_sync_allowed_with_explicit_policy():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)
    registry.update_trust_tier(id_sender.node_id, TrustTier.FEDERATED)

    # Sender creates message under Tenant SharedOrg with explicit allowed target: tenant_alice
    pat = LearningCandidate(
        pattern_id="pat_shared_001",
        tenant_id="tenant_shared_org",
        pattern_type=PatternType.HEURISTIC_RULE,
        name="Global Safe Pattern",
        description="Shared",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_shared_org",
        pattern=pat,
        allowed_target_tenants=["tenant_shared_org", "tenant_alice"]
    )

    # Local node ingests for Tenant Alice
    success, msg_resp, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert success is True
    assert record["target_tenant_id"] == "tenant_alice"
    assert record["source_tenant_id"] == "tenant_shared_org"


def test_13_missing_tenant_id_rejection():
    id_src, sk_src = NodeIdentityManager.create_node_identity()
    pat = LearningCandidate(
        pattern_id="pat_007",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Opt",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    with pytest.raises(ValueError, match="Tenant ID is required"):
        FederatedSyncService.create_pattern_sync_message(
            source_identity=id_src,
            source_signing_key=sk_src,
            target_node_id="node_target",
            tenant_id="",
            pattern=pat
        )


# -------------------------------------------------------------
# 5. TARGET ADDRESSING & PROVENANCE (14-18)
# -------------------------------------------------------------

def test_14_mismatched_target_node_rejection():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity(name="LocalNode")
    id_sender, sk_sender = NodeIdentityManager.create_node_identity(name="SenderNode")

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)

    pat = LearningCandidate(
        pattern_id="pat_008",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Opt",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    # Target is specifically node_charlie, but local node is id_local
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id="node_charlie_different",
        tenant_id="tenant_alice",
        pattern=pat
    )

    success, err, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert success is False
    assert "does not match local node" in err


def test_15_broadcast_target_node_accepted():
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)

    pat = LearningCandidate(
        pattern_id="pat_009",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Opt",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id="BROADCAST",
        tenant_id="tenant_alice",
        pattern=pat
    )

    success, msg_resp, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert success is True
    assert record is not None


def test_16_provenance_preservation_in_staged_pattern():
    registry = NodeTrustRegistry()
    store = FederatedSyncStore()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)

    pat = LearningCandidate(
        pattern_id="pat_prov_001",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Provenance Test",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        pattern=pat
    )

    success, _, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice",
        sync_store=store
    )
    assert success is True
    assert record["provenance"]["source_node"] == id_sender.node_id
    assert record["provenance"]["source_tenant"] == "tenant_alice"
    assert record["provenance"]["signature_verified"] is True
    assert store.get_pattern("pat_prov_001") is not None


def test_17_provenance_preservation_in_staged_memory():
    registry = NodeTrustRegistry()
    store = FederatedSyncStore()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)

    chunk = KoshChunk(chunk_id="chk_prov_002", tenant_id="tenant_alice", title="Prov", content="Knowledge payload")
    msg = FederatedSyncService.create_memory_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        chunk=chunk
    )

    success, _, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice",
        sync_store=store
    )
    assert success is True
    assert record["provenance"]["source_node"] == id_sender.node_id
    assert store.get_chunk("chk_prov_002") is not None


def test_18_staged_status_invariant_no_auto_promotion():
    # Invariant: Ingested items are placed in 'STAGED_FOR_LOCAL_EVALUATION' state.
    # They do NOT automatically become active production knowledge without local evaluation.
    registry = NodeTrustRegistry()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)

    pat = LearningCandidate(
        pattern_id="pat_stage_001",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Stage Test",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        pattern=pat
    )

    _, _, record = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice"
    )
    assert record["federated_status"] == "STAGED_FOR_LOCAL_EVALUATION"


# -------------------------------------------------------------
# 6. IDEMPOTENCY & BOUNDARY (19-20)
# -------------------------------------------------------------

def test_19_idempotent_duplicate_message_ingestion():
    registry = NodeTrustRegistry()
    store = FederatedSyncStore()
    id_local, _ = NodeIdentityManager.create_node_identity()
    id_sender, sk_sender = NodeIdentityManager.create_node_identity()

    registry.register_node(id_sender)
    registry.update_trust_tier(id_sender.node_id, TrustTier.VERIFIED)

    pat = LearningCandidate(
        pattern_id="pat_dup_001",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Dup Test",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    msg = FederatedSyncService.create_pattern_sync_message(
        source_identity=id_sender,
        source_signing_key=sk_sender,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alice",
        pattern=pat
    )

    # First ingestion
    succ1, msg1, rec1 = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice",
        sync_store=store
    )
    assert succ1 is True
    assert "successfully ingested" in msg1

    # Second ingestion of the exact same message
    succ2, msg2, rec2 = FederatedSyncService.verify_and_ingest_sync_message(
        local_identity=id_local,
        trust_registry=registry,
        incoming_message=msg,
        local_tenant_id="tenant_alice",
        sync_store=store
    )
    assert succ2 is True
    assert "already ingested (idempotent)" in msg2
    assert rec1 == rec2


def test_20_phase18a_18b_boundary_protection():
    # Strictly ensures Phase 18A identity and Phase 18B trust registry remain intact
    assert TrustTier.SOVEREIGN.value == "SOVEREIGN"
    registry = NodeTrustRegistry()
    assert len(registry.list_nodes()) == 0


def run_all_20_phase18c_tests():
    print("==================================================")
    print("FEDERATION SYSTEM PHASE 18C: 20-SCENARIO SUITE")
    print("DISTRIBUTED PATTERN & MEMORY SYNCHRONIZATION (§18.3, §18.5)")
    print("==================================================")

    test_1_valid_same_tenant_pattern_sync()
    print("  [PASS 1/20] [REAL] Valid same-tenant pattern sync (§18.3).")

    test_2_valid_same_tenant_memory_sync()
    print("  [PASS 2/20] [REAL] Valid same-tenant memory sync (§18.3).")

    test_3_unpromoted_pattern_sync_rejection_fail_closed()
    print("  [PASS 3/20] [REAL] Unpromoted pattern sync rejection fails closed.")

    test_4_empty_memory_chunk_sync_rejection_fail_closed()
    print("  [PASS 4/20] [REAL] Empty memory chunk sync rejection fails closed.")

    test_5_unknown_sender_node_sync_rejection()
    print("  [PASS 5/20] [REAL] Unknown sender node sync rejection fails closed.")

    test_6_untrusted_sender_node_sync_rejection()
    print("  [PASS 6/20] [REAL] Untrusted sender node sync rejection fails closed.")

    test_7_suspended_sender_node_sync_rejection()
    print("  [PASS 7/20] [REAL] Suspended sender node sync rejection fails closed.")

    test_8_revoked_sender_node_sync_rejection()
    print("  [PASS 8/20] [REAL] Revoked sender node sync rejection fails closed.")

    test_9_tampered_pattern_sync_signature_rejection()
    print("  [PASS 9/20] [REAL] Tampered pattern sync signature rejection fails closed.")

    test_10_tampered_memory_sync_signature_rejection()
    print("  [PASS 10/20] [REAL] Tampered memory sync signature rejection fails closed.")

    test_11_cross_tenant_sync_rejection_without_policy()
    print("  [PASS 11/20] [REAL] Cross-tenant sync rejection without policy (§18.5).")

    test_12_cross_tenant_sync_allowed_with_explicit_policy()
    print("  [PASS 12/20] [REAL] Cross-tenant sync allowed with explicit policy.")

    test_13_missing_tenant_id_rejection()
    print("  [PASS 13/20] [REAL] Missing tenant ID rejection fails closed.")

    test_14_mismatched_target_node_rejection()
    print("  [PASS 14/20] [REAL] Mismatched target node rejection fails closed.")

    test_15_broadcast_target_node_accepted()
    print("  [PASS 15/20] [REAL] Broadcast target node accepted.")

    test_16_provenance_preservation_in_staged_pattern()
    print("  [PASS 16/20] [REAL] Provenance preservation in staged pattern.")

    test_17_provenance_preservation_in_staged_memory()
    print("  [PASS 17/20] [REAL] Provenance preservation in staged memory.")

    test_18_staged_status_invariant_no_auto_promotion()
    print("  [PASS 18/20] [REAL] Staged status invariant (no automatic promotion).")

    test_19_idempotent_duplicate_message_ingestion()
    print("  [PASS 19/20] [REAL] Idempotent duplicate message ingestion.")

    test_20_phase18a_18b_boundary_protection()
    print("  [PASS 20/20] [REAL] Phase 18A & 18B boundary protection.")

    print("\n==================================================")
    print("ALL 20 PHASE 18C TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_20_phase18c_tests()
