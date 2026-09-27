"""
INCUMBENT PARAMETER ADAPTATION BASELINE POLICY (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Represents the incumbent baseline parameter formatting policy boundary.
Inherits from IncumbentBaselinePolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.policies.base import IncumbentBaselinePolicy
from agents.execution.registry import handle_echo


class IncumbentParameterAdaptationBaselinePolicy(IncumbentBaselinePolicy):
    """
    Incumbent baseline parameter policy.
    Uses default/unadapted parameter configuration (plain format).
    """
    POLICY_ID: str = "policy:parameter_adaptation:v1.0.0:incumbent_default"
    POLICY_VERSION: str = "1.0.0"

    @classmethod
    def execute(cls, text_or_input: str) -> Dict[str, Any]:
        """
        Executes incumbent parameter formatting (plain text).
        """
        if not text_or_input or not isinstance(text_or_input, str):
            return {
                "status": "FAILED",
                "output": None,
                "error": "EMPTY_OR_INVALID_INPUT",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }

        t0 = time.perf_counter()
        try:
            # Baseline uses unadapted format ("plain")
            out = handle_echo({"text": text_or_input, "format": "plain"})
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "EXECUTED",
                "output": out.get("output"),
                "format": out.get("format"),
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
                "output": None,
                "duration_ms": round(dur_ms, 3),
                "error": f"EXECUTION_ERROR: {str(ex)}",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }
