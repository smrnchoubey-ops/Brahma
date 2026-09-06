"""
LEARNING SYSTEM Phase 18I-1 Dedicated Test Suite: F14 Pattern Extraction Hardening
Strictly tests Whitesheet F14 requirements across all mandated scenarios A through N.
"""
import pytest
from datetime import datetime, timezone

from app.core.learning.models import (
    PatternStatus,
    PatternType,
    LearningCandidate,
    LearningEvidence
)
from app.core.learning.pattern_extractor import (
    F14PatternExtractor,
    compute_pattern_fingerprint
)
from app.core.learning.service import LearningService


# -------------------------------------------------------------
# SCENARIO A, B, C: REJECTION OF INSUFFICIENT EPISODES (< 3)
# -------------------------------------------------------------

def test_scenario_a_zero_episodes_rejected():
    with pytest.raises(ValueError, match="empty list of episodes"):
        F14PatternExtractor.extract_pattern("tenant_alpha", [])


def test_scenario_b_one_episode_rejected():
    episodes = [
        {"task_id": 101, "event_id": "evt_101", "status": "SUCCESS", "duration_ms": 120.0}
    ]
    with pytest.raises(ValueError, match="requires at least 3 valid supporting episodes"):
        F14PatternExtractor.extract_pattern("tenant_alpha", episodes)


def test_scenario_c_two_episodes_rejected():
    episodes = [
        {"task_id": 101, "event_id": "evt_101", "status": "SUCCESS", "duration_ms": 120.0},
        {"task_id": 102, "event_id": "evt_102", "status": "SUCCESS", "duration_ms": 110.0}
    ]
    with pytest.raises(ValueError, match="requires at least 3 valid supporting episodes"):
        F14PatternExtractor.extract_pattern("tenant_alpha", episodes)


# -------------------------------------------------------------
# SCENARIO D, E: VALID EXTRACTION AT k_min >= 3
# -------------------------------------------------------------

def test_scenario_d_exactly_three_valid_episodes_accepted():
    episodes = [
        {"task_id": 101, "event_id": "evt_101", "status": "SUCCESS", "duration_ms": 100.0, "tool": "calc"},
        {"task_id": 102, "event_id": "evt_102", "status": "SUCCESS", "duration_ms": 110.0, "tool": "calc"},
        {"task_id": 103, "event_id": "evt_103", "status": "SUCCESS", "duration_ms": 120.0, "tool": "calc"}
    ]
    candidate = F14PatternExtractor.extract_pattern(
        tenant_id="tenant_alpha",
        episodes=episodes,
        pattern_type=PatternType.PLAN_OPTIMIZATION
    )
    assert candidate.pattern_id.startswith("pat_")
    assert candidate.tenant_id == "tenant_alpha"
    assert candidate.evidence.sample_count == 3
    assert candidate.status == PatternStatus.CANDIDATE
    assert "fingerprint" in candidate.metadata


def test_scenario_e_four_plus_valid_episodes_accepted():
    episodes = [
        {"task_id": 101, "event_id": "evt_101", "status": "SUCCESS", "duration_ms": 100.0},
        {"task_id": 102, "event_id": "evt_102", "status": "SUCCESS", "duration_ms": 110.0},
        {"task_id": 103, "event_id": "evt_103", "status": "SUCCESS", "duration_ms": 120.0},
        {"task_id": 104, "event_id": "evt_104", "status": "SUCCESS", "duration_ms": 130.0},
        {"task_id": 105, "event_id": "evt_105", "status": "SUCCESS", "duration_ms": 140.0}
    ]
    candidate = LearningService.extract_pattern(
        tenant_id="tenant_alpha",
        episodes=episodes,
        pattern_type=PatternType.TOOL_ROUTING
    )
    assert candidate.evidence.sample_count == 5
    assert candidate.confidence >= 0.6


# -------------------------------------------------------------
# SCENARIO F: MALFORMED EPISODE HANDLING
# -------------------------------------------------------------

def test_scenario_f_malformed_episode_rejection():
    # Non-dictionary episode in list
    with pytest.raises(ValueError, match="Malformed episode record"):
        F14PatternExtractor.extract_pattern("tenant_alpha", ["not_a_dict", 12345])

    # None episode in list
    with pytest.raises(ValueError, match="Malformed episode record"):
        F14PatternExtractor.extract_pattern("tenant_alpha", [None, None, None])


# -------------------------------------------------------------
# SCENARIO G: TENANT ISOLATION
# -------------------------------------------------------------

def test_scenario_g_mixed_tenant_episodes_isolated():
    # 2 episodes for tenant_alpha, 2 episodes for tenant_beta
    episodes = [
        {"task_id": 201, "event_id": "evt_201", "tenant_id": "tenant_alpha", "status": "SUCCESS"},
        {"task_id": 202, "event_id": "evt_202", "tenant_id": "tenant_alpha", "status": "SUCCESS"},
        {"task_id": 203, "event_id": "evt_203", "tenant_id": "tenant_beta", "status": "SUCCESS"},
        {"task_id": 204, "event_id": "evt_204", "tenant_id": "tenant_beta", "status": "SUCCESS"}
    ]
    # When extracting for tenant_alpha, tenant_beta episodes are excluded -> only 2 remain -> rejected for < 3!
    with pytest.raises(ValueError, match="requires at least 3 valid supporting episodes"):
        F14PatternExtractor.extract_pattern("tenant_alpha", episodes)

    # Adding a 3rd episode for tenant_alpha succeeds and preserves strict tenant scope
    episodes.append({"task_id": 205, "event_id": "evt_205", "tenant_id": "tenant_alpha", "status": "SUCCESS"})
    candidate = F14PatternExtractor.extract_pattern("tenant_alpha", episodes)
    assert candidate.tenant_id == "tenant_alpha"
    assert candidate.evidence.sample_count == 3
    assert 203 not in candidate.evidence.source_task_ids
    assert 204 not in candidate.evidence.source_task_ids


# -------------------------------------------------------------
# SCENARIO H: SUPPORTING TASK/EVENT PROVENANCE PRESERVED
# -------------------------------------------------------------

def test_scenario_h_provenance_preservation():
    episodes = [
        {"task_id": 301, "event_id": "evt_prov_1", "status": "SUCCESS", "duration_ms": 50.0},
        {"task_id": 302, "event_id": "evt_prov_2", "status": "SUCCESS", "duration_ms": 60.0},
        {"task_id": 303, "event_id": "evt_prov_3", "status": "SUCCESS", "duration_ms": 70.0}
    ]
    candidate = F14PatternExtractor.extract_pattern("tenant_alpha", episodes)
    assert candidate.evidence.source_task_ids == [301, 302, 303]
    assert candidate.evidence.source_event_ids == ["evt_prov_1", "evt_prov_2", "evt_prov_3"]
    assert candidate.evidence.sample_count == 3
    assert candidate.evidence.metric_deltas["mean_duration_ms"] == 60.0


# -------------------------------------------------------------
# SCENARIO I: DETERMINISTIC FINGERPRINT FOR IDENTICAL INPUTS
# -------------------------------------------------------------

def test_scenario_i_deterministic_fingerprint():
    episodes = [
        {"task_id": 401, "event_id": "evt_fp_1", "status": "SUCCESS", "duration_ms": 100.0, "tool": "search"},
        {"task_id": 402, "event_id": "evt_fp_2", "status": "SUCCESS", "duration_ms": 100.0, "tool": "search"},
        {"task_id": 403, "event_id": "evt_fp_3", "status": "SUCCESS", "duration_ms": 100.0, "tool": "search"}
    ]
    c1 = F14PatternExtractor.extract_pattern("tenant_alpha", episodes, pattern_type=PatternType.PLAN_OPTIMIZATION)
    c2 = F14PatternExtractor.extract_pattern("tenant_alpha", episodes, pattern_type=PatternType.PLAN_OPTIMIZATION)

    # pattern_ids are unique ULIDs
    assert c1.pattern_id != c2.pattern_id
    # But fingerprints must be 100% identical and deterministic
    fp1 = c1.metadata["fingerprint"]
    fp2 = c2.metadata["fingerprint"]
    assert fp1 == fp2
    assert fp1.startswith("sha256:")
    assert len(fp1.split("sha256:")[1]) == 64


# -------------------------------------------------------------
# SCENARIO J, K, L, M: WHITESHEET F14 SEMANTICS & SAFETY
# -------------------------------------------------------------

def test_scenario_j_candidate_status_invariant():
    episodes = [
        {"task_id": 501, "event_id": "evt_501", "status": "SUCCESS"},
        {"task_id": 502, "event_id": "evt_502", "status": "SUCCESS"},
        {"task_id": 503, "event_id": "evt_503", "status": "SUCCESS"}
    ]
    candidate = F14PatternExtractor.extract_pattern("tenant_alpha", episodes)
    assert candidate.status == PatternStatus.CANDIDATE


def test_scenario_k_constitutional_approved_is_strictly_false():
    episodes = [
        {"task_id": 601, "event_id": "evt_601", "status": "SUCCESS"},
        {"task_id": 602, "event_id": "evt_602", "status": "SUCCESS"},
        {"task_id": 603, "event_id": "evt_603", "status": "SUCCESS"}
    ]
    candidate = F14PatternExtractor.extract_pattern("tenant_alpha", episodes)
    assert candidate.constitutional_approved is False


def test_scenario_l_regression_shadow_fields_strictly_false():
    episodes = [
        {"task_id": 701, "event_id": "evt_701", "status": "SUCCESS"},
        {"task_id": 702, "event_id": "evt_702", "status": "SUCCESS"},
        {"task_id": 703, "event_id": "evt_703", "status": "SUCCESS"}
    ]
    candidate = F14PatternExtractor.extract_pattern("tenant_alpha", episodes)
    assert candidate.regression_passed is False
    assert candidate.shadow_passed is False
    assert candidate.le_score == 0.0
    assert candidate.promoted_at is None


def test_scenario_m_no_constitutional_mutation():
    # Attempting to extract pattern with dangerous action does NOT auto-promote or mutate rules
    episodes = [
        {"task_id": 801, "event_id": "evt_801", "status": "SUCCESS"},
        {"task_id": 802, "event_id": "evt_802", "status": "SUCCESS"},
        {"task_id": 803, "event_id": "evt_803", "status": "SUCCESS"}
    ]
    candidate = F14PatternExtractor.extract_pattern(
        tenant_id="tenant_alpha",
        episodes=episodes,
        pattern_type=PatternType.HEURISTIC_RULE,
        name="rm -rf /root"
    )
    assert candidate.status == PatternStatus.CANDIDATE
    assert candidate.constitutional_approved is False


# -------------------------------------------------------------
# SCENARIO N: DUPLICATE EVIDENCE CANNOT FALSELY INFLATE COUNT
# -------------------------------------------------------------

def test_scenario_n_duplicate_evidence_deduplication():
    # 3 identical copies of the exact same episode
    duplicate_episodes = [
        {"task_id": 999, "event_id": "evt_same", "status": "SUCCESS"},
        {"task_id": 999, "event_id": "evt_same", "status": "SUCCESS"},
        {"task_id": 999, "event_id": "evt_same", "status": "SUCCESS"}
    ]
    # Unique count is only 1 < 3 -> must be rejected!
    with pytest.raises(ValueError, match="requires at least 3 valid supporting episodes"):
        F14PatternExtractor.extract_pattern("tenant_alpha", duplicate_episodes)


def run_all_phase18i_f14_tests():
    print("==================================================")
    print("LEARNING SYSTEM PHASE 18I-1: F14 PATTERN EXTRACTION HARDENING")
    print("Whitesheet F14 Comprehensive Scenario Suite (A - N)")
    print("==================================================")

    test_scenario_a_zero_episodes_rejected()
    print("  [PASS Scenario A] [REAL] 0 episodes rejected.")

    test_scenario_b_one_episode_rejected()
    print("  [PASS Scenario B] [REAL] 1 episode rejected (k_min < 3).")

    test_scenario_c_two_episodes_rejected()
    print("  [PASS Scenario C] [REAL] 2 episodes rejected (k_min < 3).")

    test_scenario_d_exactly_three_valid_episodes_accepted()
    print("  [PASS Scenario D] [REAL] Exactly 3 valid episodes accepted.")

    test_scenario_e_four_plus_valid_episodes_accepted()
    print("  [PASS Scenario E] [REAL] 4+ valid episodes accepted.")

    test_scenario_f_malformed_episode_rejection()
    print("  [PASS Scenario F] [REAL] Malformed episode records rejected fail-closed.")

    test_scenario_g_mixed_tenant_episodes_isolated()
    print("  [PASS Scenario G] [REAL] Strict tenant isolation enforced.")

    test_scenario_h_provenance_preservation()
    print("  [PASS Scenario H] [REAL] Task/event provenance preserved.")

    test_scenario_i_deterministic_fingerprint()
    print("  [PASS Scenario I] [REAL] Deterministic fingerprint verified.")

    test_scenario_j_candidate_status_invariant()
    print("  [PASS Scenario J] [REAL] Candidate status invariant preserved.")

    test_scenario_k_constitutional_approved_is_strictly_false()
    print("  [PASS Scenario K] [REAL] constitutional_approved is False.")

    test_scenario_l_regression_shadow_fields_strictly_false()
    print("  [PASS Scenario L] [REAL] Regression/shadow flags are False.")

    test_scenario_m_no_constitutional_mutation()
    print("  [PASS Scenario M] [REAL] No constitutional mutation.")

    test_scenario_n_duplicate_evidence_deduplication()
    print("  [PASS Scenario N] [REAL] Duplicate evidence deduplication enforced.")

    print("\n==================================================")
    print("ALL PHASE 18I-1 F14 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_phase18i_f14_tests()
