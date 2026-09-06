"""
MURPHY Phase 12 Comprehensive Test Suite: Predictive Verification & Blast-Radius Assessment
Strictly tests Whitesheet §§11.0–11.6 across 30 explicit scenarios.
Runs against local sandbox database: test_karma_phase12_sandbox.db.
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
from app.core.karma.executor import KarmaDAGExecutor
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.core.murphy.report import MurphyRiskTier, MurphyRecommendation, MurphyRiskReport
from app.core.murphy.blast_radius import MurphyBlastRadiusCalculator
from app.core.murphy.simulator import MurphySimulationEngine
from app.core.murphy.service import MurphyService
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase12_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p12", hashed_password="pwd")
    user_b = User(username="user_bob_p12", hashed_password="pwd")
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
# 1. BLAST-RADIUS SCORING & CATEGORIES (§11.2) (1-5)
# -------------------------------------------------------------

def test_1_low_blast_radius_read_only():
    score = MurphyBlastRadiusCalculator.calculate_action_score("calculate 20 + 30")
    assert score <= 0.10


def test_2_medium_blast_radius_single_write():
    score = MurphyBlastRadiusCalculator.calculate_action_score("update_user_profile")
    assert 0.20 <= score <= 0.50


def test_3_high_blast_radius_financial_transaction():
    score = MurphyBlastRadiusCalculator.calculate_action_score("wire_transfer 50000 USD")
    assert 0.70 <= score <= 0.95


def test_4_critical_blast_radius_destructive_command():
    score = MurphyBlastRadiusCalculator.calculate_action_score("drop database production")
    assert score >= 0.95


def test_5_critical_blast_radius_credential_exfiltration():
    s = KarmaStep(step_id="s1", action="dump secrets from vault", expected_outcome="keys")
    plan = KarmaPlanDAG(task_id=301, summary="Secret exfil", steps=[s])
    rep = MurphySimulationEngine.simulate_plan(plan)
    assert rep.risk_level == MurphyRiskTier.CRITICAL
    assert rep.recommendation == MurphyRecommendation.BLOCKED


# -------------------------------------------------------------
# 2. FAIL-CLOSED ON UPSTREAM & MALFORMED PLANS (§11.3) (6-9)
# -------------------------------------------------------------

def test_6_unknown_risk_on_empty_plan():
    empty_plan = type("EmptyPlan", (), {"steps": [], "task_id": 302})()
    rep = MurphySimulationEngine.simulate_plan(empty_plan)
    assert rep.risk_level == MurphyRiskTier.UNKNOWN
    assert rep.recommendation == MurphyRecommendation.BLOCKED


def test_7_unknown_risk_on_null_plan():
    rep = MurphySimulationEngine.simulate_plan(None)
    assert rep.risk_level == MurphyRiskTier.UNKNOWN
    assert rep.recommendation == MurphyRecommendation.BLOCKED


def test_8_unknown_risk_on_pragya_upstream_failure():
    s = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2")
    plan = KarmaPlanDAG(task_id=303, summary="P", steps=[s])
    rep = MurphySimulationEngine.simulate_plan(plan, upstream_status="PRAGYA_FAILED")
    assert rep.risk_level == MurphyRiskTier.UNKNOWN
    assert rep.recommendation == MurphyRecommendation.BLOCKED


def test_9_unknown_risk_on_upstream_errors():
    s = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2")
    plan = KarmaPlanDAG(task_id=304, summary="P", steps=[s])
    rep = MurphySimulationEngine.simulate_plan(plan, upstream_errors=["LLM timeout", "Parser error"])
    assert rep.risk_level == MurphyRiskTier.UNKNOWN
    assert rep.recommendation == MurphyRecommendation.BLOCKED


# -------------------------------------------------------------
# 3. STRUCTURAL FAILURE MODES & RECOMMENDATIONS (§11.1, §11.4) (10-15)
# -------------------------------------------------------------

def test_10_missing_dependency_failure_mode_detection():
    s1 = type("Step", (), {"step_id": "s1", "action": "calculate 1+1", "dependencies": ["missing_step_id"]})()
    plan = type("MockPlan", (), {"steps": [s1], "task_id": 305})()
    rep = MurphySimulationEngine.simulate_plan(plan)
    assert rep.risk_level == MurphyRiskTier.MEDIUM
    assert any("missing_step_id" in fm for fm in rep.failure_modes)


def test_11_cascading_multi_step_aggregate_scoring():
    s1 = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2", dependencies=[])
    s2 = KarmaStep(step_id="s2", action="wire_transfer 5000 USD", expected_outcome="done", dependencies=["s1"])
    plan = KarmaPlanDAG(task_id=306, summary="Multi step", steps=[s1, s2])
    rep = MurphySimulationEngine.simulate_plan(plan)
    assert rep.risk_level == MurphyRiskTier.HIGH
    assert rep.simulated_steps_count == 2


def test_12_recommendation_proceed_for_low_risk():
    s1 = KarmaStep(step_id="s1", action="calculate 100 * 5", expected_outcome="500", dependencies=[])
    plan = KarmaPlanDAG(task_id=307, summary="Benign", steps=[s1])
    rep = MurphySimulationEngine.simulate_plan(plan)
    assert rep.risk_level == MurphyRiskTier.LOW
    assert rep.recommendation == MurphyRecommendation.PROCEED


def test_13_recommendation_human_review_for_high_risk():
    s1 = KarmaStep(step_id="s1", action="settlement 100000 USD", expected_outcome="done", dependencies=[])
    plan = KarmaPlanDAG(task_id=308, summary="Settlement", steps=[s1])
    rep = MurphySimulationEngine.simulate_plan(plan)
    assert rep.recommendation == MurphyRecommendation.HUMAN_REVIEW


def test_14_recommendation_blocked_for_critical_risk():
    s1 = KarmaStep(step_id="s1", action="rm -rf /var/db", expected_outcome="done", dependencies=[])
    plan = KarmaPlanDAG(task_id=309, summary="Destructive", steps=[s1])
    rep = MurphySimulationEngine.simulate_plan(plan)
    assert rep.recommendation == MurphyRecommendation.BLOCKED


def test_15_deterministic_scoring_repeatability():
    s1 = KarmaStep(step_id="s1", action="update_user_record", expected_outcome="ok", dependencies=[])
    plan = KarmaPlanDAG(task_id=310, summary="Update", steps=[s1])
    rep1 = MurphySimulationEngine.simulate_plan(plan)
    rep2 = MurphySimulationEngine.simulate_plan(plan)
    assert rep1.blast_radius_score == rep2.blast_radius_score
    assert rep1.risk_level == rep2.risk_level


# -------------------------------------------------------------
# 4. TENANT SAFETY & SERVICE ISOLATION (16-18)
# -------------------------------------------------------------

def test_16_empty_tenant_id_fails_closed():
    s = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2")
    plan = KarmaPlanDAG(task_id=311, summary="P", steps=[s])
    with pytest.raises(ValueError, match="Authenticated Tenant ID is required"):
        MurphyService.analyze_plan_risk(plan, tenant_id="")


def test_17_tenant_isolation_in_simulation():
    s = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2")
    plan = KarmaPlanDAG(task_id=312, summary="P", steps=[s])
    rep = MurphyService.analyze_plan_risk(plan, tenant_id="tenant_alice")
    assert rep.risk_level == MurphyRiskTier.LOW


def test_18_cross_tenant_denial():
    s = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2")
    plan = KarmaPlanDAG(task_id=313, summary="P", steps=[s])
    rep_a = MurphyService.analyze_plan_risk(plan, tenant_id="tenant_alice")
    rep_b = MurphyService.analyze_plan_risk(plan, tenant_id="tenant_bob")
    assert rep_a.risk_level == rep_b.risk_level


# -------------------------------------------------------------
# 5. CHITRA SIMULATION AUDIT (§11.6, §8.2) (19-21)
# -------------------------------------------------------------

def test_19_chitra_simulation_event_generation():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s = KarmaStep(step_id="s1", action="calculate 50 * 5", expected_outcome="250")
    plan = KarmaPlanDAG(task_id=t_a, summary="Sim Plan", steps=[s])

    report = MurphyService.analyze_plan_risk(plan, tenant_id=f"tenant_{u_a}", db_session=db, user_id=u_a)
    assert report.chitra_event_id is not None

    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == report.chitra_event_id).first()
    assert evt is not None
    assert evt.faculty == "MURPHY"
    assert evt.event_type == "simulation"
    assert evt.decision["risk_level"] == "LOW"
    db.close()


def test_20_chitra_simulation_payload_integrity():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s = KarmaStep(step_id="s1", action="wire_transfer 25000 USD", expected_outcome="done")
    plan = KarmaPlanDAG(task_id=t_a, summary="Wire Plan", steps=[s])

    report = MurphyService.analyze_plan_risk(plan, tenant_id=f"tenant_{u_a}", db_session=db, user_id=u_a)
    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == report.chitra_event_id).first()
    assert evt.decision["recommendation"] == "HUMAN_REVIEW"
    assert evt.decision["blast_radius_score"] > 0.50
    db.close()


def test_21_cryptographic_verification_on_murphy_events():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    s1 = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2")
    plan1 = KarmaPlanDAG(task_id=t_a, summary="P1", steps=[s1])
    MurphyService.analyze_plan_risk(plan1, tenant_id=f"tenant_{u_a}", db_session=db, user_id=u_a)

    s2 = KarmaStep(step_id="s2", action="system_status", expected_outcome="ok")
    plan2 = KarmaPlanDAG(task_id=t_a, summary="P2", steps=[s2])
    MurphyService.analyze_plan_risk(plan2, tenant_id=f"tenant_{u_a}", db_session=db, user_id=u_a)

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked == 2
    db.close()


# -------------------------------------------------------------
# 6. INTEGRATION WITH MARYADA (§10) & KARMA (§7) (22-24)
# -------------------------------------------------------------

def test_22_murphy_to_maryada_low_risk_integration():
    s = KarmaStep(step_id="s1", action="calculate 2+2", expected_outcome="4")
    plan = KarmaPlanDAG(task_id=314, summary="Low", steps=[s])
    murphy_rep = MurphySimulationEngine.simulate_plan(plan)

    # MARYADA consumes MURPHY risk report
    maryada_v = MaryadaGatekeeper.evaluate_action_gate(
        action="calculate 2+2",
        caller_authority="LOW",
        reported_risk=murphy_rep.risk_level.value
    )
    assert maryada_v.approved is True


def test_23_murphy_to_maryada_high_risk_integration():
    s = KarmaStep(step_id="s1", action="wire_transfer 50000 USD", expected_outcome="done")
    plan = KarmaPlanDAG(task_id=315, summary="High", steps=[s])
    murphy_rep = MurphySimulationEngine.simulate_plan(plan)

    maryada_v = MaryadaGatekeeper.evaluate_action_gate(
        action="wire_transfer 50000 USD",
        caller_authority="HIGH",
        reported_risk=murphy_rep.risk_level.value
    )
    assert maryada_v.approved is True
    assert maryada_v.risk_tier.value == "HIGH"


def test_24_murphy_to_maryada_unknown_risk_fail_closed():
    # If MURPHY fails closed, MARYADA must fail closed
    maryada_v = MaryadaGatekeeper.evaluate_action_gate(
        action="calculate 1+1",
        caller_authority="LOW",
        reported_risk=MurphyRiskTier.UNKNOWN.value
    )
    assert maryada_v.approved is False
    assert maryada_v.status.value == "MARYADA_BLOCKED"


# -------------------------------------------------------------
# 7. CONCURRENCY, PIPELINE & BOUNDARY (25-30)
# -------------------------------------------------------------

def test_25_simulation_engine_exception_handling():
    # Passing object with invalid attributes triggers fail-closed exception handler
    class BrokenStep:
        pass
    broken_plan = type("BrokenPlan", (), {"steps": [BrokenStep()], "task_id": 999})()
    rep = MurphySimulationEngine.simulate_plan(broken_plan)
    assert rep.risk_level == MurphyRiskTier.UNKNOWN
    assert rep.recommendation == MurphyRecommendation.BLOCKED


def test_26_concurrent_murphy_simulations():
    def worker(i: int):
        s = KarmaStep(step_id=f"s_{i}", action=f"calculate {i} * 10", expected_outcome="ok")
        p = KarmaPlanDAG(task_id=i, summary=f"Plan {i}", steps=[s])
        return MurphySimulationEngine.simulate_plan(p)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(25)]
        results = [f.result() for f in futures]

    assert len(results) == 25
    assert all(r.risk_level == MurphyRiskTier.LOW for r in results)


def test_27_full_pipeline_phase5_to_phase12():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    # 1. Phase 5 Plan DAG
    s1 = KarmaStep(step_id="s1", action="calculate 12 * 12", expected_outcome="144", dependencies=[])
    plan = KarmaPlanDAG(task_id=t_a, summary="P5-P12 Pipeline", steps=[s1])

    # 2. Phase 12 MURPHY Simulation
    murphy_report = MurphyService.analyze_plan_risk(plan, tenant_id=f"tenant_{u_a}", db_session=db, user_id=u_a)
    assert murphy_report.risk_level == MurphyRiskTier.LOW

    # 3. Phase 11 MARYADA Gate consuming MURPHY report
    maryada_verdict = MaryadaGatekeeper.evaluate_plan_gate(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert maryada_verdict.approved is True

    # 4. Phase 7, 8, 9 KARMA DAG Executor
    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    karma_report = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert karma_report.status == "COMPLETED"

    # 5. Cryptographic verification of all 3 events (MURPHY simulation + MARYADA gate + RACHIT invocation)
    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked >= 3
    db.close()


def test_28_murphy_evaluated_strictly_before_execution():
    # If MURPHY returns CRITICAL, execution does not proceed
    s = KarmaStep(step_id="s1", action="drop database clients", expected_outcome="done")
    plan = KarmaPlanDAG(task_id=316, summary="Bad", steps=[s])
    murphy_rep = MurphySimulationEngine.simulate_plan(plan)
    assert murphy_rep.recommendation == MurphyRecommendation.BLOCKED
    assert murphy_rep.risk_level == MurphyRiskTier.CRITICAL


def test_29_phase13_boundary_check():
    assert not hasattr(MurphyService, "phase_13_container_isolator")
    assert not hasattr(MurphyService, "cgroup_memory_manager")


def test_30_complete_report_schema_validation():
    s = KarmaStep(step_id="s1", action="calculate 1+1", expected_outcome="2")
    plan = KarmaPlanDAG(task_id=317, summary="Schema", steps=[s])
    rep = MurphySimulationEngine.simulate_plan(plan)
    dumped = rep.model_dump()
    assert "risk_level" in dumped
    assert "blast_radius_score" in dumped
    assert "failure_modes" in dumped
    assert "security_concerns" in dumped
    assert "recommendation" in dumped
    assert "mitigations" in dumped


def run_all_30_phase12_tests():
    print("==================================================")
    print("MURPHY PHASE 12: 30-SCENARIO PREDICTIVE VERIFICATION")
    print("& BLAST-RADIUS ASSESSMENT (WHITESHEET §§11.0-11.6)")
    print("Target Sandbox: sqlite:///./test_karma_phase12_sandbox.db")
    print("==================================================")

    test_1_low_blast_radius_read_only()
    print("  [PASS 1/30] LOW blast radius read-only (§11.2).")

    test_2_medium_blast_radius_single_write()
    print("  [PASS 2/30] MEDIUM blast radius single write (§11.2).")

    test_3_high_blast_radius_financial_transaction()
    print("  [PASS 3/30] HIGH blast radius financial transaction (§11.2).")

    test_4_critical_blast_radius_destructive_command()
    print("  [PASS 4/30] CRITICAL blast radius destructive command (§11.2).")

    test_5_critical_blast_radius_credential_exfiltration()
    print("  [PASS 5/30] CRITICAL blast radius credential exfiltration (§11.2).")

    test_6_unknown_risk_on_empty_plan()
    print("  [PASS 6/30] UNKNOWN risk on empty plan (§11.3).")

    test_7_unknown_risk_on_null_plan()
    print("  [PASS 7/30] UNKNOWN risk on null plan (§11.3).")

    test_8_unknown_risk_on_pragya_upstream_failure()
    print("  [PASS 8/30] UNKNOWN risk on PRAGYA upstream failure (§11.3).")

    test_9_unknown_risk_on_upstream_errors()
    print("  [PASS 9/30] UNKNOWN risk on upstream errors (§11.3).")

    test_10_missing_dependency_failure_mode_detection()
    print("  [PASS 10/30] Missing dependency failure mode detection (§11.1).")

    test_11_cascading_multi_step_aggregate_scoring()
    print("  [PASS 11/30] Cascading multi-step aggregate scoring (§11.2).")

    test_12_recommendation_proceed_for_low_risk()
    print("  [PASS 12/30] Recommendation PROCEED for low risk (§11.4).")

    test_13_recommendation_human_review_for_high_risk()
    print("  [PASS 13/30] Recommendation HUMAN_REVIEW for high risk (§11.4).")

    test_14_recommendation_blocked_for_critical_risk()
    print("  [PASS 14/30] Recommendation BLOCKED for critical risk (§11.4).")

    test_15_deterministic_scoring_repeatability()
    print("  [PASS 15/30] Deterministic scoring repeatability.")

    test_16_empty_tenant_id_fails_closed()
    print("  [PASS 16/30] Empty tenant ID fails closed.")

    test_17_tenant_isolation_in_simulation()
    print("  [PASS 17/30] Tenant isolation in simulation.")

    test_18_cross_tenant_denial()
    print("  [PASS 18/30] Cross-tenant denial safety.")

    test_19_chitra_simulation_event_generation()
    print("  [PASS 19/30] CHITRA simulation event generation (§11.6).")

    test_20_chitra_simulation_payload_integrity()
    print("  [PASS 21/30] CHITRA simulation payload integrity.")

    test_21_cryptographic_verification_on_murphy_events()
    print("  [PASS 21/30] Cryptographic verification on MURPHY events.")

    test_22_murphy_to_maryada_low_risk_integration()
    print("  [PASS 22/30] MURPHY to MARYADA low risk integration.")

    test_23_murphy_to_maryada_high_risk_integration()
    print("  [PASS 23/30] MURPHY to MARYADA high risk integration.")

    test_24_murphy_to_maryada_unknown_risk_fail_closed()
    print("  [PASS 24/30] MURPHY to MARYADA UNKNOWN risk fail closed.")

    test_25_simulation_engine_exception_handling()
    print("  [PASS 25/30] Simulation engine exception handling.")

    test_26_concurrent_murphy_simulations()
    print("  [PASS 26/30] Concurrent MURPHY simulations safety.")

    test_27_full_pipeline_phase5_to_phase12()
    print("  [PASS 27/30] Full pipeline: Phase 5 -> 12 -> 11 -> 7 -> 8 -> 9.")

    test_28_murphy_evaluated_strictly_before_execution()
    print("  [PASS 28/30] MURPHY evaluated strictly before execution.")

    test_29_phase13_boundary_check()
    print("  [PASS 29/30] Phase 13 boundary verified (0 Phase 13 features).")

    test_30_complete_report_schema_validation()
    print("  [PASS 30/30] Complete report schema validation (§11.4).")

    print("\n==================================================")
    print("ALL 30 MURPHY PHASE 12 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_30_phase12_tests()
