"""
MANUSH Phase 13 Comprehensive Forensic Test Suite: §12.1 DELEGATE Capability
Strictly tests Whitesheet §§12.1, 12.3, 12.4, 12.5, §13.4, §8 CHITRA, and CA-006.

Verifies:
1. DELEGATE is a distinct supervisory human oversight action.
2. Delegation state records delegator, delegate_id, delegated_scope, delegated_authority_tier, expiry.
3. Submitting DELEGATE does not execute tools; execution requires separate delegate invocation.
4. Delegate execution passes through AuthorityToken verification, MARYADA gate, KARMA execution.
5. All 10 mandatory negative security invariant tests produce ZERO tool invocations.
6. Multi-tenant boundary isolation and cryptographic CHITRA audit hash chains.
"""
import pytest
import os
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

# Ensure authority signing key is set for tests
os.environ["AUTHORITY_SIGNING_KEY"] = "test_maryada_authority_signing_key_32bytes_long!"

from app.db.database import SessionLocal
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.manush.decision import (
    ReviewStatus,
    ReviewDecisionType,
    HumanReviewDecision,
    ReviewItem
)
from app.core.manush.review_queue import ManushReviewQueue
from app.core.manush.service import ManushOversightService, manush_service
from app.core.tenant import TenantContext, get_current_tenant
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.karma.executor import KarmaDAGExecutor
from app.core.maryada.token import AuthorityToken
from app.core.maryada.verdict import AuthorityTier
from main import app


def test_1_successful_delegate_decision_transitions_state_and_logs_chitra():
    """Authorized delegator submits DELEGATE decision -> status transitions to DELEGATED_BY_HUMAN with CHITRA audit."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "secops_lead_del").first()
        if not user:
            user = User(username="secops_lead_del", hashed_password="xyz", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        task = Task(user_id=user.id, title="Delegate Task", prompt="calc", status="HUMAN_REVIEW")
        db.add(task)
        db.commit()
        db.refresh(task)

        service = ManushOversightService()
        item = service.escalate_for_review(
            task_id=task.id,
            tenant_id="tenant_del_01",
            action_summary="calculate 20 * 5",
            db_session=db,
            user_id=user.id
        )

        future_exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        dec = HumanReviewDecision(
            reviewer_id="secops_lead_del",
            decision=ReviewDecisionType.DELEGATE,
            justification="Delegating mathematical review to math specialist",
            signature="valid_secops_sig_del_01",
            delegate_id="specialist_bob",
            delegated_scope=["calculate*"],
            delegated_authority_tier="HIGH",
            delegation_expiry=future_exp
        )

        success, updated_item, msg = service.resolve_review(
            review_id=item.review_id,
            tenant_id="tenant_del_01",
            decision=dec,
            db_session=db,
            user_id=user.id
        )

        assert success is True
        assert updated_item.status == ReviewStatus.DELEGATED_BY_HUMAN
        assert updated_item.delegate_id == "specialist_bob"
        assert updated_item.delegated_scope == ["calculate*"]
        assert updated_item.delegated_authority_tier == "HIGH"
        assert len(updated_item.delegations) == 1

        # Verify CHITRA audit event
        chitra_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.faculty == "MANUSH"
        ).order_by(ChitraEvent.id.desc()).all()

        assert len(chitra_events) >= 2
        latest_evt = chitra_events[0]
        assert latest_evt.confidence == 1.0
        assert latest_evt.decision.get("decision") == "DELEGATE"
        assert latest_evt.decision.get("delegate_id") == "specialist_bob"
        assert latest_evt.this_event_hash.startswith("sha256:")
    finally:
        db.close()


def test_2_authorized_delegate_executes_action_via_karma():
    """Authorized delegate with signed AuthorityToken invokes execute_delegated_review -> passes MARYADA and invokes tool."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "secops_lead_del").first()
        invocations = []

        class MockExecutor:
            def execute_plan(self, plan, caller_authority=None, tenant_scope="global", db_session=None, user_id=None):
                invocations.append({"plan": plan, "caller_authority": caller_authority})
                return {"execution_status": "SUCCESS", "results": [100]}

        task = Task(user_id=user.id, title="Delegate Exec Task", prompt="calc", status="HUMAN_REVIEW")
        db.add(task)
        db.commit()
        db.refresh(task)

        service = ManushOversightService()
        item = service.escalate_for_review(
            task_id=task.id,
            tenant_id="tenant_del_02",
            action_summary="calculate 20 * 5",
            step_id="step_calc_01",
            db_session=db,
            user_id=user.id
        )

        dec = HumanReviewDecision(
            reviewer_id="secops_lead_del",
            decision=ReviewDecisionType.DELEGATE,
            justification="Delegated to bob",
            signature="valid_secops_sig_del_02",
            delegate_id="specialist_bob",
            delegated_scope=["calculate*"],
            delegated_authority_tier="HIGH"
        )
        ok, del_item, _ = service.resolve_review(
            review_id=item.review_id,
            tenant_id="tenant_del_02",
            decision=dec,
            db_session=db,
            user_id=user.id
        )
        assert ok is True

        # Valid signed authority token for specialist_bob
        auth_tok = AuthorityToken.issue(
            tier=AuthorityTier.HIGH,
            scopes=["calculate*"],
            tenant_id="tenant_del_02"
        )

        # Delegate execution
        plan_dag = KarmaPlanDAG(
            task_id=task.id,
            summary="Delegated Calc",
            steps=[KarmaStep(step_id="step_calc_01", action="calculate 20 * 5", expected_outcome="100", dependencies=[], authority_required="HIGH")]
        )

        exec_ok, rep, msg = service.execute_delegated_review(
            review_id=del_item.review_id,
            tenant_id="tenant_del_02",
            delegate_id="specialist_bob",
            plan=plan_dag,
            caller_authority=auth_tok,
            executor=MockExecutor(),
            db_session=db,
            user_id=user.id
        )

        assert exec_ok is True
        assert "successfully completed" in msg
        assert len(invocations) == 1
    finally:
        db.close()


def test_3_live_http_end_to_end_delegate_and_execution():
    """Real HTTP flow: POST /resolve (DELEGATE) followed by POST /execute-delegated with signed token and identity binding."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "expert_charlie").first()
        if not user:
            user = User(username="expert_charlie", hashed_password="xyz", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        plan_dict = {
            "summary": "Plan for Live Delegate",
            "steps": [{"step_id": "s_del_01", "action": "calculate 30 * 3", "expected_outcome": "90", "dependencies": [], "authority_required": "HIGH"}]
        }
        task = Task(user_id=user.id, title="Live Delegate Task", prompt="calc", status="HUMAN_REVIEW", plan=plan_dict)
        db.add(task)
        db.commit()
        db.refresh(task)

        plan_dict["task_id"] = task.id
        task.plan = plan_dict
        db.commit()

        tenant_id = f"tenant_{user.id}"
        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=tenant_id,
            action_summary="calculate 30 * 3",
            step_id="s_del_01",
            db_session=db,
            user_id=user.id
        )

        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=tenant_id)
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        # 1. Delegator submits DELEGATE
        del_payload = {
            "decision": "DELEGATE",
            "reviewer_id": "manager_alice",
            "justification": "Delegating to on-call calculator expert",
            "signature": "valid_manager_alice_sig_99",
            "delegate_id": "expert_charlie",
            "delegated_scope": ["calculate*"],
            "delegated_authority_tier": "HIGH"
        }
        res1 = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=del_payload)
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["success"] is True
        assert data1["status"] == "DELEGATED_BY_HUMAN"

        # 2. Delegate executes action with signed AuthorityToken
        signed_tok = AuthorityToken.issue(
            tier=AuthorityTier.HIGH,
            scopes=["calculate*"],
            tenant_id=tenant_id
        )
        exec_payload = {
            "delegate_id": "expert_charlie",
            "authority_token": signed_tok.model_dump()
        }
        res2 = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json=exec_payload)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["success"] is True
        assert "successfully completed" in data2["message"]
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_4_missing_authority_token_blocked_zero_invocations():
    """Negative Test 1: Missing AuthorityToken blocks execution fail-closed (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=801, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Delegating to bob", signature="valid_lead_sig_123", delegate_id="bob"
    ))
    plan = KarmaPlanDAG(task_id=801, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])])

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=None, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "Missing mandatory §13.4 AuthorityToken" in msg
    assert len(invocations) == 0


def test_5_invalid_signature_authority_token_blocked_zero_invocations():
    """Negative Test 2: Invalid signature AuthorityToken blocks execution fail-closed (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=802, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Delegating to bob", signature="valid_lead_sig_123", delegate_id="bob"
    ))
    plan = KarmaPlanDAG(task_id=802, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])])

    # Tampered signature
    tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id="tenant_01")
    tok.signature = "hmac-sha256:forged_invalid_signature_bytes_1234567890"

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "signature verification failed" in msg
    assert len(invocations) == 0


def test_6_expired_authority_token_blocked_zero_invocations():
    """Negative Test 3: Expired AuthorityToken blocks execution fail-closed (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=803, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Delegating to bob", signature="valid_lead_sig_123", delegate_id="bob"
    ))
    plan = KarmaPlanDAG(task_id=803, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])])

    tok = AuthorityToken(
        tier=AuthorityTier.HIGH,
        scopes=["*"],
        tenant_id="tenant_01",
        issued_at=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    ).sign()

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "has expired" in msg
    assert len(invocations) == 0


def test_7_tenant_mismatch_authority_token_blocked_zero_invocations():
    """Negative Test 4: Tenant mismatch between AuthorityToken and review item blocks execution (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=804, tenant_id="tenant_alpha", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_alpha", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Delegating to bob", signature="valid_lead_sig_123", delegate_id="bob"
    ))
    plan = KarmaPlanDAG(task_id=804, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])])

    # Token issued for tenant_bravo
    tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id="tenant_bravo")

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_alpha", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "tenant mismatch" in msg
    assert len(invocations) == 0


def test_8_delegate_identity_mismatch_blocked_zero_invocations():
    """Negative Test 5: Caller identity mismatch with item.delegate_id blocks execution (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=805, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Delegating to specialist_bob", signature="valid_lead_sig_123", delegate_id="specialist_bob"
    ))
    plan = KarmaPlanDAG(task_id=805, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])])
    tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id="tenant_01")

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="rogue_eve", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "Access Denied" in msg
    assert len(invocations) == 0


def test_9_caller_tier_high_delegation_ceiling_low_hard_fail():
    """Negative Test 6: Caller tier HIGH exceeding delegation ceiling LOW fails closed with HARD FAIL (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=806, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del with LOW ceiling", signature="valid_lead_sig_123",
        delegate_id="bob", delegated_authority_tier="LOW"
    ))
    plan = KarmaPlanDAG(task_id=806, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[], authority_required="LOW")])

    # Caller brings HIGH token, but delegation ceiling is LOW -> HARD FAIL
    tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id="tenant_01")

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "exceeds delegated ceiling" in msg
    assert len(invocations) == 0


def test_10_caller_tier_critical_delegation_ceiling_high_hard_fail():
    """Negative Test 7: Caller tier CRITICAL exceeding delegation ceiling HIGH fails closed (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=807, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del with HIGH ceiling", signature="valid_lead_sig_123",
        delegate_id="bob", delegated_authority_tier="HIGH"
    ))
    plan = KarmaPlanDAG(task_id=807, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[], authority_required="HIGH")])

    # Caller brings CRITICAL token, but delegation ceiling is HIGH -> HARD FAIL
    tok = AuthorityToken.issue(tier=AuthorityTier.CRITICAL, scopes=["*"], tenant_id="tenant_01")

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "exceeds delegated ceiling" in msg
    assert len(invocations) == 0


def test_11_scope_outside_delegation_blocked_zero_invocations():
    """Negative Test 8: Target action outside delegated_scope blocks execution (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=808, tenant_id="tenant_01", action_summary="system_purge", step_id="s_purge")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del calc only", signature="valid_lead_sig_123",
        delegate_id="bob", delegated_scope=["calculate*"], delegated_authority_tier="HIGH"
    ))
    plan = KarmaPlanDAG(task_id=808, summary="Purge", steps=[KarmaStep(step_id="s_purge", action="system_purge", expected_outcome="purged", dependencies=[])])
    tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id="tenant_01")

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "not within authorized delegated scope" in msg
    assert len(invocations) == 0


def test_12_target_action_requiring_higher_authority_than_delegation_blocked():
    """Negative Test 9: Target action requiring CRITICAL authority when delegation is MEDIUM is blocked (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=809, tenant_id="tenant_01", action_summary="critical_action", step_id="s_crit")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del medium only", signature="valid_lead_sig_123",
        delegate_id="bob", delegated_authority_tier="MEDIUM", delegated_scope=["critical_action"]
    ))
    plan = KarmaPlanDAG(task_id=809, summary="Crit", steps=[KarmaStep(step_id="s_crit", action="critical_action", expected_outcome="done", dependencies=[], authority_required="CRITICAL")])
    tok = AuthorityToken.issue(tier=AuthorityTier.MEDIUM, scopes=["critical_action"], tenant_id="tenant_01")

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "insufficient for step requirement" in msg
    assert len(invocations) == 0


def test_13_delegation_on_finalized_item_blocked_zero_invocations():
    """Negative Test 10: Attempting DELEGATE on an already finalized review is blocked (0 tool calls)."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=810, tenant_id="tenant_01", action_summary="action1")
    queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.TERMINATE, justification="Hard stop", signature="valid_lead_sig_123"
    ))

    ok, _, msg = queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer_2", decision=ReviewDecisionType.DELEGATE, justification="Retro delegate", signature="valid_lead_sig_456", delegate_id="bob"
    ))
    assert ok is False
    assert "already finalized" in msg


def test_14_not_yet_valid_token_blocked_zero_invocations():
    """Negative Test 11: Not-yet-valid (future issued_at) token is blocked (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=811, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del", signature="valid_lead_sig_123", delegate_id="bob"
    ))
    plan = KarmaPlanDAG(task_id=811, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])])

    future_tok = AuthorityToken(
        tier=AuthorityTier.HIGH,
        scopes=["*"],
        tenant_id="tenant_01",
        issued_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    ).sign()

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=future_tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "not yet valid" in msg
    assert len(invocations) == 0


def test_15_high_caller_against_medium_delegated_ceiling_hard_fail():
    """Negative Test 12: HIGH caller against MEDIUM delegated ceiling fails closed (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=812, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del with MEDIUM ceiling", signature="valid_lead_sig_123",
        delegate_id="bob", delegated_authority_tier="MEDIUM"
    ))
    plan = KarmaPlanDAG(task_id=812, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[], authority_required="MEDIUM")])

    tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id="tenant_01")

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "exceeds delegated ceiling" in msg
    assert len(invocations) == 0


def test_16_medium_caller_against_low_delegated_ceiling_hard_fail():
    """Negative Test 13: MEDIUM caller against LOW delegated ceiling fails closed (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=813, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del with LOW ceiling", signature="valid_lead_sig_123",
        delegate_id="bob", delegated_authority_tier="LOW"
    ))
    plan = KarmaPlanDAG(task_id=813, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[], authority_required="LOW")])

    tok = AuthorityToken.issue(tier=AuthorityTier.MEDIUM, scopes=["*"], tenant_id="tenant_01")

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    ok, _, msg = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tok, executor=MockSpyExecutor()
    )
    assert ok is False
    assert "exceeds delegated ceiling" in msg
    assert len(invocations) == 0


def test_17_malformed_and_tampered_token_payload_blocked_zero_invocations():
    """Negative Test 14: Malformed string or tampered token payload is blocked (0 tool calls)."""
    service = ManushOversightService()
    item = service.queue.enqueue_review(task_id=814, tenant_id="tenant_01", action_summary="calculate 1+1", step_id="s1")
    service.queue.submit_decision(item.review_id, "tenant_01", HumanReviewDecision(
        reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del", signature="valid_lead_sig_123", delegate_id="bob"
    ))
    plan = KarmaPlanDAG(task_id=814, summary="calc", steps=[KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])])

    invocations = []
    class MockSpyExecutor:
        def execute_plan(self, *args, **kwargs):
            invocations.append(args)
            return {}

    # Malformed string
    ok1, _, msg1 = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority="malformed_garbage_string", executor=MockSpyExecutor()
    )
    assert ok1 is False
    assert "Invalid AuthorityToken structure" in msg1 or "must be a valid encoded" in msg1

    # Tampered payload (tier modified after signature)
    valid_tok = AuthorityToken.issue(tier=AuthorityTier.LOW, scopes=["*"], tenant_id="tenant_01")
    tampered_dict = valid_tok.model_dump()
    tampered_dict["tier"] = "CRITICAL"  # tampered without re-signing

    ok2, _, msg2 = service.execute_delegated_review(
        review_id=item.review_id, tenant_id="tenant_01", delegate_id="bob", plan=plan, caller_authority=tampered_dict, executor=MockSpyExecutor()
    )
    assert ok2 is False
    assert "signature verification failed" in msg2
    assert len(invocations) == 0

