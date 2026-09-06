"""
UNIFIED FEDERATION PIPELINE COORDINATOR & LIFECYCLE ORCHESTRATOR (Whitesheet §18.0 - §18.6)
Synthesizes the complete end-to-end federation lifecycle:
ReplayGuard -> Trust Registry -> Signature Verification -> Tenant Gate -> Payload Routing -> Governance/Sync -> CHITRA Audit.
"""
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone
import secrets
from pydantic import BaseModel, Field
from ecdsa import SigningKey

from app.core.federation.models import (
    TrustTier,
    NodeStatus,
    FederationPayloadType,
    NodeIdentity,
    FederationMessage
)
from app.core.federation.identity import NodeIdentityManager
from app.core.federation.trust import NodeTrustRegistry
from app.core.federation.handshake import NodeHandshakeService
from app.core.federation.sync import FederatedSyncService, FederatedSyncStore
from app.core.federation.governance import (
    GovernanceDecision,
    FederatedGovernanceVerdict,
    FederatedGovernanceEngine
)
from app.core.federation.audit import (
    FederationAuditEventType,
    FederatedAuditEvent,
    FederatedChitraAuditService
)
from app.core.federation.replay import (
    ReplayStatus,
    ReplayCheckVerdict,
    FederationReplayGuard
)
from app.core.chitra.crypto import GENESIS_HASH, generate_ulid, compute_sha256, canonical_json


class FederationIngressResult(BaseModel):
    """
    Comprehensive, authoritative result of end-to-end federation ingress pipeline processing.
    """
    message_id: str
    source_node_id: str
    target_node_id: str
    tenant_id: str
    payload_type: FederationPayloadType
    replay_verdict: ReplayCheckVerdict
    authenticated: bool
    tenant_authorized: bool
    governance_verdict: Optional[FederatedGovernanceVerdict] = None
    sync_result: Optional[Dict[str, Any]] = None
    handshake_result: Optional[Dict[str, Any]] = None
    audit_event: Optional[FederatedAuditEvent] = None
    execution_permitted: bool = False  # Strict Invariant: Never auto-executed
    status: str  # ACCEPTED | REJECTED | BLOCKED | DENIED
    reason: str
    provenance: Dict[str, Any] = Field(default_factory=dict)
    processed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FederationEgressDispatcher:
    """
    Dispatcher for creating, cryptographically signing, and auditing outgoing federation wire messages.
    """

    @classmethod
    def dispatch_message(
        cls,
        local_identity: NodeIdentity,
        local_signing_key: SigningKey,
        target_node_id: str,
        tenant_id: str,
        payload_type: FederationPayloadType,
        payload: Dict[str, Any],
        prev_audit_hash: str = GENESIS_HASH,
        secret_key: Optional[str] = None
    ) -> Tuple[FederationMessage, FederatedAuditEvent]:
        """
        Constructs, signs, and generates a CHITRA audit event for an outgoing federation message.
        """
        if not target_node_id or not target_node_id.strip():
            raise ValueError("target_node_id cannot be null or empty.")
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id cannot be null or empty.")

        unsigned_msg = FederationMessage(
            message_id=generate_ulid(prefix="msg_out_"),
            source_node_id=local_identity.node_id,
            target_node_id=target_node_id.strip(),
            tenant_id=tenant_id.strip(),
            payload_type=payload_type,
            payload=payload or {},
            nonce=secrets.token_hex(16)
        )

        signed_msg = NodeIdentityManager.sign_message(local_signing_key, unsigned_msg)

        audit_evt = FederatedChitraAuditService.create_outgoing_audit_event(
            outgoing_message=signed_msg,
            local_identity=local_identity,
            local_tenant_id=tenant_id,
            prev_event_hash=prev_audit_hash,
            secret_key=secret_key
        )

        return signed_msg, audit_evt


class FederationPipelineCoordinator:
    """
    Authoritative coordinator orchestrating the full 9-step federation ingress pipeline.
    """

    def __init__(
        self,
        local_identity: NodeIdentity,
        local_signing_key: SigningKey,
        trust_registry: NodeTrustRegistry,
        replay_guard: Optional[FederationReplayGuard] = None,
        sync_store: Optional[FederatedSyncStore] = None
    ):
        self.local_identity = local_identity
        self.local_signing_key = local_signing_key
        self.trust_registry = trust_registry
        self.replay_guard = replay_guard or FederationReplayGuard()
        self.sync_store = sync_store or FederatedSyncStore()

    def process_incoming_message(
        self,
        incoming_message: FederationMessage,
        local_tenant_id: str,
        prev_audit_hash: str = GENESIS_HASH,
        current_time: Optional[datetime] = None,
        secret_key: Optional[str] = None
    ) -> FederationIngressResult:
        """
        Executes the strict 9-step ingress lifecycle:
        1. ReplayGuard (Freshness & Nonce Uniqueness)
        2. Trust & Identity Status
        3. Cryptographic Signature Verification
        4. Target Node & Tenant Isolation
        5. Payload Routing (Handshake, Task Dispatch, Sync, Heartbeat)
        6. Governance & Blast-Radius (for Task Dispatch)
        7. Sync & Conflict Resolution (for Sync)
        8. CHITRA Federation Audit Chaining
        9. Return Unified Ingress Result (Safe Staged State)
        """
        now_iso = (current_time or datetime.now(timezone.utc)).isoformat()
        
        # -------------------------------------------------------------
        # STEP 1: REPLAY GUARD (§18.2 / Phase 18G)
        # -------------------------------------------------------------
        replay_verdict = self.replay_guard.validate_and_record(incoming_message, current_time=current_time)
        if not replay_verdict.is_valid:
            audit_evt = FederatedChitraAuditService.create_rejection_audit_event(
                incoming_message=incoming_message,
                local_identity=self.local_identity,
                local_tenant_id=local_tenant_id,
                rejection_reason=f"ReplayGuard rejected message: {replay_verdict.reason}",
                prev_event_hash=prev_audit_hash,
                secret_key=secret_key
            )
            return FederationIngressResult(
                message_id=incoming_message.message_id if incoming_message else "UNKNOWN",
                source_node_id=incoming_message.source_node_id if incoming_message else "UNKNOWN",
                target_node_id=incoming_message.target_node_id if incoming_message else "UNKNOWN",
                tenant_id=incoming_message.tenant_id if incoming_message else "UNKNOWN",
                payload_type=incoming_message.payload_type if incoming_message else FederationPayloadType.HEARTBEAT,
                replay_verdict=replay_verdict,
                authenticated=False,
                tenant_authorized=False,
                audit_event=audit_evt,
                execution_permitted=False,
                status="REJECTED",
                reason=f"ReplayGuard check failed: {replay_verdict.reason}",
                provenance={"stage": "REPLAY_GUARD_FAIL"},
                processed_at=now_iso
            )

        # -------------------------------------------------------------
        # STEP 2: PEER IDENTITY & TRUST MATRIX (§18.1, §18.2 / Phase 18A, 18B)
        # -------------------------------------------------------------
        sender_node = self.trust_registry.get_node(incoming_message.source_node_id)
        if not sender_node:
            audit_evt = FederatedChitraAuditService.create_rejection_audit_event(
                incoming_message=incoming_message,
                local_identity=self.local_identity,
                local_tenant_id=local_tenant_id,
                rejection_reason=f"Unknown peer node '{incoming_message.source_node_id}' not found in TrustRegistry.",
                prev_event_hash=prev_audit_hash,
                secret_key=secret_key
            )
            return FederationIngressResult(
                message_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                payload_type=incoming_message.payload_type,
                replay_verdict=replay_verdict,
                authenticated=False,
                tenant_authorized=False,
                audit_event=audit_evt,
                execution_permitted=False,
                status="REJECTED",
                reason=f"Unknown sender '{incoming_message.source_node_id}'",
                provenance={"stage": "TRUST_REGISTRY_NOT_FOUND"},
                processed_at=now_iso
            )

        if sender_node.status != NodeStatus.ACTIVE:
            audit_evt = FederatedChitraAuditService.create_rejection_audit_event(
                incoming_message=incoming_message,
                local_identity=self.local_identity,
                local_tenant_id=local_tenant_id,
                rejection_reason=f"Sender node '{incoming_message.source_node_id}' is in inactive state '{sender_node.status.value}'.",
                prev_event_hash=prev_audit_hash,
                secret_key=secret_key
            )
            return FederationIngressResult(
                message_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                payload_type=incoming_message.payload_type,
                replay_verdict=replay_verdict,
                authenticated=False,
                tenant_authorized=False,
                audit_event=audit_evt,
                execution_permitted=False,
                status="REJECTED",
                reason=f"Sender status '{sender_node.status.value}' inactive.",
                provenance={"stage": "SENDER_STATUS_INACTIVE"},
                processed_at=now_iso
            )

        if not self.trust_registry.is_node_trusted(sender_node.node_id, minimum_tier=TrustTier.VERIFIED):
            audit_evt = FederatedChitraAuditService.create_rejection_audit_event(
                incoming_message=incoming_message,
                local_identity=self.local_identity,
                local_tenant_id=local_tenant_id,
                rejection_reason=f"Sender node '{incoming_message.source_node_id}' has insufficient trust tier '{sender_node.trust_tier.value}'.",
                prev_event_hash=prev_audit_hash,
                secret_key=secret_key
            )
            return FederationIngressResult(
                message_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                payload_type=incoming_message.payload_type,
                replay_verdict=replay_verdict,
                authenticated=False,
                tenant_authorized=False,
                audit_event=audit_evt,
                execution_permitted=False,
                status="REJECTED",
                reason=f"Sender trust tier '{sender_node.trust_tier.value}' insufficient.",
                provenance={"stage": "TRUST_TIER_INSUFFICIENT"},
                processed_at=now_iso
            )

        # -------------------------------------------------------------
        # STEP 3: CRYPTOGRAPHIC SIGNATURE VERIFICATION (§18.1 / Phase 18A)
        # -------------------------------------------------------------
        is_sig_valid = NodeIdentityManager.verify_message_signature(
            public_key_hex=sender_node.public_key,
            message=incoming_message
        )
        if not is_sig_valid:
            audit_evt = FederatedChitraAuditService.create_rejection_audit_event(
                incoming_message=incoming_message,
                local_identity=self.local_identity,
                local_tenant_id=local_tenant_id,
                rejection_reason="Cryptographic ECDSA signature verification failed.",
                prev_event_hash=prev_audit_hash,
                secret_key=secret_key
            )
            return FederationIngressResult(
                message_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                payload_type=incoming_message.payload_type,
                replay_verdict=replay_verdict,
                authenticated=False,
                tenant_authorized=False,
                audit_event=audit_evt,
                execution_permitted=False,
                status="REJECTED",
                reason="Signature verification failed.",
                provenance={"stage": "SIGNATURE_VERIFICATION_FAIL"},
                processed_at=now_iso
            )

        # -------------------------------------------------------------
        # STEP 4: TARGET GATE & TENANT ISOLATION (§18.3, §18.5 / Phase 18C, 18E)
        # -------------------------------------------------------------
        if incoming_message.target_node_id != self.local_identity.node_id:
            audit_evt = FederatedChitraAuditService.create_rejection_audit_event(
                incoming_message=incoming_message,
                local_identity=self.local_identity,
                local_tenant_id=local_tenant_id,
                rejection_reason=f"Target node mismatch: message targeted to '{incoming_message.target_node_id}', local node is '{self.local_identity.node_id}'.",
                prev_event_hash=prev_audit_hash,
                secret_key=secret_key
            )
            return FederationIngressResult(
                message_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                payload_type=incoming_message.payload_type,
                replay_verdict=replay_verdict,
                authenticated=True,
                tenant_authorized=False,
                audit_event=audit_evt,
                execution_permitted=False,
                status="BLOCKED",
                reason="Target node mismatch. Multi-node relaying rejected.",
                provenance={"stage": "TARGET_NODE_MISMATCH"},
                processed_at=now_iso
            )

        allowed_tenants = incoming_message.payload.get("allowed_target_tenants", [incoming_message.tenant_id])
        if incoming_message.tenant_id != local_tenant_id and local_tenant_id not in allowed_tenants:
            audit_evt = FederatedChitraAuditService.create_rejection_audit_event(
                incoming_message=incoming_message,
                local_identity=self.local_identity,
                local_tenant_id=local_tenant_id,
                rejection_reason=f"Cross-tenant access denied: origin tenant '{incoming_message.tenant_id}' not authorized for local tenant '{local_tenant_id}'.",
                prev_event_hash=prev_audit_hash,
                secret_key=secret_key
            )
            return FederationIngressResult(
                message_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                payload_type=incoming_message.payload_type,
                replay_verdict=replay_verdict,
                authenticated=True,
                tenant_authorized=False,
                audit_event=audit_evt,
                execution_permitted=False,
                status="DENIED",
                reason="Cross-tenant isolation policy rejected request.",
                provenance={"stage": "TENANT_ISOLATION_DENIED"},
                processed_at=now_iso
            )

        # -------------------------------------------------------------
        # STEP 5, 6, 7: PAYLOAD ROUTING & CONTEXTUAL PROCESSING
        # -------------------------------------------------------------
        governance_verdict: Optional[FederatedGovernanceVerdict] = None
        sync_result: Optional[Dict[str, Any]] = None
        handshake_result: Optional[Dict[str, Any]] = None
        final_status = "ACCEPTED"
        final_reason = "Message successfully ingested."

        if incoming_message.payload_type == FederationPayloadType.TASK_DISPATCH:
            # Route to Phase 18E Federated Governance Engine
            governance_verdict = FederatedGovernanceEngine.evaluate_remote_action(
                local_identity=self.local_identity,
                trust_registry=self.trust_registry,
                incoming_message=incoming_message,
                local_tenant_id=local_tenant_id
            )
            final_status = governance_verdict.overall_governance_decision.value
            final_reason = f"Governance evaluation verdict: {governance_verdict.maryada_justification}"

        elif incoming_message.payload_type in [FederationPayloadType.PATTERN_SYNC, FederationPayloadType.KNOWLEDGE_SYNC]:
            # Route to Phase 18C Federated Sync Service
            sync_valid, sync_reason, sync_rec = FederatedSyncService.verify_and_ingest_sync_message(
                local_identity=self.local_identity,
                trust_registry=self.trust_registry,
                incoming_message=incoming_message,
                local_tenant_id=local_tenant_id,
                sync_store=self.sync_store
            )
            if not sync_valid:
                final_status = "REJECTED"
                final_reason = sync_reason
            else:
                sync_result = sync_rec

        elif incoming_message.payload_type == FederationPayloadType.HANDSHAKE:
            # Route to Phase 18B Handshake Service
            hs_valid, hs_reason, resp_msg = NodeHandshakeService.verify_and_process_handshake(
                local_identity=self.local_identity,
                local_signing_key=self.local_signing_key,
                trust_registry=self.trust_registry,
                incoming_message=incoming_message,
                expected_tenant_id=local_tenant_id
            )
            if not hs_valid:
                final_status = "REJECTED"
                final_reason = hs_reason
            else:
                handshake_result = {
                    "handshake_status": "ACCEPTED",
                    "response_message_id": resp_msg.message_id if resp_msg else None,
                    "session_token": resp_msg.payload.get("session_token") if resp_msg else None
                }

        elif incoming_message.payload_type == FederationPayloadType.HEARTBEAT:
            final_status = "ACCEPTED"
            final_reason = "Heartbeat acknowledged."

        # -------------------------------------------------------------
        # STEP 8: CHITRA FEDERATION AUDIT CHAINING (§18.6 / Phase 18F)
        # -------------------------------------------------------------
        audit_evt = FederatedChitraAuditService.create_incoming_audit_event(
            incoming_message=incoming_message,
            local_identity=self.local_identity,
            local_tenant_id=local_tenant_id,
            prev_event_hash=prev_audit_hash,
            constitutional_verdict="passed" if final_status == "ACCEPTED" else "blocked",
            secret_key=secret_key
        )

        provenance = {
            "source_node_id": incoming_message.source_node_id,
            "source_tenant_id": incoming_message.tenant_id,
            "target_node_id": self.local_identity.node_id,
            "local_tenant_id": local_tenant_id,
            "federation_message_id": incoming_message.message_id,
            "audit_event_hash": audit_evt.this_event_hash,
            "origin_timestamp": incoming_message.timestamp
        }

        # -------------------------------------------------------------
        # STEP 9: UNIFIED GOVERNED RESPONSE (Non-execution invariant)
        # -------------------------------------------------------------
        return FederationIngressResult(
            message_id=incoming_message.message_id,
            source_node_id=incoming_message.source_node_id,
            target_node_id=incoming_message.target_node_id,
            tenant_id=incoming_message.tenant_id,
            payload_type=incoming_message.payload_type,
            replay_verdict=replay_verdict,
            authenticated=True,
            tenant_authorized=True,
            governance_verdict=governance_verdict,
            sync_result=sync_result,
            handshake_result=handshake_result,
            audit_event=audit_evt,
            execution_permitted=False,  # Invariant: Never automatically executed
            status=final_status,
            reason=final_reason,
            provenance=provenance,
            processed_at=now_iso
        )
