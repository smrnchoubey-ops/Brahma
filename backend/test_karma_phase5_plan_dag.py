"""
KARMA Phase 5 Test Suite: Plan DAG & Step Model
Strictly tests Whitesheet §7.1, §7.2, §7.5 & §7.9 compliance.
"""
import pytest
import json
from pydantic import ValidationError

from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep, KarmaRetryPolicy
from app.core.karma.planner import build_karma_plan_from_pragya
from agents.state import PragyaPlan


def test_single_step_plan():
    step = KarmaStep(
        step_id="step_1",
        action="Fetch company financial metrics",
        tool="retrieval_tool",
        reason="Required for analysis",
        expected_outcome="Financial metrics returned in JSON format",
        dependencies=[],
        authority_required="LOW"
    )
    plan = KarmaPlanDAG(
        task_id=101,
        summary="Simple financial fetch",
        steps=[step]
    )
    assert len(plan.steps) == 1
    assert plan.get_roots() == [step]
    assert plan.get_topological_order() == [step]


def test_multi_step_branching_dag():
    # step_1 (root) -> step_2, step_3 -> step_4 (join)
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="A2", expected_outcome="O2", dependencies=["s1"])
    s3 = KarmaStep(step_id="s3", action="A3", expected_outcome="O3", dependencies=["s1"])
    s4 = KarmaStep(step_id="s4", action="A4", expected_outcome="O4", dependencies=["s2", "s3"])

    plan = KarmaPlanDAG(task_id=102, summary="Branching DAG", steps=[s4, s2, s3, s1])
    
    roots = plan.get_roots()
    assert len(roots) == 1
    assert roots[0].step_id == "s1"

    dependents_s1 = plan.get_dependents("s1")
    assert set(s.step_id for s in dependents_s1) == {"s2", "s3"}

    topo = plan.get_topological_order()
    topo_ids = [s.step_id for s in topo]
    
    assert topo_ids[0] == "s1"
    assert topo_ids.index("s2") > topo_ids.index("s1")
    assert topo_ids.index("s3") > topo_ids.index("s1")
    assert topo_ids.index("s4") > topo_ids.index("s2")
    assert topo_ids.index("s4") > topo_ids.index("s3")


def test_missing_dependency_rejection():
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=["non_existent_step"])
    with pytest.raises(ValueError, match="Missing dependency"):
        KarmaPlanDAG(task_id=103, summary="Invalid Dep Plan", steps=[s1])


def test_duplicate_step_id_rejection():
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=[])
    s2 = KarmaStep(step_id="s1", action="A2", expected_outcome="O2", dependencies=[])
    with pytest.raises(ValueError, match="Duplicate step_id"):
        KarmaPlanDAG(task_id=104, summary="Duplicate Step Plan", steps=[s1, s2])


def test_self_dependency_rejection():
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=["s1"])
    with pytest.raises(ValueError, match="Self-dependency detected"):
        KarmaPlanDAG(task_id=105, summary="Self Dep Plan", steps=[s1])


def test_direct_cycle_rejection():
    # s1 -> s2 -> s1
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=["s2"])
    s2 = KarmaStep(step_id="s2", action="A2", expected_outcome="O2", dependencies=["s1"])
    with pytest.raises(ValueError, match="Cycle detected"):
        KarmaPlanDAG(task_id=106, summary="Cycle Plan", steps=[s1, s2])


def test_complex_cycle_rejection():
    # s1 -> s2 -> s3 -> s1
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=["s3"])
    s2 = KarmaStep(step_id="s2", action="A2", expected_outcome="O2", dependencies=["s1"])
    s3 = KarmaStep(step_id="s3", action="A3", expected_outcome="O3", dependencies=["s2"])
    with pytest.raises(ValueError, match="Cycle detected"):
        KarmaPlanDAG(task_id=107, summary="Complex Cycle Plan", steps=[s1, s2, s3])


def test_empty_plan_rejection():
    with pytest.raises(ValueError):
        KarmaPlanDAG(task_id=108, summary="Empty Plan", steps=[])


def test_retry_policy_structure():
    custom_retry = KarmaRetryPolicy(
        max_attempts=5,
        backoff="exponential",
        base_delay_ms=500,
        jitter=True,
        circuit_break_after=3,
        circuit_break_window_seconds=120
    )
    step = KarmaStep(
        step_id="s1",
        action="Network call",
        expected_outcome="HTTP 200",
        retry_policy=custom_retry
    )
    assert step.retry_policy.max_attempts == 5
    assert step.retry_policy.base_delay_ms == 500
    assert step.retry_policy.circuit_break_after == 3


def test_authority_tiers_and_no_silent_actions():
    step = KarmaStep(
        step_id="s1",
        action="Execute trade",
        tool="broker_api",
        reason="Customer authorized portfolio rebalance",
        expected_outcome="Order filled at market price",
        authority_required="HIGH"
    )
    assert step.authority_required == "HIGH"
    assert step.reason != ""
    assert step.tool == "broker_api"
    assert step.expected_outcome != ""


def test_deterministic_serialization():
    s1 = KarmaStep(step_id="s1", action="A1", expected_outcome="O1", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="A2", expected_outcome="O2", dependencies=["s1"])
    plan = KarmaPlanDAG(task_id=200, summary="Serialization Test", steps=[s1, s2])

    serialized = plan.model_dump()
    deserialized = KarmaPlanDAG.model_validate(serialized)

    assert deserialized.plan_id == plan.plan_id
    assert deserialized.task_id == plan.task_id
    assert len(deserialized.steps) == 2
    assert deserialized.steps[1].dependencies == ["s1"]


def test_pragya_plan_conversion():
    pragya_output = PragyaPlan(
        summary="Synthesize risk memo",
        steps=[
            "Collect portfolio exposures",
            "Calculate Value at Risk (VaR)",
            "Draft executive summary"
        ],
        tools_needed=["retrieval", "calculator", "llm_writer"],
        assumptions=["Data is up to date"]
    )

    karma_dag = build_karma_plan_from_pragya(pragya_output, task_id=301, default_authority="MEDIUM")
    
    assert karma_dag.task_id == 301
    assert karma_dag.summary == "Synthesize risk memo"
    assert len(karma_dag.steps) == 3
    
    # Verify sequential dependencies synthesized
    assert karma_dag.steps[0].step_id == "step_1"
    assert karma_dag.steps[0].dependencies == []
    assert karma_dag.steps[0].tool == "retrieval"
    assert karma_dag.steps[0].authority_required == "MEDIUM"

    assert karma_dag.steps[1].step_id == "step_2"
    assert karma_dag.steps[1].dependencies == ["step_1"]
    assert karma_dag.steps[1].tool == "calculator"

    assert karma_dag.steps[2].step_id == "step_3"
    assert karma_dag.steps[2].dependencies == ["step_2"]
    assert karma_dag.steps[2].tool == "llm_writer"

    # Verify topological sort is valid
    topo = karma_dag.get_topological_order()
    assert [s.step_id for s in topo] == ["step_1", "step_2", "step_3"]


def run_all_karma_phase5_tests():
    print("==================================================")
    print("KARMA PHASE 5: PLAN DAG & STEP MODEL TEST SUITE")
    print("==================================================")
    
    test_single_step_plan()
    print("  [PASS] Single-step plan validation.")

    test_multi_step_branching_dag()
    print("  [PASS] Multi-step branching DAG & topological order.")

    test_missing_dependency_rejection()
    print("  [PASS] Missing dependency rejected (Fail-Closed).")

    test_duplicate_step_id_rejection()
    print("  [PASS] Duplicate step_id rejected.")

    test_self_dependency_rejection()
    print("  [PASS] Self-dependency rejected.")

    test_direct_cycle_rejection()
    print("  [PASS] Direct cycle (s1 <-> s2) rejected.")

    test_complex_cycle_rejection()
    print("  [PASS] Complex cycle (s1 -> s2 -> s3 -> s1) rejected.")

    test_empty_plan_rejection()
    print("  [PASS] Empty plan rejected.")

    test_retry_policy_structure()
    print("  [PASS] Whitesheet §7.5 retry policy representation.")

    test_authority_tiers_and_no_silent_actions()
    print("  [PASS] Whitesheet §7.2 / §7.9 authority tiers & mandatory action fields.")

    test_deterministic_serialization()
    print("  [PASS] Deterministic DAG serialization & deserialization.")

    test_pragya_plan_conversion()
    print("  [PASS] PRAGYA decision -> formal KARMA DAG conversion.")

    print("\n==================================================")
    print("ALL 12 KARMA PHASE 5 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_karma_phase5_tests()
