"""
GAP #5 TEST SUITE: Live Non-Authoritative Shadow Evaluation & Isolation Proof
Whitesheet §17.3, §17.4, §17.6, §19.5, §20.3 & Appendix B.16 (F14 / F15)

Strictly validates:
1. Live Non-Authoritative Shadow Interception on incoming live runtime task traffic.
2. Authoritative Boundary: Candidate execution can NEVER modify task.status, task.execution_result, or user deliverable.
3. Fault Injection / Fail-Open Isolation: Candidate throwing exceptions or returning malformed data does not impact primary task.
4. Independent Clean-Room Domain Verification of both baseline and candidate.
5. Comparative Provenance & CHITRA Logging with delta, scores, and verifier IDs.
6. Shadow Duration Tracking (shadow_entered_at, shadow_eval_count, last_shadow_eval_at) without false K-032 claims.
7. Strict Tenant Isolation across shadow evaluations.
8. Full coverage across all 5 canonical learning categories.
"""
import pytest
import secrets
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.learning_pattern import LearningPattern
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.learning.models import (
    PatternStatus,
    PatternType,
    LearningCandidate
)
from app.core.learning.shadow_evaluator import ShadowEvaluator
from app.core.learning.stewardship import F15EvolutionarySteward
from app.core.learning.service import LearningService
from app.core.learning.ingestion import LearningIngestionService
from app.core.learning.verifiers import (
    IndependentCalculatorVerifier,
    IndependentToolRoutingVerifier,
    IndependentParameterAdaptationVerifier,
    IndependentRecoveryVerifier,
    IndependentHeuristicVerifier
)

# Test sandbox engine to guarantee hermetic test execution across all environments
SANDBOX_DB_URL = "sqlite:///./test_gap5_sandbox.db"
sandbox_engine = create_engine(SANDBOX_DB_URL, connect_args={"check_same_thread": False})
SandboxSession = sessionmaker(bind=sandbox_engine)


@pytest.fixture(autouse=True)
def setup_sandbox_db(monkeypatch):
    """Initializes clean sandbox tables and patches SessionLocal for hermetic testing."""
    Base.metadata.drop_all(bind=sandbox_engine)
    Base.metadata.create_all(bind=sandbox_engine)
    monkeypatch.setattr("app.db.database.SessionLocal", SandboxSession)
    monkeypatch.setattr("app.core.learning.stewardship.SessionLocal", SandboxSession, raising=False)
    yield
    Base.metadata.drop_all(bind=sandbox_engine)


@pytest.fixture
def clean_test_tenants():
    """Generates unique isolated tenant IDs."""
    tenant_a = f"tenant_gap5_a_{secrets.token_hex(4)}"
    tenant_b = f"tenant_gap5_b_{secrets.token_hex(4)}"
    return tenant_a, tenant_b


# =========================================================================
# 1. Authoritative Boundary & Live Shadow Dispatch (Category 1: PLAN_OPTIMIZATION)
# =========================================================================

def test_p1_live_shadow_dispatch_math_and_isolation(clean_test_tenants):
    """
    Validates that:
    1. A live task execution triggers the candidate policy non-authoritatively.
    2. Primary task execution result remains 100% authoritative and unchanged.
    3. Candidate comparative provenance is recorded with delta and verified scores.
    """
    tenant_a, _ = clean_test_tenants
    with SandboxSession() as db:
        user = User(username=f"user_gap5_math_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()

        # 1. Create a LearningCandidate in SHADOW state
        candidate = LearningCandidate(
            pattern_id=f"pat_shadow_math_{secrets.token_hex(4)}",
            name="Candidate_Math_Optimization",
            description="Live shadow candidate for math execution",
            tenant_id=tenant_a,
            pattern_type=PatternType.PLAN_OPTIMIZATION,
            action_template={"strategy": "PLAN_OPTIMIZATION", "target_tool_preference": "calculate"},
            confidence=0.90,
            status=PatternStatus.VALIDATED
        )
        # Deploy to SHADOW using F15 Steward
        F15EvolutionarySteward.deploy_to_shadow(candidate=candidate, db_session=db, user_id=user.id)

        # Assert shadow entry metadata initialized
        pat_row = db.query(LearningPattern).filter(LearningPattern.pattern_id == candidate.pattern_id).first()
        assert pat_row.status == "SHADOW"
        assert "shadow_entered_at" in pat_row.metadata_payload
        assert pat_row.metadata_payload["shadow_eval_count"] == 0

        # 2. Simulate live authoritative task execution
        expr = "calculate 45 * 8"
        baseline_result = {"status": "EXECUTED", "expression": "45 * 8", "result": 360}
        task = Task(
            user_id=user.id,
            title="Live Math Task",
            prompt=expr,
            status="COMPLETED",
            mode="REACTIVE",
            risk_level="LOW",
            execution_result=baseline_result,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # 3. Dispatch Live Shadow Evaluation
        evals = ShadowEvaluator.dispatch_live_shadow_evaluation(
            task_id=task.id,
            user_id=user.id,
            tenant_id=tenant_a,
            prompt=task.prompt,
            execution_result=task.execution_result
        )

        # 4. Assert non-authoritative evaluation occurred
        assert len(evals) == 1
        prov = evals[0]
        assert prov["pattern_id"] == candidate.pattern_id
        assert (prov["baseline_raw_result"] == 360 or prov["baseline_raw_result"].get("result") == 360)
        assert (prov["candidate_raw_result"] == 360 or prov["candidate_raw_result"].get("result") == 360)
        assert prov["baseline_outcome_score"] == 1.0
        assert prov["candidate_outcome_score"] == 1.0
        assert prov["delta"] == 0.0
        assert prov["regression"] is False
        assert prov["shadow_mode"] == "LIVE_NON_AUTHORITATIVE"

        # 5. Assert authoritative task was NOT modified
        task_refreshed = db.query(Task).filter(Task.id == task.id).first()
        assert task_refreshed.status == "COMPLETED"
        assert task_refreshed.execution_result == baseline_result

        # 6. Assert persistent metadata tracking in learning_patterns
        db.refresh(pat_row)
        assert pat_row.metadata_payload["shadow_eval_count"] == 1
        assert "last_shadow_eval_at" in pat_row.metadata_payload
        assert len(pat_row.metadata_payload["live_shadow_evaluations"]) == 1

        # 7. Assert CHITRA shadow_evaluation audit event logged
        ch_event = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.faculty == "LEARNING",
            ChitraEvent.event_type == "shadow_evaluation"
        ).first()
        assert ch_event is not None
        assert ch_event.decision["pattern_id"] == candidate.pattern_id


# =========================================================================
# 2. Fault Injection & Fail-Open Isolation Proof
# =========================================================================

def test_p2_candidate_fault_injection_preserves_authoritative_task(clean_test_tenants):
    """
    Fault injection test:
    Proves that even when the candidate policy throws an unhandled exception or returns
    malformed output, the primary task remains COMPLETED with correct authoritative output.
    """
    tenant_a, _ = clean_test_tenants
    with SandboxSession() as db:
        user = User(username=f"user_gap5_fault_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()

        # Create a candidate in SHADOW with invalid/corrupt action template
        candidate = LearningCandidate(
            pattern_id=f"pat_fault_{secrets.token_hex(4)}",
            name="Candidate_Faulty_Math",
            description="Faulty candidate testing fail-open isolation",
            tenant_id=tenant_a,
            pattern_type=PatternType.PLAN_OPTIMIZATION,
            action_template={"strategy": "CORRUPT_STRATEGY"},
            confidence=0.80,
            status=PatternStatus.VALIDATED
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=candidate, db_session=db, user_id=user.id)

        # Live task
        expr = "calculate 100 / 0"  # Problematic expression
        baseline_result = {"status": "FAILED", "error": "Division by zero in calculation"}
        task = Task(
            user_id=user.id,
            title="Math Fault Task",
            prompt=expr,
            status="COMPLETED",
            mode="REACTIVE",
            risk_level="LOW",
            execution_result=baseline_result,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(task)
        db.commit()

        # Dispatch live shadow evaluation
        evals = ShadowEvaluator.dispatch_live_shadow_evaluation(
            task_id=task.id,
            user_id=user.id,
            tenant_id=tenant_a,
            prompt=task.prompt,
            execution_result=task.execution_result
        )

        assert len(evals) == 1
        prov = evals[0]
        assert prov["pattern_id"] == candidate.pattern_id
        # Candidate failed safely without crashing dispatcher
        assert prov["candidate_outcome_score"] == 0.0

        # Assert primary task remains 100% intact
        db.refresh(task)
        assert task.status == "COMPLETED"
        assert task.execution_result == baseline_result


# =========================================================================
# 3. Strict Tenant Isolation on Live Shadow Execution
# =========================================================================

def test_p3_strict_tenant_isolation_live_shadow(clean_test_tenants):
    """
    Validates that Tenant A's live task ONLY triggers Tenant A's shadow candidate,
    and NEVER triggers Tenant B's shadow candidate.
    """
    tenant_a, tenant_b = clean_test_tenants
    with SandboxSession() as db:
        user_a = User(username=f"user_gap5_iso_a_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        user_b = User(username=f"user_gap5_iso_b_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add_all([user_a, user_b])
        db.flush()

        # Candidate A in SHADOW for Tenant A
        cand_a = LearningCandidate(
            pattern_id=f"pat_iso_a_{secrets.token_hex(4)}",
            name="Candidate_Tenant_A",
            description="Tenant A candidate",
            tenant_id=tenant_a,
            pattern_type=PatternType.PLAN_OPTIMIZATION,
            status=PatternStatus.VALIDATED
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=cand_a, db_session=db, user_id=user_a.id)

        # Candidate B in SHADOW for Tenant B
        cand_b = LearningCandidate(
            pattern_id=f"pat_iso_b_{secrets.token_hex(4)}",
            name="Candidate_Tenant_B",
            description="Tenant B candidate",
            tenant_id=tenant_b,
            pattern_type=PatternType.PLAN_OPTIMIZATION,
            status=PatternStatus.VALIDATED
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=cand_b, db_session=db, user_id=user_b.id)

        # Live Task submitted by Tenant A
        task_a = Task(
            user_id=user_a.id,
            title="Task for Tenant A",
            prompt="calculate 20 * 5",
            status="COMPLETED",
            mode="REACTIVE",
            risk_level="LOW",
            execution_result={"result": 100},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(task_a)
        db.commit()

        # Dispatch for Tenant A
        evals_a = ShadowEvaluator.dispatch_live_shadow_evaluation(
            task_id=task_a.id,
            user_id=user_a.id,
            tenant_id=tenant_a,
            prompt=task_a.prompt,
            execution_result=task_a.execution_result
        )

        # Only Candidate A must have executed
        assert len(evals_a) == 1
        assert evals_a[0]["pattern_id"] == cand_a.pattern_id

        # Verify Candidate B received 0 evaluations
        pat_b_row = db.query(LearningPattern).filter(LearningPattern.pattern_id == cand_b.pattern_id).first()
        assert pat_b_row.metadata_payload["shadow_eval_count"] == 0
        assert len(pat_b_row.metadata_payload["live_shadow_evaluations"]) == 0


# =========================================================================
# 4. Multi-Category Live Shadow Coverage (TOOL_ROUTING, PARAMETER_ADAPTATION, RECOVERY, HEURISTIC)
# =========================================================================

def test_p4_live_shadow_tool_routing(clean_test_tenants):
    """Validates live shadow evaluation for TOOL_ROUTING category."""
    tenant_a, _ = clean_test_tenants
    with SandboxSession() as db:
        user = User(username=f"user_gap5_route_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()

        cand = LearningCandidate(
            pattern_id=f"pat_route_{secrets.token_hex(4)}",
            name="Candidate_Tool_Routing",
            description="Live shadow for tool routing",
            tenant_id=tenant_a,
            pattern_type=PatternType.TOOL_ROUTING,
            action_template={"strategy": "TOOL_ROUTING", "target_tool_preference": "calendar_lookup"},
            status=PatternStatus.VALIDATED
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=cand, db_session=db, user_id=user.id)

        task = Task(
            user_id=user.id,
            title="Holiday Query",
            prompt="when is holiday calendar for year 2026",
            status="COMPLETED",
            mode="REACTIVE",
            risk_level="LOW",
            execution_result={"action_name": "calendar_lookup", "calendar_year": 2026},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(task)
        db.commit()

        evals = ShadowEvaluator.dispatch_live_shadow_evaluation(
            task_id=task.id,
            user_id=user.id,
            tenant_id=tenant_a,
            prompt=task.prompt,
            execution_result=task.execution_result
        )

        assert len(evals) == 1
        prov = evals[0]
        assert prov["pattern_id"] == cand.pattern_id
        assert prov["baseline_outcome_score"] == 1.0
        assert prov["candidate_outcome_score"] == 1.0
        assert prov["delta"] == 0.0
        assert prov["verifier_id"] == IndependentToolRoutingVerifier.VERIFIER_ID


def test_p4_live_shadow_parameter_adaptation(clean_test_tenants):
    """Validates live shadow evaluation for PARAMETER_ADAPTATION category."""
    tenant_a, _ = clean_test_tenants
    with SandboxSession() as db:
        user = User(username=f"user_gap5_param_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()

        cand = LearningCandidate(
            pattern_id=f"pat_param_{secrets.token_hex(4)}",
            name="Candidate_Param_Adapt",
            description="Live shadow for parameter adaptation",
            tenant_id=tenant_a,
            pattern_type=PatternType.PARAMETER_ADAPTATION,
            action_template={"strategy": "PARAMETER_ADAPTATION"},
            status=PatternStatus.VALIDATED
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=cand, db_session=db, user_id=user.id)

        task = Task(
            user_id=user.id,
            title="Echo Task",
            prompt="format text uppercase: mission critical payload",
            status="COMPLETED",
            mode="REACTIVE",
            risk_level="LOW",
            execution_result={"output": "MISSION CRITICAL PAYLOAD", "format": "uppercase"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(task)
        db.commit()

        evals = ShadowEvaluator.dispatch_live_shadow_evaluation(
            task_id=task.id,
            user_id=user.id,
            tenant_id=tenant_a,
            prompt=task.prompt,
            execution_result=task.execution_result
        )

        assert len(evals) == 1
        prov = evals[0]
        assert prov["baseline_outcome_score"] == 1.0
        assert prov["candidate_outcome_score"] == 1.0
        assert prov["delta"] == 0.0
        assert prov["verifier_id"] == IndependentParameterAdaptationVerifier.VERIFIER_ID


def test_p4_live_shadow_recovery_strategy(clean_test_tenants):
    """Validates live shadow evaluation for RECOVERY_STRATEGY category."""
    tenant_a, _ = clean_test_tenants
    with SandboxSession() as db:
        user = User(username=f"user_gap5_recov_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()

        cand = LearningCandidate(
            pattern_id=f"pat_recov_{secrets.token_hex(4)}",
            name="Candidate_Recovery",
            description="Live shadow for recovery strategy",
            tenant_id=tenant_a,
            pattern_type=PatternType.RECOVERY_STRATEGY,
            action_template={"strategy": "RECOVERY_STRATEGY"},
            status=PatternStatus.VALIDATED
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=cand, db_session=db, user_id=user.id)

        task = Task(
            user_id=user.id,
            title="System Diagnostic Task",
            prompt="system status health check and diagnostic telemetry",
            status="COMPLETED",
            mode="REACTIVE",
            risk_level="LOW",
            execution_result={"engine": "BRAHMA COS Multi-Agent Orchestrator", "status": "OPERATIONAL"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(task)
        db.commit()

        evals = ShadowEvaluator.dispatch_live_shadow_evaluation(
            task_id=task.id,
            user_id=user.id,
            tenant_id=tenant_a,
            prompt=task.prompt,
            execution_result=task.execution_result
        )

        assert len(evals) == 1
        prov = evals[0]
        assert prov["baseline_outcome_score"] == 1.0
        assert prov["candidate_outcome_score"] == 1.0
        assert prov["delta"] == 0.0
        assert prov["verifier_id"] == IndependentRecoveryVerifier.VERIFIER_ID


def test_p4_live_shadow_heuristic_rule(clean_test_tenants):
    """Validates live shadow evaluation for HEURISTIC_RULE category."""
    tenant_a, _ = clean_test_tenants
    with SandboxSession() as db:
        user = User(username=f"user_gap5_heur_{secrets.token_hex(4)}", hashed_password="pw", is_active=True)
        db.add(user)
        db.flush()

        cand = LearningCandidate(
            pattern_id=f"pat_heur_{secrets.token_hex(4)}",
            name="Candidate_Heuristic_Rule",
            description="Live shadow for heuristic rule",
            tenant_id=tenant_a,
            pattern_type=PatternType.HEURISTIC_RULE,
            action_template={"strategy": "HEURISTIC_RULE"},
            status=PatternStatus.VALIDATED
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=cand, db_session=db, user_id=user.id)

        task = Task(
            user_id=user.id,
            title="Timesheet Policy Task",
            prompt="what is the corporate policy on timesheet submission deadline",
            status="COMPLETED",
            mode="REACTIVE",
            risk_level="LOW",
            execution_result={
                "policies": {
                    "timesheet": "Timesheets must be finalized and submitted by every Friday before 5:00 PM."
                }
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(task)
        db.commit()

        evals = ShadowEvaluator.dispatch_live_shadow_evaluation(
            task_id=task.id,
            user_id=user.id,
            tenant_id=tenant_a,
            prompt=task.prompt,
            execution_result=task.execution_result
        )

        assert len(evals) == 1
        prov = evals[0]
        assert prov["baseline_outcome_score"] == 1.0
        assert prov["candidate_outcome_score"] == 1.0
        assert prov["delta"] == 0.0
        assert prov["verifier_id"] == IndependentHeuristicVerifier.VERIFIER_ID


def test_p5_natural_ingestion_deploys_to_shadow_and_live_evaluates(clean_test_tenants):
    """
    Dedicated End-to-End Ingestion-to-Shadow Lifecycle Test:
    1. 3 completed verified tasks trigger runtime F14 extraction & MARYADA validation.
    2. Candidate is deployed to SHADOW and remains in SHADOW (not immediately promoted/rejected).
    3. Subsequent live task executes and triggers dispatch_live_shadow_evaluation().
    4. Observation count increments, live observation is recorded, authoritative task is unmodified.
    """
    tenant_a, _ = clean_test_tenants

    with SandboxSession() as db:
        user = User(
            username=f"user_{secrets.token_hex(4)}",
            hashed_password="fake_hashed_pw"
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        user_tenant = f"tenant_{user.id}"

        # 1. Add 3 completed arithmetic tasks (Threshold k_min=3 met)
        tasks = []
        for i, expr in enumerate(["10 + 20", "50 * 2", "100 / 4"]):
            ans = eval(expr)
            t = Task(
                user_id=user.id,
                title=f"Task {i+1}",
                prompt=f"calculate {expr}",
                status="COMPLETED",
                mode="REACTIVE",
                risk_level="LOW",
                execution_result={
                    "expression": expr,
                    "result": ans,
                    "tool": "calculator",
                    "status": "EXECUTED",
                    "duration_ms": 12.5
                },
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.add(t)
            tasks.append(t)
        db.commit()
        for t in tasks:
            db.refresh(t)

        # 2. Invoke runtime ingestion hook on task completion
        success, reason, candidate = LearningIngestionService.on_task_completed(
            db=db,
            task=tasks[-1]
        )

        assert success is True, f"Ingestion failed: {reason}"
        assert candidate is not None

        # 3. Assert candidate is strictly in SHADOW status and correctly scoped
        pat_row = db.query(LearningPattern).filter(
            LearningPattern.pattern_id == candidate.pattern_id
        ).first()

        assert pat_row is not None
        assert pat_row.status == "SHADOW"
        assert pat_row.tenant_id == user_tenant
        assert pat_row.pattern_type == "PLAN_OPTIMIZATION"
        assert pat_row.constitutional_approved is True
        assert pat_row.metadata_payload["shadow_eval_count"] == 0
        assert pat_row.metadata_payload["live_shadow_evaluations"] == []
        assert "shadow_entered_at" in pat_row.metadata_payload
        assert pat_row.status != "PROMOTED"
        assert pat_row.status != "REJECTED"

        # 4. Execute next natural live task (Task 4)
        live_task = Task(
            user_id=user.id,
            title="Live Task 4",
            prompt="calculate 8 * 9",
            status="COMPLETED",
            mode="REACTIVE",
            risk_level="LOW",
            execution_result={
                "expression": "8 * 9",
                "result": 72,
                "tool": "calculator",
                "status": "EXECUTED",
                "duration_ms": 15.0
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(live_task)
        db.commit()
        db.refresh(live_task)

        # 5. Live Shadow Evaluation Dispatch
        live_evals = ShadowEvaluator.dispatch_live_shadow_evaluation(
            task_id=live_task.id,
            user_id=user.id,
            tenant_id=user_tenant,
            prompt=live_task.prompt,
            execution_result=live_task.execution_result
        )

        assert len(live_evals) == 1
        obs = live_evals[0]
        assert obs["pattern_id"] == candidate.pattern_id
        assert obs["tenant_id"] == user_tenant
        assert obs["delta"] == 0.0
        assert obs["regression"] is False
        assert obs["shadow_mode"] == "LIVE_NON_AUTHORITATIVE"

        # 6. Verify candidate row in PostgreSQL updated with live observation
        db.refresh(pat_row)
        assert pat_row.status == "SHADOW"
        assert pat_row.metadata_payload["shadow_eval_count"] == 1
        assert "last_shadow_eval_at" in pat_row.metadata_payload
        assert len(pat_row.metadata_payload["live_shadow_evaluations"]) == 1
        assert pat_row.metadata_payload["live_shadow_evaluations"][0]["task_id"] == live_task.id

        # 7. Verify authoritative task result was NOT modified
        db.refresh(live_task)
        assert live_task.status == "COMPLETED"
        assert live_task.execution_result["result"] == 72

        # 8. Verify CHITRA shadow_evaluation audit event logged
        ch_ev = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == live_task.id,
            ChitraEvent.faculty == "LEARNING",
            ChitraEvent.event_type == "shadow_evaluation"
        ).first()
        assert ch_ev is not None
        assert ch_ev.decision["pattern_id"] == candidate.pattern_id


def test_p6_evaluate_live_shadow_promotion_gate(clean_test_tenants):
    """
    Validates the final promotion evaluation gate over accumulated live shadow observations (§19.5, §20.3):
    1. Candidate with positive live observations (delta >= 0, regressions = 0) and LE > threshold PROMOTES.
    2. Candidate with regressions detected is REJECTED fail-closed.
    3. Minimum observation count threshold is strictly enforced.
    """
    tenant_a, _ = clean_test_tenants

    with SandboxSession() as db:
        user = User(
            username=f"user_p6_{secrets.token_hex(4)}",
            hashed_password="pw"
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # 1. Create SHADOW candidate
        cand_good = LearningCandidate(
            pattern_id=f"pat_live_good_{secrets.token_hex(4)}",
            name="Live_Good_Plan",
            description="High effectiveness plan with verified live observations",
            tenant_id=tenant_a,
            pattern_type=PatternType.PLAN_OPTIMIZATION,
            action_template={"strategy": "PLAN_OPTIMIZATION"},
            status=PatternStatus.VALIDATED,
            constitutional_approved=True
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=cand_good, db_session=db, user_id=user.id)

        # 2. Add verified live observations
        live_obs = [
            {
                "task_id": 801,
                "tenant_id": tenant_a,
                "expression": "10 * 10",
                "baseline_outcome_score": 0.50,
                "candidate_outcome_score": 1.0,
                "delta": 0.50,
                "regression": False,
                "shadow_mode": "LIVE_NON_AUTHORITATIVE"
            },
            {
                "task_id": 802,
                "tenant_id": tenant_a,
                "expression": "20 * 5",
                "baseline_outcome_score": 0.50,
                "candidate_outcome_score": 1.0,
                "delta": 0.50,
                "regression": False,
                "shadow_mode": "LIVE_NON_AUTHORITATIVE"
            }
        ]

        # 3. Assert insufficient observations failure when min_live_observations > 2
        insuf_ok, insuf_msg, _ = LearningService.evaluate_live_shadow_promotion(
            candidate=cand_good,
            live_observations=live_obs,
            min_live_observations=5,
            db_session=db,
            user_id=user.id
        )
        assert insuf_ok is False
        assert "INSUFFICIENT_LIVE_OBSERVATIONS" in insuf_msg

        # 4. Evaluate and Promote with LE threshold tau_LE = 0.40 (LE = 0.50 > 0.40)
        promoted, msg, updated = LearningService.evaluate_live_shadow_promotion(
            candidate=cand_good,
            live_observations=live_obs,
            le_threshold=0.40,
            db_session=db,
            user_id=user.id
        )
        assert promoted is True
        assert updated.status == PatternStatus.PROMOTED
        assert updated.le_score == 0.50
        assert updated.regression_passed is True
        assert updated.shadow_passed is True

        # 5. Regression detection fail-closed test
        cand_bad = LearningCandidate(
            pattern_id=f"pat_live_bad_{secrets.token_hex(4)}",
            name="Live_Regressed_Plan",
            description="Plan that introduces a regression during live observation",
            tenant_id=tenant_a,
            pattern_type=PatternType.PLAN_OPTIMIZATION,
            action_template={"strategy": "PLAN_OPTIMIZATION"},
            status=PatternStatus.VALIDATED,
            constitutional_approved=True
        )
        F15EvolutionarySteward.deploy_to_shadow(candidate=cand_bad, db_session=db, user_id=user.id)

        bad_obs = [
            {
                "task_id": 803,
                "tenant_id": tenant_a,
                "expression": "100 / 0",
                "baseline_outcome_score": 1.0,
                "candidate_outcome_score": 0.0,
                "delta": -1.0,
                "regression": True,
                "shadow_mode": "LIVE_NON_AUTHORITATIVE"
            }
        ]

        rej_ok, rej_msg, rej_cand = LearningService.evaluate_live_shadow_promotion(
            candidate=cand_bad,
            live_observations=bad_obs,
            le_threshold=0.0,
            db_session=db,
            user_id=user.id
        )
        assert rej_ok is False
        assert rej_cand.status == PatternStatus.REJECTED
        assert "regressions detected" in rej_msg
