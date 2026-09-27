"""
INDEPENDENT TOOL ROUTING VERIFIER (Whitesheet §17.1)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Clean-room independent domain verifier for tool routing decisions.
Evaluates whether a given task intent was correctly routed to the appropriate
authorized tool, and whether the tool's execution returned valid domain data.
Inherits from BaseDomainVerifier without importing execution handlers.
"""
import re
from typing import Any, Optional, Dict, List, Tuple
from datetime import datetime, timezone

from app.core.learning.verifiers.base import BaseDomainVerifier, VerifierOutcome


class IndependentToolRoutingVerifier(BaseDomainVerifier):
    """
    Independent ground truth verifier for tool routing tasks.
    Determines whether the routed tool and output structure correctly satisfy the semantic intent.
    """
    VERIFIER_ID: str = "verifier:tool_routing:v1.0.0:independent_router"
    VERIFIER_VERSION: str = "1.0.0"

    # Semantic keyword mappings for expected tools
    TOOL_INTENT_RULES = [
        (re.compile(r'(calculate|math|add|sum|multiply|divide|\+|\-|\*|\/)', re.I), "calculate"),
        (re.compile(r'(calendar_lookup|calendar|holidays?|leave schedule|vacation)', re.I), "calendar_lookup"),
        (re.compile(r'(system_status|system status|health check|diagnostic|server status)', re.I), "system_status"),
        (re.compile(r'(policy_lookup|policy|guidelines?|rules?|timesheet|backup)', re.I), "policy_lookup"),
        (re.compile(r'(echo|format text|uppercase|lowercase)', re.I), "echo"),
    ]

    @classmethod
    def get_expected_tool(cls, intent: str) -> str:
        """Independently determines the expected tool for a given intent string."""
        if not intent or not isinstance(intent, str):
            return "deliverable_summary"
        clean = intent.strip()
        for pattern, tool_name in cls.TOOL_INTENT_RULES:
            if pattern.search(clean):
                return tool_name
        return "deliverable_summary"

    @classmethod
    def verify(
        cls,
        expression_or_input: Any,
        actual_result: Any
    ) -> VerifierOutcome:
        """
        Authoritatively verifies whether the observed actual_result or routed tool
        matches the independently determined expected tool routing.
        """
        intent_str = str(expression_or_input) if expression_or_input is not None else ""
        expected_tool = cls.get_expected_tool(intent_str)

        if actual_result is None:
            return VerifierOutcome(
                verifier_id=cls.VERIFIER_ID,
                verifier_version=cls.VERIFIER_VERSION,
                is_valid=False,
                outcome_score=0.0,
                expected_result=expected_tool,
                actual_result=None,
                error="ACTUAL_RESULT_IS_NONE",
                provenance={"intent": intent_str, "expected_tool": expected_tool}
            )

        # Extract actual tool from dict or string representation
        actual_tool = None
        if isinstance(actual_result, dict):
            actual_tool = actual_result.get("action_name") or actual_result.get("tool") or actual_result.get("tool_used")
            out_obj = actual_result.get("output") if isinstance(actual_result.get("output"), dict) else actual_result
            if not actual_tool and "calendar_year" in out_obj:
                actual_tool = "calendar_lookup"
            elif not actual_tool and "policies" in out_obj:
                actual_tool = "policy_lookup"
            elif not actual_tool and "expression" in out_obj and "result" in out_obj:
                actual_tool = "calculate"
            elif not actual_tool and "output" in out_obj and "format" in out_obj:
                actual_tool = "echo"
            elif not actual_tool and "engine" in out_obj:
                actual_tool = "system_status"
        elif isinstance(actual_result, str):
            actual_tool = actual_result.strip()

        is_match = (actual_tool == expected_tool)
        score = 1.0 if is_match else 0.0

        return VerifierOutcome(
            verifier_id=cls.VERIFIER_ID,
            verifier_version=cls.VERIFIER_VERSION,
            is_valid=is_match,
            outcome_score=score,
            expected_result=expected_tool,
            actual_result=actual_tool or str(actual_result),
            error=None if is_match else f"TOOL_ROUTING_MISMATCH: expected '{expected_tool}', routed to '{actual_tool}'",
            provenance={"intent": intent_str, "expected_tool": expected_tool, "actual_tool": actual_tool}
        )
