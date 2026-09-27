"""
INDEPENDENT RECOVERY STRATEGY VERIFIER (Whitesheet §17.1)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Clean-room independent domain verifier for recovery strategy decisions.
Evaluates whether a system recovery or fallback execution correctly mitigated faults,
preserved operational telemetry integrity, and avoided unhandled crashes.
Inherits from BaseDomainVerifier without importing execution handlers.
"""
from typing import Any, Optional, Dict, List, Tuple
from datetime import datetime, timezone

from app.core.learning.verifiers.base import BaseDomainVerifier, VerifierOutcome


class IndependentRecoveryVerifier(BaseDomainVerifier):
    """
    Independent ground truth verifier for recovery strategy tasks.
    Verifies that the executed fallback/recovery response is operational, valid, and fault-tolerant.
    """
    VERIFIER_ID: str = "verifier:recovery_strategy:v1.0.0:independent_recovery"
    VERIFIER_VERSION: str = "1.0.0"

    @classmethod
    def verify(
        cls,
        expression_or_input: Any,
        actual_result: Any
    ) -> VerifierOutcome:
        """
        Authoritatively verifies whether the observed actual_result demonstrates
        a successful, non-crashing recovery or fallback state.
        """
        input_str = str(expression_or_input) if expression_or_input is not None else ""

        if actual_result is None:
            return VerifierOutcome(
                verifier_id=cls.VERIFIER_ID,
                verifier_version=cls.VERIFIER_VERSION,
                is_valid=False,
                outcome_score=0.0,
                expected_result="RECOVERED_OPERATIONAL_STATE",
                actual_result=None,
                error="ACTUAL_RESULT_IS_NONE",
                provenance={"input": input_str}
            )

        is_valid_recovery = False
        details = {}

        if isinstance(actual_result, dict):
            out_obj = actual_result.get("output") if isinstance(actual_result.get("output"), dict) else actual_result
            status = out_obj.get("status", actual_result.get("status"))
            engine = out_obj.get("engine", actual_result.get("engine"))
            deliverable = out_obj.get("deliverable", actual_result.get("deliverable"))
            error = actual_result.get("error")

            # Check if output is operational status fallback or safe deliverable summary
            if status in ("OPERATIONAL", "DELIVERED", "EXECUTED", "RECOVERED") and not error:
                is_valid_recovery = True
            elif engine and not error:
                is_valid_recovery = True
            elif deliverable and not error:
                is_valid_recovery = True
            details = actual_result
        elif isinstance(actual_result, str):
            is_valid_recovery = ("OPERATIONAL" in actual_result or "DELIVERED" in actual_result or "success" in actual_result.lower()) and "FAILED" not in actual_result
            details = {"raw": actual_result}

        score = 1.0 if is_valid_recovery else 0.0

        return VerifierOutcome(
            verifier_id=cls.VERIFIER_ID,
            verifier_version=cls.VERIFIER_VERSION,
            is_valid=is_valid_recovery,
            outcome_score=score,
            expected_result="RECOVERED_OPERATIONAL_STATE",
            actual_result=actual_result,
            error=None if is_valid_recovery else "RECOVERY_FAILED_OR_UNHANDLED_ERROR",
            provenance={"input": input_str, "details": details}
        )
