"""
MANUSH REST API Endpoints: Human Oversight & Review Resolution
Conforms to BRAHMA COS Whitesheet §12.1, §12.3, §12.4, §13.4, CA-006 & §20.7.

Provides tenant-isolated review inspection, dual-authorization submission,
fail-closed plan reconstruction, authority token propagation, and automated
execution resumption for AMEND/APPROVE/REJECT decisions.
"""
from typing import Dict, Any, Optional, List, Union
import json
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.task import Task
from app.core.tenant import TenantContext, get_current_tenant
from app.core.manush.decision import (
    ReviewItem,
    ReviewStatus,
    ReviewDecisionType,
    HumanReviewDecision
)
from app.core.manush.service import ManushOversightService, manush_service
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.maryada.token import AuthorityToken

router = APIRouter(prefix="/api/manush", tags=["MANUSH Human Oversight"])


class ResolveReviewRequest(BaseModel):
    decision: ReviewDecisionType
    reviewer_id: str
    justification: str
    signature: str
    amended_action: Optional[str] = None
    amended_parameters: Optional[Dict[str, Any]] = None
    delegate_id: Optional[str] = None
    delegated_scope: Optional[List[str]] = None
    delegated_authority_tier: Optional[str] = None
    delegation_expiry: Optional[str] = None
    authority_token: Optional[Union[str, Dict[str, Any]]] = None


class ExecuteDelegatedRequest(BaseModel):
    delegate_id: str
    authority_token: Optional[Union[str, Dict[str, Any]]] = None


def reconstruct_plan_from_task(task: Task, expected_task_id: Optional[int] = None) -> Optional[KarmaPlanDAG]:
    """
    Reconstructs the persisted task.plan from PostgreSQL into a valid KarmaPlanDAG.
    Strictly fail-closed: rejects malformed plans, missing steps, missing fields, or task_id mismatches.
    """
    if not task or not task.plan:
        return None

    if expected_task_id is not None and task.id != expected_task_id:
        return None

    raw_plan = task.plan
    if isinstance(raw_plan, str):
        try:
            raw_plan = json.loads(raw_plan)
        except Exception:
            return None

    if not isinstance(raw_plan, dict):
        return None

    # Verify task_id matching if specified in raw_plan
    plan_task_id = raw_plan.get("task_id")
    if plan_task_id is not None and plan_task_id != task.id:
        return None

    # If already a valid KarmaPlanDAG schema, validate through Pydantic
    if "steps" in raw_plan and "summary" in raw_plan and "task_id" in raw_plan:
        try:
            dag = KarmaPlanDAG.model_validate(raw_plan)
            if dag.task_id != task.id:
                return None
            return dag
        except Exception:
            return None

    # Step-by-step strict validation (fail-closed on any missing required field)
    steps_data = raw_plan.get("steps")
    if not isinstance(steps_data, list) or len(steps_data) == 0:
        return None

    karma_steps = []
    for s in steps_data:
        if not isinstance(s, dict):
            return None
        s_id = s.get("step_id") or s.get("id")
        action = s.get("action") or s.get("description")
        exp_out = s.get("expected_outcome") or s.get("expected_result")

        # Required fields must exist and be non-empty strings
        if not s_id or not isinstance(s_id, str) or not s_id.strip():
            return None
        if not action or not isinstance(action, str) or not action.strip():
            return None
        if not exp_out or not isinstance(exp_out, str) or not exp_out.strip():
            return None

        deps = s.get("dependencies", [])
        if not isinstance(deps, list):
            return None

        params = s.get("parameters")
        if params is not None and not isinstance(params, dict):
            return None

        step_obj = KarmaStep(
            step_id=s_id.strip(),
            action=action.strip(),
            expected_outcome=exp_out.strip(),
            dependencies=[str(d).strip() for d in deps],
            authority_required=s.get("authority_required", "LOW")
        )
        if params:
            step_obj.__dict__["parameters"] = params
        karma_steps.append(step_obj)

    summary = raw_plan.get("summary") or task.title
    if not summary or not isinstance(summary, str) or not summary.strip():
        return None

    try:
        return KarmaPlanDAG(
            task_id=task.id,
            summary=summary.strip(),
            steps=karma_steps
        )
    except Exception:
        return None


@router.get("/reviews", response_model=List[Dict[str, Any]])
def list_reviews(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Lists all pending review items for the authenticated tenant.
    """
    items = manush_service.queue.list_pending_items(tenant_id=tenant.tenant_id)
    return [item.model_dump() for item in items]


@router.get("/reviews/{review_id}", response_model=Dict[str, Any])
def get_review(
    review_id: str,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Retrieves a single review item scoped to the authenticated tenant.
    """
    item = manush_service.queue.get_item(review_id=review_id, tenant_id=tenant.tenant_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review item '{review_id}' not found."
        )
    return item.model_dump()


@router.post("/reviews/{review_id}/resolve", response_model=Dict[str, Any])
def resolve_review_endpoint(
    review_id: str,
    request: ResolveReviewRequest,
    req: Request,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant),
    x_authority_token: Optional[str] = Header(None, alias="X-Authority-Token")
):
    """
    Resolves an escalated human review item with APPROVE, REJECT, AMEND, TERMINATE, or DELEGATE verdict.
    Enforces strict tenant isolation, loads the persisted task plan from PostgreSQL,
    propagates caller authority token, and invokes ManushOversightService.resolve_review().
    """
    item = manush_service.queue.get_item(review_id=review_id, tenant_id=tenant.tenant_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review item '{review_id}' not found."
        )

    # Tenant-isolated task query from PostgreSQL
    task = db.query(Task).filter(Task.id == item.task_id, Task.user_id == tenant.user_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {item.task_id} not found."
        )

    # Reconstruct the SAME paused plan from PostgreSQL with strict task_id binding
    plan = reconstruct_plan_from_task(task, expected_task_id=item.task_id)

    # Authority propagation (§13.4)
    caller_auth: Union[str, AuthorityToken, Dict[str, Any]] = "LOW"
    raw_tok = request.authority_token or x_authority_token
    if raw_tok:
        if isinstance(raw_tok, dict):
            try:
                caller_auth = AuthorityToken(**raw_tok)
            except Exception:
                caller_auth = raw_tok
        elif isinstance(raw_tok, str) and (raw_tok.startswith("ey") or "{" in raw_tok):
            try:
                caller_auth = AuthorityToken.decode(raw_tok)
            except Exception:
                caller_auth = raw_tok
        else:
            caller_auth = raw_tok
    else:
        if "admin" in tenant.roles or "secops" in tenant.roles:
            caller_auth = "HIGH"

    decision_obj = HumanReviewDecision(
        reviewer_id=request.reviewer_id,
        decision=request.decision,
        justification=request.justification,
        signature=request.signature,
        amended_action=request.amended_action,
        amended_parameters=request.amended_parameters,
        delegate_id=request.delegate_id,
        delegated_scope=request.delegated_scope,
        delegated_authority_tier=request.delegated_authority_tier,
        delegation_expiry=request.delegation_expiry
    )

    success, updated_item, message = manush_service.resolve_review(
        review_id=review_id,
        tenant_id=tenant.tenant_id,
        decision=decision_obj,
        plan=plan,
        caller_authority=caller_auth,
        db_session=db,
        user_id=tenant.user_id
    )

    if not success:
        return {
            "success": False,
            "review_id": review_id,
            "status": updated_item.status.value if updated_item else item.status.value,
            "message": message,
            "task_id": item.task_id
        }

    return {
        "success": True,
        "review_id": review_id,
        "status": updated_item.status.value,
        "message": message,
        "task_id": item.task_id
    }


@router.post("/reviews/{review_id}/execute-delegated", response_model=Dict[str, Any])
def execute_delegated_endpoint(
    review_id: str,
    request: ExecuteDelegatedRequest,
    req: Request,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant),
    x_authority_token: Optional[str] = Header(None, alias="X-Authority-Token")
):
    """
    Executes a delegated action by the verified delegate actor (§12.1, CA-006).
    Enforces tenant isolation, loads persisted task plan, verifies delegate authority,
    evaluates MARYADA constitutional gate, and executes via KARMA.
    """
    item = manush_service.queue.get_item(review_id=review_id, tenant_id=tenant.tenant_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review item '{review_id}' not found."
        )

    task = db.query(Task).filter(Task.id == item.task_id, Task.user_id == tenant.user_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {item.task_id} not found."
        )

    plan = reconstruct_plan_from_task(task, expected_task_id=item.task_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to reconstruct execution plan for task {item.task_id}."
        )

    # 1. Authoritative Identity Binding: verify authenticated tenant identity matches requested delegate_id
    if request.delegate_id != tenant.username and request.delegate_id != f"user_{tenant.user_id}":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Authenticated identity '{tenant.username}' does not match delegate_id '{request.delegate_id}'."
        )

    # 2. Mandatory §13.4 AuthorityToken extraction (no unsigned LOW fallback)
    raw_tok = request.authority_token or x_authority_token
    if not raw_tok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing mandatory §13.4 AuthorityToken for delegated execution."
        )

    try:
        if isinstance(raw_tok, dict):
            caller_auth = AuthorityToken(**raw_tok)
        elif isinstance(raw_tok, str):
            caller_auth = AuthorityToken.decode(raw_tok)
        elif isinstance(raw_tok, AuthorityToken):
            caller_auth = raw_tok
        else:
            raise ValueError("Unsupported token format")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid AuthorityToken: {e}"
        )

    success, report, message = manush_service.execute_delegated_review(
        review_id=review_id,
        tenant_id=tenant.tenant_id,
        delegate_id=request.delegate_id,
        plan=plan,
        caller_authority=caller_auth,
        db_session=db,
        user_id=tenant.user_id
    )

    if not success:
        return {
            "success": False,
            "review_id": review_id,
            "status": item.status.value,
            "message": message,
            "task_id": item.task_id
        }

    return {
        "success": True,
        "review_id": review_id,
        "status": item.status.value,
        "message": message,
        "task_id": item.task_id
    }

