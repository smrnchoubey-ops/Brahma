"""
PARAMETER ADAPTATION CANDIDATE POLICY ADAPTER (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Consumes an F14 LearningCandidate and provides an adapted parameter execution interface.
Executes adapted parameter formatting on the exact same input as baseline.
Inherits from CandidateExecutionPolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.models import LearningCandidate
from app.core.learning.policies.base import CandidateExecutionPolicy
from agents.execution.registry import handle_echo


class ParameterAdaptationCandidatePolicy(CandidateExecutionPolicy):
    """
    Executable candidate policy adapter for parameter adaptation.
    """

    def __init__(self, candidate: LearningCandidate):
        super().__init__(candidate)
        self.policy_id = f"policy:parameter_adaptation:candidate:{candidate.pattern_id}"
        self.policy_version = candidate.pattern_id
        self.strategy = candidate.action_template.get("strategy", "PARAMETER_ADAPTATION")

    def execute(self, text_or_input: str) -> Dict[str, Any]:
        """
        Executes candidate parameter adaptation on text input.
        """
        if not text_or_input or not isinstance(text_or_input, str):
            return {
                "status": "FAILED",
                "output": None,
                "error": "EMPTY_OR_INVALID_INPUT",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }

        t0 = time.perf_counter()
        try:
            # Determine adapted format parameter
            fmt = "plain"
            lower = text_or_input.lower()
            if "uppercase" in lower:
                fmt = "uppercase"
            elif "lowercase" in lower:
                fmt = "lowercase"
            elif "bullet" in lower:
                fmt = "bulleted"

            out = handle_echo({"text": text_or_input, "format": fmt})
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "EXECUTED",
                "output": out.get("output"),
                "format": out.get("format"),
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
                "output": None,
                "duration_ms": round(dur_ms, 3),
                "error": f"EXECUTION_ERROR: {str(ex)}",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }
