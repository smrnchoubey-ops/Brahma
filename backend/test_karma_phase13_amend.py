"""
MANUSH Phase 13 Focused Test Suite: §12 AMEND Capability
Strictly tests Whitesheet §§12.1, 12.3, 12.4, 12.5, §8 CHITRA, and Appendix A CA-006.
"""
import pytest
import time
from datetime import datetime, timezone

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
from app.core.manush.service import ManushOversightService
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.core.maryada.verdict import GateStatus
from app.repositories.chitra_repository import chitra_repository


def test_1_successful_amend():
    """Valid human reviewer amends a pending review item."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(
        task_id=901,
        tenant_id="tenant_alpha",
        action_summary="wire_transfer 500000 USD",
        metadata={"parameters": {"amount": 500000, "recipient": "acc_ext_999"}}
    )
    assert item.status == ReviewStatus.PENDING_REVIEW

    decision = HumanReviewDecision(
        reviewer_id="operator_alice",
        decision=ReviewDecisionType.AMEND,
        justification="Reduced amount to approved limit 50k",
        signature="sig_alice_valid_secops_123",
        amended_action="wire_transfer 50000 USD",
        amended_parameters={"amount": 50000, "recipient": "acc_ext_999"}
    )

    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_alpha", decision)
    assert ok is True
    assert updated.status == ReviewStatus.AMENDED_BY_HUMAN
    assert updated.status != ReviewStatus.APPROVED_BY_HUMAN
    assert "amended by operator 'operator_alice'" in msg


def test_2_preserves_original_and_amended_action_and_params():
    """Preserves original vs amended action and parameters."""
    queue = ManushReviewQueue()
    orig_action = "bulk_delete /data/customers"
    orig_params = {"path": "/data/customers", "recursive": True}

    item = queue.enqueue_review(
        task_id=902,
        tenant_id="tenant_alpha",
        action_summary=orig_action,
        metadata={"parameters": orig_params}
    )

    decision = HumanReviewDecision(
        reviewer_id="operator_bob",
        decision=ReviewDecisionType.AMEND,
        justification="Target specific temporary staging path only",
        signature="sig_bob_valid_audit_456",
        amended_action="bulk_delete /data/temp_staging",
        amended_parameters={"path": "/data/temp_staging", "recursive": False}
    )

    ok, updated, _ = queue.submit_decision(item.review_id, "tenant_alpha", decision)
    assert ok is True
    assert updated.original_action == orig_action
    assert updated.original_parameters == orig_params
    assert updated.amended_action == "bulk_delete /data/temp_staging"
    assert updated.amended_parameters == {"path": "/data/temp_staging", "recursive": False}
    assert len(updated.amendments) == 1
    assert updated.amendments[0].reviewer_id == "operator_bob"


def test_3_invalid_or_missing_signature_rejected():
    """Fail closed when reviewer signature is invalid or too short."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=903, tenant_id="tenant_alpha", action_summary="action_1")

    decision = HumanReviewDecision(
        reviewer_id="operator_carol",
        decision=ReviewDecisionType.AMEND,
        justification="Legit amendment",
        signature="short",  # Invalid < 8 chars
        amended_action="action_1_amended"
    )

    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_alpha", decision)
    assert ok is False
    assert "Invalid reviewer signature" in msg
    assert updated.status == ReviewStatus.PENDING_REVIEW


def test_4_missing_justification_rejected():
    """Fail closed when operator provides empty justification."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=904, tenant_id="tenant_alpha", action_summary="action_2")

    decision = HumanReviewDecision(
        reviewer_id="operator_dan",
        decision=ReviewDecisionType.AMEND,
        justification="   ",  # Whitespace only
        signature="sig_dan_valid_789",
        amended_action="action_2_amended"
    )

    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_alpha", decision)
    assert ok is False
    assert "Missing justification" in msg
    assert updated.status == ReviewStatus.PENDING_REVIEW


def test_5_empty_amendment_payload_rejected():
    """Fail closed if amendment specifies neither an amended action nor amended parameters."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=905, tenant_id="tenant_alpha", action_summary="action_3")

    decision = HumanReviewDecision(
        reviewer_id="operator_eve",
        decision=ReviewDecisionType.AMEND,
        justification="No changes provided",
        signature="sig_eve_valid_012",
        amended_action="",
        amended_parameters=None
    )

    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_alpha", decision)
    assert ok is False
    assert "Invalid amendment" in msg
    assert updated.status == ReviewStatus.PENDING_REVIEW


def test_6_expired_item_rejects_amendment():
    """Fail closed when review item TTL has expired (§12.3)."""
    queue = ManushReviewQueue(default_ttl_seconds=1)
    item = queue.enqueue_review(task_id=906, tenant_id="tenant_alpha", action_summary="action_4", ttl_seconds=1)
    time.sleep(1.1)

    decision = HumanReviewDecision(
        reviewer_id="operator_frank",
        decision=ReviewDecisionType.AMEND,
        justification="Late amendment",
        signature="sig_frank_valid_345",
        amended_action="action_4_amended"
    )

    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_alpha", decision)
    assert ok is False
    assert "already finalized" in msg or "TIMEOUT_EXPIRED" in updated.status.value
    assert updated.status == ReviewStatus.TIMEOUT_EXPIRED


def test_7_finalized_item_rejects_amendment():
    """Cannot amend an item that was already APPROVED or REJECTED."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=907, tenant_id="tenant_alpha", action_summary="action_5")

    # Finalize by approval
    app_dec = HumanReviewDecision(
        reviewer_id="operator_grace",
        decision=ReviewDecisionType.APPROVE,
        justification="First approval",
        signature="sig_grace_valid_678"
    )
    ok1, updated1, _ = queue.submit_decision(item.review_id, "tenant_alpha", app_dec)
    assert ok1 is True
    assert updated1.status == ReviewStatus.APPROVED_BY_HUMAN

    # Attempt amendment after approval
    amend_dec = HumanReviewDecision(
        reviewer_id="operator_heidi",
        decision=ReviewDecisionType.AMEND,
        justification="Post-approval modification attempt",
        signature="sig_heidi_valid_901",
        amended_action="action_5_modified"
    )
    ok2, updated2, msg2 = queue.submit_decision(item.review_id, "tenant_alpha", amend_dec)
    assert ok2 is False
    assert "already finalized" in msg2
    assert updated2.status == ReviewStatus.APPROVED_BY_HUMAN


def test_8_tenant_mismatch_fails_closed():
    """Tenant isolation: Tenant Beta reviewer cannot amend Tenant Alpha item."""
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=908, tenant_id="tenant_alpha", action_summary="confidential_action")

    decision = HumanReviewDecision(
        reviewer_id="operator_ivan",
        decision=ReviewDecisionType.AMEND,
        justification="Cross-tenant tampering",
        signature="sig_ivan_valid_234",
        amended_action="tampered_action"
    )

    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_beta", decision)
    assert ok is False
    assert "not found for tenant" in msg


def test_9_maryada_re_evaluation_blocks_dangerous_amendment():
    """Amended action must pass MARYADA checks; dangerous amended action is blocked (CA-006)."""
    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=909,
        tenant_id="tenant_alpha",
        action_summary="innocuous_query"
    )

    # Human amends it to an unconstitutional / invariant violating action
    decision = HumanReviewDecision(
        reviewer_id="operator_judy",
        decision=ReviewDecisionType.AMEND,
        justification="Attempting forbidden invariant operation",
        signature="sig_judy_valid_567",
        amended_action="rm -rf / --no-preserve-root"
    )

    ok, updated, _ = service.resolve_review(item.review_id, "tenant_alpha", decision)
    assert ok is True
    assert updated.status == ReviewStatus.AMENDED_BY_HUMAN

    # Re-evaluation must fail closed
    verdict = service.re_evaluate_amended_action(updated, caller_authority="HIGH")
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "Constitutional block" in verdict.justification or len(verdict.violated_invariants) > 0


def test_10_maryada_re_evaluation_passes_safe_amendment():
    """Safe amended action passes governance re-evaluation."""
    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=910,
        tenant_id="tenant_alpha",
        action_summary="excessive_action"
    )

    decision = HumanReviewDecision(
        reviewer_id="operator_karl",
        decision=ReviewDecisionType.AMEND,
        justification="Amended to benign telemetry check",
        signature="sig_karl_valid_890",
        amended_action="system_status"
    )

    ok, updated, _ = service.resolve_review(item.review_id, "tenant_alpha", decision)
    assert ok is True
    assert updated.status == ReviewStatus.AMENDED_BY_HUMAN

    verdict = service.re_evaluate_amended_action(updated, caller_authority="LOW")
    assert verdict.approved is True
    assert verdict.status == GateStatus.APPROVED


def test_11_chitra_audit_event_logged_to_live_postgresql():
    """Verifies that an AMEND decision emits a canonical CHITRA audit event into live PostgreSQL."""
    db = SessionLocal()
    try:
        # Create a unique test user and task in live PostgreSQL
        test_user = User(username=f"user_p13_amend_{int(time.time())}", hashed_password="pwd")
        db.add(test_user)
        db.commit()
        db.refresh(test_user)

        test_task = Task(user_id=test_user.id, title="AMEND Live PG Test Task", prompt="Live PG Prompt", status="PENDING")
        db.add(test_task)
        db.commit()
        db.refresh(test_task)

        service = ManushOversightService()
        item = service.escalate_for_review(
            task_id=test_task.id,
            tenant_id="tenant_audit_live",
            action_summary="wire_transfer 1000000",
            db_session=db,
            user_id=test_user.id
        )

        decision = HumanReviewDecision(
            reviewer_id="secops_lead_1",
            decision=ReviewDecisionType.AMEND,
            justification="Policy cap: adjusted to 25000",
            signature="sig_secops_live_pg_123",
            amended_action="wire_transfer 25000",
            amended_parameters={"amount": 25000}
        )

        ok, updated, msg = service.resolve_review(
            review_id=item.review_id,
            tenant_id="tenant_audit_live",
            decision=decision,
            db_session=db,
            user_id=test_user.id
        )

        assert ok is True
        assert updated.status == ReviewStatus.AMENDED_BY_HUMAN

        # Query live PostgreSQL CHITRA ledger for the event
        chitra_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == test_task.id,
            ChitraEvent.faculty == "MANUSH"
        ).order_by(ChitraEvent.id.desc()).all()

        assert len(chitra_events) >= 2  # Escalation event + Resolution event
        latest_evt = chitra_events[0]
        assert latest_evt.event_type == "human_review"
        assert latest_evt.outcome == "AMENDED_BY_HUMAN"
        assert latest_evt.decision.get("decision") == "AMEND"
        assert latest_evt.decision.get("original_action") == "wire_transfer 1000000"
        assert latest_evt.decision.get("amended_action") == "wire_transfer 25000"
        assert latest_evt.decision.get("amended_parameters") == {"amount": 25000}
        assert latest_evt.decision.get("reviewer_id") == "secops_lead_1"
        assert latest_evt.this_event_hash is not None and "sha256:" in latest_evt.this_event_hash
        assert latest_evt.signature is not None and "hmac-sha256:" in latest_evt.signature
    finally:
        db.close()


def test_12_resume_amended_execution_safe_path_end_to_end():
    """Safe AMEND executes end-to-end through production resume path after MARYADA passes."""
    from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
    from app.core.karma.executor import KarmaDAGExecutor

    invocations = []

    def spy_calc_handler(params):
        invocations.append(params)
        return {"result": 55}

    executor = KarmaDAGExecutor(
        custom_handlers={"calculator": spy_calc_handler}
    )

    s1 = KarmaStep(
        step_id="step_calc",
        action="calculate 100 * 100",
        expected_outcome="55",
        dependencies=[]
    )
    plan = KarmaPlanDAG(task_id=920, summary="Calculation Plan", steps=[s1])

    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=920,
        tenant_id="tenant_calc_user",
        action_summary="calculate 100 * 100",
        step_id="step_calc"
    )

    # Human amends calculation expression to "calculate 50 + 5"
    amend_decision = HumanReviewDecision(
        reviewer_id="math_reviewer_1",
        decision=ReviewDecisionType.AMEND,
        justification="Corrected formula to sum 50 + 5",
        signature="sig_math_valid_123",
        amended_action="calculate 50 + 5",
        amended_parameters={"expression": "50 + 5"}
    )

    ok, _, _ = service.resolve_review(
        review_id=item.review_id,
        tenant_id="tenant_calc_user",
        decision=amend_decision
    )
    assert ok is True

    # Production resume path
    ok_res, exec_rep, msg = service.resume_amended_execution(
        review_id=item.review_id,
        tenant_id="tenant_calc_user",
        plan=plan,
        caller_authority="LOW",
        executor=executor
    )

    assert ok_res is True
    assert exec_rep.status == "COMPLETED"
    assert len(invocations) == 1
    # Check amended parameters reached the handler
    assert invocations[0].get("expression") == "50 + 5"
    assert plan.steps[0].action == "calculate 50 + 5"


def test_13_resume_amended_execution_dangerous_blocked_zero_invocations():
    """Dangerous AMEND blocked by MARYADA re-evaluation; 0 tool handler invocations."""
    from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
    from app.core.karma.executor import KarmaDAGExecutor

    invocations = []

    def dangerous_spy_handler(params):
        invocations.append(params)
        return {"status": "deleted"}

    executor = KarmaDAGExecutor(
        custom_handlers={"file_ops": dangerous_spy_handler}
    )

    s1 = KarmaStep(
        step_id="step_danger",
        action="echo hello",
        expected_outcome="ok",
        dependencies=[]
    )
    plan = KarmaPlanDAG(task_id=921, summary="Danger Plan", steps=[s1])

    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=921,
        tenant_id="tenant_safe",
        action_summary="echo hello",
        step_id="step_danger"
    )

    # Operator attempts dangerous destructive invariant violation
    amend_decision = HumanReviewDecision(
        reviewer_id="bad_actor_1",
        decision=ReviewDecisionType.AMEND,
        justification="Inject wipe command",
        signature="sig_bad_actor_123",
        amended_action="rm -rf / --no-preserve-root",
        amended_parameters={"force": True}
    )

    ok, _, _ = service.resolve_review(
        review_id=item.review_id,
        tenant_id="tenant_safe",
        decision=amend_decision
    )
    assert ok is True

    # Production resume path must fail closed
    ok_res, verdict, msg = service.resume_amended_execution(
        review_id=item.review_id,
        tenant_id="tenant_safe",
        plan=plan,
        caller_authority="HIGH",
        executor=executor
    )

    assert ok_res is False
    assert len(invocations) == 0  # Tool handler NEVER called
    assert "rejected by MARYADA governance" in msg
    assert verdict.approved is False
    # Plan step was NOT mutated
    assert plan.steps[0].action == "echo hello"


def test_14_resume_amended_execution_insufficient_authority_zero_invocations():
    """Insufficient caller authority blocks re-evaluation; 0 tool handler invocations."""
    from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
    from app.core.karma.executor import KarmaDAGExecutor

    invocations = []

    def settlement_spy_handler(params):
        invocations.append(params)
        return {"settled": True}

    executor = KarmaDAGExecutor(
        custom_handlers={"financial_settlement_api": settlement_spy_handler}
    )

    s1 = KarmaStep(
        step_id="step_fin",
        action="calculate 1+1",
        expected_outcome="2",
        dependencies=[]
    )
    plan = KarmaPlanDAG(task_id=922, summary="Financial Plan", steps=[s1])

    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=922,
        tenant_id="tenant_fin",
        action_summary="calculate 1+1",
        step_id="step_fin"
    )

    # Amended to financial settlement (requires HIGH)
    amend_decision = HumanReviewDecision(
        reviewer_id="fin_lead_1",
        decision=ReviewDecisionType.AMEND,
        justification="Elevate to wire transfer",
        signature="sig_fin_lead_123",
        amended_action="wire_transfer 50000",
        amended_parameters={"amount": 50000}
    )

    service.resolve_review(item.review_id, "tenant_fin", amend_decision)

    # Caller only has LOW authority -> must block
    ok_res, verdict, msg = service.resume_amended_execution(
        review_id=item.review_id,
        tenant_id="tenant_fin",
        plan=plan,
        caller_authority="LOW",
        executor=executor
    )

    assert ok_res is False
    assert len(invocations) == 0  # Tool handler NEVER called
    assert "rejected by MARYADA governance" in msg


def test_15_resume_amended_execution_tenant_mismatch_blocked():
    """Cross-tenant resume attempt fails closed."""
    from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep

    s1 = KarmaStep(step_id="step_iso", action="system_status", expected_outcome="ok", dependencies=[])
    plan = KarmaPlanDAG(task_id=923, summary="Tenant Plan", steps=[s1])

    service = ManushOversightService()
    item = service.escalate_for_review(task_id=923, tenant_id="tenant_owner", action_summary="system_status")

    amend_decision = HumanReviewDecision(
        reviewer_id="op_owner",
        decision=ReviewDecisionType.AMEND,
        justification="Amended",
        signature="sig_owner_123",
        amended_action="system_status_verbose"
    )
    service.resolve_review(item.review_id, "tenant_owner", amend_decision)

    # Attacker from tenant_intruder tries to resume tenant_owner item
    ok_res, _, msg = service.resume_amended_execution(
        review_id=item.review_id,
        tenant_id="tenant_intruder",
        plan=plan
    )

    assert ok_res is False
    assert "not found for tenant" in msg


def test_16_resume_amended_execution_not_amended_status_fails_closed():
    """Review item in PENDING_REVIEW or APPROVED status cannot use resume_amended_execution."""
    from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep

    s1 = KarmaStep(step_id="step_p", action="system_status", expected_outcome="ok", dependencies=[])
    plan = KarmaPlanDAG(task_id=924, summary="Pending Plan", steps=[s1])

    service = ManushOversightService()
    item = service.escalate_for_review(task_id=924, tenant_id="tenant_p", action_summary="system_status")

    # Item is still PENDING_REVIEW
    ok_res, _, msg = service.resume_amended_execution(
        review_id=item.review_id,
        tenant_id="tenant_p",
        plan=plan
    )

    assert ok_res is False
    assert "not in AMENDED_BY_HUMAN status" in msg


def test_17_resolve_review_with_plan_triggers_production_amend_resume_path():
    """Calling resolve_review with plan triggers automatic production AMEND resume through MARYADA and KARMA."""
    from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
    from app.core.karma.executor import KarmaDAGExecutor

    invocations = []

    def spy_calc_handler(params):
        invocations.append(params)
        return {"result": 77}

    executor = KarmaDAGExecutor(
        custom_handlers={"calculator": spy_calc_handler}
    )

    s1 = KarmaStep(
        step_id="step_auto_1",
        action="calculate 2 * 2",
        expected_outcome="77",
        dependencies=[]
    )
    plan = KarmaPlanDAG(task_id=925, summary="Auto Resume Plan", steps=[s1])

    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=925,
        tenant_id="tenant_auto",
        action_summary="calculate 2 * 2",
        step_id="step_auto_1"
    )

    amend_decision = HumanReviewDecision(
        reviewer_id="lead_reviewer_auto",
        decision=ReviewDecisionType.AMEND,
        justification="Amended calculation to 70 + 7",
        signature="sig_auto_valid_123",
        amended_action="calculate 70 + 7",
        amended_parameters={"expression": "70 + 7"}
    )

    # Calling resolve_review with plan triggers resume_amended_execution automatically
    ok, updated_item, msg = service.resolve_review(
        review_id=item.review_id,
        tenant_id="tenant_auto",
        decision=amend_decision,
        plan=plan,
        caller_authority="LOW",
        executor=executor
    )

    assert ok is True
    assert updated_item.status == ReviewStatus.AMENDED_BY_HUMAN
    assert "execution resumed" in msg
    assert len(invocations) == 1
    assert invocations[0].get("expression") == "70 + 7"
    assert plan.steps[0].action == "calculate 70 + 7"


def test_18_resolve_review_with_plan_dangerous_amend_blocked():
    """Dangerous amendment passed via resolve_review with plan is blocked by MARYADA; 0 tool calls."""
    from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
    from app.core.karma.executor import KarmaDAGExecutor

    invocations = []

    def dangerous_spy_handler(params):
        invocations.append(params)
        return {}

    executor = KarmaDAGExecutor(
        custom_handlers={"file_ops": dangerous_spy_handler}
    )

    s1 = KarmaStep(
        step_id="step_auto_danger",
        action="echo clean",
        expected_outcome="ok",
        dependencies=[]
    )
    plan = KarmaPlanDAG(task_id=926, summary="Danger Auto Plan", steps=[s1])

    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=926,
        tenant_id="tenant_auto",
        action_summary="echo clean",
        step_id="step_auto_danger"
    )

    amend_decision = HumanReviewDecision(
        reviewer_id="lead_reviewer_auto",
        decision=ReviewDecisionType.AMEND,
        justification="Dangerous unconstitutional override",
        signature="sig_auto_valid_123",
        amended_action="rm -rf / --no-preserve-root",
        amended_parameters={"force": True}
    )

    # Calling resolve_review with plan must block execution fail-closed
    ok, updated_item, msg = service.resolve_review(
        review_id=item.review_id,
        tenant_id="tenant_auto",
        decision=amend_decision,
        plan=plan,
        caller_authority="HIGH",
        executor=executor
    )

    assert ok is False
    assert "resume blocked" in msg
    assert len(invocations) == 0  # 0 tool invocations
    assert plan.steps[0].action == "echo clean"  # Step was not mutated


def test_19_api_resolve_review_amend_end_to_end():
    """Real end-to-end AMEND execution via FastAPI TestClient loading paused task plan from PostgreSQL."""
    from fastapi.testclient import TestClient
    from main import app
    from app.core.tenant import get_current_tenant, TenantContext
    from app.core.manush.service import manush_service
    from app.core.security import create_access_token

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_auditor_alice").first()
        if not user:
            user = User(username="api_auditor_alice", hashed_password="xyz", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        paused_plan_dict = {
            "task_id": 9901,
            "summary": "Paused API Plan",
            "steps": [
                {
                    "step_id": "step_api_01",
                    "action": "calculate 50 * 2",
                    "expected_outcome": "125",
                    "dependencies": [],
                    "parameters": {"expression": "50 * 2"}
                }
            ]
        }

        task = Task(
            user_id=user.id,
            title="API Paused Task",
            prompt="calculate 50 * 2",
            status="HUMAN_REVIEW",
            plan=paused_plan_dict
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # Update task_id in plan dict
        paused_plan_dict["task_id"] = task.id
        task.plan = paused_plan_dict
        db.commit()

        # Enqueue review in MANUSH service
        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calculate 50 * 2",
            step_id="step_api_01",
            metadata={"parameters": {"expression": "50 * 2"}},
            db_session=db,
            user_id=user.id
        )

        tenant_ctx = TenantContext(
            user_id=user.id,
            username=user.username,
            tenant_id=f"tenant_{user.id}"
        )

        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "AMEND",
            "reviewer_id": "lead_secops_api",
            "justification": "Approved with amended expression 100 + 25",
            "signature": "secops_sig_api_valid",
            "amended_action": "calculate 100 + 25",
            "amended_parameters": {"expression": "100 + 25"}
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 200, response.text
        res_data = response.json()
        assert res_data["success"] is True
        assert res_data["status"] == "AMENDED_BY_HUMAN"
        assert "execution resumed" in res_data["message"]

        # Verify live PostgreSQL CHITRA audit event
        chitra_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.faculty == "MANUSH"
        ).order_by(ChitraEvent.id.desc()).all()

        assert len(chitra_events) >= 2
        latest_evt = chitra_events[0]
        assert latest_evt.outcome == "AMENDED_BY_HUMAN"
        assert latest_evt.decision.get("amended_action") == "calculate 100 + 25"
        assert latest_evt.decision.get("amended_parameters") == {"expression": "100 + 25"}
        assert latest_evt.this_event_hash.startswith("sha256:")
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_20_api_resolve_review_maryada_blocked_negative():
    """API resolve endpoint blocks dangerous invariant-violating amendment fail-closed (0 tool calls)."""
    from fastapi.testclient import TestClient
    from main import app
    from app.core.tenant import get_current_tenant, TenantContext
    from app.core.manush.service import manush_service

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_auditor_alice").first()
        if not user:
            user = User(username="api_auditor_alice", hashed_password="xyz", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        paused_plan = {
            "task_id": 9902,
            "summary": "Clean API Plan",
            "steps": [{"step_id": "s_clean", "action": "echo ok", "expected_outcome": "ok", "dependencies": []}]
        }
        task = Task(user_id=user.id, title="Danger Task", prompt="echo ok", status="HUMAN_REVIEW", plan=paused_plan)
        db.add(task)
        db.commit()
        db.refresh(task)

        # Update task_id in plan dict to match Task.id
        paused_plan["task_id"] = task.id
        task.plan = paused_plan
        db.commit()


        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="echo ok",
            step_id="s_clean",
            db_session=db,
            user_id=user.id
        )

        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "AMEND",
            "reviewer_id": "rogue_operator",
            "justification": "Malicious drop table injection",
            "signature": "valid_sig_rogue_999",
            "amended_action": "execute rm -rf /var/data --no-preserve-root",
            "amended_parameters": {}
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is False
        assert "resume blocked" in res_data["message"]

    finally:
        app.dependency_overrides.clear()
        db.close()


def test_21_api_resolve_review_tenant_mismatch_negative():
    """API resolve endpoint rejects cross-tenant review resolution with 404 (resource hiding)."""
    from fastapi.testclient import TestClient
    from main import app
    from app.core.tenant import get_current_tenant, TenantContext
    from app.core.manush.service import manush_service

    db = SessionLocal()
    try:
        user_alice = db.query(User).filter(User.username == "api_auditor_alice").first()
        task = Task(user_id=user_alice.id, title="Alice Secret Task", prompt="secret", status="HUMAN_REVIEW", plan={"steps": []})
        db.add(task)
        db.commit()
        db.refresh(task)

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user_alice.id}",
            action_summary="secret_op",
            db_session=db,
            user_id=user_alice.id
        )

        # Attacker Eve tenant
        eve_tenant_ctx = TenantContext(user_id=9999, username="eve_attacker", tenant_id="tenant_9999")
        app.dependency_overrides[get_current_tenant] = lambda: eve_tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "AMEND",
            "reviewer_id": "eve_hacker",
            "justification": "Unauthorized tenant cross-resolution",
            "signature": "valid_sig_eve_999",
            "amended_action": "calculate 1+1"
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_22_api_resolve_review_approve_regression():
    """APPROVE review resolution remains fully functional via API."""
    from fastapi.testclient import TestClient
    from main import app
    from app.core.tenant import get_current_tenant, TenantContext
    from app.core.manush.service import manush_service

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_auditor_alice").first()
        task = Task(user_id=user.id, title="Approve Task", prompt="calc", status="HUMAN_REVIEW", plan={"steps": []})
        db.add(task)
        db.commit()
        db.refresh(task)

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calc 10+10",
            db_session=db,
            user_id=user.id
        )

        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "APPROVE",
            "reviewer_id": "lead_secops_api",
            "justification": "Approved as safe by secops",
            "signature": "valid_sig_secops_123"
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is True
        assert res_data["status"] == "APPROVED_BY_HUMAN"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_23_api_resolve_review_reject_regression():
    """REJECT review resolution remains fully functional via API."""
    from fastapi.testclient import TestClient
    from main import app
    from app.core.tenant import get_current_tenant, TenantContext
    from app.core.manush.service import manush_service

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_auditor_alice").first()
        task = Task(user_id=user.id, title="Reject Task", prompt="calc", status="HUMAN_REVIEW", plan={"steps": []})
        db.add(task)
        db.commit()
        db.refresh(task)

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calc 10+10",
            db_session=db,
            user_id=user.id
        )

        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "REJECT",
            "reviewer_id": "lead_secops_api",
            "justification": "Rejected by secops: disallowed operation",
            "signature": "valid_sig_secops_123"
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is True
        assert res_data["status"] == "REJECTED_BY_HUMAN"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_24_api_resolve_review_malformed_plan_fails_closed():
    """Malformed persisted plan fails closed on AMEND resolve without guessing plan semantics."""
    from fastapi.testclient import TestClient
    from main import app
    from app.core.tenant import get_current_tenant, TenantContext
    from app.core.manush.service import manush_service

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_auditor_alice").first()

        # Malformed plan: missing expected_outcome and action
        malformed_plan = {
            "task_id": 9999,
            "steps": [{"step_id": ""}]  # Invalid empty step_id and missing fields
        }

        task = Task(user_id=user.id, title="Malformed Task", prompt="calc", status="HUMAN_REVIEW", plan=malformed_plan)
        db.add(task)
        db.commit()
        db.refresh(task)

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calc 10+10",
            step_id="step_1",
            db_session=db,
            user_id=user.id
        )

        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "AMEND",
            "reviewer_id": "secops_lead",
            "justification": "Amend calculation",
            "signature": "valid_sig_secops_123",
            "amended_action": "calculate 5+5",
            "amended_parameters": {"expression": "5+5"}
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        # With plan None (failed reconstruction), resolve_review records amendment but does not execute
        assert res_data["status"] == "AMENDED_BY_HUMAN"
        assert "execution resumed" not in res_data.get("message", "")
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_25_api_resolve_review_authority_token_propagation():
    """Privileged amendment propagates signed AuthorityToken header for HIGH-tier action."""
    from fastapi.testclient import TestClient
    from main import app
    from app.core.tenant import get_current_tenant, TenantContext
    from app.core.manush.service import manush_service
    from app.core.maryada.token import AuthorityToken
    from app.core.maryada.verdict import AuthorityTier

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "api_auditor_alice").first()

        paused_plan = {
            "task_id": 9903,
            "summary": "Privileged Task Plan",
            "steps": [
                {
                    "step_id": "s_priv",
                    "action": "calculate 10+10",
                    "expected_outcome": "20",
                    "dependencies": [],
                    "parameters": {"expression": "10+10"}
                }
            ]
        }
        task = Task(user_id=user.id, title="Privileged Task", prompt="calc", status="HUMAN_REVIEW", plan=paused_plan)
        db.add(task)
        db.commit()
        db.refresh(task)

        # Update task_id in plan
        paused_plan["task_id"] = task.id
        task.plan = paused_plan
        db.commit()

        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=f"tenant_{user.id}",
            action_summary="calculate 10+10",
            step_id="s_priv",
            db_session=db,
            user_id=user.id
        )

        tok = AuthorityToken.issue(
            tier=AuthorityTier.HIGH,
            scopes=["calculate*"],
            ttl_seconds=3600,
            signer_id="SECOPS_SIGNER_01",
            tenant_id=f"tenant_{user.id}"
        )

        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=f"tenant_{user.id}")
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)

        payload = {
            "decision": "AMEND",
            "reviewer_id": "secops_lead",
            "justification": "Elevated calculation with signed token",
            "signature": "valid_sig_secops_123",
            "amended_action": "calculate 500 + 500",
            "amended_parameters": {"expression": "500 + 500"},
            "authority_token": tok.encode()
        }

        response = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is True
        assert res_data["status"] == "AMENDED_BY_HUMAN"
        assert "execution resumed" in res_data["message"]
    finally:
        app.dependency_overrides.clear()
        db.close()




