"""
FEDERATION SYSTEM Phase 18D Dedicated Test Suite: Conflict Resolution & Convergence
Strictly tests Whitesheet §18.4 requirements across 25 explicit scenarios.
"""
import pytest
import itertools
from datetime import datetime, timezone

from app.core.federation.models import TrustTier, FederationPayloadType
from app.core.federation.conflict import (
    VersionVector,
    VectorComparison,
    FederatedVersionedRecord,
    ConflictResolutionEngine
)


# -------------------------------------------------------------
# 1. VERSION VECTOR TESTS (1-7)
# -------------------------------------------------------------

def test_1_version_vector_initialization():
    vv = VersionVector()
    assert len(vv.counters) == 0
    assert vv.get("node_a") == 0


def test_2_vector_increment():
    vv = VersionVector()
    vv1 = vv.increment("node_a")
    vv2 = vv1.increment("node_a")
    vv3 = vv2.increment("node_b")
    assert vv3.get("node_a") == 2
    assert vv3.get("node_b") == 1
    assert vv3.get("node_c") == 0


def test_3_vector_merge():
    vv_a = VersionVector(counters={"node_a": 2, "node_b": 1})
    vv_b = VersionVector(counters={"node_a": 1, "node_b": 4, "node_c": 3})
    merged = vv_a.merge(vv_b)
    assert merged.get("node_a") == 2
    assert merged.get("node_b") == 4
    assert merged.get("node_c") == 3


def test_4_equal_vectors():
    vv1 = VersionVector(counters={"node_a": 2, "node_b": 1})
    vv2 = VersionVector(counters={"node_a": 2, "node_b": 1})
    assert vv1.compare(vv2) == VectorComparison.EQUAL


def test_5_before_comparison():
    vv_old = VersionVector(counters={"node_a": 1, "node_b": 1})
    vv_new = VersionVector(counters={"node_a": 2, "node_b": 1})
    assert vv_old.compare(vv_new) == VectorComparison.BEFORE


def test_6_after_comparison():
    vv_new = VersionVector(counters={"node_a": 2, "node_b": 2})
    vv_old = VersionVector(counters={"node_a": 2, "node_b": 1})
    assert vv_new.compare(vv_old) == VectorComparison.AFTER


def test_7_concurrent_comparison():
    # Node A advanced on node_a, Node B advanced on node_b
    vv_a = VersionVector(counters={"node_a": 2, "node_b": 1})
    vv_b = VersionVector(counters={"node_a": 1, "node_b": 2})
    assert vv_a.compare(vv_b) == VectorComparison.CONCURRENT


# -------------------------------------------------------------
# 2. CONFLICT DETECTION & CAUSAL RESOLUTION (8-10)
# -------------------------------------------------------------

def test_8_causal_conflict_detection():
    # Causal dominance: descendant version must win
    rec_old = FederatedVersionedRecord(
        entity_id="pat_001",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 1}),
        payload={"param": 10},
        timestamp="2026-09-03T10:00:00Z"
    )
    rec_new = FederatedVersionedRecord(
        entity_id="pat_001",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2}),
        payload={"param": 20},
        timestamp="2026-09-03T10:05:00Z"
    )
    winner, reason = ConflictResolutionEngine.resolve_records(rec_old, rec_new, "tenant_alice")
    assert winner.payload["param"] == 20
    assert "CAUSAL_DOMINANCE" in reason
    assert winner.version_vector.get("node_a") == 2


def test_9_concurrent_conflict_detection():
    rec_a = FederatedVersionedRecord(
        entity_id="pat_002",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2, "node_b": 1}),
        payload={"value": "from_a"},
        le_score=0.90,
        timestamp="2026-09-03T10:00:00Z"
    )
    rec_b = FederatedVersionedRecord(
        entity_id="pat_002",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_a": 1, "node_b": 2}),
        payload={"value": "from_b"},
        le_score=0.75,
        timestamp="2026-09-03T10:00:00Z"
    )
    assert rec_a.version_vector.compare(rec_b.version_vector) == VectorComparison.CONCURRENT


def test_10_same_record_identification():
    # Differing entity IDs cannot be resolved together
    rec1 = FederatedVersionedRecord(
        entity_id="pat_alpha",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(),
        payload={}
    )
    rec2 = FederatedVersionedRecord(
        entity_id="pat_beta",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(),
        payload={}
    )
    with pytest.raises(ValueError, match="Cannot resolve conflict for differing entity IDs"):
        ConflictResolutionEngine.resolve_records(rec1, rec2, "tenant_alice")


# -------------------------------------------------------------
# 3. LE SCORE & LWW RESOLUTION (11-16)
# -------------------------------------------------------------

def test_11_higher_le_wins_concurrent_conflict():
    rec_high = FederatedVersionedRecord(
        entity_id="pat_003",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2, "node_b": 1}),
        payload={"strategy": "superior"},
        le_score=0.94,
        timestamp="2026-09-03T10:00:00Z"
    )
    rec_low = FederatedVersionedRecord(
        entity_id="pat_003",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_a": 1, "node_b": 2}),
        payload={"strategy": "inferior"},
        le_score=0.62,
        timestamp="2026-09-03T10:05:00Z"  # Even though rec_low has higher timestamp, LE score dominates
    )
    winner, reason = ConflictResolutionEngine.resolve_records(rec_high, rec_low, "tenant_alice")
    assert winner.payload["strategy"] == "superior"
    assert "LE_SCORE_WEIGHTING" in reason


def test_12_lower_le_loses_concurrent_conflict():
    rec_low = FederatedVersionedRecord(
        entity_id="pat_004",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2, "node_b": 1}),
        payload={"v": 1},
        le_score=0.50
    )
    rec_high = FederatedVersionedRecord(
        entity_id="pat_004",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_a": 1, "node_b": 2}),
        payload={"v": 2},
        le_score=0.85
    )
    winner, _ = ConflictResolutionEngine.resolve_records(rec_low, rec_high, "tenant_alice")
    assert winner.payload["v"] == 2


def test_13_equal_le_deterministic_fallback():
    # If LE scores are equal, LWW timestamp fallback takes precedence
    rec1 = FederatedVersionedRecord(
        entity_id="pat_005",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2, "node_b": 1}),
        payload={"author": "node_a"},
        le_score=0.80,
        timestamp="2026-09-03T11:00:00Z"
    )
    rec2 = FederatedVersionedRecord(
        entity_id="pat_005",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_a": 1, "node_b": 2}),
        payload={"author": "node_b"},
        le_score=0.80,
        timestamp="2026-09-03T11:05:00Z"  # Higher timestamp wins
    )
    winner, reason = ConflictResolutionEngine.resolve_records(rec1, rec2, "tenant_alice")
    assert winner.payload["author"] == "node_b"
    assert "TIMESTAMP_B_WINS" in reason


def test_14_missing_le_deterministic_fallback():
    # If LE is missing from one or both, fallback operates gracefully
    rec1 = FederatedVersionedRecord(
        entity_id="pat_006",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2, "node_b": 1}),
        payload={"val": "a"},
        le_score=None,
        timestamp="2026-09-03T12:00:00Z"
    )
    rec2 = FederatedVersionedRecord(
        entity_id="pat_006",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_a": 1, "node_b": 2}),
        payload={"val": "b"},
        le_score=None,
        timestamp="2026-09-03T12:10:00Z"
    )
    winner, reason = ConflictResolutionEngine.resolve_records(rec1, rec2, "tenant_alice")
    assert winner.payload["val"] == "b"


def test_15_timestamp_tie_deterministic_resolution():
    # Equal vector, equal LE, equal timestamp -> node_id lexicographical tie-break
    rec_a = FederatedVersionedRecord(
        entity_id="pat_007",
        tenant_id="tenant_alice",
        origin_node_id="node_alpha",
        version_vector=VersionVector(counters={"node_alpha": 1, "node_zeta": 1}),
        payload={"name": "alpha"},
        le_score=0.75,
        timestamp="2026-09-03T12:00:00Z"
    )
    rec_z = FederatedVersionedRecord(
        entity_id="pat_007",
        tenant_id="tenant_alice",
        origin_node_id="node_zeta",
        version_vector=VersionVector(counters={"node_alpha": 1, "node_zeta": 1}),
        payload={"name": "zeta"},
        le_score=0.75,
        timestamp="2026-09-03T12:00:00Z"
    )
    winner, reason = ConflictResolutionEngine.resolve_records(rec_a, rec_z, "tenant_alice")
    assert winner.payload["name"] == "zeta"  # 'node_zeta' > 'node_alpha'
    assert "NODE_ID" in reason


def test_16_node_id_deterministic_tie_break():
    rec1 = FederatedVersionedRecord(
        entity_id="pat_008",
        tenant_id="tenant_alice",
        origin_node_id="node_001",
        version_vector=VersionVector(counters={"n1": 1, "n2": 1}),
        payload={"node": "001"},
        timestamp="2026-09-03T12:00:00Z"
    )
    rec2 = FederatedVersionedRecord(
        entity_id="pat_008",
        tenant_id="tenant_alice",
        origin_node_id="node_002",
        version_vector=VersionVector(counters={"n1": 1, "n2": 1}),
        payload={"node": "002"},
        timestamp="2026-09-03T12:00:00Z"
    )
    winner, _ = ConflictResolutionEngine.resolve_records(rec1, rec2, "tenant_alice")
    assert winner.origin_node_id == "node_002"


# -------------------------------------------------------------
# 4. CONVERGENCE & IDEMPOTENCY (17-19)
# -------------------------------------------------------------

def test_17_arrival_order_independence():
    rec_a = FederatedVersionedRecord(
        entity_id="pat_009",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2, "node_b": 1}),
        payload={"x": 10},
        le_score=0.91,
        timestamp="2026-09-03T12:00:00Z"
    )
    rec_b = FederatedVersionedRecord(
        entity_id="pat_009",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_a": 1, "node_b": 2}),
        payload={"x": 20},
        le_score=0.70,
        timestamp="2026-09-03T12:05:00Z"
    )
    # Resolve (A, B) vs (B, A)
    win_ab, _ = ConflictResolutionEngine.resolve_records(rec_a, rec_b, "tenant_alice")
    win_ba, _ = ConflictResolutionEngine.resolve_records(rec_b, rec_a, "tenant_alice")
    assert win_ab.payload["x"] == win_ba.payload["x"]
    assert win_ab.version_vector.counters == win_ba.version_vector.counters


def test_18_permutation_convergence_test():
    # 4 distinct concurrent candidates
    records = [
        FederatedVersionedRecord(
            entity_id="pat_conv",
            tenant_id="tenant_alice",
            origin_node_id=f"node_{i}",
            version_vector=VersionVector(counters={f"node_{i}": 1}),
            payload={"opt_level": i},
            le_score=0.50 + (i * 0.1),
            timestamp=f"2026-09-03T12:0{i}:00Z"
        )
        for i in range(1, 5)
    ]

    expected_winner_id = 4  # Highest LE (0.90)

    # Test all 24 permutations (4!)
    for perm in itertools.permutations(records):
        winner = ConflictResolutionEngine.resolve_set(list(perm), "tenant_alice")
        assert winner is not None
        assert winner.payload["opt_level"] == expected_winner_id


def test_19_repeated_resolution_idempotency():
    rec_a = FederatedVersionedRecord(
        entity_id="pat_010",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2}),
        payload={"state": "A"}
    )
    rec_b = FederatedVersionedRecord(
        entity_id="pat_010",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_a": 1}),
        payload={"state": "B"}
    )

    win1, _ = ConflictResolutionEngine.resolve_records(rec_a, rec_b, "tenant_alice")
    win2, _ = ConflictResolutionEngine.resolve_records(rec_a, rec_b, "tenant_alice")
    win3, _ = ConflictResolutionEngine.resolve_records(win1, rec_b, "tenant_alice")

    assert win1.payload == win2.payload == win3.payload
    assert win1.version_vector.counters == win2.version_vector.counters == win3.version_vector.counters


# -------------------------------------------------------------
# 5. TENANT ISOLATION & PROVENANCE (20-25)
# -------------------------------------------------------------

def test_20_tenant_isolation():
    rec_alice = FederatedVersionedRecord(
        entity_id="pat_sec",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 1}),
        payload={"data": "alice_secret"}
    )
    rec_bob = FederatedVersionedRecord(
        entity_id="pat_sec",
        tenant_id="tenant_bob",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_b": 1}),
        payload={"data": "bob_secret"}
    )
    with pytest.raises(ValueError, match="Cross-tenant conflict resolution rejected"):
        ConflictResolutionEngine.resolve_records(rec_alice, rec_bob, "tenant_alice")


def test_21_cross_tenant_rejection_without_policy():
    rec1 = FederatedVersionedRecord(
        entity_id="pat_011",
        tenant_id="tenant_charlie",
        origin_node_id="node_c",
        version_vector=VersionVector(),
        payload={}
    )
    rec2 = FederatedVersionedRecord(
        entity_id="pat_011",
        tenant_id="tenant_david",
        origin_node_id="node_d",
        version_vector=VersionVector(),
        payload={}
    )
    with pytest.raises(ValueError, match="Cross-tenant conflict resolution rejected"):
        ConflictResolutionEngine.resolve_records(rec1, rec2, "tenant_charlie")


def test_22_missing_tenant_rejection():
    rec = FederatedVersionedRecord(
        entity_id="pat_012",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(),
        payload={}
    )
    rec_empty_tenant = FederatedVersionedRecord(
        entity_id="pat_012",
        tenant_id="",
        origin_node_id="node_b",
        version_vector=VersionVector(),
        payload={}
    )
    with pytest.raises(ValueError, match="Tenant ID is required"):
        ConflictResolutionEngine.resolve_records(rec, rec_empty_tenant, "tenant_alice")


def test_23_provenance_preservation():
    rec_a = FederatedVersionedRecord(
        entity_id="pat_013",
        tenant_id="tenant_alice",
        origin_node_id="node_origin_x",
        version_vector=VersionVector(counters={"node_origin_x": 2}),
        payload={"param": 100},
        provenance={"creator": "origin_x", "verified": True}
    )
    rec_b = FederatedVersionedRecord(
        entity_id="pat_013",
        tenant_id="tenant_alice",
        origin_node_id="node_origin_y",
        version_vector=VersionVector(counters={"node_origin_x": 1}),
        payload={"param": 50}
    )
    winner, _ = ConflictResolutionEngine.resolve_records(rec_a, rec_b, "tenant_alice")
    assert winner.origin_node_id == "node_origin_x"
    assert winner.provenance["creator"] == "origin_x"


def test_24_staged_status_preservation():
    rec_a = FederatedVersionedRecord(
        entity_id="pat_014",
        tenant_id="tenant_alice",
        origin_node_id="node_a",
        version_vector=VersionVector(counters={"node_a": 2}),
        payload={"act": "execute"},
        federated_status="STAGED_FOR_LOCAL_EVALUATION"
    )
    rec_b = FederatedVersionedRecord(
        entity_id="pat_014",
        tenant_id="tenant_alice",
        origin_node_id="node_b",
        version_vector=VersionVector(counters={"node_a": 1}),
        payload={"act": "wait"},
        federated_status="STAGED_FOR_LOCAL_EVALUATION"
    )
    winner, _ = ConflictResolutionEngine.resolve_records(rec_a, rec_b, "tenant_alice")
    assert winner.federated_status == "STAGED_FOR_LOCAL_EVALUATION"


def test_25_phase18a_18b_18c_boundary_protection():
    # Invariant: Phase 18A, 18B, and 18C types remain completely intact
    assert TrustTier.FEDERATED.value == "FEDERATED"
    assert FederationPayloadType.PATTERN_SYNC.value == "PATTERN_SYNC"


def run_all_25_phase18d_tests():
    print("==================================================")
    print("FEDERATION SYSTEM PHASE 18D: 25-SCENARIO SUITE")
    print("CONFLICT RESOLUTION & CONVERGENCE (§18.4)")
    print("==================================================")

    test_1_version_vector_initialization()
    print("  [PASS 1/25] [REAL] Version vector initialization (§18.4).")

    test_2_vector_increment()
    print("  [PASS 2/25] [REAL] Vector counter increment (§18.4).")

    test_3_vector_merge()
    print("  [PASS 3/25] [REAL] Vector merge operation (§18.4).")

    test_4_equal_vectors()
    print("  [PASS 4/25] [REAL] Equal vector comparison.")

    test_5_before_comparison()
    print("  [PASS 5/25] [REAL] BEFORE vector comparison.")

    test_6_after_comparison()
    print("  [PASS 6/25] [REAL] AFTER vector comparison.")

    test_7_concurrent_comparison()
    print("  [PASS 7/25] [REAL] CONCURRENT vector comparison (§18.4).")

    test_8_causal_conflict_detection()
    print("  [PASS 8/25] [REAL] Causal conflict dominance (§18.4).")

    test_9_concurrent_conflict_detection()
    print("  [PASS 9/25] [REAL] Concurrent conflict detection (§18.4).")

    test_10_same_record_identification()
    print("  [PASS 10/25] [REAL] Differing entity ID rejection fails closed.")

    test_11_higher_le_wins_concurrent_conflict()
    print("  [PASS 11/25] [REAL] Higher LE score quality weighting wins (§18.4).")

    test_12_lower_le_loses_concurrent_conflict()
    print("  [PASS 12/25] [REAL] Lower LE score quality weighting loses (§18.4).")

    test_13_equal_le_deterministic_fallback()
    print("  [PASS 13/25] [REAL] Equal LE score deterministic LWW fallback.")

    test_14_missing_le_deterministic_fallback()
    print("  [PASS 14/25] [REAL] Missing LE score deterministic fallback.")

    test_15_timestamp_tie_deterministic_resolution()
    print("  [PASS 15/25] [REAL] Timestamp tie-break deterministic resolution.")

    test_16_node_id_deterministic_tie_break()
    print("  [PASS 16/25] [REAL] Node ID deterministic tie-break.")

    test_17_arrival_order_independence()
    print("  [PASS 17/25] [REAL] Arrival-order independence.")

    test_18_permutation_convergence_test()
    print("  [PASS 18/25] [REAL] 24-permutation convergence verification (§18.4).")

    test_19_repeated_resolution_idempotency()
    print("  [PASS 19/25] [REAL] Repeated resolution idempotency.")

    test_20_tenant_isolation()
    print("  [PASS 20/25] [REAL] Tenant isolation preservation (§18.5).")

    test_21_cross_tenant_rejection_without_policy()
    print("  [PASS 21/25] [REAL] Cross-tenant rejection without policy fails closed.")

    test_22_missing_tenant_rejection()
    print("  [PASS 22/25] [REAL] Missing tenant rejection fails closed.")

    test_23_provenance_preservation()
    print("  [PASS 23/25] [REAL] Origin provenance preservation.")

    test_24_staged_status_preservation()
    print("  [PASS 24/25] [REAL] Staged status preservation invariant.")

    test_25_phase18a_18b_18c_boundary_protection()
    print("  [PASS 25/25] [REAL] Phase 18A, 18B & 18C boundary protection.")

    print("\n==================================================")
    print("ALL 25 PHASE 18D TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_25_phase18d_tests()
