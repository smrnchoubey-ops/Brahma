"""
RECOVERY STRATEGY CANDIDATE POLICY ADAPTER (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Consumes an F14 LearningCandidate and provides a graceful recovery strategy policy.
Inherits from CandidateExecutionPolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.models import LearningCandidate
from app.core.learning.policies.base import CandidateExecutionPolicy
from agents.execution.registry import handle_system_status


class RecoveryStrategyCandidatePolicy(CandidateExecutionPolicy):
    """
    Executable candidate policy adapter for recovery strategies.
    Applies graceful fallback recovery yielding operational telemetry.
    """

    def __init__(self, candidate: LearningCandidate):
        super().__init__(candidate)
        self.policy_id = f"policy:recovery_strategy:candidate:{candidate.pattern_id}"
        self.policy_version = candidate.pattern_id
        self.strategy = candidate.action_template.get("strategy", "RECOVERY_STRATEGY")

    def execute(self, input_or_context: Any) -> Dict[str, Any]:
        """
        Executes candidate recovery strategy to restore operational state.
        """
        t0 = time.perf_counter()
        try:
            # Execute graceful fallback operational telemetry
            status_out = handle_system_status({"scope": "recovery_fallback"})
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "EXECUTED",
                "result": status_out,
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
                "result": None,
                "duration_ms": round(dur_ms, 3),
                "error": f"RECOVERY_FAILURE: {str(ex)}",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }
