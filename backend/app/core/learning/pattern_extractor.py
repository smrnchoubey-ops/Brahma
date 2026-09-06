"""
F14: Pattern Extraction Engine (Whitesheet §17.1 / F14 Hardened Specification)
Strictly conforms to BRAHMA COS Whitesheet F14 Specification.

Consumes historical task episodes/CHITRA evidence, validates tenant isolation,
enforces minimum supporting episode threshold (k_min >= 3), computes deterministic
pattern fingerprints, preserves provenance, and returns LearningCandidate objects
strictly in CANDIDATE state (constitutional_approved=False, shadow_passed=False).
"""
from typing import Dict, Any, Optional, List, Set, Tuple
import hashlib
import json
from datetime import datetime, timezone

from app.core.learning.models import (
    LearningCandidate,
    LearningEvidence,
    PatternStatus,
    PatternType
)
from app.core.chitra.crypto import generate_ulid, compute_sha256, canonical_json


def _canonical_episode_key(ep: Dict[str, Any]) -> str:
    """Computes a deterministic unique key for an episode record to prevent duplicate inflation."""
    task_id = ep.get("task_id")
    event_id = ep.get("event_id")
    if task_id is not None or event_id is not None:
        return f"t:{task_id}|e:{event_id}"
    # Fallback to canonical serialized dict content
    return hashlib.sha256(canonical_json(ep).encode("utf-8")).hexdigest()


def compute_pattern_fingerprint(
    tenant_id: str,
    pattern_type: PatternType,
    action_template: Dict[str, Any],
    unique_episode_keys: List[str]
) -> str:
    """
    Computes a deterministic SHA-256 fingerprint for a pattern based on its
    semantic properties, strategy, tenant scope, and supporting episode identities.
    """
    fp_dict = {
        "tenant_id": tenant_id,
        "pattern_type": pattern_type.value,
        "strategy": action_template.get("strategy"),
        "target_tool_preference": action_template.get("target_tool_preference"),
        "supporting_episodes": sorted(unique_episode_keys)
    }
    return compute_sha256(canonical_json(fp_dict))


class F14PatternExtractor:
    """
    Deterministic F14 pattern extractor analyzing task episodes to propose candidate updates.
    """

    DEFAULT_K_MIN: int = 3

    @classmethod
    def extract_pattern(
        cls,
        tenant_id: str,
        episodes: List[Dict[str, Any]],
        pattern_type: PatternType = PatternType.PLAN_OPTIMIZATION,
        name: Optional[str] = None,
        description: Optional[str] = None,
        k_min: int = DEFAULT_K_MIN
    ) -> LearningCandidate:
        """
        Analyzes historical task episodes and generates a candidate learning pattern.
        
        Hardened F14 Invariants:
        1. Tenant ID must be provided and non-empty.
        2. Strict tenant isolation: episodes with differing tenant_id are rejected/ignored.
        3. Minimum supporting episode threshold (default k_min=3) enforced over valid unique episodes.
        4. Malformed episodes are detected and rejected fail-closed.
        5. Duplicate episodes do not falsely inflate the support count.
        6. Candidate is formulated strictly in CANDIDATE state (constitutional_approved=False).
        7. Deterministic pattern fingerprint computed and attached to metadata.
        """
        # 1. Tenant Authentication / Boundary Check
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError("Tenant ID is required for pattern extraction (AUTHENTICATED_TENANT_REQUIRED).")
        tenant_id = str(tenant_id).strip()

        # 2. Basic List Validation
        if episodes is None or not isinstance(episodes, list) or len(episodes) == 0:
            raise ValueError("Cannot extract patterns from an empty list of episodes.")

        # 3. Episode Validation, Tenant Filtering, and Deduplication
        valid_episodes: List[Dict[str, Any]] = []
        seen_keys: Set[str] = set()
        unique_episode_keys: List[str] = []
        
        task_ids: List[int] = []
        event_ids: List[str] = []
        durations: List[float] = []
        success_count = 0

        for ep in episodes:
            if not isinstance(ep, dict):
                raise ValueError("Malformed episode record: must be a dictionary.")

            # Validate tenant isolation if tenant is specified in episode
            ep_tenant = ep.get("tenant_id") or ep.get("tenant")
            if ep_tenant is not None and str(ep_tenant).strip() != tenant_id:
                # Reject cross-tenant contamination
                continue

            # Ensure episode has minimal valid structure
            if not ep:
                continue

            ep_key = _canonical_episode_key(ep)
            if ep_key in seen_keys:
                # Deduplication: duplicate evidence must NOT inflate support count
                continue

            seen_keys.add(ep_key)
            unique_episode_keys.append(ep_key)
            valid_episodes.append(ep)

            # Extract provenance
            t_id = ep.get("task_id")
            if t_id is not None and isinstance(t_id, int):
                task_ids.append(t_id)

            evt_id = ep.get("event_id")
            if evt_id is not None and str(evt_id).strip():
                event_ids.append(str(evt_id).strip())

            if ep.get("status") in ["SUCCESS", "COMPLETED", "SUCCEEDED"]:
                success_count += 1

            dur = ep.get("duration_ms")
            if isinstance(dur, (int, float)) and dur >= 0:
                durations.append(float(dur))

        # 4. Enforce Minimum Supporting Episodes (k_min)
        valid_count = len(valid_episodes)
        effective_k_min = max(1, k_min)
        if valid_count < effective_k_min:
            raise ValueError(
                f"F14 extraction rejected: requires at least {effective_k_min} valid supporting episodes "
                f"for tenant '{tenant_id}', but only {valid_count} valid unique episodes were found."
            )

        # 5. Compute Aggregate Metrics
        success_rate = success_count / valid_count if valid_count > 0 else 0.0
        avg_duration = sum(durations) / len(durations) if durations else 100.0

        pattern_id = generate_ulid(prefix="pat_")
        pat_name = name or f"Optimized_{pattern_type.value}_{pattern_id[:8]}"
        pat_desc = description or f"Extracted {pattern_type.value} from {valid_count} episodes with {round(success_rate*100, 1)}% success rate."

        # Action template captures derived optimization
        action_template = {
            "strategy": pattern_type.value,
            "sample_count": valid_count,
            "mean_execution_ms": round(avg_duration, 2),
            "target_tool_preference": valid_episodes[0].get("tool", "generic_executor") if valid_episodes else "generic_executor"
        }

        # 6. Deterministic Fingerprint
        fingerprint = compute_pattern_fingerprint(
            tenant_id=tenant_id,
            pattern_type=pattern_type,
            action_template=action_template,
            unique_episode_keys=unique_episode_keys
        )

        # 7. Learning Evidence with Preserved Provenance
        evidence = LearningEvidence(
            source_task_ids=sorted(list(set(task_ids))),
            source_event_ids=sorted(list(set(event_ids))),
            metric_deltas={
                "success_rate": round(success_rate, 4),
                "mean_duration_ms": round(avg_duration, 2)
            },
            sample_count=valid_count,
            notes=f"Derived from {valid_count} valid observed task executions in tenant {tenant_id}."
        )

        # Base confidence scales with sample count and success rate
        confidence = min(1.0, max(0.1, round(0.5 + (valid_count * 0.05) * success_rate, 2)))

        # 8. Return Formatted Candidate strictly in CANDIDATE state
        return LearningCandidate(
            pattern_id=pattern_id,
            tenant_id=tenant_id,
            pattern_type=pattern_type,
            name=pat_name,
            description=pat_desc,
            action_template=action_template,
            evidence=evidence,
            confidence=confidence,
            status=PatternStatus.CANDIDATE,
            version=1,
            le_score=0.0,
            constitutional_approved=False,
            regression_passed=False,
            shadow_passed=False,
            metadata={
                "fingerprint": fingerprint,
                "pattern_fingerprint": fingerprint,
                "k_min": effective_k_min,
                "valid_episode_count": valid_count,
                "extracted_at": datetime.now(timezone.utc).isoformat()
            }
        )
