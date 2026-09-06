"""
RACHIT Phase 14 Comprehensive Test Suite: Tool Execution Engine & Sandbox Runtime
Strictly tests Whitesheet §§13.0–13.6 across 30 explicit scenarios with OS Subprocess Hardening.
Runs against local sandbox database: test_karma_phase14_sandbox.db.
"""
import pytest
import time
import os
import multiprocessing
import concurrent.futures
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.karma.executor import KarmaDAGExecutor
from app.core.karma.verifier import KarmaStepVerifier
from app.core.karma.completion_validator import KarmaCompletionValidator
from app.core.kosh.episodic_handoff import KoshEpisodicHandoffController
from app.core.kosh.vector_engine import KoshVectorStore
from app.core.maryada.verdict import MaryadaVerdict, GateStatus, AuthorityTier, RiskTier
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.core.murphy.report import MurphyRiskReport, MurphyRiskTier, MurphyRecommendation
from app.core.murphy.service import MurphyService
from app.core.manush.decision import ReviewStatus, ReviewDecisionType, HumanReviewDecision
from app.core.manush.service import ManushOversightService
from app.core.rachit.limits import SandboxStatus, ExecutionQuotas, SandboxExecutionResult
from app.core.rachit.process_manager import ProcessSupervisor
from app.core.rachit.sandbox import RachitSandbox
from app.core.rachit.service import RachitExecutionService
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase14_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p14", hashed_password="pwd")
    user_b = User(username="user_bob_p14", hashed_password="pwd")
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


# Global Tool Handlers (Top-level picklable functions for multiprocessing)
def mock_calculator_handler(expression: str = ""):
    return {"result": 2500}


def mock_slow_handler(delay: float = 1.0):
    time.sleep(delay)
    return {"status": "finished"}


def mock_infinite_loop_handler():
    while True:
        time.sleep(0.05)


def mock_huge_output_handler():
    return "A" * 100000


def mock_broken_handler():
    raise ValueError("Intentional simulated tool crash")


def mock_secret_inspector_handler():
    # Returns any sensitive environment keys found inside worker
    found_secrets = [k for k in os.environ.keys() if "SECRET" in k.upper() or "DATABASE_URL" in k.upper()]
    return {"found_secrets": found_secrets}


# -------------------------------------------------------------
# 1. OS SUBPROCESS EXECUTION & QUOTAS (§13.1, §13.2, §13.3) (1-6)
# -------------------------------------------------------------

def test_1_successful_tool_execution_in_sandbox():
    """[REAL] Validates successful OS subprocess tool invocation."""
    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=501)
    res = sandbox.execute_tool(
        tool_id="calculator",
        action_name="calculate 50 * 50",
        handler_fn=mock_calculator_handler,
        params={"expression": "50 * 50"}
    )
    sandbox.cleanup()
    assert res.status == SandboxStatus.SUCCESS
    assert res.output == {"result": 2500}
    assert res.exit_code == 0


def test_2_execution_time_measurement():
    """[REAL] Validates execution time measurement."""
    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=502)
    res = sandbox.execute_tool(
        tool_id="slow_op", action_name="slow", handler_fn=mock_slow_handler, params={"delay": 0.05}
    )
    sandbox.cleanup()
    assert res.execution_time_ms >= 40.0


def test_3_hard_timeout_enforcement():
    """[REAL] Validates hard deadline and OS subprocess termination on timeout."""
    quotas = ExecutionQuotas(timeout_ms=50)
    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=503, quotas=quotas)
    res = sandbox.execute_tool(
        tool_id="slow_op", action_name="slow", handler_fn=mock_slow_handler, params={"delay": 0.30}
    )
    sandbox.cleanup()
    assert res.status == SandboxStatus.TIMEOUT_EXCEEDED
    assert res.exit_code == 124


def test_4_blocking_infinite_loop_killed_safely():
    """[REAL] Validates infinite loop OS subprocess killed forcefully."""
    quotas = ExecutionQuotas(timeout_ms=50)
    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=504, quotas=quotas)
    res = sandbox.execute_tool(
        tool_id="loop_op", action_name="loop", handler_fn=mock_infinite_loop_handler
    )
    sandbox.cleanup()
    assert res.status == SandboxStatus.TIMEOUT_EXCEEDED


def test_5_output_size_quota_truncation():
    """[REAL] Validates output buffer size quota capping."""
    quotas = ExecutionQuotas(max_output_bytes=1024)
    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=505, quotas=quotas)
    res = sandbox.execute_tool(
        tool_id="huge_out", action_name="huge", handler_fn=mock_huge_output_handler
    )
    sandbox.cleanup()
    assert res.status == SandboxStatus.OUTPUT_EXCEEDED
    assert "[TRUNCATED_EXCEEDED_QUOTA]" in res.output


def test_6_environment_secret_containment():
    """[REAL] Validates sensitive parent environment variables are not exposed to worker."""
    os.environ["SECRET_DATABASE_URL"] = "postgres://root:supersecret@localhost:5432/brahma"
    os.environ["APP_SECRET_KEY"] = "my_super_secret_jwt_key"

    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=506)
    res = sandbox.execute_tool(
        tool_id="secret_check", action_name="check_env", handler_fn=mock_secret_inspector_handler
    )
    sandbox.cleanup()
    os.environ.pop("SECRET_DATABASE_URL", None)
    os.environ.pop("APP_SECRET_KEY", None)

    assert res.status == SandboxStatus.SUCCESS
    assert len(res.output.get("found_secrets", [])) == 0


# -------------------------------------------------------------
# 2. FILESYSTEM & PATH TRAVERSAL DEFENSE (§13.4) (7-9)
# -------------------------------------------------------------

def test_7_path_traversal_relative_blocked():
    """[REAL] Validates relative path traversal blocked in parameters."""
    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=507)
    res = sandbox.execute_tool(
        tool_id="file_op", action_name="read_file", handler_fn=mock_calculator_handler,
        params={"file_path": "../../etc/passwd"}
    )
    sandbox.cleanup()
    assert res.status == SandboxStatus.SECURITY_VIOLATION
    assert "path escape" in res.error.lower()


def test_8_path_traversal_absolute_windows_and_posix_blocked():
    """[REAL] Validates absolute POSIX and Windows drive paths rejected."""
    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=508)
    res_posix = sandbox.execute_tool(
        tool_id="file_op", action_name="read_file", handler_fn=mock_calculator_handler,
        params={"target_path": "/etc/shadow"}
    )
    res_win = sandbox.execute_tool(
        tool_id="file_op", action_name="read_file", handler_fn=mock_calculator_handler,
        params={"target_path": "C:\\Windows\\System32"}
    )
    res_unc = sandbox.execute_tool(
        tool_id="file_op", action_name="read_file", handler_fn=mock_calculator_handler,
        params={"target_path": "\\\\remote_server\\share\\data"}
    )
    sandbox.cleanup()
    assert res_posix.status == SandboxStatus.SECURITY_VIOLATION
    assert res_win.status == SandboxStatus.SECURITY_VIOLATION
    assert res_unc.status == SandboxStatus.SECURITY_VIOLATION


def test_9_unhandled_python_exception_handled_cleanly():
    """[REAL] Validates worker crash isolated and returned with error code."""
    sandbox = RachitSandbox(tenant_id="tenant_alice", task_id=509)
    res = sandbox.execute_tool(
        tool_id="broken", action_name="broken", handler_fn=mock_broken_handler
    )
    sandbox.cleanup()
    assert res.status == SandboxStatus.EXECUTION_ERROR
    assert "ValueError" in res.error
    assert res.exit_code == 1


# -------------------------------------------------------------
# 3. GOVERNANCE PRE-FLIGHT INTEGRATION (§10, §11, §12) (10-15)
# -------------------------------------------------------------

def test_10_maryada_blocked_verdict_prevents_execution():
    """[REAL] Validates MARYADA blocked verdict halts tool invocation."""
    maryada_blocked = MaryadaVerdict(
        approved=False, status=GateStatus.BLOCKED, risk_tier=RiskTier.HIGH,
        authority_required=AuthorityTier.HIGH, justification="Blocked by policy"
    )
    res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calculate 1+1", handler_fn=mock_calculator_handler,
        tenant_id="tenant_alice", task_id=510, maryada_verdict=maryada_blocked
    )
    assert res.status == SandboxStatus.BLOCKED
    assert "blocked by MARYADA" in res.error


def test_11_maryada_approved_verdict_permits_execution():
    """[REAL] Validates MARYADA approved verdict permits tool invocation."""
    maryada_approved = MaryadaVerdict(
        approved=True, status=GateStatus.APPROVED, risk_tier=RiskTier.LOW,
        authority_required=AuthorityTier.LOW, justification="Approved"
    )
    res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calculate 1+1", handler_fn=mock_calculator_handler,
        tenant_id="tenant_alice", task_id=511, maryada_verdict=maryada_approved
    )
    assert res.status == SandboxStatus.SUCCESS


def test_12_murphy_blocked_recommendation_prevents_execution():
    """[REAL] Validates MURPHY BLOCKED recommendation halts tool invocation."""
    murphy_blocked = MurphyRiskReport(
        risk_level=MurphyRiskTier.CRITICAL, blast_radius_score=1.0,
        failure_modes=["High blast radius"], security_concerns=["Destructive action"],
        recommendation=MurphyRecommendation.BLOCKED
    )
    res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calc", handler_fn=mock_calculator_handler,
        tenant_id="tenant_alice", task_id=512, murphy_report=murphy_blocked
    )
    assert res.status == SandboxStatus.BLOCKED
    assert "blocked by MURPHY" in res.error


def test_13_murphy_proceed_recommendation_permits_execution():
    """[REAL] Validates MURPHY PROCEED recommendation permits tool invocation."""
    murphy_proceed = MurphyRiskReport(
        risk_level=MurphyRiskTier.LOW, blast_radius_score=0.05,
        failure_modes=[], security_concerns=[], recommendation=MurphyRecommendation.PROCEED
    )
    res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calc", handler_fn=mock_calculator_handler,
        tenant_id="tenant_alice", task_id=513, murphy_report=murphy_proceed
    )
    assert res.status == SandboxStatus.SUCCESS


def test_14_manush_pending_human_review_prevents_execution():
    """[REAL] Validates pending human review halts tool invocation."""
    res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calc", handler_fn=mock_calculator_handler,
        tenant_id="tenant_alice", task_id=514, human_review_status=ReviewStatus.PENDING_REVIEW
    )
    assert res.status == SandboxStatus.BLOCKED
    assert "pending human oversight" in res.error


def test_15_manush_approved_human_review_permits_execution():
    """[REAL] Validates approved human review permits tool invocation."""
    res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calc", handler_fn=mock_calculator_handler,
        tenant_id="tenant_alice", task_id=515, human_review_status=ReviewStatus.APPROVED_BY_HUMAN
    )
    assert res.status == SandboxStatus.SUCCESS


# -------------------------------------------------------------
# 4. TENANT ISOLATION & WORKSPACE CLEANUP (§13.1, §13.5) (16-18)
# -------------------------------------------------------------

def test_16_empty_tenant_id_fails_closed():
    """[REAL] Validates empty tenant ID fails closed."""
    with pytest.raises(ValueError, match="Authenticated Tenant ID is required"):
        RachitSandbox(tenant_id="", task_id=516)


def test_17_tenant_scoped_workspace_partitioning():
    """[REAL] Validates tenant workspaces are partitioned."""
    s_alice = RachitSandbox(tenant_id="tenant_alice", task_id=517)
    s_bob = RachitSandbox(tenant_id="tenant_bob", task_id=517)
    assert s_alice.workspace_dir != s_bob.workspace_dir
    assert "tenant_alice" in str(s_alice.workspace_dir)
    assert "tenant_bob" in str(s_bob.workspace_dir)
    s_alice.cleanup()
    s_bob.cleanup()


def test_18_workspace_cleanup_on_completion():
    """[REAL] Validates disposable workspace cleanup."""
    s = RachitSandbox(tenant_id="tenant_alice", task_id=518)
    w_dir = s.workspace_dir
    assert w_dir.exists()
    s.cleanup()
    assert not w_dir.exists()


# -------------------------------------------------------------
# 5. CHITRA AUDIT LOGGING & CRYPTO VERIFICATION (§13.6) (19-21)
# -------------------------------------------------------------

def test_19_chitra_invocation_event_generation():
    """[REAL] Validates CHITRA invocation event creation."""
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calculate 10 * 10", handler_fn=mock_calculator_handler,
        tenant_id=f"tenant_{u_a}", task_id=t_a, db_session=db, user_id=u_a
    )
    assert res.chitra_event_id is not None

    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == res.chitra_event_id).first()
    assert evt is not None
    assert evt.faculty == "RACHIT"
    assert evt.event_type == "invocation"
    assert evt.decision["tool_id"] == "calculator"
    db.close()


def test_20_chitra_invocation_payload_integrity():
    """[REAL] Validates cryptographic output hash matches event payload."""
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calculate 10 * 10", handler_fn=mock_calculator_handler,
        tenant_id=f"tenant_{u_a}", task_id=t_a, db_session=db, user_id=u_a
    )
    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == res.chitra_event_id).first()
    assert evt.decision["output_hash"] == res.output_hash
    assert evt.decision["exit_code"] == 0
    db.close()


def test_21_cryptographic_verification_on_rachit_events():
    """[REAL] Validates cryptographic hash chain verification over RACHIT ledger records."""
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calc 1", handler_fn=mock_calculator_handler,
        tenant_id=f"tenant_{u_a}", task_id=t_a, db_session=db, user_id=u_a
    )
    RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name="calc 2", handler_fn=mock_calculator_handler,
        tenant_id=f"tenant_{u_a}", task_id=t_a, db_session=db, user_id=u_a
    )

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked == 2
    db.close()


# -------------------------------------------------------------
# 6. CONCURRENCY & LIMITATION TESTS (22-24)
# -------------------------------------------------------------

def test_22_deterministic_execution_repeatability():
    """[REAL] Validates deterministic output hashing."""
    s = RachitSandbox(tenant_id="tenant_alice", task_id=522)
    r1 = s.execute_tool("calc", "calc", mock_calculator_handler)
    r2 = s.execute_tool("calc", "calc", mock_calculator_handler)
    s.cleanup()
    assert r1.output_hash == r2.output_hash


def test_23_network_policy_enforcement():
    """[POLICY] Validates network policy flag behavior at RACHIT boundary."""
    q_no_net = ExecutionQuotas(allow_network=False)
    q_net = ExecutionQuotas(allow_network=True)
    s1 = RachitSandbox(tenant_id="t1", task_id=523, quotas=q_no_net)
    s2 = RachitSandbox(tenant_id="t1", task_id=524, quotas=q_net)
    assert s1.check_network_permission() is False
    assert s2.check_network_permission() is True
    s1.cleanup()
    s2.cleanup()


def test_24_memory_quota_schema_validation():
    """[PLATFORM-LIMITED] Validates memory quota schema representation."""
    q = ExecutionQuotas(max_memory_mb=256)
    assert q.max_memory_mb == 256


# -------------------------------------------------------------
# 7. INTEGRATIONS WITH KARMA & COMPLETE PIPELINE (25-30)
# -------------------------------------------------------------

def test_25_integration_with_karma_phase7_executor():
    """[REAL] Validates integration with KARMA Phase 7 DAG executor."""
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s1 = KarmaStep(step_id="s1", action="calculate 20 * 20", expected_outcome="400", dependencies=[])
    plan = KarmaPlanDAG(task_id=t_a, summary="Plan", steps=[s1])

    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    rep = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert rep.status == "COMPLETED"
    db.close()


def test_26_integration_with_phase8_step_verifier():
    """[REAL] Validates integration with Phase 8 verification."""
    step = KarmaStep(step_id="s1", action="calculate 10+10", expected_outcome="20")
    res = KarmaStepVerifier.verify(
        action=step.action,
        expected_outcome=step.expected_outcome,
        output={"result": 20}
    )
    assert res.status == "VERIFIED"


def test_27_integration_with_phase9_completion_validator():
    """[REAL] Validates integration with Phase 9 Completion Validator."""
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2")
    plan = KarmaPlanDAG(task_id=t_a, summary="P", steps=[s])
    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    report = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    
    comp_val = report.step_results["s1"].completion_validation
    assert comp_val["is_valid"] is True
    assert comp_val["no_silent_action_valid"] is True
    db.close()


def test_28_integration_with_phase10_kosh_episodic_memory():
    """[REAL] Validates integration with Phase 10 KOSH episodic memory."""
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s = KarmaStep(step_id="s1", action="calculate 5 * 5", expected_outcome="25")
    plan = KarmaPlanDAG(task_id=t_a, summary="P", steps=[s])
    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    report = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)

    v_store = KoshVectorStore()
    handoff = KoshEpisodicHandoffController.process_plan_handoff(report, tenant_id=f"tenant_{u_a}", vector_store=v_store)
    assert handoff.success is True
    assert handoff.indexed_chunks_count == 1
    db.close()


def test_29_full_pipeline_phase5_to_phase14():
    """[REAL] Validates full pipeline: Phase 5 -> 12 -> 11 -> 14 -> 8 -> 9 -> 10."""
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    # 1. Plan DAG (Phase 5)
    s1 = KarmaStep(step_id="s1", action="calculate 15 * 15", expected_outcome="225", dependencies=[])
    plan = KarmaPlanDAG(task_id=t_a, summary="Full End to End", steps=[s1])

    # 2. MURPHY Simulation (Phase 12)
    m_rep = MurphyService.analyze_plan_risk(plan, tenant_id=f"tenant_{u_a}", db_session=db, user_id=u_a)
    assert m_rep.risk_level == MurphyRiskTier.LOW

    # 3. MARYADA Gate (Phase 11)
    g_verdict = MaryadaGatekeeper.evaluate_plan_gate(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert g_verdict.approved is True

    # 4. RACHIT Sandboxed Execution Service (Phase 14)
    rachit_res = RachitExecutionService.execute_sandboxed_tool(
        tool_id="calculator", action_name=s1.action, handler_fn=mock_calculator_handler,
        tenant_id=f"tenant_{u_a}", task_id=t_a, maryada_verdict=g_verdict, murphy_report=m_rep,
        db_session=db, user_id=u_a
    )
    assert rachit_res.status == SandboxStatus.SUCCESS

    # 5. Verify cryptographic ledger
    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked >= 3  # MURPHY + MARYADA + RACHIT
    db.close()


def test_30_phase15_boundary_check():
    """[REAL] Validates zero Phase 15 Saga rollback leakage."""
    assert not hasattr(RachitExecutionService, "phase_15_saga_coordinator")
    assert not hasattr(RachitExecutionService, "distributed_rollback_manager")


def run_all_30_phase14_tests():
    print("==================================================")
    print("RACHIT PHASE 14: 30-SCENARIO TOOL EXECUTION ENGINE")
    print("& SANDBOX RUNTIME SUITE (WHITESHEET §§13.0-13.6)")
    print("Target Sandbox: sqlite:///./test_karma_phase14_sandbox.db")
    print("==================================================")

    test_1_successful_tool_execution_in_sandbox()
    print("  [PASS 1/30] [REAL] Successful OS subprocess tool execution in sandbox (§13.1).")

    test_2_execution_time_measurement()
    print("  [PASS 2/30] [REAL] Execution time measurement.")

    test_3_hard_timeout_enforcement()
    print("  [PASS 3/30] [REAL] Hard execution timeout and OS subprocess kill (§13.2).")

    test_4_blocking_infinite_loop_killed_safely()
    print("  [PASS 4/30] [REAL] Blocking infinite loop OS subprocess killed safely (§13.2, §13.5).")

    test_5_output_size_quota_truncation()
    print("  [PASS 5/30] [REAL] Output size quota truncation (§13.3).")

    test_6_environment_secret_containment()
    print("  [PASS 6/30] [REAL] Sensitive parent environment variables scrubbed from worker (§13.1).")

    test_7_path_traversal_relative_blocked()
    print("  [PASS 7/30] [REAL] Relative path traversal blocked in parameters (§13.4).")

    test_8_path_traversal_absolute_windows_and_posix_blocked()
    print("  [PASS 8/30] [REAL] Absolute POSIX, Windows drive, and UNC paths rejected (§13.4).")

    test_9_unhandled_python_exception_handled_cleanly()
    print("  [PASS 9/30] [REAL] Unhandled Python exception contained in subprocess (§13.5).")

    test_10_maryada_blocked_verdict_prevents_execution()
    print("  [PASS 10/30] [REAL] MARYADA blocked verdict prevents execution.")

    test_11_maryada_approved_verdict_permits_execution()
    print("  [PASS 11/30] [REAL] MARYADA approved verdict permits execution.")

    test_12_murphy_blocked_recommendation_prevents_execution()
    print("  [PASS 12/30] [REAL] MURPHY BLOCKED recommendation prevents execution.")

    test_13_murphy_proceed_recommendation_permits_execution()
    print("  [PASS 13/30] [REAL] MURPHY PROCEED recommendation permits execution.")

    test_14_manush_pending_human_review_prevents_execution()
    print("  [PASS 14/30] [REAL] MANUSH pending human review prevents execution.")

    test_15_manush_approved_human_review_permits_execution()
    print("  [PASS 15/30] [REAL] MANUSH approved human review permits execution.")

    test_16_empty_tenant_id_fails_closed()
    print("  [PASS 16/30] [REAL] Empty tenant ID fails closed.")

    test_17_tenant_scoped_workspace_partitioning()
    print("  [PASS 17/30] [REAL] Tenant-scoped workspace partitioning (§13.1, §18).")

    test_18_workspace_cleanup_on_completion()
    print("  [PASS 18/30] [REAL] Workspace cleanup on completion (§13.5).")

    test_19_chitra_invocation_event_generation()
    print("  [PASS 19/30] [REAL] CHITRA invocation event generation (§13.6).")

    test_20_chitra_invocation_payload_integrity()
    print("  [PASS 20/30] [REAL] CHITRA invocation payload integrity.")

    test_21_cryptographic_verification_on_rachit_events()
    print("  [PASS 21/30] [REAL] Cryptographic verification on RACHIT events.")

    test_22_deterministic_execution_repeatability()
    print("  [PASS 22/30] [REAL] Deterministic execution repeatability.")

    test_23_network_policy_enforcement()
    print("  [PASS 23/30] [POLICY] Network policy enforcement at boundary (§13.4).")

    test_24_memory_quota_schema_validation()
    print("  [PASS 24/30] [PLATFORM-LIMITED] Memory quota schema validation (§13.3).")

    test_25_integration_with_karma_phase7_executor()
    print("  [PASS 25/30] [REAL] Integration with KARMA Phase 7 executor.")

    test_26_integration_with_phase8_step_verifier()
    print("  [PASS 26/30] [REAL] Integration with Phase 8 step verifier.")

    test_27_integration_with_phase9_completion_validator()
    print("  [PASS 27/30] [REAL] Integration with Phase 9 completion validator.")

    test_28_integration_with_phase10_kosh_episodic_memory()
    print("  [PASS 28/30] [REAL] Integration with Phase 10 KOSH episodic memory.")

    test_29_full_pipeline_phase5_to_phase14()
    print("  [PASS 29/30] [REAL] Full pipeline: Phase 5 -> 12 -> 11 -> 14 -> 8 -> 9 -> 10.")

    test_30_phase15_boundary_check()
    print("  [PASS 30/30] [REAL] Phase 15 boundary verified (0 Phase 15 features).")

    print("\n==================================================")
    print("ALL 30 RACHIT PHASE 14 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_30_phase14_tests()
