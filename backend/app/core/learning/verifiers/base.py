"""
Base Clean-Room Domain Verifier Contract
Strictly conforms to BRAHMA COS Whitesheet Learning System (§17.1, §19.5).

Defines the abstract interface for domain-specific independent outcome verifiers.
Clean-room verifiers MUST NOT import, delegate to, or reuse task executors,
and must produce verifiable, deterministic, traceable outcome scores.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class VerifierOutcome:
    """
    Standard outcome result from an independent clean-room domain verifier.
    """
    verifier_id: str
    verifier_version: str
    is_valid: bool
    outcome_score: float  # Numerical outcome score (e.g. 1.0 for verified match, 0.0 for mismatch/error)
    expected_result: Optional[Any] = None
    actual_result: Optional[Any] = None
    error: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BaseDomainVerifier(ABC):
    """
    Abstract contract for clean-room domain-specific task outcome verifiers.
    """
    VERIFIER_ID: str = "base_domain_verifier"
    VERIFIER_VERSION: str = "1.0.0"

    @classmethod
    @abstractmethod
    def verify(
        cls,
        expression_or_input: Any,
        actual_result: Any
    ) -> VerifierOutcome:
        """
        Independently parses, executes, or evaluates ground truth for the given input
        and compares with the actual runtime execution result.

        Must fail closed (outcome_score=0.0) on unsupported, malformed, or unparseable inputs.
        """
        raise NotImplementedError
