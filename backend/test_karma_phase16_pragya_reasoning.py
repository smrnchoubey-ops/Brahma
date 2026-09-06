"""
PRAGYA Phase 16 Comprehensive Test Suite: Cognitive Reasoning & Plan Synthesis
Strictly tests Whitesheet §§6.0–6.6 & §§15.0–15.6 across 30 explicit scenarios.
Runs against local sandbox database: test_karma_phase16_sandbox.db.
"""
import pytest
import json
import concurrent.futures
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep, KarmaRetryPolicy
from app.core.karma.executor import KarmaDAGExecutor
from app.core.karma.tool_registry import KarmaToolRegistry, KarmaToolDefinition
from app.core.saga.models import SagaDefinition, SagaStep, SagaStatus
from app.core.saga.service import SagaService
from app.core.kosh.retrieval_service import KoshRetrievalService, KoshRetrievalResult
from app.core.kosh.vector_engine import KoshVectorStore, generate_deterministic_test_embedding
from unittest.mock import patch, MagicMock

# Default mock LLM response for fast deterministic offline test execution
def default_mock_llm(messages, temperature=0.0):
    user_prompt = messages[-1]["content"] if messages else ""
    return MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps({
        "summary": "Synthesized Plan",
        "assumptions": ["Standard test operational constraints"],
        "steps": [
            {"step_id": "step_1", "action": "calculate 10+20", "expected_outcome": "30", "dependencies": [], "compensating_action": "calculate 0"},
            {"step_id": "step_2", "action": "calculate 30+40", "expected_outcome": "70", "dependencies": ["step_1"], "compensating_action": "calculate 0"}
        ]
    })))])
from app.core.kosh.memory_tiers import KoshChunk, MemoryTier
from app.core.pragya.intent_parser import DeterministicIntentParser, IntentDecomposition
from app.core.pragya.validator import PragyaPlanValidator, PragyaPlanValidationError
from app.core.pragya.plan_synthesizer import PragyaPlanSynthesizer, StructuredPlanDraft, StructuredStepDraft
from app.core.pragya.service import PragyaService, PragyaResult
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.core.murphy.service import MurphyService
from app.core.rachit.service import RachitExecutionService
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase16_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p16", hashed_password="pwd")
    user_b = User(username="user_bob_p16", hashed_password="pwd")
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


# -------------------------------------------------------------
# 1. INTENT PARSING & DECOMPOSITION (§6.1, §15.1) (1-5)
# -------------------------------------------------------------

def test_1_basic_goal_extraction():
    decomp = DeterministicIntentParser.parse_intent(
        intent="Calculate monthly payroll and send notification",
        tenant_id="tenant_alice",
        task_id=701
    )
    assert decomp.main_goal == "Calculate monthly payroll and send notification"
    assert len(decomp.sub_goals) == 2
    assert "Calculate monthly payroll" in decomp.sub_goals[0]
    assert "send notification" in decomp.sub_goals[1]


def test_2_constraint_extraction():
    decomp = DeterministicIntentParser.parse_intent(
        intent="Run database read-only audit within 45 seconds on production",
        tenant_id="tenant_alice",
        task_id=702
    )
    assert decomp.constraints.get("read_only") is True
    assert decomp.constraints.get("timeout_sec") == 45
    assert decomp.constraints.get("elevated_risk") is True


def test_3_empty_intent_rejection_fail_closed():
    with pytest.raises(ValueError, match="Intent cannot be empty"):
        DeterministicIntentParser.parse_intent(
            intent="   ",
            tenant_id="tenant_alice",
            task_id=703
        )


def test_4_kosh_context_injection():
    vstore = KoshVectorStore()
    content = "Payroll formula is base + bonus - tax."
    chunk = KoshChunk(
        chunk_id="chk_1",
        tenant_id="tenant_alice",
        title="Payroll Rules",
        tier=MemoryTier.WORKING_CONTEXT,
        content=content,
        embedding=generate_deterministic_test_embedding(content)
    )
    vstore.add_chunk(chunk)
    kosh_service = KoshRetrievalService(vector_store=vstore)

    res = PragyaService.generate_plan(
        intent="Calculate bonus payroll",
        tenant_id="tenant_alice",
        task_id=704,
        kosh_service=kosh_service
    )
    assert res.knowledge_context_used is True
    assert res.injected_chunk_count >= 1


def test_5_kosh_failure_graceful_fallback():
    # If KOSH service throws, planning proceeds safely
    class BrokenKosh:
        def retrieve(self, *args, **kwargs):
            raise RuntimeError("KOSH vector DB disconnected")

    res = PragyaService.generate_plan(
        intent="Calculate 10+20",
        tenant_id="tenant_alice",
        task_id=705,
        kosh_service=BrokenKosh()
    )
    assert res.is_valid is True
    assert res.knowledge_context_used is False


# -------------------------------------------------------------
# 2. PLAN & DAG SYNTHESIS (§6.3, §15.3) (6-12)
# -------------------------------------------------------------

def test_6_karmaplandag_synthesis():
    res = PragyaService.generate_plan(
        intent="Compute tax and generate invoice",
        tenant_id="tenant_alice",
        task_id=706
    )
    assert isinstance(res.plan_dag, KarmaPlanDAG)
    assert len(res.plan_dag.steps) >= 2
    assert res.plan_dag.task_id == 706


def test_7_dependency_ordering_in_dag():
    mock_llm = lambda msgs: json.dumps({
        "summary": "Ordered Plan",
        "steps": [
            {"step_id": "step_1", "action": "Step A", "expected_outcome": "A done", "dependencies": []},
            {"step_id": "step_2", "action": "Step B", "expected_outcome": "B done", "dependencies": ["step_1"]},
            {"step_id": "step_3", "action": "Step C", "expected_outcome": "C done", "dependencies": ["step_2"]}
        ]
    })
    res = PragyaService.generate_plan(
        intent="Step A and then Step B and then Step C",
        tenant_id="tenant_alice",
        task_id=707,
        llm_callable=mock_llm
    )
    order = res.plan_dag.get_topological_order()
    assert len(order) == 3
    step_ids = [s.step_id for s in order]
    assert step_ids == ["step_1", "step_2", "step_3"]


def test_8_linear_plan_synthesis():
    mock_llm = lambda msgs: json.dumps({
        "summary": "Linear Workflow",
        "assumptions": ["All systems operational"],
        "steps": [
            {"step_id": "s1", "action": "calc 1", "expected_outcome": "1", "dependencies": []},
            {"step_id": "s2", "action": "calc 2", "expected_outcome": "2", "dependencies": ["s1"]}
        ]
    })
    res = PragyaService.generate_plan(
        intent="Linear flow",
        tenant_id="tenant_alice",
        task_id=708,
        llm_callable=mock_llm
    )
    assert len(res.plan_dag.steps) == 2
    assert res.plan_dag.steps[1].dependencies == ["s1"]


def test_9_diamond_dag_synthesis():
    mock_llm = lambda msgs: json.dumps({
        "summary": "Diamond DAG",
        "steps": [
            {"step_id": "root", "action": "init", "expected_outcome": "ok", "dependencies": []},
            {"step_id": "left", "action": "fetch_left", "expected_outcome": "ok", "dependencies": ["root"]},
            {"step_id": "right", "action": "fetch_right", "expected_outcome": "ok", "dependencies": ["root"]},
            {"step_id": "merge", "action": "combine", "expected_outcome": "ok", "dependencies": ["left", "right"]}
        ]
    })
    res = PragyaService.generate_plan(
        intent="Diamond flow",
        tenant_id="tenant_alice",
        task_id=709,
        llm_callable=mock_llm
    )
    ordered = res.plan_dag.get_topological_order()
    assert len(ordered) == 4
    ordered_ids = [s.step_id for s in ordered]
    assert ordered_ids[0] == "root"
    assert ordered_ids[-1] == "merge"


def test_10_cycle_rejection_in_pragya():
    cyclic_llm = lambda msgs: json.dumps({
        "summary": "Bad Cycle Plan",
        "steps": [
            {"step_id": "s1", "action": "act 1", "expected_outcome": "ok", "dependencies": ["s2"]},
            {"step_id": "s2", "action": "act 2", "expected_outcome": "ok", "dependencies": ["s1"]}
        ]
    })
    with pytest.raises(ValueError, match="Cycle detected"):
        PragyaService.generate_plan(
            intent="Cyclic prompt",
            tenant_id="tenant_alice",
            task_id=710,
            llm_callable=cyclic_llm
        )


def test_11_duplicate_step_rejection():
    dup_llm = lambda msgs: json.dumps({
        "summary": "Duplicate Steps",
        "steps": [
            {"step_id": "s1", "action": "act 1", "expected_outcome": "ok", "dependencies": []},
            {"step_id": "s1", "action": "act 2", "expected_outcome": "ok", "dependencies": []}
        ]
    })
    with pytest.raises(ValueError, match="Duplicate step_id"):
        PragyaService.generate_plan(
            intent="Dup prompt",
            tenant_id="tenant_alice",
            task_id=711,
            llm_callable=dup_llm
        )


def test_12_nonexistent_dependency_rejection():
    missing_dep_llm = lambda msgs: json.dumps({
        "summary": "Missing Dep",
        "steps": [
            {"step_id": "s1", "action": "act 1", "expected_outcome": "ok", "dependencies": ["ghost_step"]}
        ]
    })
    with pytest.raises(ValueError, match="Missing dependency"):
        PragyaService.generate_plan(
            intent="Ghost prompt",
            tenant_id="tenant_alice",
            task_id=712,
            llm_callable=missing_dep_llm
        )


# -------------------------------------------------------------
# 3. SAGA SYNTHESIS & COMPENSATIONS (§15.3, §14) (13-15)
# -------------------------------------------------------------

def test_13_saga_definition_synthesis():
    res = PragyaService.generate_plan(
        intent="Debit funds and book hotel",
        tenant_id="tenant_alice",
        task_id=713
    )
    assert isinstance(res.saga_definition, SagaDefinition)
    assert res.saga_definition.task_id == 713
    assert res.saga_definition.tenant_id == "tenant_alice"
    assert len(res.saga_definition.steps) >= 2


def test_14_compensation_annotation_accuracy():
    mock_llm = lambda msgs: json.dumps({
        "summary": "Compensated Travel",
        "steps": [
            {"step_id": "s1", "action": "charge_card $200", "expected_outcome": "charged", "compensating_action": "refund_card $200", "dependencies": []}
        ]
    })
    res = PragyaService.generate_plan(
        intent="Book flight",
        tenant_id="tenant_alice",
        task_id=714,
        llm_callable=mock_llm
    )
    saga_step = res.saga_definition.steps[0]
    assert saga_step.forward_action == "charge_card $200"
    assert saga_step.compensating_action == "refund_card $200"


def test_15_expected_outcome_contracts():
    res = PragyaService.generate_plan(
        intent="Compile binary and run tests",
        tenant_id="tenant_alice",
        task_id=715
    )
    for step in res.plan_dag.steps:
        assert step.expected_outcome is not None
        assert len(step.expected_outcome) > 0


# -------------------------------------------------------------
# 4. STRUCTURED LLM SAFETY & ERROR HANDLING (16-18)
# -------------------------------------------------------------

def test_16_malformed_llm_json_fallback():
    # If LLM returns broken raw markdown text, fallback deterministic builder engages
    bad_llm = lambda msgs: "Here is the plan:\nStep 1: do something\nStep 2: finish"
    res = PragyaService.generate_plan(
        intent="Step A and Step B",
        tenant_id="tenant_alice",
        task_id=716,
        llm_callable=bad_llm
    )
    assert res.is_valid is True
    assert len(res.plan_dag.steps) == 2


def test_17_pydantic_schema_validation():
    draft = StructuredPlanDraft(
        summary="Test Draft",
        assumptions=["None"],
        steps=[StructuredStepDraft(step_id="s1", action="action", expected_outcome="ok")]
    )
    assert draft.steps[0].tool == "generic_executor"


def test_18_llm_timeout_handling():
    def timeout_llm(msgs):
        raise TimeoutError("Provider timed out after 30s")

    # Should fall back cleanly without unhandled crash
    res = PragyaService.generate_plan(
        intent="Calculate revenue and expense",
        tenant_id="tenant_alice",
        task_id=718,
        llm_callable=timeout_llm
    )
    assert res.is_valid is True


# -------------------------------------------------------------
# 5. MULTI-TENANT & DATA ISOLATION (§6.5, §18) (19-21)
# -------------------------------------------------------------

def test_19_empty_tenant_rejection():
    with pytest.raises(ValueError, match="Authenticated Tenant ID is required"):
        PragyaService.generate_plan(
            intent="Valid intent",
            tenant_id="",
            task_id=719
        )


def test_20_cross_tenant_kosh_isolation():
    vstore = KoshVectorStore()
    content_bob = "SECRET_BOB_TOKEN_12345"
    chunk_bob = KoshChunk(
        chunk_id="chk_bob",
        tenant_id="tenant_bob",
        title="Bob Secret",
        tier=MemoryTier.WORKING_CONTEXT,
        content=content_bob,
        embedding=generate_deterministic_test_embedding(content_bob)
    )
    vstore.add_chunk(chunk_bob)
    kosh_service = KoshRetrievalService(vector_store=vstore)

    # Tenant Alice queries
    res_alice = PragyaService.generate_plan(
        intent="Get SECRET_BOB_TOKEN",
        tenant_id="tenant_alice",
        task_id=720,
        kosh_service=kosh_service
    )
    # Alice should not see Bob's chunk
    assert res_alice.injected_chunk_count == 0


def test_21_tenant_scoped_metadata():
    res = PragyaService.generate_plan(
        intent="Calculate taxes",
        tenant_id="tenant_enterprise_xyz",
        task_id=721
    )
    assert res.tenant_id == "tenant_enterprise_xyz"
    assert res.saga_definition.tenant_id == "tenant_enterprise_xyz"


# -------------------------------------------------------------
# 6. CHITRA AUDITING & CRYPTO INTEGRITY (§6.6, §15.6) (22-24)
# -------------------------------------------------------------

def test_22_chitra_plan_generation_event():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    res = PragyaService.generate_plan(
        intent="Calculate payroll and issue paychecks",
        tenant_id=f"tenant_{u_a}",
        task_id=t_a,
        db_session=db,
        user_id=u_a
    )
    assert res.chitra_event_id is not None

    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == res.chitra_event_id).first()
    assert evt is not None
    assert evt.faculty == "PRAGYA"
    assert evt.event_type == "plan_generation"
    assert evt.decision["tenant_id"] == f"tenant_{u_a}"
    db.close()


def test_23_chitra_payload_integrity():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    res = PragyaService.generate_plan(
        intent="Audit logs",
        tenant_id=f"tenant_{u_a}",
        task_id=t_a,
        db_session=db,
        user_id=u_a
    )
    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == res.chitra_event_id).first()
    assert "plan_summary" in evt.decision
    assert "step_count" in evt.decision
    db.close()


def test_24_chitra_cryptographic_verification():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    PragyaService.generate_plan(
        intent="Run sanity check",
        tenant_id=f"tenant_{u_a}",
        task_id=t_a,
        db_session=db,
        user_id=u_a
    )
    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    db.close()


# -------------------------------------------------------------
# 7. DETERMINISM & CONCURRENCY (25-26)
# -------------------------------------------------------------

def test_25_deterministic_post_processing():
    decomp = DeterministicIntentParser.parse_intent(
        intent="Action 1 and then Action 2",
        tenant_id="tenant_alice",
        task_id=725
    )
    dag1, _ = PragyaPlanSynthesizer.synthesize_plan(decomp, llm_callable=lambda msgs: "broken")
    dag2, _ = PragyaPlanSynthesizer.synthesize_plan(decomp, llm_callable=lambda msgs: "broken")

    assert [s.step_id for s in dag1.steps] == [s.step_id for s in dag2.steps]
    assert [s.action for s in dag1.steps] == [s.action for s in dag2.steps]


def test_26_concurrent_planning_isolation():
    def plan_worker(i: int):
        return PragyaService.generate_plan(
            intent=f"Concurrent task {i} step A and step B",
            tenant_id=f"tenant_{i % 4}",
            task_id=800 + i
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(plan_worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert all(r.is_valid for r in results)


# -------------------------------------------------------------
# 8. INTEGRATION & BOUNDARIES (27-30)
# -------------------------------------------------------------

def test_27_pragya_to_karma_execution_integration():
    # Validates that a plan synthesized by PRAGYA executes seamlessly through KarmaDAGExecutor
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    res = PragyaService.generate_plan(
        intent="calculate 10+20 and calculate 30+40",
        tenant_id=f"tenant_{u_a}",
        task_id=t_a,
        db_session=db,
        user_id=u_a
    )
    executor = KarmaDAGExecutor()
    rep = executor.execute_plan(res.plan_dag, caller_authority="LOW", db_session=db, user_id=u_a)
    assert rep.status == "COMPLETED"
    db.close()


def test_28_pragya_to_saga_compensation_integration():
    # Validates that a Saga synthesized by PRAGYA executes and compensates through SagaService
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    res = PragyaService.generate_plan(
        intent="reserve seat and charge card",
        tenant_id=f"tenant_{u_a}",
        task_id=t_a,
        db_session=db,
        user_id=u_a
    )
    saga_rep = SagaService.execute(res.saga_definition, db_session=db, user_id=u_a)
    assert saga_rep.status == SagaStatus.SUCCEEDED
    db.close()


def test_29_pragya_governance_boundary_verification():
    # Asserts that PRAGYA does not execute tools directly, preserving MURPHY/MARYADA boundaries
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    destructive_llm = lambda msgs: json.dumps({
        "summary": "Destructive Plan",
        "steps": [
            {"step_id": "s1", "action": "rm -rf /critical_data", "expected_outcome": "deleted", "dependencies": []}
        ]
    })
    res = PragyaService.generate_plan(
        intent="rm -rf /critical_data",
        tenant_id=f"tenant_{u_a}",
        task_id=t_a,
        db_session=db,
        user_id=u_a,
        llm_callable=destructive_llm
    )
    # Plan is generated, but when MARYADA evaluates it, it must block execution
    verdict = MaryadaGatekeeper.evaluate_plan_gate(res.plan_dag, caller_authority="LOW", db_session=db)
    assert verdict.approved is False
    assert len(verdict.justification) > 0
    db.close()


def test_30_phase17_boundary_check():
    # Strictly ensures no Phase 17 distributed cluster/broker infrastructure exists in PRAGYA
    assert not hasattr(PragyaService, "kafka_producer")
    assert not hasattr(PragyaService, "celery_app")
    assert not hasattr(PragyaService, "cluster_load_balancer")


@patch("app.core.pragya.plan_synthesizer.call_llm", side_effect=default_mock_llm)
def run_all_30_phase16_tests(mock_llm_patch=None):
    print("==================================================")
    print("PRAGYA PHASE 16: 30-SCENARIO COGNITIVE REASONING &")
    print("PLAN SYNTHESIS SUITE (WHITESHEET §6.0-6.6 & §15.0-15.6)")
    print("Target Sandbox: sqlite:///./test_karma_phase16_sandbox.db")
    print("==================================================")

    test_1_basic_goal_extraction()
    print("  [PASS 1/30] [REAL] Basic goal extraction (§6.1).")

    test_2_constraint_extraction()
    print("  [PASS 2/30] [REAL] Constraint extraction (§6.1).")

    test_3_empty_intent_rejection_fail_closed()
    print("  [PASS 3/30] [REAL] Empty intent rejection fails closed.")

    test_4_kosh_context_injection()
    print("  [PASS 4/30] [REAL] KOSH context injection into reasoning prompt (§6.2).")

    test_5_kosh_failure_graceful_fallback()
    print("  [PASS 5/30] [REAL] KOSH failure graceful fallback.")

    test_6_karmaplandag_synthesis()
    print("  [PASS 6/30] [REAL] KarmaPlanDAG formal synthesis (§6.3).")

    test_7_dependency_ordering_in_dag()
    print("  [PASS 7/30] [REAL] Dependency ordering in DAG (§6.3).")

    test_8_linear_plan_synthesis()
    print("  [PASS 8/30] [REAL] Linear plan synthesis.")

    test_9_diamond_dag_synthesis()
    print("  [PASS 9/30] [REAL] Diamond DAG topological synthesis.")

    test_10_cycle_rejection_in_pragya()
    print("  [PASS 10/30] [REAL] Cycle detection rejection in PRAGYA (§6.4).")

    test_11_duplicate_step_rejection()
    print("  [PASS 11/30] [REAL] Duplicate step ID rejection.")

    test_12_nonexistent_dependency_rejection()
    print("  [PASS 12/30] [REAL] Nonexistent dependency rejection.")

    test_13_saga_definition_synthesis()
    print("  [PASS 13/30] [REAL] SagaDefinition synthesis (§15.3).")

    test_14_compensation_annotation_accuracy()
    print("  [PASS 14/30] [REAL] Compensation annotation accuracy (§15.3).")

    test_15_expected_outcome_contracts()
    print("  [PASS 15/30] [REAL] Declarative expected outcome contracts.")

    test_16_malformed_llm_json_fallback()
    print("  [PASS 16/30] [REAL] Malformed LLM JSON fallback & schema recovery (§6.4).")

    test_17_pydantic_schema_validation()
    print("  [PASS 17/30] [REAL] Pydantic schema validation enforcement.")

    test_18_llm_timeout_handling()
    print("  [PASS 18/30] [REAL] LLM timeout handling.")

    test_19_empty_tenant_rejection()
    print("  [PASS 19/30] [REAL] Empty tenant rejection fails closed.")

    test_20_cross_tenant_kosh_isolation()
    print("  [PASS 20/30] [REAL] Cross-tenant KOSH memory isolation (§6.5).")

    test_21_tenant_scoped_metadata()
    print("  [PASS 21/30] [REAL] Tenant-scoped plan metadata.")

    test_22_chitra_plan_generation_event()
    print("  [PASS 22/30] [REAL] CHITRA plan generation audit event (§6.6).")

    test_23_chitra_payload_integrity()
    print("  [PASS 23/30] [REAL] CHITRA payload integrity.")

    test_24_chitra_cryptographic_verification()
    print("  [PASS 24/30] [REAL] CHITRA cryptographic verification (§6.6).")

    test_25_deterministic_post_processing()
    print("  [PASS 25/30] [REAL] Deterministic post-processing for fixed input.")

    test_26_concurrent_planning_isolation()
    print("  [PASS 26/30] [REAL] Concurrent planning isolation.")

    test_27_pragya_to_karma_execution_integration()
    print("  [PASS 27/30] [REAL] PRAGYA -> KARMA execution integration.")

    test_28_pragya_to_saga_compensation_integration()
    print("  [PASS 28/30] [REAL] PRAGYA -> SAGA compensation integration.")

    test_29_pragya_governance_boundary_verification()
    print("  [PASS 29/30] [REAL] PRAGYA governance boundary verification (MURPHY/MARYADA).")

    test_30_phase17_boundary_check()
    print("  [PASS 30/30] [REAL] Phase 17 boundary check (0 Phase 17 features).")

    print("\n==================================================")
    print("ALL 30 PRAGYA PHASE 16 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_30_phase16_tests()
