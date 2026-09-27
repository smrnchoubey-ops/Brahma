"""
INCUMBENT HEURISTIC BASELINE POLICY (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Represents the incumbent baseline heuristic policy lookup.
Inherits from IncumbentBaselinePolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.policies.base import IncumbentBaselinePolicy
from agents.execution.registry import handle_policy_lookup


class IncumbentHeuristicBaselinePolicy(IncumbentBaselinePolicy):
    """
    Incumbent baseline heuristic policy lookup.
    """
    POLICY_ID: str = "policy:heuristic_rule:v1.0.0:incumbent_default"
    POLICY_VERSION: str = "1.0.0"

    @classmethod
    def execute(cls, topic_or_query: str) -> Dict[str, Any]:
        """
        Executes incumbent baseline policy lookup.
        """
        if not topic_or_query or not isinstance(topic_or_query, str):
            return {
                "status": "FAILED",
                "policies": {},
                "error": "EMPTY_OR_INVALID_TOPIC",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }

        t0 = time.perf_counter()
        try:
            out = handle_policy_lookup({"topic": topic_or_query})
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "EXECUTED",
                "policies": out.get("policies", {}),
                "result": out,
                "duration_ms": round(dur_ms, 3),
                "error": None,
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }
        except Exception as ex:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "FAILED",
                "policies": {},
                "duration_ms": round(dur_ms, 3),
                "error": f"EXECUTION_ERROR: {str(ex)}",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }
