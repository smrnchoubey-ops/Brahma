"""
INCUMBENT CALCULATOR BASELINE POLICY (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Represents the explicit incumbent default calculator policy boundary.
Executes baseline arithmetic without modifying production state or database records.
Inherits from IncumbentBaselinePolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.policies.base import IncumbentBaselinePolicy, PolicyExecutionResult
from agents.execution.registry import handle_calculate, ExecutionError


class IncumbentCalculatorBaselinePolicy(IncumbentBaselinePolicy):
    """
    Explicit incumbent baseline execution policy for the calculator domain.
    """
    POLICY_ID: str = "policy:calculator:v1.0.0:incumbent_default"
    POLICY_VERSION: str = "1.0.0"

    @classmethod
    def execute(cls, expression: str) -> Dict[str, Any]:
        """
        Executes the incumbent calculator behavior on the provided arithmetic expression.
        Returns a structured execution result with explicit provenance.
        """
        if not expression or not isinstance(expression, str):
            return {
                "status": "FAILED",
                "expression": expression,
                "result": None,
                "error": "EMPTY_OR_INVALID_EXPRESSION",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }

        t0 = time.perf_counter()
        try:
            out = handle_calculate({"expression": expression})
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "EXECUTED",
                "expression": out.get("expression", expression),
                "result": out.get("result"),
                "duration_ms": round(dur_ms, 3),
                "error": None,
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }
        except ExecutionError as ex:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "FAILED",
                "expression": expression,
                "result": None,
                "duration_ms": round(dur_ms, 3),
                "error": f"EXECUTION_ERROR: {str(ex)}",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }
        except Exception as ex:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "FAILED",
                "expression": expression,
                "result": None,
                "duration_ms": round(dur_ms, 3),
                "error": f"UNEXPECTED_ERROR: {str(ex)}",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }
