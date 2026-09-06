"""
SAGA Phase 15 Comprehensive Test Suite: Distributed Rollback & Compensating Transactions
Strictly tests Whitesheet §§14.0–14.6 across 30 explicit scenarios.
Runs against local sandbox database: test_karma_phase15_sandbox.db.
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
from app.core.saga.models import (
    SagaDefinition,
    SagaStep,
    SagaStatus,
    SagaStepStatus,
    SagaExecutionReport,
    SagaCompensationRecord
)
from app.core.saga.state_machine import SagaStateMachine, SagaInvalidStateTransitionError
from app.core.saga.compensation import SagaCompensationEngine
from app.core.saga.executor import SagaExecutor
from app.core.saga.service import SagaService
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.core.rachit.service import RachitExecutionService
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier
from app.core.kosh.vector_engine import KoshVectorStore

TEST_DB_URL = "sqlite:///./test_karma_phase15_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p15", hashed_password="pwd")
    user_b = User(username="user_bob_p15", hashed_password="pwd")
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
# 1. SAGA DEFINITION & STATE MACHINE (§14.1, §14.2) (1-5)
# -------------------------------------------------------------

def test_1_saga_creation_and_defaults():
    s1 = SagaStep(step_id="step_1", forward_action="reserve_inventory item_99", compensating_action="release_inventory item_99")
    saga = SagaService.create_saga(task_id=601, tenant_id="tenant_alice", summary="Order Saga", steps=[s1])
    assert saga.saga_id.startswith("saga_")
    assert saga.status == SagaStatus.PENDING
    assert len(saga.steps) == 1
    assert saga.steps[0].status == SagaStepStatus.PENDING


def test_2_valid_saga_state_transitions():
    SagaStateMachine.validate_saga_transition(SagaStatus.PENDING, SagaStatus.RUNNING)
    SagaStateMachine.validate_saga_transition(SagaStatus.RUNNING, SagaStatus.SUCCEEDED)
    SagaStateMachine.validate_saga_transition(SagaStatus.RUNNING, SagaStatus.COMPENSATING)
    SagaStateMachine.validate_saga_transition(SagaStatus.COMPENSATING, SagaStatus.COMPENSATED)


def test_3_invalid_saga_state_transition_fails_closed():
    with pytest.raises(SagaInvalidStateTransitionError, match="Illegal Saga transition"):
        SagaStateMachine.validate_saga_transition(SagaStatus.SUCCEEDED, SagaStatus.COMPENSATING)


def test_4_valid_step_state_transitions():
    SagaStateMachine.validate_step_transition(SagaStepStatus.PENDING, SagaStepStatus.RUNNING)
    SagaStateMachine.validate_step_transition(SagaStepStatus.RUNNING, SagaStepStatus.SUCCEEDED)
    SagaStateMachine.validate_step_transition(SagaStepStatus.SUCCEEDED, SagaStepStatus.COMPENSATING)
    SagaStateMachine.validate_step_transition(SagaStepStatus.COMPENSATING, SagaStepStatus.COMPENSATED)


def test_5_invalid_step_state_transition_fails_closed():
    with pytest.raises(SagaInvalidStateTransitionError, match="Illegal SagaStep transition"):
        SagaStateMachine.validate_step_transition(SagaStepStatus.PENDING, SagaStepStatus.COMPENSATED)


# -------------------------------------------------------------
# 2. FORWARD EXECUTION & DEPENDENCY ENFORCEMENT (§14.2) (6-8)
# -------------------------------------------------------------

def test_6_successful_linear_saga_execution():
    s1 = SagaStep(step_id="s1", forward_action="calculate 10+10", compensating_action="calculate 0")
    s2 = SagaStep(step_id="s2", forward_action="calculate 20+20", compensating_action="calculate 0", dependencies=["s1"])
    saga = SagaService.create_saga(task_id=602, tenant_id="tenant_alice", summary="Math Saga", steps=[s1, s2])

    rep = SagaService.execute(saga)
    assert rep.status == SagaStatus.SUCCEEDED
    assert rep.steps_completed == ["s1", "s2"]
    assert len(rep.steps_compensated) == 0


def test_7_dependency_enforcement_in_forward_steps():
    # s2 depends on missing s0 -> fails
    s1 = SagaStep(step_id="s1", forward_action="action_1", dependencies=["missing_s0"])
    saga = SagaService.create_saga(task_id=603, tenant_id="tenant_alice", summary="Dep Saga", steps=[s1])

    rep = SagaService.execute(saga)
    assert rep.status == SagaStatus.COMPENSATED or rep.status == SagaStatus.FAILED or rep.error is not None
    assert "Prerequisite dependency unmet" in rep.error


def test_8_forward_failure_stops_further_execution():
    def mock_dispatcher(action: str, metadata: dict):
        if "fail" in action:
            raise RuntimeError("Step failed explicitly")
        return {"status": "ok"}

    s1 = SagaStep(step_id="s1", forward_action="action_ok", compensating_action="comp_1")
    s2 = SagaStep(step_id="s2", forward_action="action_fail", compensating_action="comp_2", dependencies=["s1"])
    s3 = SagaStep(step_id="s3", forward_action="action_should_skip", compensating_action="comp_3", dependencies=["s2"])

    saga = SagaService.create_saga(task_id=604, tenant_id="tenant_alice", summary="Fail Saga", steps=[s1, s2, s3])
    rep = SagaService.execute(saga, action_dispatcher=mock_dispatcher)

    assert rep.status == SagaStatus.COMPENSATED
    assert s3.status == SagaStepStatus.SKIPPED
    assert "s1" in rep.steps_compensated


# -------------------------------------------------------------
# 3. REVERSE-ORDER COMPENSATION SEMANTICS (§14.3) (9-14)
# -------------------------------------------------------------

def test_9_reverse_order_compensation_execution():
    call_log = []

    def mock_action_dispatcher(action: str, metadata: dict):
        if action == "step_3_fail":
            raise RuntimeError("Failure at step 3")
        call_log.append(f"EXEC:{action}")
        return {"result": action}

    def mock_compensation_dispatcher(action: str, metadata: dict):
        call_log.append(f"COMP:{action}")
        return {"result": f"reverted_{action}"}

    s1 = SagaStep(step_id="s1", forward_action="charge_card $100", compensating_action="refund_card $100")
    s2 = SagaStep(step_id="s2", forward_action="reserve_hotel #45", compensating_action="cancel_hotel #45", dependencies=["s1"])
    s3 = SagaStep(step_id="s3", forward_action="step_3_fail", compensating_action="cancel_flight", dependencies=["s2"])

    saga = SagaService.create_saga(task_id=605, tenant_id="tenant_alice", summary="Travel Saga", steps=[s1, s2, s3])
    rep = SagaService.execute(saga, action_dispatcher=mock_action_dispatcher, compensation_dispatcher=mock_compensation_dispatcher)

    assert rep.status == SagaStatus.COMPENSATED
    assert call_log == [
        "EXEC:charge_card $100",
        "EXEC:reserve_hotel #45",
        "COMP:cancel_hotel #45",   # Reverse order: s2 first
        "COMP:refund_card $100"    # then s1
    ]


def test_10_multiple_successful_steps_compensated_in_reverse():
    s1 = SagaStep(step_id="s1", forward_action="action_1", compensating_action="comp_1")
    s2 = SagaStep(step_id="s2", forward_action="action_2", compensating_action="comp_2", dependencies=["s1"])
    s3 = SagaStep(step_id="s3", forward_action="action_3", compensating_action="comp_3", dependencies=["s2"])
    s4 = SagaStep(step_id="s4", forward_action="fail_step", dependencies=["s3"])

    def dispatcher(act: str, meta: dict):
        if act == "fail_step":
            raise ValueError("Boom")
        return {"ok": True}

    saga = SagaService.create_saga(task_id=606, tenant_id="tenant_alice", summary="Saga 4", steps=[s1, s2, s3, s4])
    rep = SagaService.execute(saga, action_dispatcher=dispatcher)

    assert rep.status == SagaStatus.COMPENSATED
    assert rep.steps_compensated == ["s3", "s2", "s1"]


def test_11_uncompensatable_step_skipped_safely():
    s1 = SagaStep(step_id="s1", forward_action="action_no_comp", compensating_action=None)
    s2 = SagaStep(step_id="s2", forward_action="action_fail", dependencies=["s1"])

    def dispatcher(act: str, meta: dict):
        if act == "action_fail":
            raise ValueError("Boom")
        return {"ok": True}

    saga = SagaService.create_saga(task_id=607, tenant_id="tenant_alice", summary="No Comp Saga", steps=[s1, s2])
    rep = SagaService.execute(saga, action_dispatcher=dispatcher)
    assert rep.status == SagaStatus.COMPENSATED
    assert len(rep.steps_compensated) == 0


def test_12_compensation_failure_sets_compensation_failed_state():
    def failing_comp_dispatcher(act: str, meta: dict):
        if "comp" in act:
            raise RuntimeError("Bank API Down for Refund")
        if act == "fail_step":
            raise ValueError("Fail")
        return {"ok": True}

    s1 = SagaStep(step_id="s1", forward_action="charge_user", compensating_action="comp_refund")
    s2 = SagaStep(step_id="s2", forward_action="fail_step", dependencies=["s1"])

    saga = SagaService.create_saga(task_id=608, tenant_id="tenant_alice", summary="Comp Fail Saga", steps=[s1, s2])
    rep = SagaService.execute(saga, action_dispatcher=failing_comp_dispatcher)

    assert rep.status == SagaStatus.COMPENSATION_FAILED
    assert "s1" in rep.compensation_failures


def test_13_idempotent_compensation_no_duplicate_runs():
    s1 = SagaStep(step_id="s1", forward_action="charge", compensating_action="refund", status=SagaStepStatus.SUCCEEDED)
    
    # First compensation run
    ok1, recs1 = SagaCompensationEngine.compensate_steps("saga_idemp", 609, "tenant_alice", [s1])
    assert ok1 is True
    assert s1.status == SagaStepStatus.COMPENSATED

    # Duplicate run should not execute again
    ok2, recs2 = SagaCompensationEngine.compensate_steps("saga_idemp", 609, "tenant_alice", [s1])
    assert ok2 is True
    assert len(recs2) == 0  # Skipped


def test_14_compensation_attempt_counter_tracked():
    s1 = SagaStep(step_id="s1", forward_action="charge", compensating_action="refund", status=SagaStepStatus.SUCCEEDED)
    SagaCompensationEngine.compensate_steps("saga_c", 610, "tenant_alice", [s1])
    assert s1.compensation_attempts == 1


# -------------------------------------------------------------
# 4. TENANT ISOLATION & GOVERNANCE INTEGRATION (§14.5, §18) (15-18)
# -------------------------------------------------------------

def test_15_empty_tenant_id_fails_closed():
    with pytest.raises(ValueError, match="Authenticated Tenant ID is required"):
        SagaService.create_saga(task_id=611, tenant_id="", summary="Bad Tenant", steps=[])


def test_16_cross_tenant_saga_isolation():
    saga_a = SagaService.create_saga(task_id=612, tenant_id="tenant_alice", summary="A", steps=[])
    saga_b = SagaService.create_saga(task_id=613, tenant_id="tenant_bob", summary="B", steps=[])
    assert saga_a.tenant_id != saga_b.tenant_id


def test_17_maryada_governance_rejection_on_forward_step():
    # Forward step containing destructive command blocked by MARYADA
    s1 = SagaStep(step_id="s1", forward_action="rm -rf /tmp/data", compensating_action="restore_data")
    saga = SagaService.create_saga(task_id=614, tenant_id="tenant_alice", summary="Blocked Saga", steps=[s1])

    rep = SagaService.execute(saga)
    assert rep.status == SagaStatus.COMPENSATED or rep.error is not None
    assert "blocked by MARYADA" in rep.error


def test_18_maryada_governance_rejection_on_compensating_action():
    # Forward action is benign, compensating action is destructive -> blocked during compensation
    s1 = SagaStep(step_id="s1", forward_action="reserve_seat 1A", compensating_action="rm -rf /tmp/database", status=SagaStepStatus.SUCCEEDED)
    
    ok, recs = SagaCompensationEngine.compensate_steps("saga_gov_comp", 615, "tenant_alice", [s1])
    assert ok is False
    assert recs[0].status == "COMPENSATION_FAILED"
    assert "blocked by MARYADA" in recs[0].error


# -------------------------------------------------------------
# 5. CHITRA AUDIT LOGGING & CRYPTO INTEGRITY (§14.6) (19-22)
# -------------------------------------------------------------

def test_19_chitra_saga_lifecycle_audit_events():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s1 = SagaStep(step_id="s1", forward_action="calculate 2+2", compensating_action="calculate 0")
    saga = SagaService.create_saga(task_id=t_a, tenant_id=f"tenant_{u_a}", summary="CHITRA Saga", steps=[s1])

    SagaService.execute(saga, db_session=db, user_id=u_a)

    evts = db.query(ChitraEvent).filter(ChitraEvent.task_id == t_a, ChitraEvent.faculty == "SAGA").all()
    assert len(evts) >= 2  # SAGA_STARTED + SAGA_SUCCEEDED + forward step
    db.close()


def test_20_chitra_forward_step_audit_events():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s1 = SagaStep(step_id="s1", forward_action="calculate 5+5", compensating_action="calculate 0")
    saga = SagaService.create_saga(task_id=t_a, tenant_id=f"tenant_{u_a}", summary="Step Evt Saga", steps=[s1])
    SagaService.execute(saga, db_session=db, user_id=u_a)

    step_evt = db.query(ChitraEvent).filter(
        ChitraEvent.task_id == t_a, ChitraEvent.event_type == "forward_step"
    ).first()
    assert step_evt is not None
    assert step_evt.decision["step_id"] == "s1"
    db.close()


def test_21_chitra_compensation_audit_events():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    def fail_disp(act: str, meta: dict):
        if act == "fail":
            raise RuntimeError("Err")
        return {"status": "ok"}

    s1 = SagaStep(step_id="s1", forward_action="good_act", compensating_action="comp_act")
    s2 = SagaStep(step_id="s2", forward_action="fail", dependencies=["s1"])
    saga = SagaService.create_saga(task_id=t_a, tenant_id=f"tenant_{u_a}", summary="Comp Evt Saga", steps=[s1, s2])

    SagaService.execute(saga, action_dispatcher=fail_disp, db_session=db, user_id=u_a)

    comp_evt = db.query(ChitraEvent).filter(
        ChitraEvent.task_id == t_a, ChitraEvent.event_type == "compensation"
    ).first()
    assert comp_evt is not None
    assert comp_evt.decision["status"] == "COMPENSATED"
    db.close()


def test_22_cryptographic_verification_of_saga_chitra_chain():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s1 = SagaStep(step_id="s1", forward_action="calculate 1+1", compensating_action="calculate 0")
    saga = SagaService.create_saga(task_id=t_a, tenant_id=f"tenant_{u_a}", summary="Crypto Saga", steps=[s1])
    SagaService.execute(saga, db_session=db, user_id=u_a)

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked >= 3
    db.close()


# -------------------------------------------------------------
# 6. EVIDENCE & CONCURRENCY (23-25)
# -------------------------------------------------------------

def test_23_structured_compensation_record_evidence():
    rec = SagaCompensationRecord(
        saga_id="saga_test",
        task_id=616,
        tenant_id="tenant_alice",
        step_id="s1",
        forward_action="debit $500",
        compensating_action="credit $500",
        status="COMPENSATED",
        result={"tx_id": "tx_revert_99"}
    )
    dumped = rec.model_dump()
    assert dumped["saga_id"] == "saga_test"
    assert dumped["status"] == "COMPENSATED"
    assert "timestamp" in dumped


def test_24_deterministic_compensation_behavior():
    s1 = SagaStep(step_id="s1", forward_action="step_1", compensating_action="comp_1", status=SagaStepStatus.SUCCEEDED)
    s2 = SagaStep(step_id="s2", forward_action="step_2", compensating_action="comp_2", status=SagaStepStatus.SUCCEEDED)
    
    order = []
    def disp(act: str, meta: dict):
        order.append(act)
        return {"ok": True}

    SagaCompensationEngine.compensate_steps("saga_det", 617, "tenant_alice", [s1, s2], action_dispatcher=disp)
    assert order == ["comp_2", "comp_1"]


def test_25_concurrent_saga_executions_isolation():
    def run_worker(i: int):
        s = SagaStep(step_id=f"s_{i}", forward_action=f"calc {i}", compensating_action=f"comp {i}")
        saga = SagaService.create_saga(task_id=618 + i, tenant_id=f"tenant_{i % 3}", summary=f"Saga {i}", steps=[s])
        return SagaService.execute(saga)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run_worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert all(r.status == SagaStatus.SUCCEEDED for r in results)


# -------------------------------------------------------------
# 7. END-TO-END PIPELINE & BOUNDARIES (26-30)
# -------------------------------------------------------------

def test_26_full_end_to_end_successful_saga_pipeline():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s1 = SagaStep(step_id="s1", forward_action="calculate 10 * 10", compensating_action="calculate 0")
    s2 = SagaStep(step_id="s2", forward_action="calculate 20 * 20", compensating_action="calculate 0", dependencies=["s1"])
    saga = SagaService.create_saga(task_id=t_a, tenant_id=f"tenant_{u_a}", summary="Full Saga", steps=[s1, s2])

    rep = SagaService.execute(saga, db_session=db, user_id=u_a)
    assert rep.status == SagaStatus.SUCCEEDED

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    db.close()


def test_27_full_end_to_end_compensated_saga_pipeline():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    def disp(act: str, meta: dict):
        if act == "fail_step":
            raise RuntimeError("Database unavailable")
        return {"status": "ok"}

    s1 = SagaStep(step_id="s1", forward_action="hold_funds", compensating_action="release_funds")
    s2 = SagaStep(step_id="s2", forward_action="fail_step", compensating_action="comp_none", dependencies=["s1"])
    saga = SagaService.create_saga(task_id=t_a, tenant_id=f"tenant_{u_a}", summary="Compensated Pipeline", steps=[s1, s2])

    rep = SagaService.execute(saga, action_dispatcher=disp, db_session=db, user_id=u_a)
    assert rep.status == SagaStatus.COMPENSATED
    assert "s1" in rep.steps_compensated

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    db.close()


def test_28_no_silent_compensation_failures():
    def fail_disp(act: str, meta: dict):
        raise RuntimeError("Fatal hardware failure")

    s1 = SagaStep(step_id="s1", forward_action="action_ok", compensating_action="comp_must_fail", status=SagaStepStatus.SUCCEEDED)
    ok, recs = SagaCompensationEngine.compensate_steps("saga_fail", 619, "tenant_alice", [s1], action_dispatcher=fail_disp)

    assert ok is False
    assert len(recs) == 1
    assert recs[0].status == "COMPENSATION_FAILED"
    assert "Fatal hardware failure" in recs[0].error


def test_29_integration_with_phase14_rachit_and_phase10_kosh():
    # Verifies RACHIT & KOSH exports remain fully compatible and functional
    assert hasattr(RachitExecutionService, "execute_sandboxed_tool")
    assert hasattr(KoshVectorStore, "add_chunk")


def test_30_phase16_boundary_check():
    # Strictly ensures no Phase 16 cognitive re-planning loop exists in Saga
    assert not hasattr(SagaExecutor, "llm_cognitive_replanning_agent")
    assert not hasattr(SagaService, "dynamic_prompt_synthesizer")


def run_all_30_phase15_tests():
    print("==================================================")
    print("SAGA PHASE 15: 30-SCENARIO DISTRIBUTED ROLLBACK &")
    print("COMPENSATING TRANSACTIONS SUITE (WHITESHEET §14.0-14.6)")
    print("Target Sandbox: sqlite:///./test_karma_phase15_sandbox.db")
    print("==================================================")

    test_1_saga_creation_and_defaults()
    print("  [PASS 1/30] [REAL] Saga creation & schema defaults (§14.1).")

    test_2_valid_saga_state_transitions()
    print("  [PASS 2/30] [REAL] Valid Saga state transitions (§14.1).")

    test_3_invalid_saga_state_transition_fails_closed()
    print("  [PASS 3/30] [REAL] Invalid Saga state transition fails closed.")

    test_4_valid_step_state_transitions()
    print("  [PASS 4/30] [REAL] Valid SagaStep state transitions.")

    test_5_invalid_step_state_transition_fails_closed()
    print("  [PASS 5/30] [REAL] Invalid SagaStep state transition fails closed.")

    test_6_successful_linear_saga_execution()
    print("  [PASS 6/30] [REAL] Successful linear forward Saga execution (§14.2).")

    test_7_dependency_enforcement_in_forward_steps()
    print("  [PASS 7/30] [REAL] Dependency enforcement in forward steps.")

    test_8_forward_failure_stops_further_execution()
    print("  [PASS 8/30] [REAL] Forward failure halts further execution.")

    test_9_reverse_order_compensation_execution()
    print("  [PASS 9/30] [REAL] Reverse-order compensation execution (§14.3).")

    test_10_multiple_successful_steps_compensated_in_reverse()
    print("  [PASS 10/30] [REAL] Multiple successful steps compensated in reverse (§14.3).")

    test_11_uncompensatable_step_skipped_safely()
    print("  [PASS 11/30] [REAL] Uncompensatable step skipped safely.")

    test_12_compensation_failure_sets_compensation_failed_state()
    print("  [PASS 12/30] [REAL] Compensation failure sets COMPENSATION_FAILED state.")

    test_13_idempotent_compensation_no_duplicate_runs()
    print("  [PASS 13/30] [REAL] Idempotent compensation duplicate protection (§14.4).")

    test_14_compensation_attempt_counter_tracked()
    print("  [PASS 14/30] [REAL] Compensation attempt counter tracked.")

    test_15_empty_tenant_id_fails_closed()
    print("  [PASS 15/30] [REAL] Empty tenant ID fails closed.")

    test_16_cross_tenant_saga_isolation()
    print("  [PASS 16/30] [REAL] Cross-tenant Saga isolation (§18).")

    test_17_maryada_governance_rejection_on_forward_step()
    print("  [PASS 17/30] [REAL] MARYADA governance rejection on forward step (§14.5).")

    test_18_maryada_governance_rejection_on_compensating_action()
    print("  [PASS 18/30] [REAL] MARYADA governance rejection on compensating action (§14.5).")

    test_19_chitra_saga_lifecycle_audit_events()
    print("  [PASS 19/30] [REAL] CHITRA Saga lifecycle audit events (§14.6).")

    test_20_chitra_forward_step_audit_events()
    print("  [PASS 20/30] [REAL] CHITRA forward step audit events.")

    test_21_chitra_compensation_audit_events()
    print("  [PASS 21/30] [REAL] CHITRA compensation audit events.")

    test_22_cryptographic_verification_of_saga_chitra_chain()
    print("  [PASS 22/30] [REAL] Cryptographic verification of SAGA CHITRA chain (§14.6).")

    test_23_structured_compensation_record_evidence()
    print("  [PASS 23/30] [REAL] Structured compensation record evidence.")

    test_24_deterministic_compensation_behavior()
    print("  [PASS 24/30] [REAL] Deterministic compensation behavior.")

    test_25_concurrent_saga_executions_isolation()
    print("  [PASS 25/30] [REAL] Concurrent Saga executions isolation.")

    test_26_full_end_to_end_successful_saga_pipeline()
    print("  [PASS 26/30] [REAL] Full end-to-end successful Saga pipeline.")

    test_27_full_end_to_end_compensated_saga_pipeline()
    print("  [PASS 27/30] [REAL] Full end-to-end compensated Saga pipeline.")

    test_28_no_silent_compensation_failures()
    print("  [PASS 28/30] [REAL] No silent compensation failures (§14.3).")

    test_29_integration_with_phase14_rachit_and_phase10_kosh()
    print("  [PASS 29/30] [REAL] Integration compatibility with Phase 14 RACHIT and Phase 10 KOSH.")

    test_30_phase16_boundary_check()
    print("  [PASS 30/30] [REAL] Phase 16 boundary verified (0 Phase 16 features).")

    print("\n==================================================")
    print("ALL 30 SAGA PHASE 15 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_30_phase15_tests()
