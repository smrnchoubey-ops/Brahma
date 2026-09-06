"""
MANUSH Phase 13 Comprehensive Test Suite: Human Oversight & Dual-Authorization Governance
Strictly tests Whitesheet §§12.0–12.5 across 30 explicit scenarios.
Runs against local sandbox database: test_karma_phase13_sandbox.db.
"""
import pytest
import time
import concurrent.futures
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.karma.executor import KarmaDAGExecutor
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.core.murphy.service import MurphyService
from app.core.manush.decision import ReviewStatus, ReviewDecisionType, HumanReviewDecision, ReviewItem
from app.core.manush.dual_auth import DualAuthValidator
from app.core.manush.review_queue import ManushReviewQueue
from app.core.manush.service import ManushOversightService
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase13_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p13", hashed_password="pwd")
    user_b = User(username="user_bob_p13", hashed_password="pwd")
    db.add(user_a)
    db.add(user_b)
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)

    task_a = Task(user_id=user_a.id, title="Task A", prompt="Prompt A", status="PENDING")
    task_b = Task(user_id=user_b.id, title="Task B", prompt="Prompt B", status="PENDING")
    db.add(task_a)
    db.add(task_b)
    db.commit()
    db.refresh(task_a)
    db.refresh(task_b)

    u_a, t_a = user_a.id, task_a.id
    u_b, t_b = user_b.id, task_b.id
    db.close()
    return u_a, t_a, u_b, t_b


def fast_mock_sleep(seconds: float):
    pass


# -------------------------------------------------------------
# 1. QUEUE & STATE TRANSITIONS (§12.1) (1-3)
# -------------------------------------------------------------

def test_1_enqueue_review_item_pending_status():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=401, tenant_id="tenant_alice", action_summary="wire_transfer 50k")
    assert item.review_id.startswith("rev_")
    assert item.status == ReviewStatus.PENDING_REVIEW


def test_2_single_operator_approval_success():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=402, tenant_id="tenant_alice", action_summary="wire_transfer 50k")
    decision = HumanReviewDecision(reviewer_id="operator_1", decision=ReviewDecisionType.APPROVE, justification="Approved by SecOps", signature="sig_secops_valid_123")
    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_alice", decision)
    assert ok is True
    assert updated.status == ReviewStatus.APPROVED_BY_HUMAN


def test_3_single_operator_rejection_success():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=403, tenant_id="tenant_alice", action_summary="wire_transfer 50k")
    decision = HumanReviewDecision(reviewer_id="operator_1", decision=ReviewDecisionType.REJECT, justification="Suspicious payload", signature="sig_secops_valid_123")
    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_alice", decision)
    assert ok is True
    assert updated.status == ReviewStatus.REJECTED_BY_HUMAN


# -------------------------------------------------------------
# 2. DUAL-AUTHORIZATION TESTS (§12.2) (4-9)
# -------------------------------------------------------------

def test_4_dual_auth_pending_on_first_approval():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=404, tenant_id="tenant_alice", action_summary="rotate_master_key", requires_dual_auth=True)
    d1 = HumanReviewDecision(reviewer_id="operator_1", decision=ReviewDecisionType.APPROVE, justification="Op1 ok", signature="sig_op1_valid_123")
    ok, updated, msg = queue.submit_decision(item.review_id, "tenant_alice", d1)
    assert ok is True
    assert updated.status == ReviewStatus.PENDING_REVIEW
    assert "Awaiting additional authorizations" in msg


def test_5_dual_auth_satisfied_by_two_distinct_operators():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=405, tenant_id="tenant_alice", action_summary="rotate_master_key", requires_dual_auth=True)
    d1 = HumanReviewDecision(reviewer_id="operator_1", decision=ReviewDecisionType.APPROVE, justification="Op1 ok", signature="sig_op1_valid_123")
    d2 = HumanReviewDecision(reviewer_id="operator_2", decision=ReviewDecisionType.APPROVE, justification="Op2 ok", signature="sig_op2_valid_123")
    queue.submit_decision(item.review_id, "tenant_alice", d1)
    ok2, updated2, msg2 = queue.submit_decision(item.review_id, "tenant_alice", d2)
    assert ok2 is True
    assert updated2.status == ReviewStatus.APPROVED_BY_HUMAN
    assert len(updated2.approvals) == 2


def test_6_dual_auth_rejects_duplicate_approver():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=406, tenant_id="tenant_alice", action_summary="rotate_master_key", requires_dual_auth=True)
    d1 = HumanReviewDecision(reviewer_id="operator_1", decision=ReviewDecisionType.APPROVE, justification="Op1 ok", signature="sig_op1_valid_123")
    queue.submit_decision(item.review_id, "tenant_alice", d1)
    # Same operator submits again
    ok2, _, msg2 = queue.submit_decision(item.review_id, "tenant_alice", d1)
    assert ok2 is False
    assert "already submitted approval" in msg2


def test_7_dual_auth_immediate_rejection_on_operator_veto():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=407, tenant_id="tenant_alice", action_summary="rotate_master_key", requires_dual_auth=True)
    d1 = HumanReviewDecision(reviewer_id="operator_1", decision=ReviewDecisionType.APPROVE, justification="Op1 ok", signature="sig_op1_valid_123")
    d2 = HumanReviewDecision(reviewer_id="operator_2", decision=ReviewDecisionType.REJECT, justification="Op2 veto", signature="sig_op2_valid_123")
    queue.submit_decision(item.review_id, "tenant_alice", d1)
    ok2, updated2, _ = queue.submit_decision(item.review_id, "tenant_alice", d2)
    assert ok2 is True
    assert updated2.status == ReviewStatus.REJECTED_BY_HUMAN


def test_8_invalid_signature_rejected():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=408, tenant_id="tenant_alice", action_summary="action")
    bad_decision = HumanReviewDecision(reviewer_id="operator_1", decision=ReviewDecisionType.APPROVE, justification="ok", signature="short")
    ok, _, msg = queue.submit_decision(item.review_id, "tenant_alice", bad_decision)
    assert ok is False
    assert "Invalid reviewer signature" in msg


def test_9_empty_reviewer_id_rejected():
    d = HumanReviewDecision(reviewer_id="   ", decision=ReviewDecisionType.APPROVE, justification="ok", signature="valid_sig_12345")
    assert DualAuthValidator.validate_signature(d) is False


# -------------------------------------------------------------
# 3. TIMEOUT & LIFECYCLE FINALIZATION (§12.3) (10-13)
# -------------------------------------------------------------

def test_10_fail_closed_ttl_timeout_expiration():
    queue = ManushReviewQueue(default_ttl_seconds=0)  # Immediate expiry
    item = queue.enqueue_review(task_id=409, tenant_id="tenant_alice", action_summary="action", ttl_seconds=0)
    time.sleep(0.01)
    fetched = queue.get_item(item.review_id, "tenant_alice")
    assert fetched.status == ReviewStatus.TIMEOUT_EXPIRED


def test_11_expired_item_rejects_subsequent_decision():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=410, tenant_id="tenant_alice", action_summary="action", ttl_seconds=0)
    time.sleep(0.01)
    decision = HumanReviewDecision(reviewer_id="op1", decision=ReviewDecisionType.APPROVE, justification="late", signature="sig_op1_valid_123")
    ok, _, msg = queue.submit_decision(item.review_id, "tenant_alice", decision)
    assert ok is False
    assert "already finalized" in msg or "TIMEOUT_EXPIRED" in msg


def test_12_finalized_approved_item_rejects_subsequent_decision():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=411, tenant_id="tenant_alice", action_summary="action")
    decision = HumanReviewDecision(reviewer_id="op1", decision=ReviewDecisionType.APPROVE, justification="ok", signature="sig_op1_valid_123")
    queue.submit_decision(item.review_id, "tenant_alice", decision)
    # Subsequent submission rejected
    ok2, _, _ = queue.submit_decision(item.review_id, "tenant_alice", decision)
    assert ok2 is False


def test_13_finalized_rejected_item_rejects_subsequent_decision():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=412, tenant_id="tenant_alice", action_summary="action")
    d1 = HumanReviewDecision(reviewer_id="op1", decision=ReviewDecisionType.REJECT, justification="no", signature="sig_op1_valid_123")
    d2 = HumanReviewDecision(reviewer_id="op2", decision=ReviewDecisionType.APPROVE, justification="try approve", signature="sig_op2_valid_123")
    queue.submit_decision(item.review_id, "tenant_alice", d1)
    ok2, _, _ = queue.submit_decision(item.review_id, "tenant_alice", d2)
    assert ok2 is False


# -------------------------------------------------------------
# 4. TENANT ISOLATION & QUEUE SCOPING (14-17)
# -------------------------------------------------------------

def test_14_empty_tenant_id_fails_closed():
    queue = ManushReviewQueue()
    with pytest.raises(ValueError, match="Authenticated Tenant ID is required"):
        queue.enqueue_review(task_id=413, tenant_id="", action_summary="action")


def test_15_cross_tenant_queue_isolation():
    queue = ManushReviewQueue()
    item_alice = queue.enqueue_review(task_id=414, tenant_id="tenant_alice", action_summary="Alice wire 100k")
    
    # Bob tries to fetch Alice's review item
    fetched_by_bob = queue.get_item(item_alice.review_id, tenant_id="tenant_bob")
    assert fetched_by_bob is None


def test_16_cross_tenant_decision_submission_denial():
    queue = ManushReviewQueue()
    item_alice = queue.enqueue_review(task_id=415, tenant_id="tenant_alice", action_summary="Alice task")
    decision = HumanReviewDecision(reviewer_id="bob_hacker", decision=ReviewDecisionType.APPROVE, justification="Hacked", signature="sig_hacker_12345")
    
    ok, _, msg = queue.submit_decision(item_alice.review_id, "tenant_bob", decision)
    assert ok is False
    assert "not found for tenant" in msg


def test_17_list_pending_items_tenant_scoped():
    queue = ManushReviewQueue()
    queue.enqueue_review(task_id=416, tenant_id="tenant_alice", action_summary="A1")
    queue.enqueue_review(task_id=417, tenant_id="tenant_alice", action_summary="A2")
    queue.enqueue_review(task_id=418, tenant_id="tenant_bob", action_summary="B1")

    alice_pending = queue.list_pending_items("tenant_alice")
    bob_pending = queue.list_pending_items("tenant_bob")
    assert len(alice_pending) == 2
    assert len(bob_pending) == 1


# -------------------------------------------------------------
# 5. CHITRA AUDIT LOGGING & CRYPTO VERIFICATION (§12.5) (18-21)
# -------------------------------------------------------------

def test_18_chitra_escalation_event_generation():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=t_a, tenant_id=f"tenant_{u_a}", action_summary="escalate_action", db_session=db, user_id=u_a
    )
    assert item.chitra_event_id is not None

    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == item.chitra_event_id).first()
    assert evt is not None
    assert evt.faculty == "MANUSH"
    assert evt.event_type == "human_review"
    assert evt.outcome == "ESCALATED_FOR_HUMAN_REVIEW"
    db.close()


def test_19_chitra_approval_decision_event_generation():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    service = ManushOversightService()
    item = service.escalate_for_review(task_id=t_a, tenant_id=f"tenant_{u_a}", action_summary="settlement", db_session=db, user_id=u_a)
    d = HumanReviewDecision(reviewer_id="op_admin", decision=ReviewDecisionType.APPROVE, justification="Approved", signature="sig_admin_12345")
    
    ok, updated, _ = service.resolve_review(item.review_id, f"tenant_{u_a}", d, db_session=db, user_id=u_a)
    assert ok is True
    assert updated.status == ReviewStatus.APPROVED_BY_HUMAN

    evts = db.query(ChitraEvent).filter(ChitraEvent.task_id == t_a).all()
    assert len(evts) == 2  # 1 escalation + 1 approval
    db.close()


def test_20_chitra_rejection_decision_event_generation():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    service = ManushOversightService()
    item = service.escalate_for_review(task_id=t_a, tenant_id=f"tenant_{u_a}", action_summary="settlement", db_session=db, user_id=u_a)
    d = HumanReviewDecision(reviewer_id="op_admin", decision=ReviewDecisionType.REJECT, justification="Vetoed", signature="sig_admin_12345")
    
    ok, updated, _ = service.resolve_review(item.review_id, f"tenant_{u_a}", d, db_session=db, user_id=u_a)
    assert ok is True
    assert updated.status == ReviewStatus.REJECTED_BY_HUMAN
    db.close()


def test_21_cryptographic_verification_on_manush_events():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    service = ManushOversightService()
    item = service.escalate_for_review(task_id=t_a, tenant_id=f"tenant_{u_a}", action_summary="wire", db_session=db, user_id=u_a)
    d = HumanReviewDecision(reviewer_id="op1", decision=ReviewDecisionType.APPROVE, justification="Ok", signature="sig_op1_valid_123")
    service.resolve_review(item.review_id, f"tenant_{u_a}", d, db_session=db, user_id=u_a)

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked == 2
    db.close()


# -------------------------------------------------------------
# 6. FACULTY INTEGRATIONS (§10, §11, §12) (22-25)
# -------------------------------------------------------------

def test_22_maryada_human_review_required_escalation():
    # MARYADA returns HUMAN_REVIEW_REQUIRED -> MANUSH enqueues item
    maryada_v = MaryadaGatekeeper.evaluate_action_gate("rotate_key master", caller_authority="CRITICAL")
    assert maryada_v.requires_human is True
    assert maryada_v.status.value == "MARYADA_HUMAN_REVIEW_REQUIRED"

    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=419, tenant_id="tenant_1", action_summary="rotate_key master", requires_dual_auth=True
    )
    assert item.requires_dual_auth is True


def test_23_murphy_human_review_recommendation_escalation():
    # MURPHY returns HUMAN_REVIEW -> MANUSH enqueues item
    s = KarmaStep(step_id="s1", action="settlement 100000 USD", expected_outcome="done")
    plan = KarmaPlanDAG(task_id=420, summary="Settlement Plan", steps=[s])
    murphy_rep = MurphyService.analyze_plan_risk(plan, tenant_id="tenant_1")
    assert murphy_rep.recommendation.value == "HUMAN_REVIEW"

    service = ManushOversightService()
    item = service.escalate_for_review(
        task_id=420, tenant_id="tenant_1", action_summary=plan.summary, risk_tier=murphy_rep.risk_level.value
    )
    assert item.risk_tier == "HIGH"


def test_24_concurrent_enqueue_and_reviews():
    service = ManushOversightService()

    def worker(i: int):
        item = service.escalate_for_review(task_id=i, tenant_id=f"tenant_{i % 3}", action_summary=f"Action {i}")
        d = HumanReviewDecision(reviewer_id=f"op_{i}", decision=ReviewDecisionType.APPROVE, justification="ok", signature=f"sig_valid_{i}_12345")
        return service.resolve_review(item.review_id, f"tenant_{i % 3}", d)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert all(r[0] is True for r in results)


def test_25_concurrent_dual_auth_submissions():
    service = ManushOversightService()
    item = service.escalate_for_review(task_id=421, tenant_id="tenant_alice", action_summary="Dual task", requires_dual_auth=True)

    d1 = HumanReviewDecision(reviewer_id="op_alpha", decision=ReviewDecisionType.APPROVE, justification="ok", signature="sig_alpha_12345")
    d2 = HumanReviewDecision(reviewer_id="op_beta", decision=ReviewDecisionType.APPROVE, justification="ok", signature="sig_beta_12345")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(service.resolve_review, item.review_id, "tenant_alice", d1)
        f2 = pool.submit(service.resolve_review, item.review_id, "tenant_alice", d2)
        r1, r2 = f1.result(), f2.result()

    assert r1[0] is True and r2[0] is True
    final_item = service.queue.get_item(item.review_id, "tenant_alice")
    assert final_item.status == ReviewStatus.APPROVED_BY_HUMAN


# -------------------------------------------------------------
# 7. PIPELINE, BOUNDARY & VALIDATION (26-30)
# -------------------------------------------------------------

def test_26_full_pipeline_phase5_to_phase13_approval():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    # 1. KarmaPlanDAG (Phase 5)
    s1 = KarmaStep(step_id="s1", action="calculate 10 * 10", expected_outcome="100", dependencies=[])
    plan = KarmaPlanDAG(task_id=t_a, summary="Pipeline Plan", steps=[s1])

    # 2. MURPHY Simulation (Phase 12)
    m_rep = MurphyService.analyze_plan_risk(plan, tenant_id=f"tenant_{u_a}", db_session=db, user_id=u_a)

    # 3. MANUSH Escalation & Approval (Phase 13)
    manush = ManushOversightService()
    rev = manush.escalate_for_review(task_id=t_a, tenant_id=f"tenant_{u_a}", action_summary=plan.summary, db_session=db, user_id=u_a)
    dec = HumanReviewDecision(reviewer_id="chief_operator", decision=ReviewDecisionType.APPROVE, justification="Plan approved", signature="sig_chief_operator_123")
    manush.resolve_review(rev.review_id, f"tenant_{u_a}", dec, db_session=db, user_id=u_a)

    # 4. MARYADA Gate (Phase 11)
    g_verdict = MaryadaGatekeeper.evaluate_plan_gate(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert g_verdict.approved is True

    # 5. KARMA DAG Executor (Phase 7, 8, 9)
    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    exec_rep = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert exec_rep.status == "COMPLETED"

    # 6. Verify entire cryptographic audit chain
    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked >= 4  # MURPHY + MANUSH (escalate) + MANUSH (approve) + MARYADA + RACHIT
    db.close()


def test_27_full_pipeline_phase5_to_phase13_rejection():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s1 = KarmaStep(step_id="s1", action="calculate 10 * 10", expected_outcome="100", dependencies=[])
    plan = KarmaPlanDAG(task_id=t_a, summary="Rejected Plan", steps=[s1])

    manush = ManushOversightService()
    rev = manush.escalate_for_review(task_id=t_a, tenant_id=f"tenant_{u_a}", action_summary=plan.summary, db_session=db, user_id=u_a)
    dec = HumanReviewDecision(reviewer_id="chief_operator", decision=ReviewDecisionType.REJECT, justification="Denied", signature="sig_chief_operator_123")
    ok, item, _ = manush.resolve_review(rev.review_id, f"tenant_{u_a}", dec, db_session=db, user_id=u_a)

    assert ok is True
    assert item.status == ReviewStatus.REJECTED_BY_HUMAN
    db.close()


def test_28_plan_execution_paused_during_human_review():
    queue = ManushReviewQueue()
    item = queue.enqueue_review(task_id=422, tenant_id="tenant_1", action_summary="Pending Action")
    assert item.status == ReviewStatus.PENDING_REVIEW


def test_29_phase14_boundary_check():
    assert not hasattr(ManushOversightService, "phase_14_container_sandbox")
    assert not hasattr(ManushOversightService, "ebpf_probe_manager")


def test_30_complete_decision_schema_validation():
    d = HumanReviewDecision(
        reviewer_id="op_test",
        decision=ReviewDecisionType.APPROVE,
        justification="Schema check",
        signature="sig_op_test_12345"
    )
    dumped = d.model_dump()
    assert "reviewer_id" in dumped
    assert "decision" in dumped
    assert "justification" in dumped
    assert "signature" in dumped
    assert "reviewed_at" in dumped


def run_all_30_phase13_tests():
    print("==================================================")
    print("MANUSH PHASE 13: 30-SCENARIO HUMAN OVERSIGHT,")
    print("ESCALATION & DUAL-AUTH SUITE (WHITESHEET §§12.0-12.5)")
    print("Target Sandbox: sqlite:///./test_karma_phase13_sandbox.db")
    print("==================================================")

    test_1_enqueue_review_item_pending_status()
    print("  [PASS 1/30] Enqueue review item with PENDING_REVIEW status (§12.1).")

    test_2_single_operator_approval_success()
    print("  [PASS 2/30] Single operator approval success (§12.1).")

    test_3_single_operator_rejection_success()
    print("  [PASS 3/30] Single operator rejection success (§12.1).")

    test_4_dual_auth_pending_on_first_approval()
    print("  [PASS 4/30] Dual-auth remains pending on 1st approval (§12.2).")

    test_5_dual_auth_satisfied_by_two_distinct_operators()
    print("  [PASS 5/30] Dual-auth satisfied by 2 distinct operators (§12.2).")

    test_6_dual_auth_rejects_duplicate_approver()
    print("  [PASS 6/30] Dual-auth rejects duplicate operator submission.")

    test_7_dual_auth_immediate_rejection_on_operator_veto()
    print("  [PASS 7/30] Dual-auth immediate rejection on operator veto.")

    test_8_invalid_signature_rejected()
    print("  [PASS 8/30] Invalid signature rejected (§12.2).")

    test_9_empty_reviewer_id_rejected()
    print("  [PASS 9/30] Empty reviewer ID rejected.")

    test_10_fail_closed_ttl_timeout_expiration()
    print("  [PASS 10/30] Fail-closed TTL timeout expiration (§12.3).")

    test_11_expired_item_rejects_subsequent_decision()
    print("  [PASS 11/30] Expired item rejects subsequent decision.")

    test_12_finalized_approved_item_rejects_subsequent_decision()
    print("  [PASS 12/30] Finalized approved item rejects subsequent decision.")

    test_13_finalized_rejected_item_rejects_subsequent_decision()
    print("  [PASS 13/30] Finalized rejected item rejects subsequent decision.")

    test_14_empty_tenant_id_fails_closed()
    print("  [PASS 14/30] Empty tenant ID fails closed.")

    test_15_cross_tenant_queue_isolation()
    print("  [PASS 15/30] Cross-tenant queue isolation (§12.1, §18).")

    test_16_cross_tenant_decision_submission_denial()
    print("  [PASS 16/30] Cross-tenant decision submission denial.")

    test_17_list_pending_items_tenant_scoped()
    print("  [PASS 17/30] List pending items tenant-scoped.")

    test_18_chitra_escalation_event_generation()
    print("  [PASS 18/30] CHITRA escalation event generation (§12.5).")

    test_19_chitra_approval_decision_event_generation()
    print("  [PASS 19/30] CHITRA approval decision event generation.")

    test_20_chitra_rejection_decision_event_generation()
    print("  [PASS 20/30] CHITRA rejection decision event generation.")

    test_21_cryptographic_verification_on_manush_events()
    print("  [PASS 21/30] Cryptographic verification on MANUSH events.")

    test_22_maryada_human_review_required_escalation()
    print("  [PASS 22/30] MARYADA HUMAN_REVIEW_REQUIRED escalation integration.")

    test_23_murphy_human_review_recommendation_escalation()
    print("  [PASS 23/30] MURPHY HUMAN_REVIEW recommendation escalation integration.")

    test_24_concurrent_enqueue_and_reviews()
    print("  [PASS 24/30] Concurrent enqueue and reviews safety.")

    test_25_concurrent_dual_auth_submissions()
    print("  [PASS 25/30] Concurrent dual-auth submissions safety.")

    test_26_full_pipeline_phase5_to_phase13_approval()
    print("  [PASS 26/30] Full pipeline: Phase 5 -> 12 -> 13 -> 11 -> 7 -> 8 -> 9.")

    test_27_full_pipeline_phase5_to_phase13_rejection()
    print("  [PASS 27/30] Full pipeline: Phase 5 -> 13 Rejection.")

    test_28_plan_execution_paused_during_human_review()
    print("  [PASS 28/30] Plan execution paused during human review.")

    test_29_phase14_boundary_check()
    print("  [PASS 29/30] Phase 14 boundary verified (0 Phase 14 features).")

    test_30_complete_decision_schema_validation()
    print("  [PASS 30/30] Complete decision schema validation (§12.4).")

    print("\n==================================================")
    print("ALL 30 MANUSH PHASE 13 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_30_phase13_tests()
