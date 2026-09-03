"""
FEDERATION CONFLICT RESOLUTION & CONVERGENCE (Whitesheet §18.4)
Deterministic version-vector tracking, causality comparison, LE-score quality weighting,
and deterministic LWW fallback ensuring eventual consistency across federated nodes.
"""
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class VectorComparison(str, Enum):
    EQUAL = "EQUAL"
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    CONCURRENT = "CONCURRENT"


class VersionVector(BaseModel):
    """
    Deterministic Version Vector mapping node_id -> monotonically increasing logical clock counter.
    """
    counters: Dict[str, int] = Field(default_factory=dict)

    def increment(self, node_id: str) -> "VersionVector":
        """Increments the logical counter for a given node_id."""
        if not node_id or not node_id.strip():
            raise ValueError("node_id is required to increment version vector.")
        clean_id = node_id.strip()
        new_counters = dict(self.counters)
        new_counters[clean_id] = new_counters.get(clean_id, 0) + 1
        return VersionVector(counters=new_counters)

    def get(self, node_id: str) -> int:
        return self.counters.get(node_id.strip(), 0)

    def merge(self, other: "VersionVector") -> "VersionVector":
        """Component-wise maximum across all known node IDs."""
        all_keys = set(self.counters.keys()) | set(other.counters.keys())
        merged = {}
        for k in all_keys:
            merged[k] = max(self.counters.get(k, 0), other.counters.get(k, 0))
        return VersionVector(counters=merged)

    def compare(self, other: "VersionVector") -> VectorComparison:
        """
        Compares this vector (A) against another vector (B).
        - EQUAL: for all k, A[k] == B[k]
        - BEFORE: for all k, A[k] <= B[k] and exists k such that A[k] < B[k]
        - AFTER: for all k, A[k] >= B[k] and exists k such that A[k] > B[k]
        - CONCURRENT: otherwise
        """
        all_keys = set(self.counters.keys()) | set(other.counters.keys())
        has_greater = False
        has_lesser = False

        for k in all_keys:
            v_a = self.counters.get(k, 0)
            v_b = other.counters.get(k, 0)
            if v_a > v_b:
                has_greater = True
            elif v_a < v_b:
                has_lesser = True

        if not has_greater and not has_lesser:
            return VectorComparison.EQUAL
        if has_lesser and not has_greater:
            return VectorComparison.BEFORE
        if has_greater and not has_lesser:
            return VectorComparison.AFTER
        return VectorComparison.CONCURRENT


class FederatedVersionedRecord(BaseModel):
    """
    Standardized container for versioned federated knowledge/pattern items.
    """
    entity_id: str
    tenant_id: str
    origin_node_id: str
    version_vector: VersionVector
    payload: Dict[str, Any]
    le_score: Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    federated_status: str = "STAGED_FOR_LOCAL_EVALUATION"
    provenance: Dict[str, Any] = Field(default_factory=dict)
    allowed_target_tenants: List[str] = Field(default_factory=list)


class ConflictResolutionEngine:
    """
    Deterministic resolution engine implementing Whitesheet §18.4 conflict resolution rules.
    """

    @classmethod
    def resolve_records(
        cls,
        record_a: FederatedVersionedRecord,
        record_b: FederatedVersionedRecord,
        local_tenant_id: str
    ) -> Tuple[FederatedVersionedRecord, str]:
        """
        Deterministically resolves conflict between two federated records.
        Returns: (winning_record, resolution_reason)

        Resolution Hierarchy:
        1. Tenant boundaries (fail-closed if cross-tenant unauthorized).
        2. Version Vector causality (AFTER wins).
        3. If CONCURRENT: Learning Effectiveness (LE) score quality weighting.
        4. If LE equal/absent: Deterministic Last-Write-Wins (timestamp > origin_node_id > entity_id).
        """
        # 1. Tenant boundary validation (§18.5)
        if not record_a.tenant_id or not record_b.tenant_id or not local_tenant_id:
            raise ValueError("Tenant ID is required for all records in conflict resolution (FAIL-CLOSED).")

        # Check tenant compatibility
        a_allowed = (record_a.tenant_id == local_tenant_id) or (local_tenant_id in record_a.allowed_target_tenants)
        b_allowed = (record_b.tenant_id == local_tenant_id) or (local_tenant_id in record_b.allowed_target_tenants)

        if not a_allowed or not b_allowed:
            raise ValueError(
                f"Cross-tenant conflict resolution rejected: record_a ('{record_a.tenant_id}') or "
                f"record_b ('{record_b.tenant_id}') not permitted for local tenant '{local_tenant_id}'."
            )

        if record_a.entity_id != record_b.entity_id:
            raise ValueError(
                f"Cannot resolve conflict for differing entity IDs: '{record_a.entity_id}' != '{record_b.entity_id}'."
            )

        # 2. Version Vector causality check
        comparison = record_a.version_vector.compare(record_b.version_vector)
        merged_vector = record_a.version_vector.merge(record_b.version_vector)

        if comparison == VectorComparison.EQUAL:
            # Identical vector clocks -> deterministic LWW tie-break
            winner, reason = cls._deterministic_lww_tiebreak(record_a, record_b)
            return cls._apply_merged_vector(winner, merged_vector), f"EQUAL_VECTOR_TIEBREAK: {reason}"

        if comparison == VectorComparison.AFTER:
            # record_a dominates causally
            return cls._apply_merged_vector(record_a, merged_vector), "CAUSAL_DOMINANCE_A"

        if comparison == VectorComparison.BEFORE:
            # record_b dominates causally
            return cls._apply_merged_vector(record_b, merged_vector), "CAUSAL_DOMINANCE_B"

        # 3. CONCURRENT conflict resolution (§18.4)
        # Priority 1: LE-score weighting
        le_a = cls._sanitize_le_score(record_a.le_score)
        le_b = cls._sanitize_le_score(record_b.le_score)

        if le_a is not None and le_b is not None:
            if abs(le_a - le_b) > 1e-6:
                if le_a > le_b:
                    return cls._apply_merged_vector(record_a, merged_vector), f"LE_SCORE_WEIGHTING_A (LE {le_a:.4f} > {le_b:.4f})"
                else:
                    return cls._apply_merged_vector(record_b, merged_vector), f"LE_SCORE_WEIGHTING_B (LE {le_b:.4f} > {le_a:.4f})"
        elif le_a is not None and le_b is None:
            return cls._apply_merged_vector(record_a, merged_vector), "LE_SCORE_PRESENCE_A"
        elif le_b is not None and le_a is None:
            return cls._apply_merged_vector(record_b, merged_vector), "LE_SCORE_PRESENCE_B"

        # Priority 2: Deterministic LWW Fallback
        winner, reason = cls._deterministic_lww_tiebreak(record_a, record_b)
        return cls._apply_merged_vector(winner, merged_vector), f"CONCURRENT_LWW: {reason}"

    @classmethod
    def _sanitize_le_score(cls, score: Optional[float]) -> Optional[float]:
        if score is None:
            return None
        try:
            val = float(score)
            if val != val:  # NaN check
                return None
            return val
        except (ValueError, TypeError):
            return None

    @classmethod
    def _deterministic_lww_tiebreak(
        cls,
        rec_a: FederatedVersionedRecord,
        rec_b: FederatedVersionedRecord
    ) -> Tuple[FederatedVersionedRecord, str]:
        """
        Deterministic tie-break invariant:
        1. Higher timestamp string (ISO-8601 UTC)
        2. Lexicographically greater origin_node_id
        3. Stable comparison of entity_id
        """
        # Timestamp comparison
        if rec_a.timestamp != rec_b.timestamp:
            if rec_a.timestamp > rec_b.timestamp:
                return rec_a, "TIMESTAMP_A_WINS"
            else:
                return rec_b, "TIMESTAMP_B_WINS"

        # Node ID comparison
        if rec_a.origin_node_id != rec_b.origin_node_id:
            if rec_a.origin_node_id > rec_b.origin_node_id:
                return rec_a, "NODE_ID_A_WINS"
            else:
                return rec_b, "NODE_ID_B_WINS"

        # Default stable choice
        return rec_a, "IDENTICAL_TIEBREAK_DEFAULT_A"

    @classmethod
    def _apply_merged_vector(
        cls,
        winner: FederatedVersionedRecord,
        merged_vector: VersionVector
    ) -> FederatedVersionedRecord:
        """
        Returns a copy of the winning record with the unified merged version vector,
        preserving original provenance and STAGED status.
        """
        return winner.model_copy(update={
            "version_vector": merged_vector,
            "federated_status": "STAGED_FOR_LOCAL_EVALUATION"
        })

    @classmethod
    def resolve_set(
        cls,
        records: List[FederatedVersionedRecord],
        local_tenant_id: str
    ) -> Optional[FederatedVersionedRecord]:
        """
        Deterministically resolves a set of conflicting records for the same entity into a single winner,
        guaranteeing convergence regardless of the order of input records.
        """
        if not records:
            return None
        if len(records) == 1:
            return records[0].model_copy()

        # Sort initially by deterministic criteria to guarantee commutativity and associativity
        sorted_records = sorted(
            records,
            key=lambda r: (r.timestamp, r.origin_node_id, r.le_score if r.le_score is not None else -1.0)
        )

        current_winner = sorted_records[0]
        for candidate in sorted_records[1:]:
            current_winner, _ = cls.resolve_records(current_winner, candidate, local_tenant_id)

        return current_winner
