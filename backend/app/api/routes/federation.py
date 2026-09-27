"""
FEDERATION HTTP TRANSPORT ROUTER (Whitesheet §18 & §23 Phase 4 - Gap #9)
Exposes minimal HTTP wire endpoints for inter-instance Federation messaging and identity discovery.
All inbound messages strictly pass through the 9-step FederationPipelineCoordinator.
"""
import logging
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.federation.models import FederationMessage, NodeIdentity
from app.core.federation.orchestrator import FederationIngressResult
from app.core.federation.runtime import get_federation_runtime

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/identity", response_model=NodeIdentity)
def get_local_node_identity() -> NodeIdentity:
    """
    Returns the public cryptographic NodeIdentity of this BRAHMA instance (§18.1).
    Private keys are strictly excluded.
    """
    runtime = get_federation_runtime()
    return runtime.local_identity


@router.get("/peers", response_model=List[NodeIdentity])
def list_registered_peers(db: Session = Depends(get_db)) -> List[NodeIdentity]:
    """
    Lists all peer nodes registered in the local Federation Trust Registry (§18.1, §18.3).
    """
    runtime = get_federation_runtime()
    return runtime.trust_registry.list_nodes(db_session=db)


@router.post("/messages", response_model=FederationIngressResult)
def receive_federation_message(
    message: FederationMessage
) -> FederationIngressResult:
    """
    Authoritative HTTP wire ingress endpoint for Federation messages (§18.2 - §18.6).
    Processes incoming message through the complete 9-step pipeline:
    Replay Guard -> Peer Identity & Trust -> Signature Verification -> Tenant Gate ->
    Payload Routing (Handshake / Sync / Heartbeat) -> Governance -> CHITRA Audit.
    """
    runtime = get_federation_runtime()
    try:
        ingress_result = runtime.coordinator.process_incoming_message(
            incoming_message=message,
            local_tenant_id=runtime.local_identity.tenant_id or "tenant_global"
        )
        return ingress_result
    except Exception as e:
        logger.error(f"Unhandled exception during federation message ingress: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Federation message processing failed: {str(e)}"
        )
