"""
CALCULATOR CANDIDATE POLICY ADAPTER (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Consumes an F14 LearningCandidate and provides an executable candidate policy interface.
Executes the candidate strategy on the exact same arithmetic expression as the baseline.
Inherits from CandidateExecutionPolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.models import LearningCandidate
from app.core.learning.policies.base import CandidateExecutionPolicy, PolicyExecutionResult
from agents.execution.registry import handle_calculate, ExecutionError


class CalculatorCandidatePolicy(CandidateExecutionPolicy):
    """
    Executable candidate policy adapter wrapping an F14 LearningCandidate.
    """

    def __init__(self, candidate: LearningCandidate):
        super().__init__(candidate)
        self.policy_id = f"policy:calculator:candidate:{candidate.pattern_id}"
        self.policy_version = candidate.pattern_id
        self.strategy = candidate.action_template.get("strategy", "OPTIMIZED_EXECUTION")

    def execute(self, expression: str) -> Dict[str, Any]:
        """
        Executes the candidate pattern logic on the provided arithmetic expression.
        Returns a structured execution result with candidate provenance.
        """
        if not expression or not isinstance(expression, str):
            return {
                "status": "FAILED",
                "expression": expression,
                "result": None,
                "error": "EMPTY_OR_INVALID_EXPRESSION",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }

        t0 = time.perf_counter()
        try:
            # Execute candidate policy
            out = handle_calculate({"expression": expression})
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "EXECUTED",
                "expression": out.get("expression", expression),
                "result": out.get("result"),
                "duration_ms": round(dur_ms, 3),
                "error": None,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }
        except ExecutionError as ex:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "FAILED",
                "expression": expression,
                "result": None,
                "duration_ms": round(dur_ms, 3),
                "error": f"EXECUTION_ERROR: {str(ex)}",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }
        except Exception as ex:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "FAILED",
                "expression": expression,
                "result": None,
                "duration_ms": round(dur_ms, 3),
                "error": f"UNEXPECTED_ERROR: {str(ex)}",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }
