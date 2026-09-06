"""
LEARNING SYSTEM Phase 18I-2 Dedicated Test Suite: F14 Learning Pipeline Integration
Strictly tests F14 integration into LearningService across mandated scenarios A through J.
"""
import pytest
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
    LearningEvidence
)
from app.core.learning.pattern_extractor import F14PatternExtractor
from app.core.learning.service import LearningService
from app.core.learning.stewardship import F15EvolutionarySteward, StewardshipError

TEST_DB_URL = "sqlite:///./test_karma_phase18i_f14_integration_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p18i", hashed_password="pwd")
    db.add(user_a)
    db.commit()
    db.refresh(user_a)

    task_a = Task(user_id=user_a.id, title="Task A", prompt="Prompt A", status="PENDING")
    db.add(task_a)
    db.commit()
    db.refresh(task_a)

    u_a, t_a = user_a.id, task_a.id
    db.close()
    return u_a, t_a


# -------------------------------------------------------------
# TEST A: F14 EXTRACTION THROUGH LEARNINGSERVICE
# -------------------------------------------------------------

def test_scenario_a_extraction_through_learning_service():
    episodes = [
        {"task_id": 1001, "event_id": "evt_1", "status": "SUCCESS", "duration_ms": 120.0, "tool": "calc"},
        {"task_id": 1002, "event_id": "evt_2", "status": "SUCCESS", "duration_ms": 110.0, "tool": "calc"},
        {"task_id": 1003, "event_id": "evt_3", "status": "SUCCESS", "duration_ms": 115.0, "tool": "calc"}
    ]
    candidate = LearningService.extract_pattern(
        tenant_id="tenant_service_test",
        episodes=episodes,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Service Extracted Pattern"
    )
    assert candidate.pattern_id.startswith("pat_")
    assert candidate.tenant_id == "tenant_service_test"
    assert candidate.name == "Service Extracted Pattern"
    assert candidate.evidence.sample_count == 3


# -------------------------------------------------------------
# TEST B: k_min=3 ENFORCEMENT THROUGH LEARNINGSERVICE
# -------------------------------------------------------------

def test_scenario_b_k_min_enforcement():
    # 0 episodes rejected
    with pytest.raises(ValueError, match="empty list of episodes"):
        LearningService.extract_pattern("tenant_service_test", [])

    # 1 episode rejected
    with pytest.raises(ValueError, match="requires at least 3 valid supporting episodes"):
        LearningService.extract_pattern("tenant_service_test", [{"task_id": 101, "status": "SUCCESS"}])

    # 2 episodes rejected
    with pytest.raises(ValueError, match="requires at least 3 valid supporting episodes"):
        LearningService.extract_pattern("tenant_service_test", [
            {"task_id": 101, "status": "SUCCESS"},
            {"task_id": 102, "status": "SUCCESS"}
        ])

    # Custom k_min supported
    episodes_2 = [
        {"task_id": 101, "status": "SUCCESS"},
        {"task_id": 102, "status": "SUCCESS"}
    ]
    candidate_k2 = LearningService.extract_pattern(
        tenant_id="tenant_service_test",
        episodes=episodes_2,
        k_min=2
    )
    assert candidate_k2.evidence.sample_count == 2


# -------------------------------------------------------------
# TEST C: TENANT ISOLATION THROUGH LEARNINGSERVICE
# -------------------------------------------------------------

def test_scenario_c_tenant_isolation():
    episodes = [
        {"task_id": 201, "event_id": "e1", "tenant_id": "tenant_alice", "status": "SUCCESS"},
        {"task_id": 202, "event_id": "e2", "tenant_id": "tenant_alice", "status": "SUCCESS"},
        {"task_id": 203, "event_id": "e3", "tenant_id": "tenant_bob", "status": "SUCCESS"}
    ]
    # tenant_bob episode is ignored, leaving only 2 valid episodes for tenant_alice -> rejected!
    with pytest.raises(ValueError, match="requires at least 3 valid supporting episodes"):
        LearningService.extract_pattern("tenant_alice", episodes)


# -------------------------------------------------------------
# TEST D: PROVENANCE SURVIVES SERVICE BOUNDARY
# -------------------------------------------------------------

def test_scenario_d_provenance_survives_boundary():
    episodes = [
        {"task_id": 301, "event_id": "evt_301", "status": "SUCCESS", "duration_ms": 100.0},
        {"task_id": 302, "event_id": "evt_302", "status": "SUCCESS", "duration_ms": 200.0},
        {"task_id": 303, "event_id": "evt_303", "status": "SUCCESS", "duration_ms": 300.0}
    ]
    candidate = LearningService.extract_pattern("tenant_alice", episodes)
    assert candidate.evidence.source_task_ids == [301, 302, 303]
    assert candidate.evidence.source_event_ids == ["evt_301", "evt_302", "evt_303"]
    assert candidate.evidence.sample_count == 3
    assert candidate.evidence.metric_deltas["mean_duration_ms"] == 200.0


# -------------------------------------------------------------
# TEST E: FINGERPRINT SURVIVES SERVICE BOUNDARY
# -------------------------------------------------------------

def test_scenario_e_fingerprint_survives_boundary():
    episodes = [
        {"task_id": 401, "event_id": "evt_401", "status": "SUCCESS", "duration_ms": 50.0, "tool": "search"},
        {"task_id": 402, "event_id": "evt_402", "status": "SUCCESS", "duration_ms": 50.0, "tool": "search"},
        {"task_id": 403, "event_id": "evt_403", "status": "SUCCESS", "duration_ms": 50.0, "tool": "search"}
    ]
    candidate = LearningService.extract_pattern("tenant_alice", episodes)
    assert "fingerprint" in candidate.metadata
    assert candidate.metadata["fingerprint"].startswith("sha256:")
    assert len(candidate.metadata["fingerprint"].split("sha256:")[1]) == 64


# -------------------------------------------------------------
# TEST F: CANDIDATE STARTS IN CANDIDATE STATE
# -------------------------------------------------------------

def test_scenario_f_candidate_initial_state():
    episodes = [
        {"task_id": 501, "status": "SUCCESS"},
        {"task_id": 502, "status": "SUCCESS"},
        {"task_id": 503, "status": "SUCCESS"}
    ]
    candidate = LearningService.extract_pattern("tenant_alice", episodes)
    assert candidate.status == PatternStatus.CANDIDATE
    assert candidate.version == 1


# -------------------------------------------------------------
# TEST G: UNSAFE FLAGS REMAIN FALSE
# -------------------------------------------------------------

def test_scenario_g_unsafe_flags_remain_false():
    episodes = [
        {"task_id": 601, "status": "SUCCESS"},
        {"task_id": 602, "status": "SUCCESS"},
        {"task_id": 603, "status": "SUCCESS"}
    ]
    candidate = LearningService.extract_pattern("tenant_alice", episodes)
    assert candidate.constitutional_approved is False
    assert candidate.regression_passed is False
    assert candidate.shadow_passed is False
    assert candidate.le_score == 0.0
    assert candidate.promoted_at is None


# -------------------------------------------------------------
# TEST H: LIFECYCLE DOES NOT BYPASS MARYADA
# -------------------------------------------------------------

def test_scenario_h_lifecycle_does_not_bypass_maryada():
    # Destructive pattern candidate
    episodes = [
        {"task_id": 701, "status": "SUCCESS"},
        {"task_id": 702, "status": "SUCCESS"},
        {"task_id": 703, "status": "SUCCESS"}
    ]
    dangerous_candidate = LearningService.extract_pattern(
        tenant_id="tenant_alice",
        episodes=episodes,
        pattern_type=PatternType.HEURISTIC_RULE,
        name="rm -rf /production_database"
    )
    # Process through lifecycle
    promoted, msg, updated = LearningService.process_candidate_lifecycle(
        candidate=dangerous_candidate,
        le_threshold=0.30
    )
    assert promoted is False
    assert updated.status == PatternStatus.REJECTED
    assert updated.constitutional_approved is False
    assert "Failed constitutional validation" in msg


# -------------------------------------------------------------
# TEST I: F14 CANNOT DIRECTLY PROMOTE
# -------------------------------------------------------------

def test_scenario_i_f14_cannot_directly_promote():
    episodes = [
        {"task_id": 801, "status": "SUCCESS"},
        {"task_id": 802, "status": "SUCCESS"},
        {"task_id": 803, "status": "SUCCESS"}
    ]
    candidate = LearningService.extract_pattern("tenant_alice", episodes)
    # Direct attempt to promote candidate from CANDIDATE state must fail with StewardshipError
    with pytest.raises(StewardshipError, match="Expected SHADOW"):
        from app.core.learning.models import LEResult, RegressionTestResult
        le_res = LEResult(candidate_id=candidate.pattern_id, le_score=0.95, threshold=0.70, passed=True)
        regr_res = RegressionTestResult(candidate_id=candidate.pattern_id, benchmark_count=1, regressions_detected=0, passed=True)
        F15EvolutionarySteward.evaluate_and_promote(candidate, le_res, regr_res)


# -------------------------------------------------------------
# TEST J: EXISTING PHASE 17 COMPATIBILITY & CHITRA AUDITING
# -------------------------------------------------------------

def test_scenario_j_full_lifecycle_compatibility():
    u_a, t_a = reset_sandbox()
    db = TestSession()

    episodes = [
        {"task_id": t_a, "event_id": "evt_j_1", "status": "SUCCESS", "duration_ms": 50.0, "tool": "calc"},
        {"task_id": t_a, "event_id": "evt_j_2", "status": "SUCCESS", "duration_ms": 45.0, "tool": "calc"},
        {"task_id": t_a, "event_id": "evt_j_3", "status": "SUCCESS", "duration_ms": 55.0, "tool": "calc"}
    ]
    candidate = LearningService.extract_pattern(
        tenant_id=f"tenant_{u_a}",
        episodes=episodes,
        pattern_type=PatternType.PLAN_OPTIMIZATION,
        name="Phase 18I-2 Verified Optimization"
    )

    promoted, msg, updated = LearningService.process_candidate_lifecycle(
        candidate=candidate,
        le_threshold=0.30,
        db_session=db,
        user_id=u_a,
        task_id=t_a
    )

    assert promoted is True
    assert updated.status == PatternStatus.PROMOTED
    assert updated.constitutional_approved is True
    assert updated.promoted_at is not None

    # Verify audit event in CHITRA
    evt = db.query(ChitraEvent).filter(ChitraEvent.task_id == t_a, ChitraEvent.faculty == "LEARNING").first()
    assert evt is not None
    assert evt.decision["pattern_id"] == updated.pattern_id
    db.close()


def run_all_phase18i_f14_integration_tests():
    print("==================================================")
    print("LEARNING SYSTEM PHASE 18I-2: F14 PIPELINE INTEGRATION")
    print("Comprehensive Scenario Suite (A - J)")
    print("==================================================")

    test_scenario_a_extraction_through_learning_service()
    print("  [PASS Scenario A] [REAL] F14 extraction through LearningService.")

    test_scenario_b_k_min_enforcement()
    print("  [PASS Scenario B] [REAL] k_min=3 enforcement through LearningService.")

    test_scenario_c_tenant_isolation()
    print("  [PASS Scenario C] [REAL] Strict tenant isolation.")

    test_scenario_d_provenance_survives_boundary()
    print("  [PASS Scenario D] [REAL] Provenance survives service boundary.")

    test_scenario_e_fingerprint_survives_boundary()
    print("  [PASS Scenario E] [REAL] Fingerprint survives service boundary.")

    test_scenario_f_candidate_initial_state()
    print("  [PASS Scenario F] [REAL] Candidate starts in CANDIDATE state.")

    test_scenario_g_unsafe_flags_remain_false()
    print("  [PASS Scenario G] [REAL] Unsafe flags strictly False.")

    test_scenario_h_lifecycle_does_not_bypass_maryada()
    print("  [PASS Scenario H] [REAL] Lifecycle does not bypass MARYADA.")

    test_scenario_i_f14_cannot_directly_promote()
    print("  [PASS Scenario I] [REAL] F14 cannot directly promote.")

    test_scenario_j_full_lifecycle_compatibility()
    print("  [PASS Scenario J] [REAL] Full lifecycle compatibility & CHITRA auditing.")

    print("\n==================================================")
    print("ALL PHASE 18I-2 F14 INTEGRATION TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_phase18i_f14_integration_tests()
