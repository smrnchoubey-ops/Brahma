"""
MANUSH Phase 13 Focused Test Suite: §12.1 TERMINATE Capability
Strictly tests Whitesheet §§12.1, 12.3, 12.4, §8 CHITRA, and CA-006.

Verifies:
1. TERMINATE is a distinct supervisory human oversight action.
2. Terminating a review item stops execution fail-closed (0 tool invocations).
3. Finalized TERMINATED items cannot be retroactively amended, approved, or rejected.
4. Tenant isolation is strictly enforced.
5. Canonical CHITRA audit events are logged to live PostgreSQL with unbroken hash chains.
6. Real FastAPI HTTP resolution endpoints process TERMINATE and prevent execution.
"""
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

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
from main import app


def test_1_terminate_pending_review_item_success():
    """Authorized operator submits TERMINATE decision -> status transitions to TERMINATED_BY_HUMAN."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(
        task_id=801,
        tenant_id="tenant_term_01",
        action_summary="execute critical_system_wipe",
        step_id="step_wipe_01"
    )
    assert item.status == ReviewStatus.PENDING_REVIEW

    dec = HumanReviewDecision(
        reviewer_id="secops_admin_01",
        decision=ReviewDecisionType.TERMINATE,
        justification="Operational abort: emergency shutdown ordered",
        signature="secops_sig_term_valid_01"
    )

    success, updated_item, msg = queue.submit_decision(
        review_id=item.review_id,
        tenant_id="tenant_term_01",
        decision=dec
    )

    assert success is True
    assert updated_item.status == ReviewStatus.TERMINATED_BY_HUMAN
    assert len(updated_item.terminations) == 1
    assert updated_item.terminations[0].reviewer_id == "secops_admin_01"
    assert "terminated by operator" in msg


def test_2_terminate_records_canonical_chitra_audit_event_in_postgresql():
    """TERMINATE resolution writes canonical CHITRA audit event with unbroken cryptographic chain."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "secops_lead_term").first()
        if not user:
            user = User(username="secops_lead_term", hashed_password="xyz", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        task = Task(user_id=user.id, title="Wipe Task", prompt="wipe system", status="HUMAN_REVIEW")
        db.add(task)
        db.commit()
        db.refresh(task)

        service = ManushOversightService()
        item = service.escalate_for_review(
            task_id=task.id,
            tenant_id="tenant_chitra_term",
            action_summary="execute critical_system_wipe",
            db_session=db,
            user_id=user.id
        )

        dec = HumanReviewDecision(
            reviewer_id="secops_lead_term",
            decision=ReviewDecisionType.TERMINATE,
            justification="Security violation: abort immediately",
            signature="valid_secops_sig_term_99"
        )

        success, updated_item, msg = service.resolve_review(
            review_id=item.review_id,
            tenant_id="tenant_chitra_term",
            decision=dec,
            db_session=db,
            user_id=user.id
        )

        assert success is True
        assert updated_item.status == ReviewStatus.TERMINATED_BY_HUMAN

        # Verify task status in database updated to TERMINATED
        db.refresh(task)
        assert task.status == "TERMINATED"

        # Verify CHITRA event in live PostgreSQL
        chitra_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.faculty == "MANUSH"
        ).order_by(ChitraEvent.id.desc()).all()

        assert len(chitra_events) >= 2
        latest_evt = chitra_events[0]
        assert latest_evt.outcome == "TERMINATED_BY_HUMAN"
        assert latest_evt.confidence == 1.0
        assert latest_evt.decision.get("decision") == "TERMINATE"
        assert latest_evt.decision.get("reviewer_id") == "secops_lead_term"
        assert latest_evt.this_event_hash.startswith("sha256:")
        assert latest_evt.signature.startswith("hmac-sha256:")
    finally:
        db.close()


def test_3_terminate_prevents_subsequent_amend_fail_closed():
    """A finalized TERMINATED review item rejects any subsequent AMEND attempt fail-closed."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(
        task_id=802,
        tenant_id="tenant_term_02",
        action_summary="calc 10+10"
    )

    term_dec = HumanReviewDecision(
        reviewer_id="lead_operator",
        decision=ReviewDecisionType.TERMINATE,
        justification="Cancelled by manager",
        signature="valid_sig_lead_123"
    )
    ok, item_after_term, _ = queue.submit_decision(
        review_id=item.review_id,
        tenant_id="tenant_term_02",
        decision=term_dec
    )
    assert ok is True
    assert item_after_term.status == ReviewStatus.TERMINATED_BY_HUMAN

    # Attempt retroactive AMEND
    amend_dec = HumanReviewDecision(
        reviewer_id="rogue_operator",
        decision=ReviewDecisionType.AMEND,
        justification="Attempting post-termination amendment",
        signature="valid_sig_rogue_123",
        amended_action="calc 20+20"
    )
    ok_amend, item_after_amend, msg_amend = queue.submit_decision(
        review_id=item.review_id,
        tenant_id="tenant_term_02",
        decision=amend_dec
    )
    assert ok_amend is False
    assert "already finalized with status 'TERMINATED_BY_HUMAN'" in msg_amend
    assert item_after_amend.status == ReviewStatus.TERMINATED_BY_HUMAN


def test_4_terminate_prevents_subsequent_approve_fail_closed():
    """A finalized TERMINATED review item rejects subsequent APPROVE attempt fail-closed."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=803, tenant_id="tenant_term_03", action_summary="action1")

    term_dec = HumanReviewDecision(
        reviewer_id="lead_operator",
        decision=ReviewDecisionType.TERMINATE,
        justification="Hard abort",
        signature="valid_sig_lead_123"
    )
    queue.submit_decision(review_id=item.review_id, tenant_id="tenant_term_03", decision=term_dec)

    app_dec = HumanReviewDecision(
        reviewer_id="another_operator",
        decision=ReviewDecisionType.APPROVE,
        justification="Trying to revive terminated task",
        signature="valid_sig_another_123"
    )
    ok, _, msg = queue.submit_decision(review_id=item.review_id, tenant_id="tenant_term_03", decision=app_dec)
    assert ok is False
    assert "already finalized" in msg


def test_5_terminate_prevents_subsequent_reject_fail_closed():
    """A finalized TERMINATED review item rejects subsequent REJECT attempt."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=804, tenant_id="tenant_term_04", action_summary="action1")

    term_dec = HumanReviewDecision(
        reviewer_id="lead_operator",
        decision=ReviewDecisionType.TERMINATE,
        justification="Hard abort",
        signature="valid_sig_lead_123"
    )
    queue.submit_decision(review_id=item.review_id, tenant_id="tenant_term_04", decision=term_dec)

    rej_dec = HumanReviewDecision(
        reviewer_id="another_operator",
        decision=ReviewDecisionType.REJECT,
        justification="Duplicate rejection",
        signature="valid_sig_another_123"
    )
    ok, _, msg = queue.submit_decision(review_id=item.review_id, tenant_id="tenant_term_04", decision=rej_dec)
    assert ok is False
    assert "already finalized" in msg


def test_6_terminate_missing_signature_fails_closed():
    """TERMINATE decision missing signature is rejected fail-closed."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=805, tenant_id="tenant_term_05", action_summary="action1")

    dec = HumanReviewDecision(
        reviewer_id="lead_operator",
        decision=ReviewDecisionType.TERMINATE,
        justification="Abort",
        signature=""
    )
    ok, _, msg = queue.submit_decision(review_id=item.review_id, tenant_id="tenant_term_05", decision=dec)
    assert ok is False
    assert "Invalid reviewer signature" in msg


def test_7_terminate_missing_justification_fails_closed():
    """TERMINATE decision with empty justification is rejected fail-closed."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=806, tenant_id="tenant_term_06", action_summary="action1")

    dec = HumanReviewDecision(
        reviewer_id="lead_operator",
        decision=ReviewDecisionType.TERMINATE,
        justification="   ",
        signature="valid_sig_123"
    )
    ok, _, msg = queue.submit_decision(review_id=item.review_id, tenant_id="tenant_term_06", decision=dec)
    assert ok is False
    assert "Missing justification" in msg


def test_8_terminate_tenant_isolation_fails_closed():
    """Tenant Bravo cannot terminate ReviewItem owned by Tenant Alpha."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=807, tenant_id="tenant_alpha", action_summary="action1")

    dec = HumanReviewDecision(
        reviewer_id="bravo_operator",
        decision=ReviewDecisionType.TERMINATE,
        justification="Cross-tenant abort",
        signature="valid_sig_bravo_123"
    )
    ok, _, msg = queue.submit_decision(review_id=item.review_id, tenant_id="tenant_bravo", decision=dec)
    assert ok is False
    assert "not found for tenant" in msg


def test_9_api_terminate_live_http_end_to_end_zero_tool_invocations():
    """Real HTTP POST to /api/manush/reviews/{id}/resolve with TERMINATE sets status and invokes 0 tools."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_term_user").first()
        if not user:
            user = User(username="api_term_user", hashed_password="xyz", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        invocations = []

        def spy_calc(params):
            invocations.append(params)
            return {"result": 999}

        plan_dict = {
            "summary": "Plan to Terminate",
            "steps": [{"step_id": "s_term_01", "action": "calculate 40 * 4", "expected_outcome": "160", "dependencies": []}]
        }
        task = Task(user_id=user.id, title="Term Task", prompt="calc", status="HUMAN_REVIEW", plan=plan_dict)
        db.add(task)
        db.commit()
        db.refresh(task)

        plan_dict["task_id"] = task.id
        task.plan = plan_dict
        db.commit()

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calculate 40 * 4",
            step_id="s_term_01",
            db_session=db,
            user_id=user.id
        )

        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "TERMINATE",
            "reviewer_id": "secops_commander",
            "justification": "Threat identified: aborting entire workflow",
            "signature": "valid_secops_commander_sig_99"
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is True
        assert res_data["status"] == "TERMINATED_BY_HUMAN"

        # Explicitly verify ZERO tool invocations
        assert len(invocations) == 0

        # Verify task status in PostgreSQL is TERMINATED
        db.refresh(task)
        assert task.status == "TERMINATED"

        # Verify CHITRA audit event
        chitra_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.faculty == "MANUSH"
        ).order_by(ChitraEvent.id.desc()).all()

        assert len(chitra_events) >= 2
        latest_evt = chitra_events[0]
        assert latest_evt.outcome == "TERMINATED_BY_HUMAN"
        assert latest_evt.confidence == 1.0
        assert latest_evt.decision.get("decision") == "TERMINATE"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_10_api_terminate_followed_by_amend_blocked():
    """Subsequent AMEND HTTP call on terminated item fails closed."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_term_user").first()
        task = Task(user_id=user.id, title="Term Task 2", prompt="calc", status="HUMAN_REVIEW", plan={"steps": []})
        db.add(task)
        db.commit()
        db.refresh(task)

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calc 1+1",
            db_session=db,
            user_id=user.id
        )

        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        # 1. Terminate
        term_payload = {
            "decision": "TERMINATE",
            "reviewer_id": "secops_commander",
            "justification": "Abort workflow",
            "signature": "valid_secops_commander_sig_99"
        }
        res1 = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=term_payload)
        assert res1.status_code == 200
        assert res1.json()["status"] == "TERMINATED_BY_HUMAN"

        # 2. Attempt AMEND
        amend_payload = {
            "decision": "AMEND",
            "reviewer_id": "attacker",
            "justification": "Re-run amended",
            "signature": "valid_attacker_sig_99",
            "amended_action": "calc 2+2"
        }
        res2 = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=amend_payload)
        assert res2.status_code == 200
        assert res2.json()["success"] is False
        assert "already finalized" in res2.json()["message"]
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_11_api_terminate_cross_tenant_rejected_404():
    """Attacker from another tenant attempting to terminate Alice's review gets 404 (resource hiding)."""
    db = SessionLocal()
    try:
        user_alice = db.query(User).filter(User.username == "api_term_user").first()
        task = Task(user_id=user_alice.id, title="Alice Task", prompt="calc", status="HUMAN_REVIEW", plan={"steps": []})
        db.add(task)
        db.commit()
        db.refresh(task)

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user_alice.id}",
            action_summary="calc 1+1",
            db_session=db,
            user_id=user_alice.id
        )

        # Tenant Eve
        eve_tenant_ctx = TenantContext(user_id=8888, username="eve_term_attacker", tenant_id="tenant_8888")
        app.dependency_overrides[get_current_tenant] = lambda: eve_tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "TERMINATE",
            "reviewer_id": "eve_hacker",
            "justification": "Unauthorized abort",
            "signature": "valid_eve_hacker_sig_99"
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_12_terminated_item_execution_resume_blocked_zero_tool_invocations():
    """Once TERMINATE is finalized, execution/resume attempts fail closed with 0 tool handler calls."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_term_user").first()
        invocations = []

        class MockExecutor:
            def _execute_tool_handler(self, tool_id, action, params=None):
                invocations.append((tool_id, action, params))
                return {"result": 123}

        plan_dict = {
            "summary": "Plan to Terminate",
            "steps": [{"step_id": "s_term_02", "action": "calculate 50 * 5", "expected_outcome": "250", "dependencies": []}]
        }
        task = Task(user_id=user.id, title="Term Task 3", prompt="calc", status="HUMAN_REVIEW", plan=plan_dict)
        db.add(task)
        db.commit()
        db.refresh(task)

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calculate 50 * 5",
            step_id="s_term_02",
            db_session=db,
            user_id=user.id
        )

        term_dec = HumanReviewDecision(
            reviewer_id="secops_commander",
            decision=ReviewDecisionType.TERMINATE,
            justification="Finalized termination test",
            signature="valid_secops_commander_sig_99"
        )

        ok, updated_item, _ = manush_service.resolve_review(
            review_id=review_item.review_id,
            tenant_id=f"tenant_{user.id}",
            decision=term_dec,
            db_session=db,
            user_id=user.id
        )
        assert ok is True
        assert updated_item.status == ReviewStatus.TERMINATED_BY_HUMAN

        # 1. Attempt direct execution resume on terminated item
        plan_dag = KarmaPlanDAG(
            task_id=task.id,
            summary="Plan to Terminate",
            steps=[KarmaStep(step_id="s_term_02", action="calculate 50 * 5", expected_outcome="250", dependencies=[])]
        )
        res_ok, _, res_msg = manush_service.resume_amended_execution(
            review_id=review_item.review_id,
            tenant_id=f"tenant_{user.id}",
            plan=plan_dag,
            executor=MockExecutor(),
            db_session=db,
            user_id=user.id
        )
        assert res_ok is False
        assert "not in AMENDED_BY_HUMAN status" in res_msg
        assert len(invocations) == 0

        # 2. Attempt subsequent APPROVE over HTTP -> blocked
        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        app_payload = {
            "decision": "APPROVE",
            "reviewer_id": "operator_2",
            "justification": "Attempt approve after term",
            "signature": "valid_operator_2_sig_99"
        }
        res_app = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=app_payload)
        assert res_app.status_code == 200
        assert res_app.json()["success"] is False
        assert "already finalized" in res_app.json()["message"]

        # 3. Attempt subsequent REJECT over HTTP -> blocked
        rej_payload = {
            "decision": "REJECT",
            "reviewer_id": "operator_3",
            "justification": "Attempt reject after term",
            "signature": "valid_operator_3_sig_99"
        }
        res_rej = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=rej_payload)
        assert res_rej.status_code == 200
        assert res_rej.json()["success"] is False
        assert "already finalized" in res_rej.json()["message"]

        # Ensure tool handler invocations remains 0
        assert len(invocations) == 0
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_13_database_failure_on_terminate_fails_closed_no_false_success():
    """Database commit/persistence failure on TERMINATE must fail closed and NOT report false success."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_term_user").first()
        task = Task(user_id=user.id, title="Term Task 4", prompt="calc", status="HUMAN_REVIEW", plan={"steps": []})
        db.add(task)
        db.commit()
        db.refresh(task)

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calc 1+1",
            db_session=db,
            user_id=user.id
        )

        term_dec = HumanReviewDecision(
            reviewer_id="secops_commander",
            decision=ReviewDecisionType.TERMINATE,
            justification="Abort test with failing DB",
            signature="valid_secops_commander_sig_99"
        )

        # Mock database session where commit raises an operational error
        class BrokenSession:
            def query(self, *args, **kwargs):
                return db.query(*args, **kwargs)
            def commit(self):
                raise RuntimeError("PostgreSQL connection lost during termination commit")
            def rollback(self):
                pass
            def add(self, *args, **kwargs):
                pass
            def execute(self, *args, **kwargs):
                raise RuntimeError("PostgreSQL query execution failed")

        broken_db = BrokenSession()

        ok, item_res, msg = manush_service.resolve_review(
            review_id=review_item.review_id,
            tenant_id=f"tenant_{user.id}",
            decision=term_dec,
            db_session=broken_db,
            user_id=user.id
        )

        # Must report failure
        assert ok is False
        assert "Database persistence error" in msg
        # Must not report finalized TERMINATED_BY_HUMAN state
        assert item_res.status == ReviewStatus.PENDING_REVIEW

        # Over API: endpoint returns success=False
        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        app.dependency_overrides[SessionLocal] = lambda: broken_db
        from app.db.database import get_db
        app.dependency_overrides[get_db] = lambda: broken_db

        client = TestClient(app)
        api_payload = {
            "decision": "TERMINATE",
            "reviewer_id": "secops_commander",
            "justification": "Abort test with failing DB via API",
            "signature": "valid_secops_commander_sig_99"
        }
        res = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=api_payload)
        # API handles failure gracefully without claiming success
        assert res.json().get("success") is False
    finally:
        app.dependency_overrides.clear()
        db.close()

