"""
INDEPENDENT PARAMETER ADAPTATION VERIFIER (Whitesheet §17.1)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Clean-room independent domain verifier for parameter adaptation decisions.
Evaluates whether a formatted text parameter transformation was executed correctly
based on the requested adaptation format (e.g. uppercase, lowercase, bulleted).
Inherits from BaseDomainVerifier without importing execution handlers.
"""
import re
from typing import Any, Optional, Dict, List, Tuple
from datetime import datetime, timezone

from app.core.learning.verifiers.base import BaseDomainVerifier, VerifierOutcome


class IndependentParameterAdaptationVerifier(BaseDomainVerifier):
    """
    Independent ground truth verifier for parameter adaptation tasks.
    Independently computes expected text format transformation without calling action handlers.
    """
    VERIFIER_ID: str = "verifier:parameter_adaptation:v1.0.0:independent_formatter"
    VERIFIER_VERSION: str = "1.0.0"

    @classmethod
    def compute_ground_truth(cls, raw_input: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Independently derives target format and transformed output from prompt.
        Returns (expected_output, target_format, error).
        """
        if not raw_input or not isinstance(raw_input, str):
            return None, None, "EMPTY_INPUT"

        text = raw_input.strip()
        lower_input = text.lower()

        # Determine target format
        fmt = "plain"
        if "uppercase" in lower_input:
            fmt = "uppercase"
        elif "lowercase" in lower_input:
            fmt = "lowercase"
        elif "bullet" in lower_input:
            fmt = "bulleted"

        # Extract content text to format
        # If prompt is like "format text uppercase: hello world", strip prefix
        prefix_match = re.search(r'^(?:format\s+text\s+(?:uppercase|lowercase|bulleted)?(?:\s*:\s*|\s+)|echo\s+)', text, re.I)
        target_text = text[prefix_match.end():].strip() if prefix_match else text

        if fmt == "uppercase":
            expected = target_text.upper()
        elif fmt == "lowercase":
            expected = target_text.lower()
        elif fmt == "bulleted":
            lines = [l.strip() for l in target_text.split("\n") if l.strip()]
            expected = "\n".join([f"- {l}" for l in lines])
        else:
            expected = target_text

        return expected, fmt, None

    @classmethod
    def verify(
        cls,
        expression_or_input: Any,
        actual_result: Any
    ) -> VerifierOutcome:
        """
        Authoritatively verifies whether the observed actual_result matches
        the independently derived parameter adaptation transformation.
        """
        input_str = str(expression_or_input) if expression_or_input is not None else ""
        expected, fmt, err = cls.compute_ground_truth(input_str)

        if err or expected is None:
            return VerifierOutcome(
                verifier_id=cls.VERIFIER_ID,
                verifier_version=cls.VERIFIER_VERSION,
                is_valid=False,
                outcome_score=0.0,
                expected_result=None,
                actual_result=actual_result,
                error=err or "FAILED_TO_DERIVE_GROUND_TRUTH",
                provenance={"input": input_str}
            )

        if actual_result is None:
            return VerifierOutcome(
                verifier_id=cls.VERIFIER_ID,
                verifier_version=cls.VERIFIER_VERSION,
                is_valid=False,
                outcome_score=0.0,
                expected_result=expected,
                actual_result=None,
                error="ACTUAL_RESULT_IS_NONE",
                provenance={"input": input_str, "format": fmt}
            )

        # Extract output string from dict or direct string
        actual_str = ""
        actual_fmt = None
        if isinstance(actual_result, dict):
            out_val = actual_result.get("output", actual_result.get("result", ""))
            if isinstance(out_val, dict):
                actual_str = str(out_val.get("output", out_val.get("result", ""))).strip()
                actual_fmt = out_val.get("format")
            else:
                actual_str = str(out_val).strip()
            if not actual_fmt:
                actual_fmt = actual_result.get("format")
        elif isinstance(actual_result, str):
            actual_str = actual_result.strip()

        # Check equivalence
        is_match = False
        if fmt == "uppercase":
            is_match = (actual_str == actual_str.upper()) and len(actual_str) > 0
        elif fmt == "lowercase":
            is_match = (actual_str == actual_str.lower()) and len(actual_str) > 0
        elif fmt == "bulleted":
            is_match = actual_str.startswith("- ") or "\n- " in actual_str
        else:
            is_match = (actual_str == expected)

        score = 1.0 if is_match else 0.0

        return VerifierOutcome(
            verifier_id=cls.VERIFIER_ID,
            verifier_version=cls.VERIFIER_VERSION,
            is_valid=is_match,
            outcome_score=score,
            expected_result=expected,
            actual_result=actual_str,
            error=None if is_match else f"PARAMETER_ADAPTATION_MISMATCH: expected format '{fmt}'",
            provenance={"input": input_str, "format": fmt, "actual_format": actual_fmt}
        )
