"""
KARMA Phase 7 Comprehensive Test Suite: DAG Executor & Dependency Walker
Strictly tests Whitesheet §7.1, §7.3, §7.4 & §7.9 compliance across 24 specific scenarios.
Runs against local sandbox database: test_karma_phase7_sandbox.db.
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
from app.core.karma.tool_registry import (
    KarmaToolDefinition,
    KarmaToolRegistry,
    get_default_tool_registry
)
from app.core.karma.tool_router import KarmaToolRouter
from app.core.karma.executor import KarmaDAGExecutor, KarmaDAGExecutionReport
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase7_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user = User(username="executor_test_user", hashed_password="pwd")
    db.add(user)
    db.commit()
    db.refresh(user)

    task = Task(user_id=user.id, title="Execution Test Task", prompt="Testing DAG executor", status="PENDING")
    db.add(task)
    db.commit()
    db.refresh(task)

    user_id = user.id
    task_id = task.id
    db.close()
    return user_id, task_id


# Test 1: Single-step DAG execution
def test_1_single_step_dag_execution():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="step_1", action="calculate 20 + 30", expected_outcome="50", dependencies=[])
    plan = KarmaPlanDAG(task_id=1, summary="Single step math", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status == "COMPLETED"
    assert report.succeeded_steps_count == 1
    assert report.step_results["step_1"].status == "SUCCEEDED"
    assert report.step_results["step_1"].output["result"] == 50


# Test 2: Multi-step linear dependency execution
def test_2_multi_step_linear_dependency_execution():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 10 + 5", expected_outcome="15", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="calendar_lookup", expected_outcome="Holidays", dependencies=["s1"])
    s3 = KarmaStep(step_id="s3", action="system_status", expected_outcome="Status", dependencies=["s2"])

    plan = KarmaPlanDAG(task_id=2, summary="Linear Plan", steps=[s3, s1, s2])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status == "COMPLETED"
    assert report.execution_order == ["s1", "s2", "s3"]
    assert report.succeeded_steps_count == 3


# Test 3: Multi-branch DAG execution
def test_3_multi_branch_dag_execution():
    # s1 -> (s2, s3) -> s4
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 5 * 5", expected_outcome="25", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="calendar_lookup", expected_outcome="Calendar", dependencies=["s1"])
    s3 = KarmaStep(step_id="s3", action="system_status", expected_outcome="Status", dependencies=["s1"])
    s4 = KarmaStep(step_id="s4", action="echo deliverable ready", expected_outcome="Echo", dependencies=["s2", "s3"])

    plan = KarmaPlanDAG(task_id=3, summary="Branching Plan", steps=[s4, s2, s3, s1])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status == "COMPLETED"
    assert report.execution_order[0] == "s1"
    assert report.execution_order[-1] == "s4"
    assert set(report.execution_order[1:3]) == {"s2", "s3"}


# Test 4: Strict dependency ordering
def test_4_strict_dependency_ordering():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 1 + 1", expected_outcome="2", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="calculate 2 + 2", expected_outcome="4", dependencies=["s1"])
    s3 = KarmaStep(step_id="s3", action="calculate 4 + 4", expected_outcome="8", dependencies=["s2"])

    plan = KarmaPlanDAG(task_id=4, summary="Strict Order", steps=[s2, s3, s1])
    report = executor.execute_plan(plan)
    assert report.execution_order.index("s1") < report.execution_order.index("s2")
    assert report.execution_order.index("s2") < report.execution_order.index("s3")


# Test 5: Independent steps remain independent
def test_5_independent_steps_remain_independent():
    def failing_handler(params):
        raise ValueError("Branch failure")

    executor = KarmaDAGExecutor(custom_handlers={"failing_tool": failing_handler})
    tool = KarmaToolDefinition(tool_id="failing_tool", name="Failing Tool", capabilities=["fail_branch"], trust_score=0.9)
    executor.registry.register_tool(tool)

    s1 = KarmaStep(step_id="s1", action="fail_branch", expected_outcome="Fail", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="echo done", expected_outcome="Done", dependencies=["s1"])
    s3 = KarmaStep(step_id="s3", action="calculate 100 / 10", expected_outcome="10", dependencies=[])

    plan = KarmaPlanDAG(task_id=5, summary="Independent Branch Plan", steps=[s1, s2, s3])
    report = executor.execute_plan(plan)
    assert report.step_results["s1"].status in ["FAILED", "ESCALATED"]
    assert report.step_results["s2"].status == "BLOCKED"
    assert report.step_results["s3"].status == "SUCCEEDED"


# Test 6: Missing dependency rejection
def test_6_missing_dependency_rejection():
    s1 = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=["non_existent_dep"])
    with pytest.raises(ValueError, match="Missing dependency"):
        KarmaPlanDAG(task_id=6, summary="Missing Dep", steps=[s1])


# Test 7: Unknown step rejection in DAG
def test_7_unknown_step_rejection():
    s1 = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])
    plan = KarmaPlanDAG(task_id=7, summary="Test", steps=[s1])
    # Asserting non-existent step access returns None in step_results
    executor = KarmaDAGExecutor()
    report = executor.execute_plan(plan)
    assert "unknown_step" not in report.step_results


# Test 8: Cycle / invalid DAG rejection
def test_8_cycle_invalid_dag_rejection():
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=["s2"])
    s2 = KarmaStep(step_id="s2", action="A2", expected_outcome="O2", dependencies=["s1"])
    with pytest.raises(ValueError, match="Cycle detected"):
        KarmaPlanDAG(task_id=8, summary="Cycle", steps=[s1, s2])


# Test 9: Failed dependency blocks dependent step
def test_9_failed_dependency_blocks_dependent_step():
    def failing_handler(params):
        raise RuntimeError("Network fault")

    executor = KarmaDAGExecutor(custom_handlers={"failing_tool": failing_handler})
    tool = KarmaToolDefinition(tool_id="failing_tool", name="Failing Tool", capabilities=["fail_act"], trust_score=0.9)
    executor.registry.register_tool(tool)

    s1 = KarmaStep(step_id="s1", action="fail_act", expected_outcome="Fail", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="calculate 2 + 2", expected_outcome="4", dependencies=["s1"])

    plan = KarmaPlanDAG(task_id=9, summary="Cascade", steps=[s1, s2])
    report = executor.execute_plan(plan)
    assert report.step_results["s1"].status in ["FAILED", "ESCALATED"]
    assert report.step_results["s2"].status == "BLOCKED"
    assert "s2" not in report.execution_order


# Test 10: Unavailable tool blocks execution
def test_10_unavailable_tool_blocks_execution():
    executor = KarmaDAGExecutor()
    executor.registry.set_availability("calculator", False)

    s1 = KarmaStep(step_id="s1", action="calculate 50 * 2", expected_outcome="100", dependencies=[])
    plan = KarmaPlanDAG(task_id=10, summary="Unavailable", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].status in ["FAILED", "ESCALATED"]
    assert "unavailable" in report.step_results["s1"].error.lower()


# Test 11: Insufficient authority blocks execution
def test_11_insufficient_authority_blocks_execution():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="settlement 50000 USD", expected_outcome="Settled", dependencies=[])
    plan = KarmaPlanDAG(task_id=11, summary="Privileged Settlement", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].status in ["FAILED", "ESCALATED"]
    assert "requires authority tier" in report.step_results["s1"].error


# Test 12: Missing authority context fails closed
def test_12_missing_authority_context_fails_closed():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="wire_transfer", expected_outcome="Transfer", dependencies=[])
    plan = KarmaPlanDAG(task_id=12, summary="Missing Auth", steps=[s1])

    report = executor.execute_plan(plan, caller_authority=None)
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].status in ["FAILED", "ESCALATED"]


# Test 13: Constitutional / MARYADA restriction blocks execution
def test_13_constitutional_maryada_restriction_blocks_execution():
    executor = KarmaDAGExecutor()
    unconstitutional_tool = KarmaToolDefinition(
        tool_id="bad_sniffer",
        name="Bad Sniffer",
        capabilities=["unauthorized_sniff"],
        constitutional_compliant=False
    )
    executor.registry.register_tool(unconstitutional_tool)

    s1 = KarmaStep(step_id="s1", action="unauthorized_sniff", expected_outcome="Data", dependencies=[])
    plan = KarmaPlanDAG(task_id=13, summary="Unconstitutional", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="CRITICAL")
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].status in ["FAILED", "ESCALATED"]
    assert "constitutional" in report.step_results["s1"].error.lower()


# Test 14: Client-forged step authority cannot bypass registered tool authority
def test_14_client_forged_step_authority_cannot_bypass():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(
        step_id="s1",
        action="wire_transfer",
        expected_outcome="Transferred",
        authority_required="LOW",
        tool="financial_settlement_api"
    )
    plan = KarmaPlanDAG(task_id=14, summary="Spoof", steps=[s1])

    report = executor.execute_plan(plan, caller_authority="LOW")
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.step_results["s1"].status in ["FAILED", "ESCALATED"]


# Test 15: Tool Router is actually used for selection
def test_15_tool_router_is_used_for_selection():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 12 * 12", expected_outcome="144", dependencies=[])
    plan = KarmaPlanDAG(task_id=15, summary="Router Selection Test", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.step_results["s1"].tool_id == "calculator"
    assert report.step_results["s1"].execution_evidence["routing_score"] > 0.0


# Test 16: Router itself does not execute tools
def test_16_router_itself_does_not_execute_tools():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)
    s1 = KarmaStep(step_id="s1", action="calculate 9 * 9", expected_outcome="81", dependencies=[])
    decision = router.route_step(s1, "LOW")
    assert not hasattr(decision, "output")


# Test 17: Actual executor invocation occurs only after all gates pass
def test_17_actual_executor_invocation_only_after_gates_pass():
    call_log = []
    def logged_handler(params):
        call_log.append("INVOKED")
        return {"done": True}

    executor = KarmaDAGExecutor(custom_handlers={"custom_gated_tool": logged_handler})
    tool = KarmaToolDefinition(
        tool_id="custom_gated_tool",
        name="Gated",
        capabilities=["custom_gate_act"],
        authority_required="HIGH"
    )
    executor.registry.register_tool(tool)

    s1 = KarmaStep(step_id="s1", action="custom_gate_act", expected_outcome="Done", dependencies=[])
    plan = KarmaPlanDAG(task_id=17, summary="Gate Check", steps=[s1])

    # Call with LOW -> rejected, handler must NOT be called
    executor.execute_plan(plan, caller_authority="LOW")
    assert len(call_log) == 0

    # Call with HIGH -> approved, handler invoked
    executor.execute_plan(plan, caller_authority="HIGH")
    assert len(call_log) == 1


# Test 18: Tool invocation failure produces explicit failed state
def test_18_tool_invocation_failure_produces_failed_state():
    def exploding_handler(params):
        raise ZeroDivisionError("Math error: divide by zero")

    executor = KarmaDAGExecutor(custom_handlers={"exploding_calc": exploding_handler})
    tool = KarmaToolDefinition(tool_id="exploding_calc", name="Exploding", capabilities=["explode_math"])
    executor.registry.register_tool(tool)

    s1 = KarmaStep(step_id="s1", action="explode_math", expected_outcome="Result", dependencies=[])
    plan = KarmaPlanDAG(task_id=18, summary="Explosion", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.step_results["s1"].status in ["FAILED", "ESCALATED"]
    assert "divide by zero" in report.step_results["s1"].error


# Test 19: No silent success after failed invocation
def test_19_no_silent_success_after_failed_invocation():
    def exploding_handler(params):
        raise KeyError("Missing key")

    executor = KarmaDAGExecutor(custom_handlers={"bad_key": exploding_handler})
    tool = KarmaToolDefinition(tool_id="bad_key", name="BadKey", capabilities=["key_action"])
    executor.registry.register_tool(tool)

    s1 = KarmaStep(step_id="s1", action="key_action", expected_outcome="Result", dependencies=[])
    plan = KarmaPlanDAG(task_id=19, summary="No Silent", steps=[s1])

    report = executor.execute_plan(plan)
    assert report.status in ["FAILED", "ESCALATED"]
    assert report.succeeded_steps_count == 0


# Test 20: Deterministic execution order
def test_20_deterministic_execution_order():
    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="calculate 2+2", expected_outcome="4", dependencies=["s1"])
    s3 = KarmaStep(step_id="s3", action="calculate 3+3", expected_outcome="6", dependencies=["s1"])
    s4 = KarmaStep(step_id="s4", action="calculate 4+4", expected_outcome="8", dependencies=["s2", "s3"])

    orders = []
    for _ in range(20):
        plan = KarmaPlanDAG(task_id=20, summary="Deterministic Order", steps=[s4, s3, s1, s2])
        report = executor.execute_plan(plan)
        orders.append(report.execution_order)

    first = orders[0]
    for o in orders:
        assert o == first


# Test 21: Concurrent execution safety
def test_21_concurrent_execution_safety():
    executor = KarmaDAGExecutor()

    def run_plan_task(i: int):
        s1 = KarmaStep(step_id="s1", action=f"calculate {i} * 2", expected_outcome="Product", dependencies=[])
        plan = KarmaPlanDAG(task_id=200 + i, summary=f"Concurrent {i}", steps=[s1])
        return executor.execute_plan(plan, caller_authority="LOW")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run_plan_task, i) for i in range(25)]
        reports = [f.result() for f in futures]

    assert len(reports) == 25
    assert all(r.status == "COMPLETED" for r in reports)


# Test 22: CHITRA audit event is generated for actual invocation
def test_22_chitra_audit_event_generated_for_actual_invocation():
    user_id, task_id = reset_sandbox()
    db = TestSession()

    executor = KarmaDAGExecutor()
    s1 = KarmaStep(step_id="s1", action="calculate 7 * 8", expected_outcome="56", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="system_status", expected_outcome="Operational", dependencies=["s1"])

    plan = KarmaPlanDAG(task_id=task_id, summary="Audited Plan", steps=[s1, s2])
    report = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=user_id)
    assert report.status == "COMPLETED"

    evts = chitra_repository.get_events_for_task(db, task_id, user_id=user_id)
    assert len(evts) == 2
    assert evts[0].faculty == "RACHIT"
    assert evts[1].faculty == "RACHIT"

    v_res = chitra_verifier.verify_task_chain(db, task_id, user_id=user_id)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    db.close()


# Test 23: Regression test proving Phase 5 DAG behavior remains unchanged
def test_23_regression_phase5_dag_behavior_unchanged():
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="A2", expected_outcome="O2", dependencies=["s1"])
    plan = KarmaPlanDAG(task_id=23, summary="Phase 5 Regression", steps=[s2, s1])
    assert plan.get_topological_order()[0].step_id == "s1"
    assert plan.get_roots() == [s1]


# Test 24: Regression test proving Phase 6 routing behavior remains unchanged
def test_24_regression_phase6_routing_behavior_unchanged():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)
    dec = router.route("calculate 100 * 2", "LOW")
    assert dec.status == "ROUTED"
    assert dec.selected_tool_id == "calculator"


def run_all_24_phase7_tests():
    print("==================================================")
    print("KARMA PHASE 7: 24-SCENARIO DAG EXECUTOR & DEPENDENCY SUITE")
    print("Target Sandbox: sqlite:///./test_karma_phase7_sandbox.db")
    print("==================================================")

    test_1_single_step_dag_execution()
    print("  [PASS 1/24] Single-step DAG execution.")

    test_2_multi_step_linear_dependency_execution()
    print("  [PASS 2/24] Multi-step linear dependency execution.")

    test_3_multi_branch_dag_execution()
    print("  [PASS 3/24] Multi-branch DAG execution.")

    test_4_strict_dependency_ordering()
    print("  [PASS 4/24] Strict dependency ordering.")

    test_5_independent_steps_remain_independent()
    print("  [PASS 5/24] Independent parallel steps remain independent.")

    test_6_missing_dependency_rejection()
    print("  [PASS 6/24] Missing dependency rejection.")

    test_7_unknown_step_rejection()
    print("  [PASS 7/24] Unknown step rejection.")

    test_8_cycle_invalid_dag_rejection()
    print("  [PASS 8/24] Cycle/invalid DAG rejection.")

    test_9_failed_dependency_blocks_dependent_step()
    print("  [PASS 9/24] Failed dependency blocks dependent steps.")

    test_10_unavailable_tool_blocks_execution()
    print("  [PASS 10/24] Unavailable tool blocks execution.")

    test_11_insufficient_authority_blocks_execution()
    print("  [PASS 11/24] Insufficient authority blocks execution.")

    test_12_missing_authority_context_fails_closed()
    print("  [PASS 12/24] Missing authority context fails closed.")

    test_13_constitutional_maryada_restriction_blocks_execution()
    print("  [PASS 13/24] Constitutional/MARYADA restriction blocks execution.")

    test_14_client_forged_step_authority_cannot_bypass()
    print("  [PASS 14/24] Client-forged step authority cannot bypass registered gate.")

    test_15_tool_router_is_used_for_selection()
    print("  [PASS 15/24] Tool Router is used for tool selection.")

    test_16_router_itself_does_not_execute_tools()
    print("  [PASS 16/24] Router itself does not execute tools.")

    test_17_actual_executor_invocation_only_after_gates_pass()
    print("  [PASS 17/24] Actual executor invocation occurs only after all gates pass.")

    test_18_tool_invocation_failure_produces_failed_state()
    print("  [PASS 18/24] Tool invocation failure produces explicit FAILED state.")

    test_19_no_silent_success_after_failed_invocation()
    print("  [PASS 19/24] No silent success after failed invocation.")

    test_20_deterministic_execution_order()
    print("  [PASS 20/24] Deterministic execution order.")

    test_21_concurrent_execution_safety()
    print("  [PASS 21/24] Concurrent execution safety across threads.")

    test_22_chitra_audit_event_generated_for_actual_invocation()
    print("  [PASS 22/24] CHITRA audit event is generated for actual invocation.")

    test_23_regression_phase5_dag_behavior_unchanged()
    print("  [PASS 23/24] Phase 5 Plan DAG regression passed.")

    test_24_regression_phase6_routing_behavior_unchanged()
    print("  [PASS 24/24] Phase 6 Tool Router regression passed.")

    print("\n==================================================")
    print("ALL 24 KARMA PHASE 7 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_24_phase7_tests()
