"""
Base Execution Policy Contracts
Strictly conforms to BRAHMA COS Whitesheet Learning System (§17.3, §17.4).

Defines the abstract execution policy interfaces for:
1. Incumbent Baseline Policies (representing default production agent execution)
2. Candidate Execution Policies (consuming LearningCandidate action_templates to parameterize behavior)
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.learning.models import LearningCandidate


@dataclass
class PolicyExecutionResult:
    """
    Standard result returned from an execution policy run.
    """
    policy_id: str
    policy_version: str
    status: str
    result: Any
    duration_ms: float = 0.0
    telemetry: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BaseExecutionPolicy(ABC):
    """
    Abstract contract for all baseline and candidate execution policies.
    """
    POLICY_ID: str = "base_execution_policy"
    POLICY_VERSION: str = "1.0.0"

    @abstractmethod
    def execute(self, expression_or_input: Any) -> PolicyExecutionResult:
        """
        Executes the given input under this policy configuration.
        Must NOT alter persistent production database state.
        """
        raise NotImplementedError


class IncumbentBaselinePolicy(BaseExecutionPolicy):
    """
    Base contract for incumbent production default policies.
    """
    pass


class CandidateExecutionPolicy(BaseExecutionPolicy):
    """
    Base contract for candidate policies parameterized by an F14 LearningCandidate.
    """
    def __init__(self, candidate: LearningCandidate):
        self.candidate = candidate
        self.pattern_id = candidate.pattern_id
        self.tenant_id = candidate.tenant_id
        self.action_template = candidate.action_template or {}
