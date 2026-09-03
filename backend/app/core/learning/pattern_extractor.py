"""
F14: Pattern Extraction Engine
Strictly conforms to BRAHMA COS Whitesheet F14 Specification.

Consumes historical episodes/CHITRA evidence, extracts recurring behavioral patterns,
preserves provenance, and formulates LearningCandidate objects in CANDIDATE state.
"""
from typing import Dict, Any, Optional, List
import hashlib
from datetime import datetime, timezone

from app.core.learning.models import (
    LearningCandidate,
    LearningEvidence,
    PatternStatus,
    PatternType
)
from app.core.chitra.crypto import generate_ulid


class F14PatternExtractor:
    """
    Deterministic pattern extractor analyzing task episodes to propose candidate updates.
    """

    @classmethod
    def extract_pattern(
        cls,
        tenant_id: str,
        episodes: List[Dict[str, Any]],
        pattern_type: PatternType = PatternType.PLAN_OPTIMIZATION,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> LearningCandidate:
        """
        Analyzes historical task episodes and generates a candidate learning pattern.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Tenant ID is required for pattern extraction (AUTHENTICATED_TENANT_REQUIRED).")

        if not episodes:
            raise ValueError("Cannot extract patterns from an empty list of episodes.")

        task_ids: List[int] = []
        event_ids: List[str] = []
        durations: List[float] = []
        success_count = 0

        for ep in episodes:
            if not isinstance(ep, dict):
                raise ValueError("Malformed episode record: must be a dictionary.")

            t_id = ep.get("task_id")
            if t_id and isinstance(t_id, int):
                task_ids.append(t_id)

            evt_id = ep.get("event_id")
            if evt_id:
                event_ids.append(str(evt_id))

            if ep.get("status") in ["SUCCESS", "COMPLETED", "SUCCEEDED"]:
                success_count += 1

            dur = ep.get("duration_ms")
            if isinstance(dur, (int, float)):
                durations.append(float(dur))

        sample_count = len(episodes)
        success_rate = success_count / sample_count if sample_count > 0 else 0.0
        avg_duration = sum(durations) / len(durations) if durations else 100.0

        pattern_id = generate_ulid(prefix="pat_")
        pat_name = name or f"Optimized_{pattern_type.value}_{pattern_id[:8]}"
        pat_desc = description or f"Extracted {pattern_type.value} from {sample_count} episodes with {round(success_rate*100, 1)}% success rate."

        # Action template captures derived optimization
        action_template = {
            "strategy": pattern_type.value,
            "sample_count": sample_count,
            "mean_execution_ms": round(avg_duration, 2),
            "target_tool_preference": episodes[0].get("tool", "generic_executor") if episodes else "generic_executor"
        }

        evidence = LearningEvidence(
            source_task_ids=list(set(task_ids)),
            source_event_ids=list(set(event_ids)),
            metric_deltas={"success_rate": round(success_rate, 4), "mean_duration_ms": round(avg_duration, 2)},
            sample_count=sample_count,
            notes=f"Derived from {sample_count} observed task executions in tenant {tenant_id}."
        )

        # Base confidence scales with sample count and success rate
        confidence = min(1.0, max(0.1, round(0.5 + (sample_count * 0.05) * success_rate, 2)))

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
            shadow_passed=False
        )
