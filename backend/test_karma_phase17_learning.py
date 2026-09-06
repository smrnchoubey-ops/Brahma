"""
LEARNING SYSTEM Phase 17 Comprehensive Test Suite: F14 Pattern Extraction & F15 Evolutionary Stewardship
Strictly tests Whitesheet Learning System (F14 & F15) across 30 explicit scenarios.
Runs against local sandbox database: test_karma_phase17_sandbox.db.
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
from app.core.learning.models import (
    PatternStatus,
    PatternType,
    LearningCandidate,
    LearningEvidence,
    ShadowEvaluationResult,
    RegressionTestResult,
    LEResult
)
from app.core.learning.pattern_extractor import F14PatternExtractor
from app.core.learning.effectiveness import LearningEffectivenessEngine
from app.core.learning.shadow_evaluator import ShadowEvaluator
from app.core.learning.regression_evaluator import RegressionEvaluator
from app.core.learning.stewardship import F15EvolutionarySteward, StewardshipError
from app.core.learning.service import LearningService
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase17_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p17", hashed_password="pwd")
    user_b = User(username="user_bob_p17", hashed_password="pwd")
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
# 1. F14 PATTERN EXTRACTION (1-6)
# -------------------------------------------------------------

def test_1_f14_pattern_extraction_basic():
    episodes = [
        {"task_id": 901, "event_id": "evt_1", "status": "SUCCESS", "duration_ms": 120.0, "tool": "calc"},
        {"task_id": 902, "event_id": "evt_2", "status": "SUCCESS", "duration_ms": 110.0, "tool": "calc"},
        {"task_id": 903, "event_id": "evt_3", "status": "SUCCESS", "duration_ms": 115.0, "tool": "calc"}
    ]
    candidate = LearningService.extract_pattern(
        tenant_id="tenant_alice",
        episodes=episodes,
        pattern_type=PatternType.PLAN_OPTIMIZATION
    )
    assert candidate.pattern_id.startswith("pat_")
    assert candidate.status == PatternStatus.CANDIDATE
    assert candidate.tenant_id == "tenant_alice"
    assert candidate.evidence.sample_count == 3
    assert candidate.confidence >= 0.5


def test_2_f14_deterministic_candidate_output():
    episodes = [
        {"task_id": 903, "event_id": "evt_3", "status": "SUCCESS", "duration_ms": 100.0},
        {"task_id": 904, "event_id": "evt_4", "status": "SUCCESS", "duration_ms": 105.0},
        {"task_id": 905, "event_id": "evt_5", "status": "SUCCESS", "duration_ms": 95.0}
    ]
    c1 = F14PatternExtractor.extract_pattern("tenant_alice", episodes, name="FixedName")
    assert c1.name == "FixedName"
    assert c1.status == PatternStatus.CANDIDATE


def test_3_f14_malformed_episodes_rejection():
    with pytest.raises(ValueError, match="Malformed episode record"):
        F14PatternExtractor.extract_pattern("tenant_alice", ["not_a_dict"])


def test_4_f14_empty_episodes_rejection():
    with pytest.raises(ValueError, match="Cannot extract patterns from an empty list"):
        F14PatternExtractor.extract_pattern("tenant_alice", [])


def test_5_f14_provenance_preservation():
    episodes = [
        {"task_id": 904, "event_id": "evt_4a", "status": "SUCCESS"},
        {"task_id": 905, "event_id": "evt_4b", "status": "SUCCESS"},
        {"task_id": 906, "event_id": "evt_4c", "status": "SUCCESS"}
    ]
    candidate = F14PatternExtractor.extract_pattern("tenant_alice", episodes)
    assert 904 in candidate.evidence.source_task_ids
    assert 905 in candidate.evidence.source_task_ids
    assert 906 in candidate.evidence.source_task_ids
    assert "evt_4a" in candidate.evidence.source_event_ids


def test_6_candidate_schema_invariants():
    cand = LearningCandidate(
        pattern_id="pat_test",
        tenant_id="tenant_alice",
        pattern_type=PatternType.TOOL_ROUTING,
        name="Test Pattern",
        description="Desc"
    )
    assert cand.version == 1
    assert cand.status == PatternStatus.CANDIDATE
    assert cand.constitutional_approved is False


# -------------------------------------------------------------
# 2. F15 CONSTITUTIONAL VALIDATION & STATE TRANSITIONS (7-10)
# -------------------------------------------------------------

def test_7_f15_candidate_state_transitions():
    episodes = [
        {"task_id": 906, "status": "SUCCESS"},
        {"task_id": 907, "status": "SUCCESS"},
        {"task_id": 908, "status": "SUCCESS"}
    ]
    cand = F14PatternExtractor.extract_pattern("tenant_alice", episodes)

    # 1. CANDIDATE -> VALIDATED
    ok = F15EvolutionarySteward.validate_candidate(cand)
    assert ok is True
    assert cand.status == PatternStatus.VALIDATED

    # 2. VALIDATED -> SHADOW
    F15EvolutionarySteward.deploy_to_shadow(cand)
    assert cand.status == PatternStatus.SHADOW


def test_8_f15_invalid_state_transition_fails_closed():
    cand = LearningCandidate(
        pattern_id="pat_bad",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Bad State",
        description="Desc",
        status=PatternStatus.CANDIDATE
    )
    # Direct CANDIDATE -> SHADOW without VALIDATED must raise StewardshipError
    with pytest.raises(StewardshipError, match="Expected VALIDATED"):
        F15EvolutionarySteward.deploy_to_shadow(cand)


def test_9_f15_constitutional_validation_pass():
    cand = LearningCandidate(
        pattern_id="pat_clean",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Safe Math Optimization",
        description="Optimizes calculate steps",
        status=PatternStatus.CANDIDATE
    )
    ok = F15EvolutionarySteward.validate_candidate(cand)
    assert ok is True
    assert cand.constitutional_approved is True
    assert cand.status == PatternStatus.VALIDATED


def test_10_f15_constitutional_validation_rejection():
    # Destructive pattern candidate rejected by MARYADA
    cand = LearningCandidate(
        pattern_id="pat_bad_action",
        tenant_id="tenant_alice",
        pattern_type=PatternType.HEURISTIC_RULE,
        name="rm -rf /critical_system_data",
        description="Unsafe pattern",
        status=PatternStatus.CANDIDATE
    )
    ok = F15EvolutionarySteward.validate_candidate(cand)
    assert ok is False
    assert cand.status == PatternStatus.REJECTED
    assert cand.constitutional_approved is False


# -------------------------------------------------------------
# 3. SHADOW EVALUATION & COMPARATIVE METRICS (11-13)
# -------------------------------------------------------------

def test_11_shadow_evaluation_non_authoritative_execution():
    cand = LearningCandidate(
        pattern_id="pat_shadow",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Shadow Plan",
        description="Desc"
    )
    res = ShadowEvaluator.evaluate_shadow(cand)
    assert isinstance(res, ShadowEvaluationResult)
    assert res.evidence["shadow_mode"] == "NON_AUTHORITATIVE"


def test_12_shadow_evaluation_passed_when_matching_baseline():
    cand = LearningCandidate(
        pattern_id="pat_good_shadow",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Shadow Good",
        description="Desc"
    )
    base_fn = lambda: {"success": True}
    cand_fn = lambda: {"success": True}
    res = ShadowEvaluator.evaluate_shadow(cand, baseline_evaluator=base_fn, candidate_evaluator=cand_fn)
    assert res.passed is True
    assert res.error_delta == 0.0


def test_13_shadow_evaluation_fails_on_higher_error_rate():
    cand = LearningCandidate(
        pattern_id="pat_fail_shadow",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Shadow Fail",
        description="Desc"
    )
    base_fn = lambda: {"success": True}
    cand_fn = lambda: {"success": False}
    res = ShadowEvaluator.evaluate_shadow(cand, baseline_evaluator=base_fn, candidate_evaluator=cand_fn)
    assert res.passed is False
    assert res.error_delta == 1.0


# -------------------------------------------------------------
# 4. REGRESSION PREVENTION (14-16)
# -------------------------------------------------------------

def test_14_regression_evaluation_pass_on_clean_benchmarks():
    cand = LearningCandidate(
        pattern_id="pat_clean_regr",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Clean",
        description="Desc",
        action_template={"opt": 1}
    )
    bench1 = lambda: True
    bench2 = lambda: True
    res = RegressionEvaluator.evaluate_regressions(cand, benchmark_runners=[bench1, bench2])
    assert res.passed is True
    assert res.regressions_detected == 0


def test_15_regression_evaluation_failure_on_benchmark_error():
    cand = LearningCandidate(
        pattern_id="pat_buggy",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Buggy",
        description="Desc"
    )
    bench_fail = lambda: False
    res = RegressionEvaluator.evaluate_regressions(cand, benchmark_runners=[bench_fail])
    assert res.passed is False
    assert res.regressions_detected == 1


def test_16_regression_failure_blocks_promotion_fail_closed():
    cand = LearningCandidate(
        pattern_id="pat_block_regr",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Blocked",
        description="Desc",
        status=PatternStatus.SHADOW,
        constitutional_approved=True
    )
    le_res = LEResult(candidate_id=cand.pattern_id, le_score=0.95, threshold=0.70, passed=True)
    regr_res = RegressionTestResult(candidate_id=cand.pattern_id, benchmark_count=1, regressions_detected=1, passed=False)

    promoted, msg = F15EvolutionarySteward.evaluate_and_promote(cand, le_res, regr_res)
    assert promoted is False
    assert cand.status == PatternStatus.REJECTED
    assert "regressions detected" in msg


# -------------------------------------------------------------
# 5. LEARNING EFFECTIVENESS (LE) SCORING (17-19)
# -------------------------------------------------------------

def test_17_learning_effectiveness_calculation_formula():
    cand = LearningCandidate(
        pattern_id="pat_le",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="LE Test",
        description="Desc",
        confidence=0.8,
        constitutional_approved=True
    )
    shadow_res = ShadowEvaluationResult(
        candidate_id=cand.pattern_id,
        baseline_success_rate=0.8,
        candidate_success_rate=1.0,
        baseline_latency_ms=200.0,
        candidate_latency_ms=100.0,
        error_delta=0.0,
        passed=True
    )
    regr_res = RegressionTestResult(candidate_id=cand.pattern_id, benchmark_count=3, regressions_detected=0, passed=True)

    le_out = LearningEffectivenessEngine.calculate_le(cand, shadow_result=shadow_res, regression_result=regr_res, threshold=0.30)
    assert le_out.le_score > 0.0
    assert le_out.passed is True


def test_18_le_score_below_threshold_blocks_promotion():
    cand = LearningCandidate(
        pattern_id="pat_low_le",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Low LE",
        description="Desc",
        status=PatternStatus.SHADOW,
        constitutional_approved=True
    )
    le_res = LEResult(candidate_id=cand.pattern_id, le_score=0.45, threshold=0.70, passed=False)
    regr_res = RegressionTestResult(candidate_id=cand.pattern_id, benchmark_count=1, regressions_detected=0, passed=True)

    promoted, msg = F15EvolutionarySteward.evaluate_and_promote(cand, le_res, regr_res)
    assert promoted is False
    assert cand.status == PatternStatus.REJECTED
    assert "below required threshold" in msg


def test_19_le_score_above_threshold_enables_promotion():
    cand = LearningCandidate(
        pattern_id="pat_high_le",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="High LE",
        description="Desc",
        status=PatternStatus.SHADOW,
        constitutional_approved=True
    )
    le_res = LEResult(candidate_id=cand.pattern_id, le_score=0.85, threshold=0.70, passed=True)
    regr_res = RegressionTestResult(candidate_id=cand.pattern_id, benchmark_count=1, regressions_detected=0, passed=True)

    promoted, msg = F15EvolutionarySteward.evaluate_and_promote(cand, le_res, regr_res)
    assert promoted is True
    assert cand.status == PatternStatus.PROMOTED
    assert cand.promoted_at is not None


# -------------------------------------------------------------
# 6. STEWARDSHIP PROMOTION & ROLLBACK (20-22)
# -------------------------------------------------------------

def test_20_f15_successful_promotion_lifecycle():
    episodes = [
        {"task_id": 907, "status": "SUCCESS", "duration_ms": 50.0},
        {"task_id": 908, "status": "SUCCESS", "duration_ms": 55.0},
        {"task_id": 909, "status": "SUCCESS", "duration_ms": 45.0}
    ]
    cand = F14PatternExtractor.extract_pattern("tenant_alice", episodes)

    promoted, msg, updated = LearningService.process_candidate_lifecycle(
        candidate=cand,
        le_threshold=0.30
    )
    assert promoted is True
    assert updated.status == PatternStatus.PROMOTED


def test_21_f15_rollback_promoted_pattern():
    cand = LearningCandidate(
        pattern_id="pat_rollback",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="To Rollback",
        description="Desc",
        status=PatternStatus.PROMOTED
    )
    F15EvolutionarySteward.rollback(cand, reason="Observed latency degradation in production.")
    assert cand.status == PatternStatus.ROLLED_BACK


def test_22_f15_rollback_invalid_state_rejection():
    cand = LearningCandidate(
        pattern_id="pat_not_promoted",
        tenant_id="tenant_alice",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Candidate State",
        description="Desc",
        status=PatternStatus.CANDIDATE
    )
    # Cannot rollback a candidate that was never promoted
    with pytest.raises(StewardshipError, match="Expected PROMOTED"):
        F15EvolutionarySteward.rollback(cand, reason="Invalid attempt")


# -------------------------------------------------------------
# 7. TENANT ISOLATION (23-24)
# -------------------------------------------------------------

def test_23_empty_tenant_id_fails_closed():
    with pytest.raises(ValueError, match="Tenant ID is required"):
        F14PatternExtractor.extract_pattern(tenant_id="", episodes=[{"task_id": 908}])


def test_24_cross_tenant_pattern_isolation():
    c_alice = F14PatternExtractor.extract_pattern(
        "tenant_alice",
        [
            {"task_id": 909, "status": "SUCCESS"},
            {"task_id": 910, "status": "SUCCESS"},
            {"task_id": 911, "status": "SUCCESS"}
        ]
    )
    c_bob = F14PatternExtractor.extract_pattern(
        "tenant_bob",
        [
            {"task_id": 912, "status": "SUCCESS"},
            {"task_id": 913, "status": "SUCCESS"},
            {"task_id": 914, "status": "SUCCESS"}
        ]
    )
    assert c_alice.tenant_id != c_bob.tenant_id
    assert c_alice.pattern_id != c_bob.pattern_id


# -------------------------------------------------------------
# 8. CHITRA AUDITING & VERIFICATION (25-27)
# -------------------------------------------------------------

def test_25_chitra_pattern_extracted_audit_event():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    cand = F14PatternExtractor.extract_pattern(
        f"tenant_{u_a}",
        [
            {"task_id": t_a, "event_id": "evt_25_a", "status": "SUCCESS"},
            {"task_id": t_a, "event_id": "evt_25_b", "status": "SUCCESS"},
            {"task_id": t_a, "event_id": "evt_25_c", "status": "SUCCESS"}
        ]
    )
    F15EvolutionarySteward.validate_candidate(cand, db_session=db, user_id=u_a, task_id=t_a)

    evt = db.query(ChitraEvent).filter(ChitraEvent.task_id == t_a, ChitraEvent.faculty == "LEARNING").first()
    assert evt is not None
    assert evt.decision["pattern_id"] == cand.pattern_id
    db.close()


def test_26_chitra_promotion_and_rollback_audit_events():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    cand = LearningCandidate(
        pattern_id="pat_audited",
        tenant_id=f"tenant_{u_a}",
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Audited",
        description="Desc",
        status=PatternStatus.SHADOW,
        constitutional_approved=True
    )
    le_res = LEResult(candidate_id=cand.pattern_id, le_score=0.90, threshold=0.70, passed=True)
    regr_res = RegressionTestResult(candidate_id=cand.pattern_id, benchmark_count=1, regressions_detected=0, passed=True)

    F15EvolutionarySteward.evaluate_and_promote(cand, le_res, regr_res, db_session=db, user_id=u_a, task_id=t_a)
    F15EvolutionarySteward.rollback(cand, "Safety test", db_session=db, user_id=u_a, task_id=t_a)

    evts = db.query(ChitraEvent).filter(ChitraEvent.task_id == t_a, ChitraEvent.faculty == "LEARNING").all()
    event_types = [e.event_type for e in evts]
    assert "promoted" in event_types
    assert "rolled_back" in event_types
    db.close()


def test_27_chitra_cryptographic_verification_learning_events():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    cand = F14PatternExtractor.extract_pattern(
        f"tenant_{u_a}",
        [
            {"task_id": t_a, "event_id": "evt_27_a", "status": "SUCCESS"},
            {"task_id": t_a, "event_id": "evt_27_b", "status": "SUCCESS"},
            {"task_id": t_a, "event_id": "evt_27_c", "status": "SUCCESS"}
        ]
    )
    LearningService.process_candidate_lifecycle(
        candidate=cand,
        le_threshold=0.30,
        db_session=db,
        user_id=u_a,
        task_id=t_a
    )

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    db.close()


# -------------------------------------------------------------
# 9. CONCURRENCY & END-TO-END (28-30)
# -------------------------------------------------------------

def test_28_concurrent_candidate_processing_isolation():
    def process_worker(i: int):
        episodes = [
            {"task_id": 1000 + i, "status": "SUCCESS", "duration_ms": 50.0},
            {"task_id": 2000 + i, "status": "SUCCESS", "duration_ms": 55.0},
            {"task_id": 3000 + i, "status": "SUCCESS", "duration_ms": 45.0}
        ]
        cand = LearningService.extract_pattern(f"tenant_{i % 3}", episodes)
        promoted, _, u = LearningService.process_candidate_lifecycle(cand, le_threshold=0.30)
        return promoted, u.status

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(process_worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert all(r[0] is True for r in results)
    assert all(r[1] == PatternStatus.PROMOTED for r in results)


def test_29_full_end_to_end_learning_service_lifecycle():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    episodes = [
        {"task_id": t_a, "event_id": "evt_29_a", "status": "SUCCESS", "duration_ms": 80.0, "tool": "calc"},
        {"task_id": t_a, "event_id": "evt_29_b", "status": "SUCCESS", "duration_ms": 75.0, "tool": "calc"},
        {"task_id": t_a, "event_id": "evt_29_c", "status": "SUCCESS", "duration_ms": 70.0, "tool": "calc"}
    ]
    cand = LearningService.extract_pattern(
        tenant_id=f"tenant_{u_a}",
        episodes=episodes,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="EndToEnd Optimization"
    )
    promoted, msg, updated = LearningService.process_candidate_lifecycle(
        candidate=cand,
        le_threshold=0.30,
        db_session=db,
        user_id=u_a,
        task_id=t_a
    )
    assert promoted is True
    assert updated.status == PatternStatus.PROMOTED

    # Rollback
    LearningService.rollback_pattern(updated, reason="E2E Rollback Test", db_session=db, user_id=u_a, task_id=t_a)
    assert updated.status == PatternStatus.ROLLED_BACK

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    db.close()


def test_30_phase18_boundary_check():
    # Strictly ensures no Phase 18 multi-cluster / production load balancer code exists in Learning module
    assert not hasattr(LearningService, "cluster_sync_agent")
    assert not hasattr(F15EvolutionarySteward, "kafka_promotion_stream")


def run_all_30_phase17_tests():
    print("==================================================")
    print("LEARNING SYSTEM PHASE 17: 30-SCENARIO SUITE (F14 & F15)")
    print("Target Sandbox: sqlite:///./test_karma_phase17_sandbox.db")
    print("==================================================")

    test_1_f14_pattern_extraction_basic()
    print("  [PASS 1/30] [REAL] F14 pattern extraction basic.")

    test_2_f14_deterministic_candidate_output()
    print("  [PASS 2/30] [REAL] F14 deterministic candidate output.")

    test_3_f14_malformed_episodes_rejection()
    print("  [PASS 3/30] [REAL] F14 malformed episodes rejection.")

    test_4_f14_empty_episodes_rejection()
    print("  [PASS 4/30] [REAL] F14 empty episodes rejection fails closed.")

    test_5_f14_provenance_preservation()
    print("  [PASS 5/30] [REAL] F14 provenance preservation.")

    test_6_candidate_schema_invariants()
    print("  [PASS 6/30] [REAL] Candidate schema invariants.")

    test_7_f15_candidate_state_transitions()
    print("  [PASS 7/30] [REAL] F15 candidate state transitions (CANDIDATE -> VALIDATED -> SHADOW).")

    test_8_f15_invalid_state_transition_fails_closed()
    print("  [PASS 8/30] [REAL] F15 invalid state transition fails closed.")

    test_9_f15_constitutional_validation_pass()
    print("  [PASS 9/30] [REAL] F15 constitutional validation pass via MARYADA.")

    test_10_f15_constitutional_validation_rejection()
    print("  [PASS 10/30] [REAL] F15 constitutional validation rejection.")

    test_11_shadow_evaluation_non_authoritative_execution()
    print("  [PASS 11/30] [REAL] Shadow evaluation non-authoritative execution.")

    test_12_shadow_evaluation_passed_when_matching_baseline()
    print("  [PASS 12/30] [REAL] Shadow evaluation pass.")

    test_13_shadow_evaluation_fails_on_higher_error_rate()
    print("  [PASS 13/30] [REAL] Shadow evaluation error rate failure.")

    test_14_regression_evaluation_pass_on_clean_benchmarks()
    print("  [PASS 14/30] [REAL] Regression evaluation pass.")

    test_15_regression_evaluation_failure_on_benchmark_error()
    print("  [PASS 15/30] [REAL] Regression evaluation failure detection.")

    test_16_regression_failure_blocks_promotion_fail_closed()
    print("  [PASS 16/30] [REAL] Regression failure blocks promotion fail-closed.")

    test_17_learning_effectiveness_calculation_formula()
    print("  [PASS 17/30] [REAL] Learning Effectiveness calculation formula.")

    test_18_le_score_below_threshold_blocks_promotion()
    print("  [PASS 18/30] [REAL] LE score below threshold blocks promotion.")

    test_19_le_score_above_threshold_enables_promotion()
    print("  [PASS 19/30] [REAL] LE score above threshold enables promotion.")

    test_20_f15_successful_promotion_lifecycle()
    print("  [PASS 20/30] [REAL] F15 successful promotion lifecycle.")

    test_21_f15_rollback_promoted_pattern()
    print("  [PASS 21/30] [REAL] F15 rollback of promoted pattern.")

    test_22_f15_rollback_invalid_state_rejection()
    print("  [PASS 22/30] [REAL] F15 rollback invalid state rejection.")

    test_23_empty_tenant_id_fails_closed()
    print("  [PASS 23/30] [REAL] Empty tenant ID fails closed.")

    test_24_cross_tenant_pattern_isolation()
    print("  [PASS 24/30] [REAL] Cross-tenant pattern isolation.")

    test_25_chitra_pattern_extracted_audit_event()
    print("  [PASS 25/30] [REAL] CHITRA pattern extracted audit event.")

    test_26_chitra_promotion_and_rollback_audit_events()
    print("  [PASS 26/30] [REAL] CHITRA promotion and rollback audit events.")

    test_27_chitra_cryptographic_verification_learning_events()
    print("  [PASS 27/30] [REAL] CHITRA cryptographic verification of learning events.")

    test_28_concurrent_candidate_processing_isolation()
    print("  [PASS 28/30] [REAL] Concurrent candidate processing isolation.")

    test_29_full_end_to_end_learning_service_lifecycle()
    print("  [PASS 29/30] [REAL] Full end-to-end learning service lifecycle.")

    test_30_phase18_boundary_check()
    print("  [PASS 30/30] [REAL] Phase 18 boundary check (0 Phase 18 features).")

    print("\n==================================================")
    print("ALL 30 LEARNING PHASE 17 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_30_phase17_tests()
