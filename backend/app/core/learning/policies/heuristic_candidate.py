"""
HEURISTIC RULE CANDIDATE POLICY ADAPTER (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Consumes an F14 LearningCandidate and provides a learned heuristic rule matcher policy.
Inherits from CandidateExecutionPolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.models import LearningCandidate
from app.core.learning.policies.base import CandidateExecutionPolicy
from agents.execution.registry import handle_policy_lookup


class HeuristicRuleCandidatePolicy(CandidateExecutionPolicy):
    """
    Executable candidate policy adapter for heuristic rule matching.
    """

    def __init__(self, candidate: LearningCandidate):
        super().__init__(candidate)
        self.policy_id = f"policy:heuristic_rule:candidate:{candidate.pattern_id}"
        self.policy_version = candidate.pattern_id
        self.strategy = candidate.action_template.get("strategy", "HEURISTIC_RULE")

    def execute(self, topic_or_query: str) -> Dict[str, Any]:
        """
        Executes candidate heuristic rule matching.
        """
        if not topic_or_query or not isinstance(topic_or_query, str):
            return {
                "status": "FAILED",
                "policies": {},
                "error": "EMPTY_OR_INVALID_TOPIC",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
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
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }
        except Exception as ex:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "FAILED",
                "policies": {},
                "duration_ms": round(dur_ms, 3),
                "error": f"EXECUTION_ERROR: {str(ex)}",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }
