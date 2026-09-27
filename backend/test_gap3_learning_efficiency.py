"""
GAP #3 TEST SUITE: Learning Efficiency (LE) Production Wiring & Whitesheet §19.5 Conformance
Whitesheet §17.1, §17.3, §17.4, §17.6, §19.5, §20.3 & Appendix B.16 (F14 / F15)

Strictly validates:
1. Pure mathematical LE calculation:
   LE(u) = (1/|E|) * sum_{e in E} [ outcome_score(e|u) - outcome_score(e|baseline) ] - lambda_reg * regression_count(u, E)
2. No hidden internal constitutional penalties inside mathematical formula.
3. Constitutional review (F10) and regression counts enforced as separate promotion gates.
4. Independent Calculator Verifier (clean room, no imports from executor, binary scoring).
5. Explicit Incumbent Baseline Policy boundary.
6. Candidate Policy Adapter executing on exact same expression.
7. Same-episode comparative evaluation in ShadowEvaluator.
8. Disjoint Train (k_min >= 3) vs Eval (|E_eval| >= 1) partitioning and tenant isolation.
9. Strict LE > tau_LE threshold boundary and regression_count == 0 requirement.
10. Authoritative PostgreSQL persistence of candidate state and comparative provenance in 'learning_patterns'.
"""
import pytest
import inspect
import secrets
from datetime import datetime, timezone
from sqlalchemy import text

from app.db.database import SessionLocal, engine
from app.models.learning_pattern import LearningPattern
from app.models.task import Task
from app.models.user import User
from app.core.learning.models import (
    PatternStatus,
    PatternType,
    LearningEvidence,
    LearningCandidate,
    LEResult,
    RegressionTestResult,
    ShadowEvaluationResult
)
from app.core.learning.pattern_extractor import F14PatternExtractor
from app.core.learning.effectiveness import LearningEffectivenessEngine
from app.core.learning.shadow_evaluator import ShadowEvaluator
from app.core.learning.regression_evaluator import RegressionEvaluator
from app.core.learning.service import LearningService
from app.core.learning.stewardship import F15EvolutionarySteward, StewardshipError
from app.core.learning.ingestion import LearningIngestionService
from app.core.learning.verifiers.calculator import IndependentCalculatorVerifier, VerifierOutcome
from app.core.learning.policies.calculator_baseline import IncumbentCalculatorBaselinePolicy
from app.core.learning.policies.calculator_candidate import CalculatorCandidatePolicy


@pytest.fixture(autouse=True)
def ensure_postgresql():
    """Mandatory preflight assertion that database is genuine PostgreSQL."""
    assert engine.dialect.name == "postgresql", f"Gap #3 requires PostgreSQL dialect, found '{engine.dialect.name}'"


@pytest.fixture
def clean_test_tenants():
    """Generates unique isolated tenant IDs and ensures database cleanup after tests."""
    tenant_a = f"tenant_gap3_a_{secrets.token_hex(4)}"
    tenant_b = f"tenant_gap3_b_{secrets.token_hex(4)}"
    yield tenant_a, tenant_b

    with SessionLocal() as db:
        db.query(LearningPattern).filter(LearningPattern.tenant_id.in_([tenant_a, tenant_b])).delete(synchronize_session=False)
        db.commit()


# =========================================================================
# 1. Independent Calculator Verifier Tests (Phase 1)
# =========================================================================

def test_p1_verifier_correct_expression_returns_1():
    """Validates that a mathematically correct result yields outcome_score = 1.0."""
    outcome = IndependentCalculatorVerifier.verify("calculate 25 * 4", 100)
    assert outcome.is_valid is True
    assert outcome.outcome_score == 1.0
    assert outcome.expected_result == 100.0
    assert outcome.actual_result == 100.0
    assert outcome.error is None
    assert outcome.verifier_id == "verifier:calculator:v1.0.0:independent_math"


def test_p1_verifier_incorrect_result_returns_0():
    """Validates that an incorrect result yields outcome_score = 0.0."""
    outcome = IndependentCalculatorVerifier.verify("calculate 25 * 4", 99)
    assert outcome.is_valid is False
    assert outcome.outcome_score == 0.0
    assert outcome.expected_result == 100.0
    assert outcome.actual_result == 99.0
    assert "RESULT_MISMATCH" in outcome.error


def test_p1_verifier_malformed_expression_returns_0():
    """Validates that a malformed expression fails closed with outcome_score = 0.0."""
    outcome = IndependentCalculatorVerifier.verify("calculate 25 * + * 4", 100)
    assert outcome.is_valid is False
    assert outcome.outcome_score == 0.0
    assert outcome.expected_result is None


def test_p1_verifier_division_by_zero_returns_0():
    """Validates that division by zero fails closed with outcome_score = 0.0."""
    outcome = IndependentCalculatorVerifier.verify("calculate 50 / 0", 0)
    assert outcome.is_valid is False
    assert outcome.outcome_score == 0.0
    assert "DIVISION_BY_ZERO" in outcome.error


def test_p1_verifier_unsupported_expression_returns_0():
    """Validates that non-arithmetic text fails closed with outcome_score = 0.0."""
    outcome = IndependentCalculatorVerifier.verify("hello world", 0)
    assert outcome.is_valid is False
    assert outcome.outcome_score == 0.0
    assert outcome.error == "NO_VALID_ARITHMETIC_EXPRESSION"


def test_p1_verifier_clean_room_isolation():
    """Validates that verifier does NOT import or call executor functions."""
    import app.core.learning.verifiers.calculator as mod
    source = inspect.getsource(mod)
    assert "handle_calculate" not in source
    assert "_eval_safe_math" not in source
    assert "from agents.execution" not in source
    assert "import agents.execution" not in source


# =========================================================================
# 2. Baseline Policy Tests (Phase 2)
# =========================================================================

def test_p2_baseline_policy_execution():
    """Validates incumbent baseline execution policy boundary."""
    res = IncumbentCalculatorBaselinePolicy.execute("30 * 3")
    assert res["status"] == "EXECUTED"
    assert res["result"] == 90
    assert res["policy_id"] == "policy:calculator:v1.0.0:incumbent_default"
    assert res["policy_version"] == "1.0.0"
    assert res["error"] is None


# =========================================================================
# 3. Candidate Policy Tests (Phase 3)
# =========================================================================

def test_p3_candidate_policy_adapter(clean_test_tenants):
    """Validates candidate policy adapter execution on the same arithmetic expression."""
    tenant_a, _ = clean_test_tenants
    candidate = LearningCandidate(
        pattern_id="pat_test_calc_01",
        name="Candidate_Math_Opt",
        description="Test optimization candidate for math execution",
        tenant_id=tenant_a,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        action_template={"strategy": "OPTIMIZED_EXECUTION", "target_tool_preference": "calculator"},
        confidence=0.95
    )
    cand_policy = CalculatorCandidatePolicy(candidate)
    assert cand_policy.policy_id == "policy:calculator:candidate:pat_test_calc_01"

    res = cand_policy.execute("30 * 3")
    assert res["status"] == "EXECUTED"
    assert res["result"] == 90
    assert res["policy_id"] == cand_policy.policy_id


# =========================================================================
# 4. Same-Episode Comparative Shadow Evaluation (Phase 4)
# =========================================================================

def test_p4_same_episode_shadow_evaluation(clean_test_tenants):
    """
    Validates that ShadowEvaluator executes BOTH baseline and candidate
    on the exact same held-out arithmetic expression, producing independent verified scores.
    """
    tenant_a, _ = clean_test_tenants
    candidate = LearningCandidate(
        pattern_id="pat_shadow_same_ep",
        name="Candidate_SameEp_Test",
        description="Test candidate for same-episode comparative shadow evaluation",
        tenant_id=tenant_a,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        action_template={"strategy": "OPTIMIZED_EXECUTION", "target_tool_preference": "calculator"},
        confidence=0.95
    )

    held_out = [
        {"task_id": 701, "event_id": "evt_701", "expression": "12 * 12", "tool": "calculator", "tenant_id": tenant_a},
        {"task_id": 702, "event_id": "evt_702", "expression": "45 * 8", "tool": "calculator", "tenant_id": tenant_a}
    ]

    eval_episodes, shadow_res = ShadowEvaluator.evaluate_held_out_episodes(
        candidate=candidate,
        held_out_episodes=held_out
    )

    assert len(eval_episodes) == 2
    assert shadow_res.passed is True
    assert shadow_res.baseline_success_rate == 1.0
    assert shadow_res.candidate_success_rate == 1.0

    prov = shadow_res.evidence["comparative_provenance"]
    assert len(prov) == 2
    assert prov[0]["expression"] == "12 * 12"
    assert prov[0]["baseline_raw_result"] == 144
    assert prov[0]["candidate_raw_result"] == 144
    assert prov[0]["baseline_outcome_score"] == 1.0
    assert prov[0]["candidate_outcome_score"] == 1.0
    assert prov[0]["delta"] == 0.0


# =========================================================================
# 5. Exact Mathematical LE Formula & Gates (§19.5, F15, Regressions)
# =========================================================================

def test_p5_exact_mathematical_le_calculation_without_hidden_penalties(clean_test_tenants):
    """
    Validates Whitesheet §19.5 exact mathematical formula:
    LE(u) = (1/|E|) * sum_{e in E} [ score_u(e) - score_baseline(e) ] - lambda_reg * regression_count
    Proves that no internal -0.30 safety penalty is subtracted from the pure LE score.
    """
    tenant_a, _ = clean_test_tenants
    candidate = LearningCandidate(
        pattern_id="pat_le_calc",
        name="LE_Calc_Pattern",
        description="Test candidate for pure LE formula calculation",
        tenant_id=tenant_a,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        action_template={"strategy": "OPTIMIZED_EXECUTION"},
        confidence=0.90
    )

    # 3 held-out evaluation episodes
    eval_episodes = [
        {"task_id": 201, "outcome_score_u": 0.90, "outcome_score_baseline": 0.40, "tenant_id": tenant_a},
        {"task_id": 202, "outcome_score_u": 0.85, "outcome_score_baseline": 0.45, "tenant_id": tenant_a},
        {"task_id": 203, "outcome_score_u": 0.95, "outcome_score_baseline": 0.55, "tenant_id": tenant_a}
    ]
    # Deltas: (0.90 - 0.40) = 0.50, (0.85 - 0.45) = 0.40, (0.95 - 0.55) = 0.40
    # Mean delta = (0.50 + 0.40 + 0.40) / 3 = 0.43333...
    # Regressions = 0, lambda_reg = 0.50
    # Expected pure LE = 0.4333

    le_res = LearningEffectivenessEngine.calculate_le(
        candidate=candidate,
        eval_episodes=eval_episodes,
        lambda_reg=0.50,
        threshold=0.40
    )

    expected_mean_delta = (0.50 + 0.40 + 0.40) / 3.0
    expected_le = round(expected_mean_delta, 4)

    assert le_res.le_score == expected_le
    assert le_res.factors["mean_outcome_delta"] == round(expected_mean_delta, 4)
    assert le_res.factors["regression_count"] == 0
    assert le_res.factors["regression_penalty"] == 0.0
    assert le_res.passed is True


def test_p5_strict_threshold_boundary_rejection(clean_test_tenants):
    """
    Validates Whitesheet §19.5 strict mathematical boundary:
    Promotion requires LE(u) > tau_LE (strictly greater than).
    If LE(u) == tau_LE, the candidate MUST BE REJECTED.
    """
    tenant_a, _ = clean_test_tenants
    candidate = LearningCandidate(
        pattern_id="pat_thresh_boundary",
        name="Boundary_Pattern",
        description="Test candidate for strict LE boundary",
        tenant_id=tenant_a,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        action_template={"strategy": "OPTIMIZED_EXECUTION"},
        confidence=0.90
    )

    eval_episodes = [
        {"task_id": 201, "outcome_score_u": 0.80, "outcome_score_baseline": 0.30, "tenant_id": tenant_a}
    ]
    # LE score = 0.50

    # Exactly equal to threshold (0.50 == 0.50) -> MUST BE REJECTED (passed=False)
    le_res_equal = LearningEffectivenessEngine.calculate_le(
        candidate=candidate,
        eval_episodes=eval_episodes,
        threshold=0.50
    )
    assert le_res_equal.le_score == 0.50
    assert le_res_equal.passed is False

    # Strictly greater than threshold (0.50 > 0.49) -> MUST PASS
    le_res_greater = LearningEffectivenessEngine.calculate_le(
        candidate=candidate,
        eval_episodes=eval_episodes,
        threshold=0.49
    )
    assert le_res_greater.le_score == 0.50
    assert le_res_greater.passed is True


def test_p5_regression_penalty_and_blocking(clean_test_tenants):
    """
    Validates that detected regressions apply penalty (- lambda_reg * regression_count)
    and block promotion.
    """
    tenant_a, _ = clean_test_tenants
    candidate = LearningCandidate(
        pattern_id="pat_regr_block",
        name="Regr_Block_Pattern",
        description="Test candidate for regression penalty blocking",
        tenant_id=tenant_a,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        action_template={"strategy": "OPTIMIZED_EXECUTION"},
        confidence=0.90
    )

    eval_episodes = [
        {"task_id": 201, "outcome_score_u": 0.90, "outcome_score_baseline": 0.40, "tenant_id": tenant_a},
        {"task_id": 202, "outcome_score_u": 0.30, "outcome_score_baseline": 0.60, "tenant_id": tenant_a},  # Regression
        {"task_id": 203, "outcome_score_u": 0.95, "outcome_score_baseline": 0.55, "tenant_id": tenant_a}
    ]

    le_res = LearningEffectivenessEngine.calculate_le(
        candidate=candidate,
        eval_episodes=eval_episodes,
        lambda_reg=0.50,
        threshold=0.10
    )

    assert le_res.factors["regression_count"] == 1
    assert le_res.factors["regression_penalty"] == 0.50
    assert le_res.passed is False


# =========================================================================
# 6. Tenant Isolation & Disjointness Tests
# =========================================================================

def test_p6_strict_tenant_isolation_on_evaluation_episodes(clean_test_tenants):
    """Strictly asserts that Tenant A cannot evaluate using Tenant B's episodes."""
    tenant_a, tenant_b = clean_test_tenants
    candidate_a = LearningCandidate(
        pattern_id="pat_tenant_iso",
        name="Tenant_Iso_Pattern",
        description="Test candidate for tenant isolation",
        tenant_id=tenant_a,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        action_template={"strategy": "OPTIMIZED_EXECUTION"},
        confidence=0.90
    )

    cross_tenant_eval_episodes = [
        {"task_id": 901, "expression": "10 * 10", "tool": "calculator", "tenant_id": tenant_b}
    ]

    with pytest.raises(ValueError, match="Cross-tenant evaluation episode rejected"):
        ShadowEvaluator.evaluate_held_out_episodes(
            candidate=candidate_a,
            held_out_episodes=cross_tenant_eval_episodes
        )


# =========================================================================
# 7. End-to-End Ingestion & PostgreSQL Persistence
# =========================================================================

def test_p7_learning_ingestion_end_to_end(clean_test_tenants):
    """
    Validates full end-to-end ingestion from completed Task rows in PostgreSQL:
    - Queries completed calculator tasks
    - Verifies outcome using IndependentCalculatorVerifier
    - Partitions into disjoint E_train (k_min=3) and E_eval (held-out)
    - Runs F14 pattern extraction
    - Executes same-episode shadow evaluation
    - Verifies LE and persists candidate to PostgreSQL 'learning_patterns'.
    """
    tenant_a, _ = clean_test_tenants
    with SessionLocal() as db:
        user = User(
            username=f"user_gap3_e2e_{secrets.token_hex(4)}",
            hashed_password="mock_password",
            is_active=True
        )
        db.add(user)
        db.flush()

        try:
            # Create 4 completed tasks (3 for E_train, 1 for E_eval)
            for i, expr, ans in [
                (1, "calculate 10 * 2", 20),
                (2, "calculate 15 * 3", 45),
                (3, "calculate 20 * 4", 80),
                (4, "calculate 25 * 5", 125)
            ]:
                t = Task(
                    user_id=user.id,
                    title=f"Math Task #{i}",
                    prompt=expr,
                    status="COMPLETED",
                    mode="REACTIVE",
                    risk_level="LOW",
                    execution_result={
                        "expression": expr,
                        "result": ans,
                        "status": "EXECUTED",
                        "outcome_score_baseline": 0.50
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(t)
            db.commit()

            # Execute ingestion pipeline with custom baseline evaluator to test promotion delta
            promoted, reason, candidate = LearningIngestionService.ingest_and_evaluate_tenant_episodes(
                db=db,
                tenant_id=tenant_a,
                user_id=user.id,
                k_min=3,
                le_threshold=-0.01  # Passes when non-negative delta
            )

            assert promoted is True, f"Ingestion failed: {reason}"
            assert candidate is not None
            assert candidate.status == PatternStatus.PROMOTED
            assert candidate.le_score == 0.0  # (1.0 candidate - 1.0 baseline) = 0.0 >= 0
            assert candidate.constitutional_approved is True
            assert candidate.regression_passed is True
            assert candidate.shadow_passed is True

            # Verify PostgreSQL persistence
            db_row = db.query(LearningPattern).filter(LearningPattern.pattern_id == candidate.pattern_id).first()
            assert db_row is not None
            assert db_row.tenant_id == tenant_a
            assert db_row.le_score == 0.0
            assert db_row.status == "PROMOTED"
            assert db_row.constitutional_approved is True
            assert db_row.regression_passed is True
            assert db_row.shadow_passed is True
        finally:
            db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
            db.commit()


# =========================================================================
# 8. Category: TOOL_ROUTING Tests
# =========================================================================

def test_p8_tool_routing_verifier_and_policies(clean_test_tenants):
    """Validates Tool Routing verifier and policy execution."""
    from app.core.learning.verifiers.tool_routing import IndependentToolRoutingVerifier
    from app.core.learning.policies.tool_routing_baseline import IncumbentToolRoutingBaselinePolicy
    from app.core.learning.policies.tool_routing_candidate import ToolRoutingCandidatePolicy

    tenant_a, _ = clean_test_tenants
    prompt = "when is diwali 2026 holiday schedule"
    outcome = IndependentToolRoutingVerifier.verify(prompt, {"action_name": "calendar_lookup", "calendar_year": 2026})
    assert outcome.is_valid is True
    assert outcome.outcome_score == 1.0
    assert outcome.expected_result == "calendar_lookup"

    # Mismatch check
    outcome_bad = IndependentToolRoutingVerifier.verify(prompt, {"action_name": "calculate"})
    assert outcome_bad.is_valid is False
    assert outcome_bad.outcome_score == 0.0

    # Baseline & candidate policies
    base_res = IncumbentToolRoutingBaselinePolicy.execute(prompt)
    assert base_res["status"] == "EXECUTED"

    candidate = LearningCandidate(
        pattern_id="pat_tool_route_01",
        name="Candidate_Tool_Routing",
        description="Learned tool routing for calendar intents",
        tenant_id=tenant_a,
        pattern_type=PatternType.TOOL_ROUTING,
        action_template={"strategy": "TOOL_ROUTING", "target_tool_preference": "calendar_lookup"},
        confidence=0.95
    )
    cand_policy = ToolRoutingCandidatePolicy(candidate)
    cand_res = cand_policy.execute(prompt)
    assert cand_res["status"] == "EXECUTED"
    assert cand_res["action_name"] == "calendar_lookup"


def test_p8_tool_routing_end_to_end_ingestion(clean_test_tenants):
    """Validates end-to-end ingestion and LE evaluation for TOOL_ROUTING category."""
    tenant_a, _ = clean_test_tenants
    with SessionLocal() as db:
        user = User(username=f"user_route_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()
        try:
            for i in range(1, 5):
                t = Task(
                    user_id=user.id,
                    title=f"Holiday Calendar Query #{i}",
                    prompt=f"when is holiday calendar for year 2026 query #{i}",
                    status="COMPLETED",
                    mode="REACTIVE",
                    risk_level="LOW",
                    execution_result={
                        "action_name": "calendar_lookup",
                        "calendar_year": 2026,
                        "status": "EXECUTED",
                        "outcome_score_baseline": 0.50
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(t)
            db.commit()

            promoted, reason, candidate = LearningIngestionService.ingest_and_evaluate_tenant_episodes(
                db=db,
                tenant_id=tenant_a,
                user_id=user.id,
                pattern_type=PatternType.TOOL_ROUTING,
                k_min=3,
                le_threshold=-0.01
            )
            assert promoted is True, f"Routing ingestion failed: {reason}"
            assert candidate.pattern_type == PatternType.TOOL_ROUTING
            assert candidate.status == PatternStatus.PROMOTED

            db_row = db.query(LearningPattern).filter(LearningPattern.pattern_id == candidate.pattern_id).first()
            assert db_row is not None
            assert db_row.pattern_type == "TOOL_ROUTING"
            assert db_row.status == "PROMOTED"
        finally:
            db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
            db.commit()


# =========================================================================
# 9. Category: PARAMETER_ADAPTATION Tests
# =========================================================================

def test_p9_parameter_adaptation_verifier_and_policies(clean_test_tenants):
    """Validates Parameter Adaptation verifier and policy execution."""
    from app.core.learning.verifiers.parameter_adaptation import IndependentParameterAdaptationVerifier
    from app.core.learning.policies.parameter_adaptation_baseline import IncumbentParameterAdaptationBaselinePolicy
    from app.core.learning.policies.parameter_adaptation_candidate import ParameterAdaptationCandidatePolicy

    tenant_a, _ = clean_test_tenants
    prompt = "format text uppercase: brahma cos platform"
    outcome = IndependentParameterAdaptationVerifier.verify(prompt, {"output": "BRAHMA COS PLATFORM", "format": "uppercase"})
    assert outcome.is_valid is True
    assert outcome.outcome_score == 1.0

    base_res = IncumbentParameterAdaptationBaselinePolicy.execute(prompt)
    assert base_res["status"] == "EXECUTED"

    candidate = LearningCandidate(
        pattern_id="pat_param_adapt_01",
        name="Candidate_Param_Adapt",
        description="Learned uppercase text formatting adaptation",
        tenant_id=tenant_a,
        pattern_type=PatternType.PARAMETER_ADAPTATION,
        action_template={"strategy": "PARAMETER_ADAPTATION", "target_tool_preference": "echo"},
        confidence=0.95
    )
    cand_policy = ParameterAdaptationCandidatePolicy(candidate)
    cand_res = cand_policy.execute(prompt)
    assert cand_res["status"] == "EXECUTED"
    assert cand_res["format"] == "uppercase"


def test_p9_parameter_adaptation_end_to_end_ingestion(clean_test_tenants):
    """Validates end-to-end ingestion and LE evaluation for PARAMETER_ADAPTATION category."""
    tenant_a, _ = clean_test_tenants
    with SessionLocal() as db:
        user = User(username=f"user_param_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()
        try:
            for i in range(1, 5):
                t = Task(
                    user_id=user.id,
                    title=f"Format Echo Query #{i}",
                    prompt=f"format text uppercase: message payload #{i}",
                    status="COMPLETED",
                    mode="REACTIVE",
                    risk_level="LOW",
                    execution_result={
                        "action_name": "echo",
                        "output": f"MESSAGE PAYLOAD #{i}",
                        "format": "uppercase",
                        "status": "EXECUTED",
                        "outcome_score_baseline": 0.50
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(t)
            db.commit()

            promoted, reason, candidate = LearningIngestionService.ingest_and_evaluate_tenant_episodes(
                db=db,
                tenant_id=tenant_a,
                user_id=user.id,
                pattern_type=PatternType.PARAMETER_ADAPTATION,
                k_min=3,
                le_threshold=-0.01
            )
            assert promoted is True, f"Parameter adaptation ingestion failed: {reason}"
            assert candidate.pattern_type == PatternType.PARAMETER_ADAPTATION
            assert candidate.status == PatternStatus.PROMOTED

            db_row = db.query(LearningPattern).filter(LearningPattern.pattern_id == candidate.pattern_id).first()
            assert db_row is not None
            assert db_row.pattern_type == "PARAMETER_ADAPTATION"
            assert db_row.status == "PROMOTED"
        finally:
            db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
            db.commit()


# =========================================================================
# 10. Category: RECOVERY_STRATEGY Tests
# =========================================================================

def test_p10_recovery_strategy_verifier_and_policies(clean_test_tenants):
    """Validates Recovery Strategy verifier and policy execution."""
    from app.core.learning.verifiers.recovery_strategy import IndependentRecoveryVerifier
    from app.core.learning.policies.recovery_baseline import IncumbentRecoveryBaselinePolicy
    from app.core.learning.policies.recovery_candidate import RecoveryStrategyCandidatePolicy

    tenant_a, _ = clean_test_tenants
    prompt = "system status health check and diagnostic telemetry"
    outcome = IndependentRecoveryVerifier.verify(prompt, {"status": "OPERATIONAL", "engine": "BRAHMA COS Multi-Agent Orchestrator"})
    assert outcome.is_valid is True
    assert outcome.outcome_score == 1.0

    base_res = IncumbentRecoveryBaselinePolicy.execute(prompt)
    assert base_res["status"] == "FAILED"

    candidate = LearningCandidate(
        pattern_id="pat_recov_01",
        name="Candidate_Recovery_Strategy",
        description="Graceful operational recovery strategy",
        tenant_id=tenant_a,
        pattern_type=PatternType.RECOVERY_STRATEGY,
        action_template={"strategy": "RECOVERY_STRATEGY", "target_tool_preference": "system_status"},
        confidence=0.95
    )
    cand_policy = RecoveryStrategyCandidatePolicy(candidate)
    cand_res = cand_policy.execute(prompt)
    assert cand_res["status"] == "EXECUTED"
    assert cand_res["result"]["status"] == "OPERATIONAL"


def test_p10_recovery_strategy_end_to_end_ingestion(clean_test_tenants):
    """Validates end-to-end ingestion and LE evaluation for RECOVERY_STRATEGY category."""
    tenant_a, _ = clean_test_tenants
    with SessionLocal() as db:
        user = User(username=f"user_recov_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()
        try:
            for i in range(1, 5):
                t = Task(
                    user_id=user.id,
                    title=f"Health Diagnostic #{i}",
                    prompt=f"system status health check diagnostic #{i}",
                    status="COMPLETED",
                    mode="REACTIVE",
                    risk_level="LOW",
                    execution_result={
                        "action_name": "system_status",
                        "status": "OPERATIONAL",
                        "engine": "BRAHMA COS Multi-Agent Orchestrator",
                        "outcome_score_baseline": 0.0
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(t)
            db.commit()

            promoted, reason, candidate = LearningIngestionService.ingest_and_evaluate_tenant_episodes(
                db=db,
                tenant_id=tenant_a,
                user_id=user.id,
                pattern_type=PatternType.RECOVERY_STRATEGY,
                k_min=3,
                le_threshold=-0.01
            )
            assert promoted is True, f"Recovery ingestion failed: {reason}"
            assert candidate.pattern_type == PatternType.RECOVERY_STRATEGY
            assert candidate.status == PatternStatus.PROMOTED

            db_row = db.query(LearningPattern).filter(LearningPattern.pattern_id == candidate.pattern_id).first()
            assert db_row is not None
            assert db_row.pattern_type == "RECOVERY_STRATEGY"
            assert db_row.status == "PROMOTED"
        finally:
            db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
            db.commit()


# =========================================================================
# 11. Category: HEURISTIC_RULE Tests
# =========================================================================

def test_p11_heuristic_rule_verifier_and_policies(clean_test_tenants):
    """Validates Heuristic Rule verifier and policy execution."""
    from app.core.learning.verifiers.heuristic_rule import IndependentHeuristicVerifier
    from app.core.learning.policies.heuristic_baseline import IncumbentHeuristicBaselinePolicy
    from app.core.learning.policies.heuristic_candidate import HeuristicRuleCandidatePolicy

    tenant_a, _ = clean_test_tenants
    prompt = "what is the company policy on timesheets submission"
    outcome = IndependentHeuristicVerifier.verify(prompt, {"policies": {"timesheet": "Timesheets must be finalized and submitted by every Friday before 5:00 PM."}})
    assert outcome.is_valid is True
    assert outcome.outcome_score == 1.0

    base_res = IncumbentHeuristicBaselinePolicy.execute(prompt)
    assert base_res["status"] == "EXECUTED"

    candidate = LearningCandidate(
        pattern_id="pat_heur_01",
        name="Candidate_Heuristic_Rule",
        description="Corporate governance heuristic rule matching",
        tenant_id=tenant_a,
        pattern_type=PatternType.HEURISTIC_RULE,
        action_template={"strategy": "HEURISTIC_RULE", "target_tool_preference": "policy_lookup"},
        confidence=0.95
    )
    cand_policy = HeuristicRuleCandidatePolicy(candidate)
    cand_res = cand_policy.execute(prompt)
    assert cand_res["status"] == "EXECUTED"
    assert "timesheet" in cand_res["policies"]


def test_p11_heuristic_rule_end_to_end_ingestion(clean_test_tenants):
    """Validates end-to-end ingestion and LE evaluation for HEURISTIC_RULE category."""
    tenant_a, _ = clean_test_tenants
    with SessionLocal() as db:
        user = User(username=f"user_heur_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()
        try:
            for i, topic in [(1, "timesheet"), (2, "backup"), (3, "deployment"), (4, "timesheet")]:
                t = Task(
                    user_id=user.id,
                    title=f"Governance Policy Query #{i}",
                    prompt=f"what is the company policy on {topic} guidelines",
                    status="COMPLETED",
                    mode="REACTIVE",
                    risk_level="LOW",
                    execution_result={
                        "action_name": "policy_lookup",
                        "topic_queried": topic,
                        "policies": {
                            "timesheet": "Timesheets must be finalized and submitted by every Friday before 5:00 PM.",
                            "backup": "Project Phoenix and all mission-critical production databases must execute cold-storage backups daily.",
                            "deployment": "Production deployments require Maryada governance approval and must pass Murphy risk verification."
                        },
                        "status": "EXECUTED",
                        "outcome_score_baseline": 0.50
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(t)
            db.commit()

            promoted, reason, candidate = LearningIngestionService.ingest_and_evaluate_tenant_episodes(
                db=db,
                tenant_id=tenant_a,
                user_id=user.id,
                pattern_type=PatternType.HEURISTIC_RULE,
                k_min=3,
                le_threshold=-0.01
            )
            assert promoted is True, f"Heuristic ingestion failed: {reason}"
            assert candidate.pattern_type == PatternType.HEURISTIC_RULE
            assert candidate.status == PatternStatus.PROMOTED

            db_row = db.query(LearningPattern).filter(LearningPattern.pattern_id == candidate.pattern_id).first()
            assert db_row is not None
            assert db_row.pattern_type == "HEURISTIC_RULE"
            assert db_row.status == "PROMOTED"
        finally:
            db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
            db.commit()
