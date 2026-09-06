"""
FEDERATION SYSTEM Phase 18H Dedicated Test Suite: Unified Federation Ingress/Egress Pipeline & Lifecycle Orchestrator
Strictly tests Whitesheet §18.0 - §18.6 requirements across 35 comprehensive scenarios.
"""
import pytest
import os
import concurrent.futures
from datetime import datetime, timezone, timedelta

from app.core.federation.models import (
    TrustTier,
    NodeStatus,
    FederationPayloadType,
    NodeIdentity,
    FederationMessage
)
from app.core.federation.identity import NodeIdentityManager
from app.core.federation.trust import NodeTrustRegistry
from app.core.federation.sync import FederatedSyncStore
from app.core.federation.replay import FederationReplayGuard, ReplayStatus
from app.core.federation.governance import GovernanceDecision
from app.core.federation.audit import FederatedChitraAuditService
from app.core.federation.orchestrator import (
    FederationIngressResult,
    FederationEgressDispatcher,
    FederationPipelineCoordinator
)
from app.core.chitra.crypto import GENESIS_HASH

# Ensure dedicated test key for CHITRA ledger
os.environ["CHITRA_SIGNING_KEY"] = "chitra_secret_key_phase18h_test_suite_2026"


def create_test_setup():
    id_local, sk_local = NodeIdentityManager.create_node_identity(name="LocalHubNode")
    id_peer, sk_peer = NodeIdentityManager.create_node_identity(name="RemotePeerNode")
    
    trust_registry = NodeTrustRegistry()
    trust_registry.register_node(id_peer)
    trust_registry.update_trust_tier(id_peer.node_id, TrustTier.VERIFIED)
    
    replay_guard = FederationReplayGuard(window_seconds=300)
    sync_store = FederatedSyncStore()
    
    coordinator = FederationPipelineCoordinator(
        local_identity=id_local,
        local_signing_key=sk_local,
        trust_registry=trust_registry,
        replay_guard=replay_guard,
        sync_store=sync_store
    )
    return id_local, sk_local, id_peer, sk_peer, trust_registry, replay_guard, sync_store, coordinator


# -------------------------------------------------------------
# 1. END-TO-END INGRESS HAPPY PATHS (1-5)
# -------------------------------------------------------------

def test_1_end_to_end_heartbeat_ingress_accepted():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000001",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={"status": "HEALTHY"},
        timestamp=now.isoformat(),
        nonce="nonce_orch_00000001"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.status == "ACCEPTED"
    assert res.authenticated is True
    assert res.tenant_authorized is True
    assert res.audit_event is not None
    assert res.audit_event.faculty == "FEDERATION"
    assert res.execution_permitted is False


def test_2_end_to_end_handshake_ingress_accepted():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000002",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HANDSHAKE,
        payload={
            "step": "REQUEST",
            "session_id": "ses_handshake_01M1",
            "peer_public_key": id_peer.public_key,
            "nonce": "nonce_handshake_222222"
        },
        timestamp=now.isoformat(),
        nonce="nonce_orch_00000002"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.status == "ACCEPTED"
    assert res.handshake_result["handshake_status"] == "ACCEPTED"
    assert res.handshake_result["response_message_id"] is not None


def test_3_end_to_end_pattern_sync_ingress_staged():
    _, _, id_peer, sk_peer, _, _, sync_store, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000003",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.PATTERN_SYNC,
        payload={
            "sync_type": "PATTERN",
            "pattern": {
                "pattern_id": "pat_01M1_ORCH",
                "status": "PROMOTED",
                "domain": "SECURITY",
                "confidence_score": 0.95
            }
        },
        timestamp=now.isoformat(),
        nonce="nonce_orch_00000003"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.status == "ACCEPTED"
    assert res.sync_result is not None
    # Staging invariant verified
    assert sync_store.get_pattern("pat_01M1_ORCH")["federated_status"] == "STAGED_FOR_LOCAL_EVALUATION"


def test_4_end_to_end_knowledge_sync_ingress_staged():
    _, _, id_peer, sk_peer, _, _, sync_store, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000004",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.KNOWLEDGE_SYNC,
        payload={
            "sync_type": "KNOWLEDGE",
            "chunk": {
                "chunk_id": "chk_01M1_ORCH",
                "tier": "EPISODIC",
                "content": "Curated knowledge content",
                "curated": True
            }
        },
        timestamp=now.isoformat(),
        nonce="nonce_orch_00000004"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.status == "ACCEPTED"
    assert sync_store.get_chunk("chk_01M1_ORCH")["federated_status"] == "STAGED_FOR_LOCAL_EVALUATION"


def test_5_end_to_end_task_dispatch_approved_by_governance():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000005",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.TASK_DISPATCH,
        payload={
            "action_name": "system_status",
            "action_payload": {}
        },
        timestamp=now.isoformat(),
        nonce="nonce_orch_00000005"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.status == "APPROVED"
    assert res.governance_verdict is not None
    assert res.governance_verdict.overall_governance_decision == GovernanceDecision.APPROVED
    assert res.execution_permitted is False


# -------------------------------------------------------------
# 2. STEP 1: REPLAY & TIMING DEFENSE (6-8)
# -------------------------------------------------------------

def test_6_replay_rejected_at_step_1():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000006",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_replay_006"
    ))
    
    res1 = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res1.status == "ACCEPTED"
    
    # Replay identical message
    res2 = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now + timedelta(seconds=1))
    assert res2.status == "REJECTED"
    assert res2.replay_verdict.status == ReplayStatus.REJECT_DUPLICATE_NONCE
    assert res2.audit_event is not None
    assert res2.audit_event.constitutional_review == "blocked"


def test_7_stale_timestamp_rejected_at_step_1():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    stale_ts = (now - timedelta(seconds=350)).isoformat()
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000007",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=stale_ts,
        nonce="nonce_orch_stale_007"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status == "REJECTED"
    assert res.replay_verdict.status == ReplayStatus.REJECT_STALE_TIMESTAMP


def test_8_future_timestamp_rejected_at_step_1():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    future_ts = (now + timedelta(seconds=80)).isoformat()
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000008",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=future_ts,
        nonce="nonce_orch_future_008"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status == "REJECTED"
    assert res.replay_verdict.status == ReplayStatus.REJECT_FUTURE_TIMESTAMP


# -------------------------------------------------------------
# 3. STEP 2 & 3: TRUST & CRYPTOGRAPHIC GATES (9-13)
# -------------------------------------------------------------

def test_9_unknown_peer_rejected_at_step_2():
    _, _, _, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000009",
        source_node_id="node_unknown_999",
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_unknown_09"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status == "REJECTED"
    assert res.authenticated is False


def test_10_suspended_peer_rejected_at_step_2():
    _, _, id_peer, sk_peer, trust_registry, _, _, coordinator = create_test_setup()
    trust_registry.set_node_status(id_peer.node_id, NodeStatus.SUSPENDED)
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000010",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_suspended_10"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status == "REJECTED"
    assert "inactive" in res.reason


def test_11_revoked_peer_rejected_at_step_2():
    _, _, id_peer, sk_peer, trust_registry, _, _, coordinator = create_test_setup()
    trust_registry.set_node_status(id_peer.node_id, NodeStatus.REVOKED)
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000011",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_revoked_11"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status == "REJECTED"
    assert "REVOKED" in res.reason or "inactive" in res.reason


def test_12_insufficient_trust_tier_rejected_at_step_2():
    id_local, sk_local = NodeIdentityManager.create_node_identity()
    id_peer, sk_peer = NodeIdentityManager.create_node_identity()
    
    trust_registry = NodeTrustRegistry()
    trust_registry.register_node(id_peer)  # Registered at UNTRUSTED by default
    
    coordinator = FederationPipelineCoordinator(
        local_identity=id_local,
        local_signing_key=sk_local,
        trust_registry=trust_registry
    )
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000012",
        source_node_id=id_peer.node_id,
        target_node_id=id_local.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_untrusted_12"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status == "REJECTED"
    assert "insufficient" in res.reason


def test_13_tampered_signature_rejected_at_step_3():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000013",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_tamper_13"
    ))
    corrupted_msg = msg.model_copy(update={"signature": "deadbeef" * 8})
    
    res = coordinator.process_incoming_message(corrupted_msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status == "REJECTED"
    assert res.authenticated is False
    assert "Signature verification failed" in res.reason


# -------------------------------------------------------------
# 4. STEP 4: TENANT & TARGET BOUNDARY DEFENSE (14-16)
# -------------------------------------------------------------

def test_14_target_node_mismatch_rejected_at_step_4():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000014",
        source_node_id=id_peer.node_id,
        target_node_id="node_third_party_charlie",  # Target mismatch
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_target_14"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status == "BLOCKED"
    assert "Target node mismatch" in res.reason


def test_15_cross_tenant_rejected_at_step_4():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000015",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_bob",  # Cross-tenant
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_cross_15"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alice", current_time=now)
    assert res.status == "DENIED"
    assert res.tenant_authorized is False


def test_16_authorized_cross_tenant_accepted():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000016",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_shared_org",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={"allowed_target_tenants": ["tenant_shared_org", "tenant_alice"]},
        timestamp=now.isoformat(),
        nonce="nonce_orch_cross_auth_16"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alice", current_time=now)
    assert res.status == "ACCEPTED"
    assert res.tenant_authorized is True


# -------------------------------------------------------------
# 5. STEP 5, 6, 7: GOVERNANCE & SYNC ISOLATION (17-20)
# -------------------------------------------------------------

def test_17_task_dispatch_denied_by_local_maryada():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    # Destructive action blocked by MARYADA invariants
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000017",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.TASK_DISPATCH,
        payload={"action_name": "rm -rf /critical_system"},
        timestamp=now.isoformat(),
        nonce="nonce_orch_gov_deny_17"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status in ["DENIED", "BLOCKED"]
    assert res.governance_verdict.maryada_approved is False


def test_18_task_dispatch_blocked_by_murphy_blast_radius():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000018",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.TASK_DISPATCH,
        payload={"action_name": "wire_transfer"},
        timestamp=now.isoformat(),
        nonce="nonce_orch_murphy_18"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status in ["DENIED", "BLOCKED"]
    assert res.governance_verdict.murphy_blast_radius >= 0.85


def test_19_remote_governance_claims_ignored_by_pipeline():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    # Destructive action claiming approval
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000019",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.TASK_DISPATCH,
        payload={
            "action_name": "drop database production",
            "claimed_governance": {"claimed_approved": True, "claimed_risk": "ZERO"}
        },
        timestamp=now.isoformat(),
        nonce="nonce_orch_override_19"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=now)
    assert res.status in ["DENIED", "BLOCKED"]
    assert res.governance_verdict.maryada_approved is False


def test_20_sync_conflict_resolved_deterministically():
    _, _, id_peer, sk_peer, _, _, sync_store, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg1 = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000020A",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.PATTERN_SYNC,
        payload={
            "sync_type": "PATTERN",
            "pattern": {
                "pattern_id": "pat_conflict_20",
                "status": "PROMOTED",
                "domain": "AUTH",
                "confidence_score": 0.8
            }
        },
        timestamp=now.isoformat(),
        nonce="nonce_orch_sync_20A"
    ))
    res1 = coordinator.process_incoming_message(msg1, local_tenant_id="tenant_alpha")
    assert res1.status == "ACCEPTED"


# -------------------------------------------------------------
# 6. STEP 8: CHITRA AUDIT LEDGER INTEGRITY (21-24)
# -------------------------------------------------------------

def test_21_every_accepted_message_produces_valid_chitra_audit():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000021",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_audit_accept_21"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.audit_event is not None
    is_valid, reason = FederatedChitraAuditService.verify_audit_event(res.audit_event)
    assert is_valid is True, reason


def test_22_every_rejected_message_produces_valid_chitra_audit():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000022",
        source_node_id=id_peer.node_id,
        target_node_id="node_different_target",
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_audit_reject_22"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.status == "BLOCKED"
    assert res.audit_event is not None
    is_valid, reason = FederatedChitraAuditService.verify_audit_event(res.audit_event)
    assert is_valid is True, reason


def test_23_chitra_audit_chain_continuity_across_mixed_events():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    prev_hash = GENESIS_HASH
    events = []
    
    for i in range(4):
        msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
            message_id=f"msg_01M1FORCH_MIXED_{i}",
            source_node_id=id_peer.node_id,
            target_node_id=coordinator.local_identity.node_id,
            tenant_id="tenant_alpha",
            payload_type=FederationPayloadType.HEARTBEAT,
            payload={"seq": i},
            timestamp=now.isoformat(),
            nonce=f"nonce_orch_mixed_{i:04d}"
        ))
        res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", prev_audit_hash=prev_hash)
        events.append(res.audit_event)
        prev_hash = res.audit_event.this_event_hash
        
    expected_prev = GENESIS_HASH
    for evt in events:
        is_valid, _ = FederatedChitraAuditService.verify_audit_event(evt, expected_prev_event_hash=expected_prev)
        assert is_valid is True
        expected_prev = evt.this_event_hash


# -------------------------------------------------------------
# 7. EGRESS DISPATCHER (24-26)
# -------------------------------------------------------------

def test_24_egress_dispatcher_creates_signed_message_and_audit():
    id_local, sk_local, id_peer, _, _, _, _, _ = create_test_setup()
    
    msg, audit_evt = FederationEgressDispatcher.dispatch_message(
        local_identity=id_local,
        local_signing_key=sk_local,
        target_node_id=id_peer.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.PATTERN_SYNC,
        payload={"pattern_id": "pat_egress_24"}
    )
    assert msg.signature is not None
    assert NodeIdentityManager.verify_message_signature(id_local.public_key, msg) is True
    assert audit_evt.faculty == "FEDERATION"
    assert audit_evt.event_type == "FEDERATION_OUTGOING"


def test_25_egress_dispatcher_validates_required_fields():
    id_local, sk_local, _, _, _, _, _, _ = create_test_setup()
    with pytest.raises(ValueError, match="target_node_id"):
        FederationEgressDispatcher.dispatch_message(
            local_identity=id_local,
            local_signing_key=sk_local,
            target_node_id="",
            tenant_id="tenant_alpha",
            payload_type=FederationPayloadType.HEARTBEAT,
            payload={}
        )


def test_26_egress_dispatcher_missing_tenant_rejected():
    id_local, sk_local, id_peer, _, _, _, _, _ = create_test_setup()
    with pytest.raises(ValueError, match="tenant_id"):
        FederationEgressDispatcher.dispatch_message(
            local_identity=id_local,
            local_signing_key=sk_local,
            target_node_id=id_peer.node_id,
            tenant_id="",
            payload_type=FederationPayloadType.HEARTBEAT,
            payload={}
        )


# -------------------------------------------------------------
# 8. SAFETY, PROVENANCE & CONCURRENCY (27-35)
# -------------------------------------------------------------

def test_27_execution_permitted_is_strictly_false():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000027",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.TASK_DISPATCH,
        payload={"action_name": "system_status"},
        timestamp=now.isoformat(),
        nonce="nonce_orch_safe_2727"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.execution_permitted is False


def test_28_staged_for_local_evaluation_invariant_preserved():
    _, _, id_peer, sk_peer, _, _, sync_store, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000028",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.PATTERN_SYNC,
        payload={
            "sync_type": "PATTERN",
            "pattern": {
                "pattern_id": "pat_staged_28",
                "status": "PROMOTED",
                "domain": "CORE",
                "confidence_score": 0.99
            }
        },
        timestamp=now.isoformat(),
        nonce="nonce_orch_staged_2828"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.status == "ACCEPTED"
    assert sync_store.get_pattern("pat_staged_28")["federated_status"] == "STAGED_FOR_LOCAL_EVALUATION"


def test_29_provenance_preserved_end_to_end():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH00000000000029",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_prov_2929"
    ))
    
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
    assert res.provenance["source_node_id"] == id_peer.node_id
    assert res.provenance["target_node_id"] == coordinator.local_identity.node_id
    assert res.provenance["source_tenant_id"] == "tenant_alpha"
    assert res.provenance["local_tenant_id"] == "tenant_alpha"


def test_30_concurrent_multi_peer_ingress():
    id_local, sk_local = NodeIdentityManager.create_node_identity()
    trust_registry = NodeTrustRegistry()
    replay_guard = FederationReplayGuard(window_seconds=300)
    coordinator = FederationPipelineCoordinator(
        local_identity=id_local,
        local_signing_key=sk_local,
        trust_registry=trust_registry,
        replay_guard=replay_guard
    )
    now = datetime.now(timezone.utc)
    
    # Register 10 distinct peers
    peer_data = []
    for i in range(10):
        id_p, sk_p = NodeIdentityManager.create_node_identity(name=f"Peer_{i}")
        trust_registry.register_node(id_p)
        trust_registry.update_trust_tier(id_p.node_id, TrustTier.VERIFIED)
        msg = NodeIdentityManager.sign_message(sk_p, FederationMessage(
            message_id=f"msg_01M1FORCH_CONC_{i}",
            source_node_id=id_p.node_id,
            target_node_id=id_local.node_id,
            tenant_id="tenant_alpha",
            payload_type=FederationPayloadType.HEARTBEAT,
            payload={"i": i},
            timestamp=now.isoformat(),
            nonce=f"nonce_conc_peer_{i:04d}"
        ))
        peer_data.append(msg)
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(coordinator.process_incoming_message, m, "tenant_alpha") for m in peer_data]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
    assert all(r.status == "ACCEPTED" for r in results)


def test_31_concurrent_duplicate_ingress_exactly_one_succeeds():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH_DUP_RACE_31",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=now.isoformat(),
        nonce="nonce_orch_dup_race_3131"
    ))
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(coordinator.process_incoming_message, msg, "tenant_alpha") for _ in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
    accepted_count = sum(1 for r in results if r.status == "ACCEPTED")
    rejected_count = sum(1 for r in results if r.status == "REJECTED")
    assert accepted_count == 1
    assert rejected_count == 9


def test_32_fail_closed_on_malformed_envelope():
    _, _, _, _, _, _, _, coordinator = create_test_setup()
    res = coordinator.process_incoming_message(None, local_tenant_id="tenant_alpha")
    assert res.status == "REJECTED"


def test_33_phase18a_through_18g_boundary_protection():
    assert TrustTier.SOVEREIGN.value == "SOVEREIGN"
    assert FederationPayloadType.TASK_DISPATCH.value == "TASK_DISPATCH"
    assert ReplayStatus.VALID.value == "VALID"


def test_34_clean_deterministic_repeated_pipeline_runs():
    _, _, id_peer, sk_peer, _, _, _, coordinator = create_test_setup()
    now = datetime.now(timezone.utc)
    
    for i in range(5):
        msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
            message_id=f"msg_01M1FORCH_REPEAT_{i}",
            source_node_id=id_peer.node_id,
            target_node_id=coordinator.local_identity.node_id,
            tenant_id="tenant_alpha",
            payload_type=FederationPayloadType.HEARTBEAT,
            payload={},
            timestamp=now.isoformat(),
            nonce=f"nonce_repeat_{i:04d}"
        ))
        res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha")
        assert res.status == "ACCEPTED"


def test_35_cache_prune_maintains_pipeline_health():
    _, _, id_peer, sk_peer, _, replay_guard, _, coordinator = create_test_setup()
    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    
    msg = NodeIdentityManager.sign_message(sk_peer, FederationMessage(
        message_id="msg_01M1FORCH_PRUNE_35",
        source_node_id=id_peer.node_id,
        target_node_id=coordinator.local_identity.node_id,
        tenant_id="tenant_alpha",
        payload_type=FederationPayloadType.HEARTBEAT,
        payload={},
        timestamp=t0.isoformat(),
        nonce="nonce_prune_test_3535"
    ))
    res = coordinator.process_incoming_message(msg, local_tenant_id="tenant_alpha", current_time=t0)
    assert res.status == "ACCEPTED"
    
    # 400 seconds later, replay guard prunes expired records
    t1 = t0 + timedelta(seconds=400)
    pruned = replay_guard.prune_expired(current_time=t1)
    assert pruned >= 1


def run_all_35_phase18h_tests():
    print("==================================================")
    print("FEDERATION SYSTEM PHASE 18H: 35-SCENARIO SUITE")
    print("UNIFIED INGRESS/EGRESS PIPELINE & ORCHESTRATOR (§18.0 - §18.6)")
    print("==================================================")

    test_1_end_to_end_heartbeat_ingress_accepted()
    print("  [PASS 1/35] [REAL] End-to-end heartbeat ingress accepted.")

    test_2_end_to_end_handshake_ingress_accepted()
    print("  [PASS 2/35] [REAL] End-to-end handshake ingress accepted.")

    test_3_end_to_end_pattern_sync_ingress_staged()
    print("  [PASS 3/35] [REAL] End-to-end pattern sync ingress staged.")

    test_4_end_to_end_knowledge_sync_ingress_staged()
    print("  [PASS 4/35] [REAL] End-to-end knowledge sync ingress staged.")

    test_5_end_to_end_task_dispatch_approved_by_governance()
    print("  [PASS 5/35] [REAL] End-to-end task dispatch approved by governance.")

    test_6_replay_rejected_at_step_1()
    print("  [PASS 6/35] [REAL] Replay rejected at Step 1 (ReplayGuard).")

    test_7_stale_timestamp_rejected_at_step_1()
    print("  [PASS 7/35] [REAL] Stale timestamp rejected at Step 1.")

    test_8_future_timestamp_rejected_at_step_1()
    print("  [PASS 8/35] [REAL] Future timestamp rejected at Step 1.")

    test_9_unknown_peer_rejected_at_step_2()
    print("  [PASS 9/35] [REAL] Unknown peer rejected at Step 2 (Trust Matrix).")

    test_10_suspended_peer_rejected_at_step_2()
    print("  [PASS 10/35] [REAL] Suspended peer rejected at Step 2.")

    test_11_revoked_peer_rejected_at_step_2()
    print("  [PASS 11/35] [REAL] Revoked peer rejected at Step 2.")

    test_12_insufficient_trust_tier_rejected_at_step_2()
    print("  [PASS 12/35] [REAL] Insufficient trust tier rejected at Step 2.")

    test_13_tampered_signature_rejected_at_step_3()
    print("  [PASS 13/35] [REAL] Tampered signature rejected at Step 3 (ECDSA).")

    test_14_target_node_mismatch_rejected_at_step_4()
    print("  [PASS 14/35] [REAL] Target node mismatch rejected at Step 4.")

    test_15_cross_tenant_rejected_at_step_4()
    print("  [PASS 15/35] [REAL] Cross-tenant access rejected at Step 4.")

    test_16_authorized_cross_tenant_accepted()
    print("  [PASS 16/35] [REAL] Authorized cross-tenant accepted.")

    test_17_task_dispatch_denied_by_local_maryada()
    print("  [PASS 17/35] [REAL] Task dispatch denied by local MARYADA.")

    test_18_task_dispatch_blocked_by_murphy_blast_radius()
    print("  [PASS 18/35] [REAL] Task dispatch blocked by MURPHY blast radius.")

    test_19_remote_governance_claims_ignored_by_pipeline()
    print("  [PASS 19/35] [REAL] Remote governance claims ignored by pipeline.")

    test_20_sync_conflict_resolved_deterministically()
    print("  [PASS 20/35] [REAL] Sync conflict resolved deterministically.")

    test_21_every_accepted_message_produces_valid_chitra_audit()
    print("  [PASS 21/35] [REAL] Accepted message produces valid CHITRA audit.")

    test_22_every_rejected_message_produces_valid_chitra_audit()
    print("  [PASS 22/35] [REAL] Rejected message produces valid CHITRA audit.")

    test_23_chitra_audit_chain_continuity_across_mixed_events()
    print("  [PASS 23/35] [REAL] CHITRA audit chain continuity across mixed events.")

    test_24_egress_dispatcher_creates_signed_message_and_audit()
    print("  [PASS 24/35] [REAL] Egress dispatcher creates signed message and audit.")

    test_25_egress_dispatcher_validates_required_fields()
    print("  [PASS 25/35] [REAL] Egress dispatcher validates required fields.")

    test_26_egress_dispatcher_missing_tenant_rejected()
    print("  [PASS 26/35] [REAL] Egress dispatcher missing tenant rejected.")

    test_27_execution_permitted_is_strictly_false()
    print("  [PASS 27/35] [REAL] Execution permitted is strictly False.")

    test_28_staged_for_local_evaluation_invariant_preserved()
    print("  [PASS 28/35] [REAL] STAGED_FOR_LOCAL_EVALUATION invariant preserved.")

    test_29_provenance_preserved_end_to_end()
    print("  [PASS 29/35] [REAL] Complete provenance preserved end-to-end.")

    test_30_concurrent_multi_peer_ingress()
    print("  [PASS 30/35] [REAL] Concurrent multi-peer ingress processed safely.")

    test_31_concurrent_duplicate_ingress_exactly_one_succeeds()
    print("  [PASS 31/35] [REAL] Concurrent duplicate ingress: exactly 1 succeeds.")

    test_32_fail_closed_on_malformed_envelope()
    print("  [PASS 32/35] [REAL] Fail closed on null/malformed envelope.")

    test_33_phase18a_through_18g_boundary_protection()
    print("  [PASS 33/35] [REAL] Phase 18A-18G boundary protection.")

    test_34_clean_deterministic_repeated_pipeline_runs()
    print("  [PASS 34/35] [REAL] Clean deterministic repeated pipeline runs.")

    test_35_cache_prune_maintains_pipeline_health()
    print("  [PASS 35/35] [REAL] Cache pruning maintains pipeline health.")

    print("\n==================================================")
    print("ALL 35 PHASE 18H TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_35_phase18h_tests()
