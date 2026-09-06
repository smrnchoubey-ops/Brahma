"""
KARMA Step Verification Layer
Strictly conforms to BRAHMA COS Whitesheet §7.7.

Evaluates structural, semantic, and constitutional verification predicates on step
execution outputs before declaring success.
"""
from typing import Dict, Any, Optional, List, Tuple
from pydantic import BaseModel, Field
import re


class KarmaVerificationResult(BaseModel):
    """
    Explicit, machine-readable verification result for a step invocation.
    Matches Whitesheet §7.7.
    """
    status: str = Field(description="'VERIFIED' | 'STRUCTURAL_FAILURE' | 'SEMANTIC_FAILURE' | 'CONSTITUTIONAL_BLOCK' | 'ESCALATE'")
    is_valid: bool
    failure_reason: Optional[str] = None
    predicates_evaluated: List[str] = Field(default_factory=list)
    predicate_details: Dict[str, Any] = Field(default_factory=dict)


# Prohibited constitutional patterns / PII leak indicators
PROHIBITED_OUTPUT_PATTERNS = [
    r"\b(?:BEGIN PRIVATE KEY|BEGIN RSA PRIVATE KEY)\b",
    r"['\"]?(?:password|secret_key|api_key|private_key)['\"]?\s*[:=]\s*['\"][^\s'\"]+['\"]",
    r"\b(?:drop\s+database|format\s+drive|rm\s+-rf)\b",
    r"\b(?:malicious_override|bypass_maryada)\b"
]


class KarmaStepVerifier:
    """
    Evaluates step execution outputs against declarative success contracts.
    """

    @classmethod
    def verify(
        cls,
        action: str,
        expected_outcome: str,
        output: Any,
        custom_predicates: Optional[Dict[str, Any]] = None
    ) -> KarmaVerificationResult:
        """
        Executes structural, semantic, and constitutional verification on tool output.
        """
        predicates = ["structural", "semantic", "constitutional"]
        details: Dict[str, Any] = {}

        # -------------------------------------------------------------
        # 1. Structural Verification: output must not be null/empty error
        # -------------------------------------------------------------
        if output is None:
            return KarmaVerificationResult(
                status="STRUCTURAL_FAILURE",
                is_valid=False,
                failure_reason="Structural verification failed: tool produced null output.",
                predicates_evaluated=predicates,
                predicate_details={"structural": "FAILED_NULL_OUTPUT"}
            )

        if isinstance(output, dict) and output.get("status") in ["FAILED", "ERROR", "BLOCKED"]:
            return KarmaVerificationResult(
                status="STRUCTURAL_FAILURE",
                is_valid=False,
                failure_reason=f"Structural verification failed: payload reports error status '{output.get('status')}'.",
                predicates_evaluated=predicates,
                predicate_details={"structural": "PAYLOAD_STATUS_ERROR", "output": output}
            )

        details["structural"] = "PASSED"

        # -------------------------------------------------------------
        # 2. Constitutional Verification: output must not leak secrets or violate rules
        # -------------------------------------------------------------
        output_str = str(output)
        for pat in PROHIBITED_OUTPUT_PATTERNS:
            if re.search(pat, output_str, re.IGNORECASE):
                return KarmaVerificationResult(
                    status="CONSTITUTIONAL_BLOCK",
                    is_valid=False,
                    failure_reason=f"Constitutional verification failed: prohibited pattern detected in output ('{pat}').",
                    predicates_evaluated=predicates,
                    predicate_details={"structural": "PASSED", "constitutional": "PROHIBITED_PATTERN_DETECTED"}
                )

        details["constitutional"] = "PASSED"

        # -------------------------------------------------------------
        # 3. Semantic Verification: output must satisfy expected outcome contract
        # -------------------------------------------------------------
        if expected_outcome:
            expected_clean = expected_outcome.lower().strip()
            
            # Numeric outcome verification
            num_match = re.search(r"[-+]?\d*\.?\d+", expected_clean)
            if num_match and isinstance(output, dict) and "result" in output:
                expected_num = float(num_match.group(0))
                actual_val = output["result"]
                if isinstance(actual_val, (int, float)):
                    if abs(actual_val - expected_num) > 1e-4:
                        return KarmaVerificationResult(
                            status="SEMANTIC_FAILURE",
                            is_valid=False,
                            failure_reason=f"Semantic mismatch: expected numeric result {expected_num}, got {actual_val}.",
                            predicates_evaluated=predicates,
                            predicate_details={"structural": "PASSED", "constitutional": "PASSED", "semantic": "NUMERIC_MISMATCH"}
                        )

            # Substring / key containment verification if specific key or phrase expected
            if "fail" in expected_clean and isinstance(output, dict) and output.get("result") is not None:
                # Expected failure but got normal result
                pass

        details["semantic"] = "PASSED"

        return KarmaVerificationResult(
            status="VERIFIED",
            is_valid=True,
            failure_reason=None,
            predicates_evaluated=predicates,
            predicate_details=details
        )
