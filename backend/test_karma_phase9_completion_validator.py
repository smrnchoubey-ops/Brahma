"""
KARMA Phase 9 Comprehensive Test Suite: Completion Validator & No-Silent-Actions
Strictly tests Whitesheet §§7.8 & 7.9 across 32 explicit scenarios.
Runs against local sandbox database: test_karma_phase9_sandbox.db.
"""
import pytest
import concurrent.futures
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.karma.tool_registry import KarmaToolDefinition, get_default_tool_registry
from app.core.karma.tool_router import KarmaToolRouter
from app.core.karma.executor import KarmaDAGExecutor
from app.core.karma.completion_validator import (
    KarmaCompletionValidator,
    KarmaCompletionValidationResult,
    KarmaNoSilentActionEvidence
)
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase9_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p9", hashed_password="pwd")
    user_b = User(username="user_bob_p9", hashed_password="pwd")
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
# A. COMPLETION VALIDATOR TESTS (§7.8) (1-10)
# -------------------------------------------------------------

def test_1_successful_completion():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()
    evt = chitra_repository.append_event(
        db=db, task_id=t_a, faculty="RACHIT", event_type="invocation",
        decision={"step_id": "s1"}, outcome="{'result': 42}", user_id=u_a
    )

    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="calculate 40 + 2", expected_outcome="42",
        actual_output={"result": 42}, status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calculator", authority_token="LOW", ledger_entry_ref=evt.event_id,
        db_session=db, expected_task_id=t_a, expected_user_id=u_a
    )
    assert res.is_valid is True
    assert res.status == "COMPLETED"
    assert res.success is True
    assert res.outcome_observed is True
    assert res.alignment_score == 1.0
    assert res.no_silent_action_valid is True
    db.close()


def test_2_outcome_not_observed_fails():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="calculate", expected_outcome="10",
        actual_output=None, status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calculator", authority_token="LOW", ledger_entry_ref="evt_123",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "INCOMPLETE_OUTCOME"
    assert res.outcome_observed is False


def test_3_failed_execution_fails_completion():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="calculate", expected_outcome="10",
        actual_output={"result": 10}, status="FAILED", verification_status="VERIFIED",
        tool_id="calculator", authority_token="LOW", ledger_entry_ref="evt_123",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


def test_4_failed_verification_fails_completion():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="calculate", expected_outcome="10",
        actual_output={"result": 999}, status="SUCCEEDED", verification_status="SEMANTIC_FAILURE",
        tool_id="calculator", authority_token="LOW", ledger_entry_ref="evt_123",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


def test_5_recovery_failure_fails_completion():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="O",
        actual_output=None, status="ESCALATED", verification_status=None,
        tool_id="calc", authority_token="LOW", ledger_entry_ref="evt_123",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


def test_6_alignment_score_calculation():
    res_good = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="O",
        actual_output={"result": "O"}, status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calc", authority_token="LOW", ledger_entry_ref="evt_123",
        require_ledger_ref=False
    )
    assert res_good.alignment_score == 1.0


def test_7_missing_completion_evidence_fails():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="", expected_outcome="",
        actual_output={"result": 10}, status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="", authority_token="", ledger_entry_ref="",
        require_ledger_ref=True
    )
    assert res.is_valid is False
    assert res.status == "SILENT_ACTION_BLOCKED"


def test_8_malformed_completion_evidence_fails():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="   ", expected_outcome="outcome",
        actual_output="out", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="tool", authority_token="LOW", ledger_entry_ref="evt_123",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "SILENT_ACTION_BLOCKED"


def test_9_deterministic_validation_result():
    res1 = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="exp",
        actual_output="act", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="tool", authority_token="LOW", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    res2 = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="exp",
        actual_output="act", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="tool", authority_token="LOW", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res1.model_dump() == res2.model_dump()


def test_10_repeated_validation_consistency():
    for _ in range(50):
        res = KarmaCompletionValidator.validate_step_completion(
            step_id="s1", action="act", expected_outcome="exp",
            actual_output="act", status="SUCCEEDED", verification_status="VERIFIED",
            tool_id="tool", authority_token="LOW", ledger_entry_ref="evt_1",
            require_ledger_ref=False
        )
        assert res.is_valid is True


# -------------------------------------------------------------
# B. NO-SILENT-ACTIONS TESTS (§7.9) (11-20)
# -------------------------------------------------------------

def test_11_complete_mandatory_evidence_accepted():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()
    evt = chitra_repository.append_event(
        db=db, task_id=t_a, faculty="RACHIT", event_type="invocation",
        decision={"step_id": "s1"}, outcome="res", user_id=u_a
    )

    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="Compute sum", expected_outcome="10",
        actual_output="10", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calculator", authority_token="LOW", ledger_entry_ref=evt.event_id,
        db_session=db, expected_task_id=t_a, expected_user_id=u_a
    )
    assert res.no_silent_action_valid is True
    assert "no_silent_action" in res.evidence_details
    db.close()


def test_12_missing_reason_rejected():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="", expected_outcome="10",
        actual_output="10", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calculator", authority_token="LOW", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "SILENT_ACTION_BLOCKED"
    assert "reason" in res.failure_reason


def test_13_missing_tool_rejected():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="10",
        actual_output="10", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id=None, authority_token="LOW", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "SILENT_ACTION_BLOCKED"
    assert "tool" in res.failure_reason


def test_14_missing_authority_token_rejected():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="10",
        actual_output="10", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calc", authority_token=None, ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "SILENT_ACTION_BLOCKED"
    assert "authority_token" in res.failure_reason


def test_15_missing_expected_outcome_rejected():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="",
        actual_output="10", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calc", authority_token="LOW", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "SILENT_ACTION_BLOCKED"
    assert "expected_outcome" in res.failure_reason


def test_16_missing_actual_outcome_rejected():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="10",
        actual_output=None, status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calc", authority_token="LOW", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "INCOMPLETE_OUTCOME"


def test_17_missing_ledger_reference_rejected():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="10",
        actual_output="10", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calc", authority_token="LOW", ledger_entry_ref=None,
        require_ledger_ref=True
    )
    assert res.is_valid is False
    assert res.status == "SILENT_ACTION_BLOCKED"
    assert "ledger_entry_ref" in res.failure_reason


def test_18_forged_nonexistent_ledger_reference_rejected():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="10",
        actual_output="10", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calc", authority_token="LOW", ledger_entry_ref="non_existent_evt_9999",
        db_session=db, expected_task_id=t_a, expected_user_id=u_a, require_ledger_ref=True
    )
    assert res.is_valid is False
    assert res.status == "AUDIT_VERIFICATION_FAILED"
    db.close()


def test_19_forged_authority_token_cannot_fabricate_completion():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="wire_transfer", expected_outcome="Transferred",
        actual_output="Done", status="FAILED", verification_status=None,
        tool_id="fin_tool", authority_token="CRITICAL", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


def test_20_completion_without_actual_invocation_rejected():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="calculate", expected_outcome="10",
        actual_output=None, status="PENDING", verification_status=None,
        tool_id="calculator", authority_token="LOW", ledger_entry_ref=None,
        require_ledger_ref=True
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


# -------------------------------------------------------------
# C. SECURITY & TENANT ISOLATION TESTS (21-26)
# -------------------------------------------------------------

def test_21_cross_tenant_ledger_reference_rejected():
    u_a, t_a, u_b, t_b = reset_sandbox()
    db = TestSession()

    # Bob logs an event
    evt_b = chitra_repository.append_event(
        db=db, task_id=t_b, faculty="RACHIT", event_type="invocation",
        decision={"step": "b1"}, outcome="ok", user_id=u_b
    )

    # Alice tries to use Bob's event ID to claim completion for Task A
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="ok",
        actual_output="ok", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calc", authority_token="LOW", ledger_entry_ref=evt_b.event_id,
        db_session=db, expected_task_id=t_a, expected_user_id=u_a, require_ledger_ref=True
    )
    assert res.is_valid is False
    assert res.status == "AUDIT_VERIFICATION_FAILED"
    assert "Security violation" in res.failure_reason
    db.close()


def test_22_cross_task_ledger_reference_rejected():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    # Create second task for Alice
    task_2 = Task(user_id=u_a, title="Task 2", prompt="P2", status="PENDING")
    db.add(task_2)
    db.commit()
    db.refresh(task_2)

    evt_t2 = chitra_repository.append_event(
        db=db, task_id=task_2.id, faculty="RACHIT", event_type="invocation",
        decision={"step": "t2_step"}, outcome="ok", user_id=u_a
    )

    # Try validating task t_a with task_2's event
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="act", expected_outcome="ok",
        actual_output="ok", status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calc", authority_token="LOW", ledger_entry_ref=evt_t2.event_id,
        db_session=db, expected_task_id=t_a, expected_user_id=u_a, require_ledger_ref=True
    )
    assert res.is_valid is False
    assert res.status == "AUDIT_VERIFICATION_FAILED"
    assert "Task mismatch" in res.failure_reason
    db.close()


def test_23_constitutional_block_cannot_become_success():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="bad_act", expected_outcome="secret",
        actual_output={"secret_key": "123"}, status="FAILED", verification_status="CONSTITUTIONAL_BLOCK",
        tool_id="bad_tool", authority_token="CRITICAL", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


def test_24_authority_rejection_cannot_become_success():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="settle", expected_outcome="Done",
        actual_output=None, status="FAILED", verification_status=None,
        tool_id="fin_tool", authority_token="LOW", ledger_entry_ref=None,
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


def test_25_exhausted_retry_cannot_become_success():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="flaky", expected_outcome="Done",
        actual_output=None, status="FAILED", verification_status="STRUCTURAL_FAILURE",
        tool_id="flaky_tool", authority_token="LOW", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


def test_26_recovery_failure_cannot_become_success():
    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="fatal", expected_outcome="Done",
        actual_output=None, status="ESCALATED", verification_status="SEMANTIC_FAILURE",
        tool_id="fatal_tool", authority_token="LOW", ledger_entry_ref="evt_1",
        require_ledger_ref=False
    )
    assert res.is_valid is False
    assert res.status == "REJECTED"


# -------------------------------------------------------------
# D. FULL RUNTIME INTEGRATION & CONCURRENCY TESTS (27-32)
# -------------------------------------------------------------

def test_27_phase7_to_phase9_full_pipeline_flow():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    s1 = KarmaStep(step_id="s1", action="calculate 15 * 4", expected_outcome="60", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="system_status", expected_outcome="OPERATIONAL", dependencies=["s1"])

    plan = KarmaPlanDAG(task_id=t_a, summary="Full Pipeline", steps=[s1, s2])
    report = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)

    assert report.status == "COMPLETED"
    assert report.step_results["s1"].completion_validation is not None
    assert report.step_results["s1"].completion_validation["status"] == "COMPLETED"
    assert report.step_results["s1"].completion_validation["no_silent_action_valid"] is True
    assert report.step_results["s2"].completion_validation["status"] == "COMPLETED"
    db.close()


def test_28_chitra_cryptographic_verification_integration():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    s1 = KarmaStep(step_id="s1", action="calculate 100 - 25", expected_outcome="75", dependencies=[])
    plan = KarmaPlanDAG(task_id=t_a, summary="Chitra Verif", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert report.status == "COMPLETED"

    # Verify whole chain
    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    db.close()


def test_29_real_tool_invocation_evidence_verified():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    s1 = KarmaStep(step_id="s1", action="echo Hello Brahma", expected_outcome="Hello Brahma", dependencies=[])
    plan = KarmaPlanDAG(task_id=t_a, summary="Echo Evid", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert report.status == "COMPLETED"
    assert report.step_results["s1"].completion_validation["evidence_details"]["no_silent_action"]["tool"] == "echo_formatter"
    db.close()


def test_30_concurrent_completion_validation_safety():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()
    evt = chitra_repository.append_event(
        db=db, task_id=t_a, faculty="RACHIT", event_type="invocation",
        decision={"s": "thread"}, outcome="10", user_id=u_a
    )

    def worker(i: int):
        local_db = TestSession()
        res = KarmaCompletionValidator.validate_step_completion(
            step_id=f"s_{i}", action="calculate 5+5", expected_outcome="10",
            actual_output=10, status="SUCCEEDED", verification_status="VERIFIED",
            tool_id="calculator", authority_token="LOW", ledger_entry_ref=evt.event_id,
            db_session=local_db, expected_task_id=t_a, expected_user_id=u_a
        )
        local_db.close()
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(25)]
        results = [f.result() for f in futures]

    assert len(results) == 25
    assert all(r.is_valid is True for r in results)
    db.close()


def test_31_tampered_ledger_entry_fails_closed():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    evt = chitra_repository.append_event(
        db=db, task_id=t_a, faculty="RACHIT", event_type="invocation",
        decision={"s": "tamper"}, outcome="10", user_id=u_a
    )

    # Tamper with the event in DB (change signature)
    evt.signature = "tampered_signature_0000"
    db.commit()

    res = KarmaCompletionValidator.validate_step_completion(
        step_id="s1", action="calculate", expected_outcome="10",
        actual_output=10, status="SUCCEEDED", verification_status="VERIFIED",
        tool_id="calculator", authority_token="LOW", ledger_entry_ref=evt.event_id,
        db_session=db, expected_task_id=t_a, expected_user_id=u_a
    )
    assert res.is_valid is False
    assert res.status == "AUDIT_VERIFICATION_FAILED"
    assert "Cryptographic chain verification failed" in res.failure_reason
    db.close()


def test_32_no_phase10_functionality_introduced():
    # Verify strict Phase 9 boundary
    assert not hasattr(KarmaCompletionValidator, "episodic_memory_handoff")
    assert not hasattr(KarmaCompletionValidator, "phase_10_controller")


def run_all_32_phase9_tests():
    print("==================================================")
    print("KARMA PHASE 9: 32-SCENARIO COMPLETION VALIDATOR &")
    print("NO-SILENT-ACTIONS SUITE (WHITESHEET §§7.8-7.9)")
    print("Target Sandbox: sqlite:///./test_karma_phase9_sandbox.db")
    print("==================================================")

    test_1_successful_completion()
    print("  [PASS 1/32] Successful completion validation.")

    test_2_outcome_not_observed_fails()
    print("  [PASS 2/32] Outcome not observed fails completion.")

    test_3_failed_execution_fails_completion()
    print("  [PASS 3/32] Failed execution fails completion.")

    test_4_failed_verification_fails_completion()
    print("  [PASS 4/32] Failed verification fails completion.")

    test_5_recovery_failure_fails_completion()
    print("  [PASS 5/32] Recovery failure fails completion.")

    test_6_alignment_score_calculation()
    print("  [PASS 6/32] Alignment score calculation (§7.8).")

    test_7_missing_completion_evidence_fails()
    print("  [PASS 7/32] Missing completion evidence fails.")

    test_8_malformed_completion_evidence_fails()
    print("  [PASS 8/32] Malformed completion evidence fails.")

    test_9_deterministic_validation_result()
    print("  [PASS 9/32] Deterministic validation result.")

    test_10_repeated_validation_consistency()
    print("  [PASS 10/32] Repeated validation consistency.")

    test_11_complete_mandatory_evidence_accepted()
    print("  [PASS 11/32] Complete No-Silent-Actions evidence accepted.")

    test_12_missing_reason_rejected()
    print("  [PASS 12/32] Missing reason rejected (§7.9).")

    test_13_missing_tool_rejected()
    print("  [PASS 13/32] Missing tool rejected (§7.9).")

    test_14_missing_authority_token_rejected()
    print("  [PASS 14/32] Missing authority_token rejected (§7.9).")

    test_15_missing_expected_outcome_rejected()
    print("  [PASS 15/32] Missing expected_outcome rejected (§7.9).")

    test_16_missing_actual_outcome_rejected()
    print("  [PASS 16/32] Missing actual_outcome rejected (§7.9).")

    test_17_missing_ledger_reference_rejected()
    print("  [PASS 17/32] Missing ledger_entry_ref rejected (§7.9).")

    test_18_forged_nonexistent_ledger_reference_rejected()
    print("  [PASS 18/32] Forged nonexistent ledger reference rejected.")

    test_19_forged_authority_token_cannot_fabricate_completion()
    print("  [PASS 19/32] Forged authority token cannot fabricate completion.")

    test_20_completion_without_actual_invocation_rejected()
    print("  [PASS 20/32] Completion without actual invocation rejected.")

    test_21_cross_tenant_ledger_reference_rejected()
    print("  [PASS 21/32] Cross-tenant ledger reference rejected (§4C/§7.9).")

    test_22_cross_task_ledger_reference_rejected()
    print("  [PASS 22/32] Cross-task ledger reference rejected.")

    test_23_constitutional_block_cannot_become_success()
    print("  [PASS 23/32] Constitutional block cannot become success.")

    test_24_authority_rejection_cannot_become_success()
    print("  [PASS 24/32] Authority rejection cannot become success.")

    test_25_exhausted_retry_cannot_become_success()
    print("  [PASS 25/32] Exhausted retry cannot become success.")

    test_26_recovery_failure_cannot_become_success()
    print("  [PASS 26/32] Recovery failure cannot become success.")

    test_27_phase7_to_phase9_full_pipeline_flow()
    print("  [PASS 27/32] Full pipeline: Phase 7 -> Phase 8 -> Phase 9.")

    test_28_chitra_cryptographic_verification_integration()
    print("  [PASS 28/32] CHITRA cryptographic verification integration.")

    test_29_real_tool_invocation_evidence_verified()
    print("  [PASS 29/32] Real tool invocation evidence verified.")

    test_30_concurrent_completion_validation_safety()
    print("  [PASS 30/32] Concurrent completion validation safety.")

    test_31_tampered_ledger_entry_fails_closed()
    print("  [PASS 31/32] Tampered ledger entry fails closed.")

    test_32_no_phase10_functionality_introduced()
    print("  [PASS 32/32] Phase 10 boundary verified (0 Phase 10 features).")

    print("\n==================================================")
    print("ALL 32 KARMA PHASE 9 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_32_phase9_tests()
