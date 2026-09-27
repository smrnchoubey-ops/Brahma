"""
TOOL ROUTING CANDIDATE POLICY ADAPTER (Whitesheet §17.3)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Consumes an F14 LearningCandidate and provides an optimized tool routing policy interface.
Executes candidate routing on the exact same intent as the baseline.
Inherits from CandidateExecutionPolicy.
"""
from typing import Dict, Any, Optional
import time

from app.core.learning.models import LearningCandidate
from app.core.learning.policies.base import CandidateExecutionPolicy
from agents.execution.registry import ACTION_REGISTRY, handle_deliverable_summary


class ToolRoutingCandidatePolicy(CandidateExecutionPolicy):
    """
    Executable candidate policy adapter for tool routing optimizations.
    """

    def __init__(self, candidate: LearningCandidate):
        super().__init__(candidate)
        self.policy_id = f"policy:tool_routing:candidate:{candidate.pattern_id}"
        self.policy_version = candidate.pattern_id
        self.strategy = candidate.action_template.get("strategy", "TOOL_ROUTING")
        self.tool_pref = candidate.action_template.get("target_tool_preference")

    def execute(self, intent_or_input: str) -> Dict[str, Any]:
        """
        Executes the candidate tool routing pattern logic.
        """
        if not intent_or_input or not isinstance(intent_or_input, str):
            return {
                "status": "FAILED",
                "intent": intent_or_input,
                "action_name": "none",
                "result": None,
                "error": "EMPTY_OR_INVALID_INTENT",
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }

        t0 = time.perf_counter()
        try:
            from agents.execution.router import _resolve_action_and_params, _extract_params_for_action
            mock_state = {"intent": intent_or_input, "plan": {}, "policy_verdict": {"approved": True}}

            # Candidate tool routing preference optimization
            if self.tool_pref and self.tool_pref in ACTION_REGISTRY:
                action_name = self.tool_pref
                params = _extract_params_for_action(action_name, mock_state)
            else:
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
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
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
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "strategy": self.strategy
            }
