"""
INDEPENDENT HEURISTIC RULE VERIFIER (Whitesheet §17.1)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Clean-room independent domain verifier for heuristic rule decisions.
Evaluates whether corporate governance policy queries correctly matched
the authoritative policy rules without importing execution handlers.
Inherits from BaseDomainVerifier.
"""
from typing import Any, Optional, Dict, List, Tuple
from datetime import datetime, timezone

from app.core.learning.verifiers.base import BaseDomainVerifier, VerifierOutcome


class IndependentHeuristicVerifier(BaseDomainVerifier):
    """
    Independent ground truth verifier for heuristic rule matching tasks.
    Verifies that the retrieved policy information contains the authoritative rule content.
    """
    VERIFIER_ID: str = "verifier:heuristic_rule:v1.0.0:independent_rules"
    VERIFIER_VERSION: str = "1.0.0"

    # Canonical authoritative policy rules (clean-room ground truth)
    AUTHORITATIVE_POLICIES = {
        "timesheet": "Timesheets must be finalized and submitted by every Friday before 5:00 PM.",
        "backup": "Project Phoenix and all mission-critical production databases must execute cold-storage backups daily.",
        "deployment": "Production deployments require Maryada governance approval and must pass Murphy risk verification."
    }

    @classmethod
    def get_expected_policy(cls, query: str) -> Optional[Tuple[str, str]]:
        """Independently determines the target policy key and canonical rule text."""
        if not query or not isinstance(query, str):
            return None
        lower = query.lower()
        for key, text in cls.AUTHORITATIVE_POLICIES.items():
            if key in lower:
                return key, text
        return None

    @classmethod
    def verify(
        cls,
        expression_or_input: Any,
        actual_result: Any
    ) -> VerifierOutcome:
        """
        Authoritatively verifies whether the observed actual_result contains
        the canonical governance rule text for the query topic.
        """
        input_str = str(expression_or_input) if expression_or_input is not None else ""
        expected_meta = cls.get_expected_policy(input_str)

        if actual_result is None:
            return VerifierOutcome(
                verifier_id=cls.VERIFIER_ID,
                verifier_version=cls.VERIFIER_VERSION,
                is_valid=False,
                outcome_score=0.0,
                expected_result=expected_meta[1] if expected_meta else "AUTHORITATIVE_POLICY",
                actual_result=None,
                error="ACTUAL_RESULT_IS_NONE",
                provenance={"input": input_str}
            )

        # Extract policies map or text from actual_result
        matched_policies = {}
        if isinstance(actual_result, dict):
            out_obj = actual_result.get("output") if isinstance(actual_result.get("output"), dict) else actual_result
            matched_policies = out_obj.get("policies", actual_result.get("policies", actual_result))
        elif isinstance(actual_result, str):
            matched_policies = {"raw": actual_result}

        is_valid = False
        if expected_meta:
            key, expected_text = expected_meta
            if isinstance(matched_policies, dict):
                act_text = matched_policies.get(key, "")
                if expected_text.lower() in act_text.lower() or any(expected_text.lower() in str(v).lower() for v in matched_policies.values()):
                    is_valid = True
            elif isinstance(matched_policies, str):
                if expected_text.lower() in matched_policies.lower():
                    is_valid = True
        else:
            # General query with non-empty policies result
            if isinstance(matched_policies, dict) and len(matched_policies) > 0:
                is_valid = True

        score = 1.0 if is_valid else 0.0

        return VerifierOutcome(
            verifier_id=cls.VERIFIER_ID,
            verifier_version=cls.VERIFIER_VERSION,
            is_valid=is_valid,
            outcome_score=score,
            expected_result=expected_meta[1] if expected_meta else "AUTHORITATIVE_POLICY",
            actual_result=actual_result,
            error=None if is_valid else "HEURISTIC_RULE_MISMATCH: Authoritative policy text not matched.",
            provenance={"input": input_str, "matched_policies": matched_policies}
        )
