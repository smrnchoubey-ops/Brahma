"""
MANUSH Multi-Tenant Human Review Queue & State Engine
Strictly conforms to BRAHMA COS Whitesheet §12.1 & §12.3.

Manages review items, state transitions (PENDING_REVIEW -> APPROVED_BY_HUMAN / REJECTED_BY_HUMAN / TIMEOUT_EXPIRED),
multi-tenant partitioning, and fail-closed TTL expiration.
"""
from typing import Dict, Any, Optional, List, Tuple
import threading
from datetime import datetime, timezone, timedelta

from app.core.manush.decision import ReviewItem, ReviewStatus, HumanReviewDecision, ReviewDecisionType
from app.core.manush.dual_auth import DualAuthValidator
from app.core.chitra.crypto import generate_ulid


class ManushReviewQueue:
    """
    Thread-safe, multi-tenant human oversight review queue.
    """
    def __init__(self, default_ttl_seconds: int = 3600):
        self._items: Dict[str, ReviewItem] = {}
        self._default_ttl = default_ttl_seconds
        self._lock = threading.Lock()

    def enqueue_review(
        self,
        task_id: int,
        tenant_id: str,
        action_summary: str,
        step_id: Optional[str] = None,
        risk_tier: str = "HIGH",
        requires_dual_auth: bool = False,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ReviewItem:
        """
        Enqueues an action or task for human review.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Authenticated Tenant ID is required to enqueue human review.")

        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=ttl)).isoformat()

        review_id = generate_ulid(prefix="rev_")
        orig_params = metadata.get("parameters") if metadata and isinstance(metadata.get("parameters"), dict) else None
        item = ReviewItem(
            review_id=review_id,
            task_id=task_id,
            tenant_id=tenant_id,
            step_id=step_id,
            action_summary=action_summary,
            original_action=action_summary,
            original_parameters=orig_params,
            risk_tier=risk_tier,
            requires_dual_auth=requires_dual_auth,
            status=ReviewStatus.PENDING_REVIEW,
            created_at=now.isoformat(),
            expires_at=expires_at,
            metadata=metadata or {}
        )

        with self._lock:
            self._items[review_id] = item

        return item

    def get_item(self, review_id: str, tenant_id: str) -> Optional[ReviewItem]:
        """
        Retrieves a review item scoped to tenant_id.
        """
        with self._lock:
            item = self._items.get(review_id)
            if item and (item.tenant_id == tenant_id or tenant_id == "global"):
                self._check_timeout(item)
                return item
            return None

    def list_pending_items(self, tenant_id: str) -> List[ReviewItem]:
        """
        Lists all pending review items for a tenant.
        """
        with self._lock:
            results: List[ReviewItem] = []
            for item in self._items.values():
                if item.tenant_id == tenant_id or tenant_id == "global":
                    self._check_timeout(item)
                    if item.status == ReviewStatus.PENDING_REVIEW:
                        results.append(item)
            return results

    def submit_decision(
        self,
        review_id: str,
        tenant_id: str,
        decision: HumanReviewDecision
    ) -> Tuple[bool, ReviewItem, str]:
        """
        Submits an operator review decision and evaluates item resolution.
        Returns (success: bool, updated_item: ReviewItem, message: str).
        """
        with self._lock:
            item = self._items.get(review_id)
            if not item or (item.tenant_id != tenant_id and tenant_id != "global"):
                return False, item, f"Review item '{review_id}' not found for tenant."

            self._check_timeout(item)

            if item.status != ReviewStatus.PENDING_REVIEW:
                return False, item, f"Review item '{review_id}' is already finalized with status '{item.status.value}'."

            if not DualAuthValidator.validate_signature(decision):
                return False, item, "Invalid reviewer signature or missing reviewer credentials."

            if not decision.justification or not decision.justification.strip():
                return False, item, "Missing justification for human review decision."

            # AMEND (§12.1)
            if decision.decision == ReviewDecisionType.AMEND:
                has_action = bool(decision.amended_action and decision.amended_action.strip())
                has_params = bool(decision.amended_parameters is not None and len(decision.amended_parameters) > 0)
                if not has_action and not has_params:
                    return False, item, "Invalid amendment: amended action or parameters must be provided."

                item.original_action = item.original_action or item.action_summary
                item.amended_action = decision.amended_action.strip() if has_action else item.original_action
                item.amended_parameters = decision.amended_parameters if has_params else (item.original_parameters or {})
                item.action_summary = item.amended_action
                item.amendments.append(decision)
                item.status = ReviewStatus.AMENDED_BY_HUMAN
                item.final_justification = f"Amended: {decision.justification}"
                return True, item, f"Review '{review_id}' amended by operator '{decision.reviewer_id}'."

            # TERMINATE (§12.1)
            if decision.decision == ReviewDecisionType.TERMINATE:
                item.terminations.append(decision)
                item.status = ReviewStatus.TERMINATED_BY_HUMAN
                item.final_justification = f"Terminated: {decision.justification}"
                return True, item, f"Review '{review_id}' terminated by operator '{decision.reviewer_id}'."

            # DELEGATE (§12.1)
            if decision.decision == ReviewDecisionType.DELEGATE:
                if not decision.delegate_id or not decision.delegate_id.strip():
                    return False, item, "Missing delegate_id for DELEGATE decision."

                if decision.delegation_expiry:
                    try:
                        exp_dt = datetime.fromisoformat(decision.delegation_expiry)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) > exp_dt:
                            return False, item, "Delegation expiry cannot be in the past."
                    except Exception as e:
                        return False, item, f"Invalid delegation_expiry format: {e}"

                item.delegate_id = decision.delegate_id.strip()
                item.delegated_scope = decision.delegated_scope if decision.delegated_scope is not None else ["*"]
                item.delegated_authority_tier = decision.delegated_authority_tier
                item.delegation_expiry = decision.delegation_expiry
                item.delegations.append(decision)
                item.status = ReviewStatus.DELEGATED_BY_HUMAN
                item.final_justification = f"Delegated to {item.delegate_id}: {decision.justification}"
                return True, item, f"Review '{review_id}' delegated to '{item.delegate_id}' by operator '{decision.reviewer_id}'."

            # Check for duplicate submission by the same operator
            if any(app.reviewer_id == decision.reviewer_id for app in item.approvals):
                return False, item, f"Operator '{decision.reviewer_id}' has already submitted approval."

            if decision.decision == ReviewDecisionType.REJECT:
                item.rejections.append(decision)
                item.status = ReviewStatus.REJECTED_BY_HUMAN
                item.final_justification = f"Rejected: {decision.justification}"
                return True, item, f"Review '{review_id}' rejected by operator '{decision.reviewer_id}'."


            # APPROVE
            item.approvals.append(decision)
            is_ready, reason = DualAuthValidator.evaluate_item_readiness(item)

            if is_ready:
                item.status = ReviewStatus.APPROVED_BY_HUMAN
                item.final_justification = reason
                return True, item, f"Review '{review_id}' approved: {reason}"
            else:
                return True, item, f"Approval recorded ({reason}). Awaiting additional authorizations."

    def _check_timeout(self, item: ReviewItem) -> None:
        """
        Checks if item has expired and applies fail-closed timeout status (§12.3).
        """
        if item.status == ReviewStatus.PENDING_REVIEW and item.expires_at:
            now = datetime.now(timezone.utc)
            exp = datetime.fromisoformat(item.expires_at)
            if now > exp:
                item.status = ReviewStatus.TIMEOUT_EXPIRED
                item.final_justification = "Review request timed out without required human authorization (fail-closed)."

    def clear(self) -> None:
        """Clears queue (for test isolation)."""
        with self._lock:
            self._items.clear()
