"""
INCUMBENT TOOL ROUTING BASELINE POLICY (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Represents the incumbent default tool routing policy boundary.
Executes baseline action resolution without modifying persistent database records.
Inherits from IncumbentBaselinePolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.policies.base import IncumbentBaselinePolicy
from agents.execution.registry import ACTION_REGISTRY, handle_deliverable_summary


class IncumbentToolRoutingBaselinePolicy(IncumbentBaselinePolicy):
    """
    Incumbent default tool routing policy.
    Uses default fallback routing without learned tool preference optimizations.
    """
    POLICY_ID: str = "policy:tool_routing:v1.0.0:incumbent_default"
    POLICY_VERSION: str = "1.0.0"

    @classmethod
    def execute(cls, intent_or_input: str) -> Dict[str, Any]:
        """
        Executes incumbent tool routing on the given input intent.
        """
        if not intent_or_input or not isinstance(intent_or_input, str):
            return {
                "status": "FAILED",
                "intent": intent_or_input,
                "action_name": "none",
                "result": None,
                "error": "EMPTY_OR_INVALID_INTENT",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }

        t0 = time.perf_counter()
        try:
            # Baseline execution resolves directly via deliverable summary or basic action handler
            from agents.execution.router import _resolve_action_and_params
            mock_state = {"intent": intent_or_input, "plan": {}, "policy_verdict": {"approved": True}}
            action_name, params = _resolve_action_and_params(mock_state)
            action_meta = ACTION_REGISTRY.get(action_name)
            if action_meta:
                handler = action_meta["handler"]
                out = handler(params)
            else:
                out = handle_deliverable_summary({"plan_summary": intent_or_input})
                action_name = "deliverable_summary"
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "status": "EXECUTED",
                "intent": intent_or_input,
                "action_name": action_name,
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
                "intent": intent_or_input,
                "action_name": "error_handler",
                "result": None,
                "duration_ms": round(dur_ms, 3),
                "error": f"EXECUTION_ERROR: {str(ex)}",
                "policy_id": cls.POLICY_ID,
                "policy_version": cls.POLICY_VERSION
            }
