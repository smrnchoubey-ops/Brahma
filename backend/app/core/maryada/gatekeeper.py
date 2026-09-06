"""
MARYADA Dynamic Gatekeeper & Governance Orchestrator
Strictly conforms to BRAHMA COS Whitesheet §§10.0–10.6.

Orchestrates constitutional invariant enforcement, authority matrix evaluation,
risk tier synthesis, fail-closed handling, tenant-scoped governance, and CHITRA
gate audit integration.
"""
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from sqlalchemy.orm import Session

from app.core.maryada.verdict import MaryadaVerdict, AuthorityTier, RiskTier, GateStatus
from app.core.maryada.invariants import MaryadaConstitutionalEvaluator
from app.core.maryada.authority_matrix import MaryadaAuthorityMatrix
from app.core.maryada.token import AuthorityToken
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.repositories.chitra_repository import chitra_repository


class MaryadaGatekeeper:
    """
    Evaluates actions, plans, and intents prior to execution.
    Enforces fail-closed semantics on any invariant violation or authority deficit.
    """

    @classmethod
    def evaluate_action_gate(
        cls,
        action: str,
        caller_authority: Optional[Union[str, AuthorityToken, Dict[str, Any]]] = None,
        declared_authority: Optional[str] = None,
        tool_tier: Optional[str] = None,
        authority_token: Optional[Union[str, AuthorityToken, Dict[str, Any]]] = None,
        tenant_id: str = "global",
        upstream_errors: Optional[List[str]] = None,
        reported_risk: Optional[str] = None,
        db_session: Optional[Session] = None,
        task_id: Optional[int] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        tenant_custom_rules: Optional[Dict[str, Any]] = None,
        require_signed_token: bool = False,
        secret_key: Optional[bytes] = None,
        current_time: Optional[datetime] = None
    ) -> MaryadaVerdict:
        """
        Comprehensive pre-flight evaluation of a single action or tool call.
        """
        auth_repr: Optional[str] = None
        if isinstance(caller_authority, AuthorityToken):
            auth_repr = f"{caller_authority.tier.value}:{caller_authority.token_id}"
        elif isinstance(authority_token, AuthorityToken):
            auth_repr = f"{authority_token.tier.value}:{authority_token.token_id}"
        elif caller_authority:
            auth_repr = str(caller_authority)
        # -------------------------------------------------------------
        # 1. Fail-Closed on Upstream Errors or Missing Input (§10.3)
        # -------------------------------------------------------------
        if upstream_errors and len(upstream_errors) > 0:
            return cls._finalize_verdict(
                verdict=MaryadaVerdict(
                    approved=False,
                    status=GateStatus.BLOCKED,
                    risk_tier=RiskTier.UNKNOWN,
                    authority_required=AuthorityTier.HIGH,
                    caller_authority=auth_repr,
                    requires_human=False,
                    justification=f"Fail-closed: upstream errors detected: {', '.join(upstream_errors)}"
                ),
                action=action, db_session=db_session, task_id=task_id, user_id=user_id, session_id=session_id
            )

        if not action or not action.strip():
            return cls._finalize_verdict(
                verdict=MaryadaVerdict(
                    approved=False,
                    status=GateStatus.BLOCKED,
                    risk_tier=RiskTier.UNKNOWN,
                    authority_required=AuthorityTier.HIGH,
                    caller_authority=auth_repr,
                    requires_human=False,
                    justification="Fail-closed: action description is null or empty."
                ),
                action="<EMPTY_ACTION>", db_session=db_session, task_id=task_id, user_id=user_id, session_id=session_id
            )

        # -------------------------------------------------------------
        # 2. Constitutional Invariant Checks (§10.2)
        # -------------------------------------------------------------
        is_const_ok, violated_invs, reasons = MaryadaConstitutionalEvaluator.evaluate(
            action_or_intent=action,
            tenant_id=tenant_id
        )

        if not is_const_ok:
            return cls._finalize_verdict(
                verdict=MaryadaVerdict(
                    approved=False,
                    status=GateStatus.BLOCKED,
                    risk_tier=RiskTier.CRITICAL,
                    authority_required=AuthorityTier.CRITICAL,
                    caller_authority=auth_repr,
                    requires_human=False,
                    justification=f"Constitutional block: {'; '.join(reasons)}",
                    violated_invariants=violated_invs
                ),
                action=action, db_session=db_session, task_id=task_id, user_id=user_id, session_id=session_id
            )

        # -------------------------------------------------------------
        # 3. Four-Tier Authority Matrix Evaluation (§10.1 & §13.4)
        # -------------------------------------------------------------
        is_auth, req_tier, risk_tier, req_human, auth_reason = MaryadaAuthorityMatrix.evaluate_authority(
            action_name=action,
            declared_tier=declared_authority,
            caller_authority=caller_authority,
            tool_tier=tool_tier,
            authority_token=authority_token,
            expected_tenant_id=tenant_id,
            require_signed_token=require_signed_token,
            secret_key=secret_key,
            current_time=current_time
        )

        # Reconcile with reported risk from predictive verification (MURPHY) (§10.3)
        if reported_risk:
            rep_clean = reported_risk.strip().upper()
            if rep_clean == "UNKNOWN":
                return cls._finalize_verdict(
                    verdict=MaryadaVerdict(
                        approved=False,
                        status=GateStatus.BLOCKED,
                        risk_tier=RiskTier.UNKNOWN,
                        authority_required=req_tier,
                        caller_authority=auth_repr,
                        requires_human=False,
                        justification="Fail-closed: predictive verification reported UNKNOWN risk."
                    ),
                    action=action, db_session=db_session, task_id=task_id, user_id=user_id, session_id=session_id
                )
            elif rep_clean in ["HIGH", "CRITICAL"] and risk_tier not in [RiskTier.HIGH, RiskTier.CRITICAL]:
                risk_tier = RiskTier(rep_clean)

        # -------------------------------------------------------------
        # 4. Multi-Tenant Scoped Custom Rule Overrides (§10.5)
        # -------------------------------------------------------------
        if tenant_custom_rules:
            disallowed_actions = tenant_custom_rules.get("disallowed_actions", [])
            if any(dis.lower() in action.lower() for dis in disallowed_actions):
                return cls._finalize_verdict(
                    verdict=MaryadaVerdict(
                        approved=False,
                        status=GateStatus.BLOCKED,
                        risk_tier=risk_tier,
                        authority_required=req_tier,
                        caller_authority=auth_repr,
                        requires_human=False,
                        justification=f"Tenant policy override: action '{action}' is disallowed by tenant configuration.",
                        policy_id=tenant_custom_rules.get("policy_id", "TENANT-CUSTOM-POLICY")
                    ),
                    action=action, db_session=db_session, task_id=task_id, user_id=user_id, session_id=session_id
                )

        if not is_auth:
            return cls._finalize_verdict(
                verdict=MaryadaVerdict(
                    approved=False,
                    status=GateStatus.BLOCKED,
                    risk_tier=risk_tier,
                    authority_required=req_tier,
                    caller_authority=auth_repr,
                    requires_human=False,
                    justification=auth_reason
                ),
                action=action, db_session=db_session, task_id=task_id, user_id=user_id, session_id=session_id
            )

        if req_human:
            return cls._finalize_verdict(
                verdict=MaryadaVerdict(
                    approved=False,
                    status=GateStatus.HUMAN_REVIEW_REQUIRED,
                    risk_tier=risk_tier,
                    authority_required=req_tier,
                    caller_authority=auth_repr,
                    requires_human=True,
                    justification=auth_reason
                ),
                action=action, db_session=db_session, task_id=task_id, user_id=user_id, session_id=session_id
            )

        # Approved
        return cls._finalize_verdict(
            verdict=MaryadaVerdict(
                approved=True,
                status=GateStatus.APPROVED,
                risk_tier=risk_tier,
                authority_required=req_tier,
                caller_authority=auth_repr,
                requires_human=False,
                justification=auth_reason
            ),
            action=action, db_session=db_session, task_id=task_id, user_id=user_id, session_id=session_id
        )

    @classmethod
    def evaluate_privileged_action_gate(
        cls,
        action: str,
        authority_token: Union[AuthorityToken, str, Dict[str, Any]],
        declared_authority: Optional[str] = None,
        tool_tier: Optional[str] = None,
        tenant_id: str = "global",
        db_session: Optional[Session] = None,
        task_id: Optional[int] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        secret_key: Optional[bytes] = None,
        current_time: Optional[datetime] = None
    ) -> MaryadaVerdict:
        """
        Dedicated gate for privileged execution requiring §13.4 cryptographically signed Authority Tokens.
        Rejects unsigned strings, tampered payloads, expired tokens, or out-of-scope actions.
        """
        return cls.evaluate_action_gate(
            action=action,
            caller_authority=None,
            declared_authority=declared_authority,
            tool_tier=tool_tier,
            authority_token=authority_token,
            tenant_id=tenant_id,
            db_session=db_session,
            task_id=task_id,
            user_id=user_id,
            session_id=session_id,
            require_signed_token=True,
            secret_key=secret_key,
            current_time=current_time
        )

    @classmethod
    def evaluate_plan_gate(
        cls,
        plan: KarmaPlanDAG,
        caller_authority: Optional[str],
        tenant_id: str = "global",
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None
    ) -> MaryadaVerdict:
        """
        Pre-flight evaluation of an entire KarmaPlanDAG.
        Fails closed if any single step violates constitutional invariants or authority.
        """
        if not plan or not plan.steps:
            return MaryadaVerdict(
                approved=False,
                status=GateStatus.BLOCKED,
                risk_tier=RiskTier.UNKNOWN,
                authority_required=AuthorityTier.HIGH,
                caller_authority=caller_authority,
                justification="Fail-closed: plan contains no steps."
            )

        for step in plan.steps:
            step_verdict = cls.evaluate_action_gate(
                action=step.action,
                caller_authority=caller_authority,
                declared_authority=step.authority_required,
                tenant_id=tenant_id,
                db_session=db_session,
                task_id=plan.task_id,
                user_id=user_id
            )
            if not step_verdict.approved:
                return step_verdict

        return MaryadaVerdict(
            approved=True,
            status=GateStatus.APPROVED,
            risk_tier=RiskTier.LOW,
            authority_required=AuthorityTier.LOW,
            caller_authority=caller_authority,
            justification="All DAG steps passed constitutional governance and authority checks."
        )

    @classmethod
    def _finalize_verdict(
        cls,
        verdict: MaryadaVerdict,
        action: str,
        db_session: Optional[Session] = None,
        task_id: Optional[int] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> MaryadaVerdict:
        """
        Appends canonical CHITRA gate audit event (§10.6, §8.2).
        """
        if db_session and task_id:
            try:
                chitra_evt = chitra_repository.append_event(
                    db=db_session,
                    task_id=task_id,
                    faculty="MARYADA",
                    event_type="gate",
                    decision={
                        "action": action,
                        "approved": verdict.approved,
                        "status": verdict.status.value,
                        "risk_tier": verdict.risk_tier.value,
                        "authority_required": verdict.authority_required.value,
                        "caller_authority": verdict.caller_authority,
                        "requires_human": verdict.requires_human,
                        "justification": verdict.justification,
                        "violated_invariants": verdict.violated_invariants
                    },
                    confidence=1.0 if verdict.approved else 0.0,
                    outcome="PASSED" if verdict.approved else "BLOCKED",
                    session_id=session_id or f"ses_gate_{task_id}",
                    user_id=user_id
                )
                verdict.chitra_event_id = chitra_evt.event_id
            except Exception:
                pass

        return verdict
