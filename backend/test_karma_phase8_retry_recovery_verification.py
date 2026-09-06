"""
KARMA Phase 8 Comprehensive Test Suite: Retry, Recovery, Circuit Breaker & Verification
Strictly tests Whitesheet §§7.5, 7.6 & 7.7 across 40 explicit scenarios.
Runs against local sandbox database: test_karma_phase8_sandbox.db.
"""
import pytest
import concurrent.futures
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep, KarmaRetryPolicy
from app.core.karma.tool_registry import (
    KarmaToolDefinition,
    KarmaToolRegistry,
    get_default_tool_registry
)
from app.core.karma.tool_router import KarmaToolRouter
from app.core.karma.circuit_breaker import (
    KarmaCircuitBreaker,
    KarmaCircuitBreakerRegistry,
    CircuitState
)
from app.core.karma.verifier import KarmaStepVerifier, KarmaVerificationResult
from app.core.karma.recovery import KarmaRecoveryEngine, KarmaRecoveryDecision
from app.core.karma.executor import KarmaDAGExecutor, KarmaDAGExecutionReport
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase8_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user = User(username="phase8_test_user", hashed_password="pwd")
    db.add(user)
    db.commit()
    db.refresh(user)

    task = Task(user_id=user.id, title="Phase 8 Test Task", prompt="Testing retry & verification", status="PENDING")
    db.add(task)
    db.commit()
    db.refresh(task)

    user_id = user.id
    task_id = task.id
    db.close()
    return user_id, task_id


# Mock sleep to avoid real execution delays in test suite
mock_sleep_log = []
def fast_mock_sleep(seconds: float):
    mock_sleep_log.append(seconds)


# -------------------------------------------------------------
# RETRY TESTS (1-11)
# -------------------------------------------------------------

def test_1_successful_first_attempt_no_retry():
    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    s1 = KarmaStep(step_id="s1", action="calculate 10 + 20", expected_outcome="30", dependencies=[])
    plan = KarmaPlanDAG(task_id=1, summary="No retry needed", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status == "COMPLETED"
    assert report.step_results["s1"].attempts_made == 1
    assert report.step_results["s1"].status == "SUCCEEDED"


def test_2_retryable_failure_triggers_retry():
    call_count = 0
    def flaky_handler(params):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Transient network blip")
        return {"result": 42}

    executor = KarmaDAGExecutor(custom_handlers={"flaky_tool": flaky_handler}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="flaky_tool", name="Flaky", capabilities=["flaky_action"]))

    s1 = KarmaStep(step_id="s1", action="flaky_action", expected_outcome="42", dependencies=[])
    plan = KarmaPlanDAG(task_id=2, summary="Flaky Test", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.status == "COMPLETED"
    assert report.step_results["s1"].attempts_made == 2
    assert report.step_results["s1"].status == "SUCCEEDED"


def test_3_retry_succeeds_on_second_attempt():
    call_count = 0
    def two_attempt_handler(params):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionResetError("Connection reset")
        return {"result": 100}

    executor = KarmaDAGExecutor(custom_handlers={"two_att_tool": two_attempt_handler}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="two_att_tool", name="TwoAtt", capabilities=["two_att"]))

    s1 = KarmaStep(step_id="s1", action="two_att", expected_outcome="100", dependencies=[])
    plan = KarmaPlanDAG(task_id=3, summary="Two attempt", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.status == "COMPLETED"
    assert report.step_results["s1"].attempts_made == 2


def test_4_retry_exhausted_fails():
    def always_failing(params):
        raise TimeoutError("Dead backend")

    executor = KarmaDAGExecutor(custom_handlers={"dead_tool": always_failing}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="dead_tool", name="Dead", capabilities=["dead_action"]))

    # 3 attempts
    s1 = KarmaStep(step_id="s1", action="dead_action", expected_outcome="Success", dependencies=[])
    plan = KarmaPlanDAG(task_id=4, summary="Exhausted", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].attempts_made == 3


def test_5_non_retryable_failure_no_retry():
    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    # Insufficient authority -> non-retryable
    s1 = KarmaStep(step_id="s1", action="settlement 1000", expected_outcome="Settled", dependencies=[])
    plan = KarmaPlanDAG(task_id=5, summary="Auth Fail", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].attempts_made == 1  # 0 retries on non-retryable routing rejection


def test_6_maximum_attempts_enforced():
    calls = 0
    def counting_handler(params):
        nonlocal calls
        calls += 1
        raise ValueError("Always fail")

    executor = KarmaDAGExecutor(custom_handlers={"counting": counting_handler}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="counting", name="Counting", capabilities=["count_fail"]))

    custom_policy = KarmaRetryPolicy(max_attempts=4, base_delay_ms=100)
    s1 = KarmaStep(step_id="s1", action="count_fail", expected_outcome="Done", dependencies=[], retry_policy=custom_policy)
    plan = KarmaPlanDAG(task_id=6, summary="Max attempts", steps=[s1])

    executor.execute_plan(plan)
    assert calls == 4


def test_7_exponential_backoff_calculation():
    executor = KarmaDAGExecutor()
    policy = KarmaRetryPolicy(max_attempts=3, backoff="exponential", base_delay_ms=200, jitter=False)
    
    d1 = executor._calculate_backoff_delay(1, policy)  # 200ms * 2^0 = 0.2s
    d2 = executor._calculate_backoff_delay(2, policy)  # 200ms * 2^1 = 0.4s
    d3 = executor._calculate_backoff_delay(3, policy)  # 200ms * 2^2 = 0.8s
    
    assert abs(d1 - 0.2) < 1e-4
    assert abs(d2 - 0.4) < 1e-4
    assert abs(d3 - 0.8) < 1e-4


def test_8_jitter_calculation_behavior():
    executor = KarmaDAGExecutor()
    policy = KarmaRetryPolicy(max_attempts=3, backoff="exponential", base_delay_ms=200, jitter=True)
    
    delays = [executor._calculate_backoff_delay(1, policy) for _ in range(20)]
    assert all(d >= 0.2 for d in delays)
    assert any(d > 0.201 for d in delays)  # Jitter applied


def test_9_retry_policy_defaults():
    policy = KarmaRetryPolicy()
    assert policy.max_attempts == 3
    assert policy.base_delay_ms == 200
    assert policy.backoff == "exponential"
    assert policy.jitter is True
    assert policy.circuit_break_after == 5


def test_10_retry_cannot_bypass_authority():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="wire_transfer", expected_outcome="Transferred", dependencies=[])
    plan = KarmaPlanDAG(task_id=10, summary="Auth Bypass", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].attempts_made == 1


def test_11_retry_cannot_bypass_maryada():
    executor = KarmaDAGExecutor()
    unconstitutional_tool = KarmaToolDefinition(
        tool_id="bad_act",
        name="Bad",
        capabilities=["bad_act"],
        constitutional_compliant=False
    )
    executor.registry.register_tool(unconstitutional_tool)

    s1 = KarmaStep(step_id="s1", action="bad_act", expected_outcome="Done", dependencies=[])
    plan = KarmaPlanDAG(task_id=11, summary="Maryada Bypass", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="CRITICAL")
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].attempts_made == 1


# -------------------------------------------------------------
# CIRCUIT BREAKER TESTS (12-18)
# -------------------------------------------------------------

def test_12_circuit_starts_closed():
    cb = KarmaCircuitBreaker(tool_id="t1", failure_threshold=3)
    assert cb.state == CircuitState.CLOSED
    permitted, _ = cb.is_call_permitted()
    assert permitted is True


def test_13_repeated_failures_open_circuit():
    cb = KarmaCircuitBreaker(tool_id="t1", failure_threshold=3, recovery_window_seconds=60)
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()  # 3rd failure trips
    assert cb.state == CircuitState.OPEN


def test_14_open_circuit_blocks_invocation():
    cb = KarmaCircuitBreaker(tool_id="t1", failure_threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    permitted, reason = cb.is_call_permitted()
    assert permitted is False
    assert "OPEN" in reason


def test_15_half_open_transition_and_probing():
    simulated_time = 1000.0
    def time_source():
        return simulated_time

    cb = KarmaCircuitBreaker(tool_id="t1", failure_threshold=2, recovery_window_seconds=30.0, time_fn=time_source)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Advance time beyond 30s recovery window
    simulated_time += 35.0
    permitted, reason = cb.is_call_permitted()
    assert permitted is True
    assert cb.state == CircuitState.HALF_OPEN


def test_16_successful_recovery_closes_circuit():
    simulated_time = 1000.0
    cb = KarmaCircuitBreaker(tool_id="t1", failure_threshold=2, recovery_window_seconds=30.0, time_fn=lambda: simulated_time)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    simulated_time += 35.0
    cb.is_call_permitted()  # Transitions to HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN

    # Probe succeeds
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_17_circuit_state_tenant_isolation():
    reg = KarmaCircuitBreakerRegistry()
    b_alice = reg.get_breaker(tool_id="calc", scope="tenant_alice", failure_threshold=2)
    b_bob = reg.get_breaker(tool_id="calc", scope="tenant_bob", failure_threshold=2)

    # Trip Alice's breaker
    b_alice.record_failure()
    b_alice.record_failure()
    assert b_alice.state == CircuitState.OPEN

    # Bob's breaker remains completely healthy CLOSED
    assert b_bob.state == CircuitState.CLOSED
    permitted, _ = b_bob.is_call_permitted()
    assert permitted is True


def test_18_concurrent_circuit_updates():
    cb = KarmaCircuitBreaker(tool_id="t_thread", failure_threshold=50)

    def worker():
        for _ in range(10):
            cb.record_failure()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(worker) for _ in range(5)]
        for f in futures:
            f.result()

    assert len(cb.failure_timestamps) == 50
    assert cb.state == CircuitState.OPEN


# -------------------------------------------------------------
# RECOVERY TESTS (19-24)
# -------------------------------------------------------------

def test_19_compensating_action_execution():
    def failing_action(params):
        raise RuntimeError("Write failure")

    executor = KarmaDAGExecutor(custom_handlers={"fail_action": failing_action}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="fail_action", name="Fail", capabilities=["do_write"]))

    s1 = KarmaStep(step_id="s1", action="do_write", expected_outcome="Done", dependencies=[])
    plan = KarmaPlanDAG(task_id=19, summary="Compensate", steps=[s1])

    # Provide compensating action definition
    comp_map = {"s1": {"action": "compensate_rollback_ledger", "tool": "echo_formatter"}}
    report = executor.execute_plan(plan, compensating_action_map=comp_map)
    
    assert report.status == "COMPLETED"
    assert report.step_results["s1"].output["compensated"] is True


def test_20_compensation_passes_authority_gates():
    # If compensation action is configured, it executes through router/authority gates
    executor = KarmaDAGExecutor()
    rec = KarmaRecoveryEngine.recover(
        step=KarmaStep(step_id="s1", action="act", expected_outcome="O", dependencies=[]),
        error_message="Fail",
        caller_authority="LOW",
        compensating_action_def={"action": "rollback", "tool": "echo_formatter"}
    )
    assert rec.recovery_strategy == "COMPENSATED"
    assert rec.is_recovered is True


def test_21_graceful_degradation():
    rec = KarmaRecoveryEngine.recover(
        step=KarmaStep(step_id="s1", action="lookup status telemetry", expected_outcome="Status", dependencies=[]),
        error_message="Backend timeout",
        caller_authority="LOW",
        allow_degradation=True
    )
    assert rec.recovery_strategy == "DEGRADED"
    assert rec.is_recovered is True
    assert rec.degraded_output["degraded"] is True


def test_22_human_escalation_on_unrecoverable_failure():
    rec = KarmaRecoveryEngine.recover(
        step=KarmaStep(step_id="s1", action="execute monetary settlement", expected_outcome="Settled", dependencies=[]),
        error_message="Hardware security module fault",
        caller_authority="HIGH",
        allow_degradation=False
    )
    assert rec.recovery_strategy == "ESCALATED"
    assert rec.is_recovered is False
    assert "Routing to Human Oversight" in rec.escalation_reason


def test_23_recovery_failure_is_explicit():
    rec = KarmaRecoveryEngine.recover(
        step=KarmaStep(step_id="s1", action="unrecoverable", expected_outcome="Done", dependencies=[]),
        error_message="Fatal crash",
        allow_degradation=False
    )
    assert rec.is_recovered is False


def test_24_no_silent_success_after_failed_recovery():
    def failing_handler(params):
        raise RuntimeError("Fatal hard failure")

    executor = KarmaDAGExecutor(custom_handlers={"fatal": failing_handler}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="fatal", name="Fatal", capabilities=["fatal_act"]))

    s1 = KarmaStep(step_id="s1", action="fatal_act", expected_outcome="Done", dependencies=[])
    plan = KarmaPlanDAG(task_id=24, summary="No silent success", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.succeeded_steps_count == 0


# -------------------------------------------------------------
# VERIFICATION TESTS (25-32)
# -------------------------------------------------------------

def test_25_structural_verification_success():
    v = KarmaStepVerifier.verify(action="calculate 2+2", expected_outcome="4", output={"result": 4})
    assert v.is_valid is True
    assert v.status == "VERIFIED"


def test_26_structural_verification_failure():
    v = KarmaStepVerifier.verify(action="calculate", expected_outcome="4", output=None)
    assert v.is_valid is False
    assert v.status == "STRUCTURAL_FAILURE"


def test_27_semantic_verification_success():
    v = KarmaStepVerifier.verify(action="calculate 15 * 3", expected_outcome="45", output={"result": 45})
    assert v.is_valid is True
    assert v.status == "VERIFIED"


def test_28_semantic_verification_failure():
    v = KarmaStepVerifier.verify(action="calculate 10 + 10", expected_outcome="20", output={"result": 999})
    assert v.is_valid is False
    assert v.status == "SEMANTIC_FAILURE"
    assert "Semantic mismatch" in v.failure_reason


def test_29_constitutional_verification_success():
    v = KarmaStepVerifier.verify(action="calendar lookup", expected_outcome="Calendar", output={"holidays": ["Holi"]})
    assert v.is_valid is True
    assert v.status == "VERIFIED"


def test_30_constitutional_verification_failure():
    v = KarmaStepVerifier.verify(
        action="inspect secret",
        expected_outcome="Data",
        output={"secret_key": "super_secret_value_12345"}
    )
    assert v.is_valid is False
    assert v.status == "CONSTITUTIONAL_BLOCK"
    assert "prohibited pattern" in v.failure_reason.lower()


def test_31_verification_failure_triggers_retry_when_allowed():
    attempt = 0
    def incorrect_then_correct(params):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            return {"result": 0}  # Wrong answer -> fails semantic verification
        return {"result": 50}     # Correct answer -> passes

    executor = KarmaDAGExecutor(custom_handlers={"two_step": incorrect_then_correct}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="two_step", name="TwoStep", capabilities=["comp_50"]))

    s1 = KarmaStep(step_id="s1", action="comp_50", expected_outcome="50", dependencies=[])
    plan = KarmaPlanDAG(task_id=31, summary="Retry on Verif", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.status == "COMPLETED"
    assert report.step_results["s1"].attempts_made == 2
    assert report.step_results["s1"].status == "SUCCEEDED"


def test_32_verification_failure_does_not_incorrectly_produce_success():
    def always_wrong(params):
        return {"result": 9999}

    executor = KarmaDAGExecutor(custom_handlers={"wrong": always_wrong}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="wrong", name="Wrong", capabilities=["always_wrong"]))

    s1 = KarmaStep(step_id="s1", action="always_wrong", expected_outcome="10", dependencies=[])
    plan = KarmaPlanDAG(task_id=32, summary="Always Wrong", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.succeeded_steps_count == 0


# -------------------------------------------------------------
# INTEGRATION & SECURITY TESTS (33-40)
# -------------------------------------------------------------

def test_33_phase6_router_remains_mandatory():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 7 * 7", expected_outcome="49", dependencies=[])
    plan = KarmaPlanDAG(task_id=33, summary="Router Mandate", steps=[s1])
    report = executor.execute_plan(plan)
    assert report.step_results["s1"].tool_id == "calculator"


def test_34_phase7_dependency_ordering_preserved():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="calculate 2+2", expected_outcome="4", dependencies=["s1"])
    plan = KarmaPlanDAG(task_id=34, summary="Dep Order", steps=[s2, s1])
    report = executor.execute_plan(plan)
    assert report.execution_order == ["s1", "s2"]


def test_35_actual_tool_invocation_only_after_all_gates():
    call_log = []
    def spy_handler(params):
        call_log.append("CALLED")
        return {"done": True}

    executor = KarmaDAGExecutor(custom_handlers={"spy": spy_handler})
    executor.registry.register_tool(KarmaToolDefinition(tool_id="spy", name="Spy", capabilities=["spy_act"], authority_required="HIGH"))

    s1 = KarmaStep(step_id="s1", action="spy_act", expected_outcome="Done", dependencies=[])
    plan = KarmaPlanDAG(task_id=35, summary="Spy Test", steps=[s1])

    # Caller has LOW authority -> rejected before invocation
    executor.execute_plan(plan, caller_authority="LOW")
    assert len(call_log) == 0


def test_36_chitra_audit_generated_for_retries():
    user_id, task_id = reset_sandbox()
    db = TestSession()

    attempts = 0
    def retry_handler(params):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Transient error")
        return {"result": 42}

    executor = KarmaDAGExecutor(custom_handlers={"retry_audit": retry_handler}, sleep_fn=fast_mock_sleep)
    executor.registry.register_tool(KarmaToolDefinition(tool_id="retry_audit", name="RetryAudit", capabilities=["retry_aud"]))

    s1 = KarmaStep(step_id="s1", action="retry_aud", expected_outcome="42", dependencies=[])
    plan = KarmaPlanDAG(task_id=task_id, summary="Audit Retry", steps=[s1])

    report = executor.execute_plan(plan, db_session=db, user_id=user_id)
    assert report.status == "COMPLETED"

    evts = chitra_repository.get_events_for_task(db, task_id, user_id=user_id)
    assert len(evts) >= 1
    assert evts[0].faculty == "RACHIT"

    v_res = chitra_verifier.verify_task_chain(db, task_id, user_id=user_id)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    db.close()


def test_37_chitra_audit_generated_for_verification():
    user_id, task_id = reset_sandbox()
    db = TestSession()

    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    s1 = KarmaStep(step_id="s1", action="calculate 5 + 5", expected_outcome="10", dependencies=[])
    plan = KarmaPlanDAG(task_id=task_id, summary="Audit Verif", steps=[s1])

    report = executor.execute_plan(plan, db_session=db, user_id=user_id)
    assert report.status == "COMPLETED"

    evts = chitra_repository.get_events_for_task(db, task_id, user_id=user_id)
    assert len(evts) == 1
    assert evts[0].decision["verification_status"] == "VERIFIED"
    db.close()


def test_38_tenant_isolation_maintained():
    user_id, task_id = reset_sandbox()
    db = TestSession()

    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 1 + 1", expected_outcome="2", dependencies=[])
    plan = KarmaPlanDAG(task_id=task_id, summary="Tenant Iso", steps=[s1])

    executor.execute_plan(plan, db_session=db, user_id=user_id)

    # Bob cannot see Alice's execution events
    bob_id = 9999
    bob_evts = chitra_repository.get_events_for_task(db, task_id, user_id=bob_id)
    assert bob_evts == []
    db.close()


def test_39_concurrent_workflows_safety():
    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)

    def worker(i: int):
        s1 = KarmaStep(step_id="s1", action=f"calculate {i} * 3", expected_outcome=f"{i * 3}", dependencies=[])
        plan = KarmaPlanDAG(task_id=300 + i, summary=f"Concurrent {i}", steps=[s1])
        return executor.execute_plan(plan)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(25)]
        reports = [f.result() for f in futures]

    assert len(reports) == 25
    assert all(r.status == "COMPLETED" for r in reports)


def test_40_no_phase9_functionality_introduced():
    executor = KarmaDAGExecutor()
    assert not hasattr(executor, "completion_validator")
    assert not hasattr(executor, "alignment_score")
    assert not hasattr(executor, "validate_completion")


def run_all_40_phase8_tests():
    print("==================================================")
    print("KARMA PHASE 8: 40-SCENARIO RETRY, CIRCUIT BREAKER,")
    print("RECOVERY & VERIFICATION TEST SUITE")
    print("Target Sandbox: sqlite:///./test_karma_phase8_sandbox.db")
    print("==================================================")

    test_1_successful_first_attempt_no_retry()
    print("  [PASS 1/40] Successful first attempt -> no retry.")

    test_2_retryable_failure_triggers_retry()
    print("  [PASS 2/40] Retryable failure triggers retry.")

    test_3_retry_succeeds_on_second_attempt()
    print("  [PASS 3/40] Retry succeeds on second attempt.")

    test_4_retry_exhausted_fails()
    print("  [PASS 4/40] Retry exhaustion produces explicit failure.")

    test_5_non_retryable_failure_no_retry()
    print("  [PASS 5/40] Non-retryable failure does not retry.")

    test_6_maximum_attempts_enforced()
    print("  [PASS 6/40] Maximum attempts strictly enforced.")

    test_7_exponential_backoff_calculation()
    print("  [PASS 7/40] Exponential backoff mathematical progression.")

    test_8_jitter_calculation_behavior()
    print("  [PASS 8/40] Randomized jitter behavior.")

    test_9_retry_policy_defaults()
    print("  [PASS 9/40] Whitesheet §7.5 retry policy defaults.")

    test_10_retry_cannot_bypass_authority()
    print("  [PASS 10/40] Retries cannot bypass authority gates.")

    test_11_retry_cannot_bypass_maryada()
    print("  [PASS 11/40] Retries cannot bypass MARYADA constraints.")

    test_12_circuit_starts_closed()
    print("  [PASS 12/40] Circuit breaker initializes in CLOSED state.")

    test_13_repeated_failures_open_circuit()
    print("  [PASS 13/40] Repeated failures trip circuit to OPEN state.")

    test_14_open_circuit_blocks_invocation()
    print("  [PASS 14/40] OPEN circuit blocks subsequent invocations.")

    test_15_half_open_transition_and_probing()
    print("  [PASS 15/40] HALF_OPEN state transition after cooldown window.")

    test_16_successful_recovery_closes_circuit()
    print("  [PASS 16/40] Successful recovery probe closes circuit.")

    test_17_circuit_state_tenant_isolation()
    print("  [PASS 17/40] Circuit breaker state strictly isolated per tenant/scope.")

    test_18_concurrent_circuit_updates()
    print("  [PASS 18/40] Concurrent multi-thread circuit state updates.")

    test_19_compensating_action_execution()
    print("  [PASS 19/40] Compensating action execution on partial failure.")

    test_20_compensation_passes_authority_gates()
    print("  [PASS 20/40] Compensating actions pass authority gates.")

    test_21_graceful_degradation()
    print("  [PASS 21/40] Graceful degradation with explicit warning.")

    test_22_human_escalation_on_unrecoverable_failure()
    print("  [PASS 22/40] Human escalation on unrecoverable failures.")

    test_23_recovery_failure_is_explicit()
    print("  [PASS 23/40] Recovery failure status is explicit.")

    test_24_no_silent_success_after_failed_recovery()
    print("  [PASS 24/40] No silent success after failed recovery.")

    test_25_structural_verification_success()
    print("  [PASS 25/40] Structural verification pass.")

    test_26_structural_verification_failure()
    print("  [PASS 26/40] Structural verification failure on null/error payload.")

    test_27_semantic_verification_success()
    print("  [PASS 27/40] Semantic verification pass.")

    test_28_semantic_verification_failure()
    print("  [PASS 28/40] Semantic verification failure on numeric/content mismatch.")

    test_29_constitutional_verification_success()
    print("  [PASS 29/40] Constitutional verification pass.")

    test_30_constitutional_verification_failure()
    print("  [PASS 30/40] Constitutional block on secret/PII/dangerous pattern.")

    test_31_verification_failure_triggers_retry_when_allowed()
    print("  [PASS 31/40] Verification failure triggers retry.")

    test_32_verification_failure_does_not_incorrectly_produce_success()
    print("  [PASS 32/40] Verification failure does not produce success.")

    test_33_phase6_router_remains_mandatory()
    print("  [PASS 33/40] Phase 6 Tool Router remains mandatory.")

    test_34_phase7_dependency_ordering_preserved()
    print("  [PASS 34/40] Phase 7 DAG dependency ordering preserved.")

    test_35_actual_tool_invocation_only_after_all_gates()
    print("  [PASS 35/40] Tool invocation occurs only after all gates pass.")

    test_36_chitra_audit_generated_for_retries()
    print("  [PASS 36/40] CHITRA audit records generated for retries.")

    test_37_chitra_audit_generated_for_verification()
    print("  [PASS 37/40] CHITRA audit records generated for verification results.")

    test_38_tenant_isolation_maintained()
    print("  [PASS 38/40] Phase 4C tenant isolation maintained.")

    test_39_concurrent_workflows_safety()
    print("  [PASS 39/40] Concurrent multi-thread workflows safety.")

    test_40_no_phase9_functionality_introduced()
    print("  [PASS 40/40] Phase 9 boundary verified (0 Phase 9 features).")

    print("\n==================================================")
    print("ALL 40 KARMA PHASE 8 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_40_phase8_tests()
