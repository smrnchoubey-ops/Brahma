"""
CROSS-NODE CONSTITUTIONAL GOVERNANCE & BLAST RADIUS (Whitesheet §18.5)
Enforces local authoritative MARYADA constitutional validation and MURPHY blast-radius risk
constraints on incoming federated remote-action requests.

Invariant: Remote nodes may request actions, but they can NEVER bypass or override
the receiving node's local constitutional governance.
"""
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from datetime import datetime, timezone
import secrets
from pydantic import BaseModel, Field

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
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.core.maryada.verdict import MaryadaVerdict, GateStatus, RiskTier
from app.core.murphy.blast_radius import MurphyBlastRadiusCalculator
from app.core.chitra.crypto import generate_ulid


class GovernanceDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"


class FederatedGovernanceVerdict(BaseModel):
    """
    Comprehensive result of local constitutional evaluation for a remote action request.
    """
    request_id: str
    source_node_id: str
    target_node_id: str
    tenant_id: str
    authenticated: bool
    tenant_authorized: bool
    maryada_approved: bool
    maryada_risk_tier: str
    maryada_justification: str
    murphy_blast_radius: float
    overall_governance_decision: GovernanceDecision
    execution_permitted: bool = False  # Invariant: Never auto-executed
    blast_radius_constrained: bool = True
    remote_claims: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FederatedGovernanceEngine:
    """
    Authoritative local governance engine for cross-node action requests.
    """

    @classmethod
    def create_remote_action_request(
        cls,
        source_identity: NodeIdentity,
        source_signing_key: SigningKey,
        target_node_id: str,
        tenant_id: str,
        action_name: str,
        action_payload: Optional[Dict[str, Any]] = None,
        allowed_target_tenants: Optional[List[str]] = None,
        claimed_governance: Optional[Dict[str, Any]] = None,
        provenance_metadata: Optional[Dict[str, Any]] = None
    ) -> FederationMessage:
        """
        Packages and cryptographically signs a TASK_DISPATCH FederationMessage requesting remote action execution.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required for remote action requests (AUTHENTICATED_TENANT_REQUIRED).")

        if not target_node_id or not target_node_id.strip():
            raise ValueError("target_node_id is required for remote action requests (FAIL-CLOSED).")

        if not action_name or not action_name.strip():
            raise ValueError("action_name cannot be empty (FAIL-CLOSED).")

        payload = {
            "action_name": action_name.strip(),
            "action_payload": action_payload or {},
            "allowed_target_tenants": allowed_target_tenants or [tenant_id],
            "claimed_governance": claimed_governance or {},
            "origin_node_id": source_identity.node_id,
            "origin_timestamp": datetime.now(timezone.utc).isoformat(),
            "provenance": provenance_metadata or {}
        }

        unsigned_msg = FederationMessage(
            message_id=generate_ulid(prefix="msg_req_act_"),
            source_node_id=source_identity.node_id,
            target_node_id=target_node_id.strip(),
            tenant_id=tenant_id.strip(),
            payload_type=FederationPayloadType.TASK_DISPATCH,
            payload=payload,
            nonce=secrets.token_hex(16)
        )

        return NodeIdentityManager.sign_message(source_signing_key, unsigned_msg)

    @classmethod
    def evaluate_remote_action(
        cls,
        local_identity: NodeIdentity,
        trust_registry: NodeTrustRegistry,
        incoming_message: FederationMessage,
        local_tenant_id: str,
        max_allowed_blast_radius: float = 0.80
    ) -> FederatedGovernanceVerdict:
        """
        Authoritatively evaluates an incoming remote action request:
        1. Authenticates cryptographic signature & NodeTrustRegistry status.
        2. Validates tenant scope (cross-tenant denied unless signed allow-list permits).
        3. Enforces single-hop target constraint (no uncontrolled multi-node fan-out).
        4. Evaluates action against local MARYADA constitutional rules (ignores remote claimed approvals).
        5. Evaluates quantitative blast radius via local MURPHY engine (ignores remote claimed risks).
        6. Preserves provenance while keeping execution_permitted = False (no auto-execution).
        """
        evaluated_at = datetime.now(timezone.utc).isoformat()
        remote_claims = incoming_message.payload.get("claimed_governance", {})
        provenance = {
            "source_node_id": incoming_message.source_node_id,
            "source_tenant_id": incoming_message.tenant_id,
            "origin_timestamp": incoming_message.payload.get("origin_timestamp"),
            "target_node_id": incoming_message.target_node_id,
            "evaluated_by_node": local_identity.node_id,
            "signature_verified": False
        }

        # -------------------------------------------------------------
        # 1. PROTOCOL & PAYLOAD INTEGRITY
        # -------------------------------------------------------------
        if incoming_message.payload_type != FederationPayloadType.TASK_DISPATCH:
            return FederatedGovernanceVerdict(
                request_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                authenticated=False,
                tenant_authorized=False,
                maryada_approved=False,
                maryada_risk_tier=RiskTier.UNKNOWN.value,
                maryada_justification="Invalid payload type: expected TASK_DISPATCH.",
                murphy_blast_radius=1.0,
                overall_governance_decision=GovernanceDecision.REJECTED,
                remote_claims=remote_claims,
                provenance=provenance,
                evaluated_at=evaluated_at
            )

        # -------------------------------------------------------------
        # 2. SENDER AUTHENTICATION & TRUST MATRIX (§18.1, §18.2)
        # -------------------------------------------------------------
        sender_node = trust_registry.get_node(incoming_message.source_node_id)
        if not sender_node:
            return FederatedGovernanceVerdict(
                request_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                authenticated=False,
                tenant_authorized=False,
                maryada_approved=False,
                maryada_risk_tier=RiskTier.UNKNOWN.value,
                maryada_justification=f"Unknown sender node '{incoming_message.source_node_id}' not found in TrustRegistry.",
                murphy_blast_radius=1.0,
                overall_governance_decision=GovernanceDecision.REJECTED,
                remote_claims=remote_claims,
                provenance=provenance,
                evaluated_at=evaluated_at
            )

        if sender_node.status != NodeStatus.ACTIVE:
            return FederatedGovernanceVerdict(
                request_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                authenticated=False,
                tenant_authorized=False,
                maryada_approved=False,
                maryada_risk_tier=RiskTier.UNKNOWN.value,
                maryada_justification=f"Sender node '{incoming_message.source_node_id}' is in inactive state '{sender_node.status.value}'.",
                murphy_blast_radius=1.0,
                overall_governance_decision=GovernanceDecision.REJECTED,
                remote_claims=remote_claims,
                provenance=provenance,
                evaluated_at=evaluated_at
            )

        if not trust_registry.is_node_trusted(sender_node.node_id, minimum_tier=TrustTier.VERIFIED):
            return FederatedGovernanceVerdict(
                request_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                authenticated=False,
                tenant_authorized=False,
                maryada_approved=False,
                maryada_risk_tier=RiskTier.UNKNOWN.value,
                maryada_justification=f"Sender node '{incoming_message.source_node_id}' has insufficient trust tier '{sender_node.trust_tier.value}'.",
                murphy_blast_radius=1.0,
                overall_governance_decision=GovernanceDecision.REJECTED,
                remote_claims=remote_claims,
                provenance=provenance,
                evaluated_at=evaluated_at
            )

        # Cryptographic signature validation
        is_sig_valid = NodeIdentityManager.verify_message_signature(
            public_key_hex=sender_node.public_key,
            message=incoming_message
        )
        if not is_sig_valid:
            return FederatedGovernanceVerdict(
                request_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                authenticated=False,
                tenant_authorized=False,
                maryada_approved=False,
                maryada_risk_tier=RiskTier.UNKNOWN.value,
                maryada_justification="Cryptographic signature verification failed.",
                murphy_blast_radius=1.0,
                overall_governance_decision=GovernanceDecision.REJECTED,
                remote_claims=remote_claims,
                provenance=provenance,
                evaluated_at=evaluated_at
            )

        provenance["signature_verified"] = True

        # -------------------------------------------------------------
        # 3. TARGET NODE & BLAST-RADIUS CONTAINMENT (§18.5)
        # -------------------------------------------------------------
        # Strictly rejects multi-node relay / fan-out
        if incoming_message.target_node_id != local_identity.node_id:
            return FederatedGovernanceVerdict(
                request_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                authenticated=True,
                tenant_authorized=False,
                maryada_approved=False,
                maryada_risk_tier=RiskTier.UNKNOWN.value,
                maryada_justification=f"Target node mismatch: message target '{incoming_message.target_node_id}' != local node '{local_identity.node_id}'. Multi-node fan-out rejected.",
                murphy_blast_radius=1.0,
                overall_governance_decision=GovernanceDecision.BLOCKED,
                blast_radius_constrained=True,
                remote_claims=remote_claims,
                provenance=provenance,
                evaluated_at=evaluated_at
            )

        # -------------------------------------------------------------
        # 4. TENANT ISOLATION (§18.5)
        # -------------------------------------------------------------
        allowed_targets = incoming_message.payload.get("allowed_target_tenants", [incoming_message.tenant_id])
        if incoming_message.tenant_id != local_tenant_id and local_tenant_id not in allowed_targets:
            return FederatedGovernanceVerdict(
                request_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                authenticated=True,
                tenant_authorized=False,
                maryada_approved=False,
                maryada_risk_tier=RiskTier.UNKNOWN.value,
                maryada_justification=f"Cross-tenant action rejected. Origin tenant '{incoming_message.tenant_id}' not authorized for local tenant '{local_tenant_id}'.",
                murphy_blast_radius=1.0,
                overall_governance_decision=GovernanceDecision.DENIED,
                remote_claims=remote_claims,
                provenance=provenance,
                evaluated_at=evaluated_at
            )

        # -------------------------------------------------------------
        # 5. ACTION EXTRACTION & LOCAL MARYADA EVALUATION
        # -------------------------------------------------------------
        action_name = incoming_message.payload.get("action_name")
        if not action_name or not isinstance(action_name, str) or not action_name.strip():
            return FederatedGovernanceVerdict(
                request_id=incoming_message.message_id,
                source_node_id=incoming_message.source_node_id,
                target_node_id=incoming_message.target_node_id,
                tenant_id=incoming_message.tenant_id,
                authenticated=True,
                tenant_authorized=True,
                maryada_approved=False,
                maryada_risk_tier=RiskTier.UNKNOWN.value,
                maryada_justification="Malformed action: missing or empty action_name.",
                murphy_blast_radius=1.0,
                overall_governance_decision=GovernanceDecision.BLOCKED,
                remote_claims=remote_claims,
                provenance=provenance,
                evaluated_at=evaluated_at
            )

        # Map sender trust tier to appropriate caller authority tier
        from app.core.maryada.verdict import AuthorityTier
        tier_to_authority = {
            TrustTier.UNTRUSTED: AuthorityTier.LOW.value,
            TrustTier.VERIFIED: AuthorityTier.MEDIUM.value,
            TrustTier.FEDERATED: AuthorityTier.HIGH.value,
            TrustTier.SOVEREIGN: AuthorityTier.CRITICAL.value,
        }
        caller_auth = tier_to_authority.get(sender_node.trust_tier, AuthorityTier.MEDIUM.value)

        # Local MARYADA evaluation: Remote claims are strictly IGNORED
        maryada_verdict: MaryadaVerdict = MaryadaGatekeeper.evaluate_action_gate(
            action=action_name,
            caller_authority=caller_auth,
            tenant_id=local_tenant_id
        )

        # -------------------------------------------------------------
        # 6. LOCAL MURPHY BLAST-RADIUS EVALUATION
        # -------------------------------------------------------------
        blast_radius_score = MurphyBlastRadiusCalculator.calculate_action_score(action_name)

        # -------------------------------------------------------------
        # 7. OVERALL GOVERNANCE DECISION
        # -------------------------------------------------------------
        if not maryada_verdict.approved or maryada_verdict.status != GateStatus.APPROVED:
            overall_decision = GovernanceDecision.DENIED
        elif blast_radius_score > max_allowed_blast_radius:
            overall_decision = GovernanceDecision.BLOCKED
        else:
            overall_decision = GovernanceDecision.APPROVED

        return FederatedGovernanceVerdict(
            request_id=incoming_message.message_id,
            source_node_id=incoming_message.source_node_id,
            target_node_id=incoming_message.target_node_id,
            tenant_id=incoming_message.tenant_id,
            authenticated=True,
            tenant_authorized=True,
            maryada_approved=maryada_verdict.approved,
            maryada_risk_tier=maryada_verdict.risk_tier.value,
            maryada_justification=maryada_verdict.justification,
            murphy_blast_radius=blast_radius_score,
            overall_governance_decision=overall_decision,
            execution_permitted=False,  # Invariant: Never automatically executed
            blast_radius_constrained=True,
            remote_claims=remote_claims,
            provenance=provenance,
            evaluated_at=evaluated_at
        )
