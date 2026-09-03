"""
LEARNING SYSTEM: Data Models & Candidate Lifecycle Invariants
Strictly conforms to BRAHMA COS Whitesheet Learning System (F14 & F15).
"""
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class PatternStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    SHADOW = "SHADOW"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class PatternType(str, Enum):
    PLAN_OPTIMIZATION = "PLAN_OPTIMIZATION"
    TOOL_ROUTING = "TOOL_ROUTING"
    PARAMETER_ADAPTATION = "PARAMETER_ADAPTATION"
    RECOVERY_STRATEGY = "RECOVERY_STRATEGY"
    HEURISTIC_RULE = "HEURISTIC_RULE"


class LearningEvidence(BaseModel):
    """
    Structured provenance and metric evidence supporting a learning candidate.
    """
    source_task_ids: List[int] = Field(default_factory=list)
    source_event_ids: List[str] = Field(default_factory=list)
    metric_deltas: Dict[str, float] = Field(default_factory=dict)
    sample_count: int = 1
    notes: str = ""


class LearningCandidate(BaseModel):
    """
    Formal representation of an extracted learning pattern candidate.
    """
    pattern_id: str
    tenant_id: str
    pattern_type: PatternType
    name: str
    description: str
    action_template: Dict[str, Any] = Field(default_factory=dict)
    evidence: LearningEvidence = Field(default_factory=LearningEvidence)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: PatternStatus = PatternStatus.CANDIDATE
    version: int = 1
    le_score: float = 0.0
    constitutional_approved: bool = False
    regression_passed: bool = False
    shadow_passed: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    promoted_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ShadowEvaluationResult(BaseModel):
    """
    Outcome of a non-authoritative shadow deployment evaluation.
    """
    candidate_id: str
    baseline_success_rate: float
    candidate_success_rate: float
    baseline_latency_ms: float
    candidate_latency_ms: float
    error_delta: float
    passed: bool
    evidence: Dict[str, Any] = Field(default_factory=dict)


class RegressionTestResult(BaseModel):
    """
    Outcome of regression testing against canonical benchmarks.
    """
    candidate_id: str
    benchmark_count: int
    regressions_detected: int
    passed: bool
    details: List[str] = Field(default_factory=list)


class LEResult(BaseModel):
    """
    Structured outcome of Learning Effectiveness calculation.
    """
    candidate_id: str
    le_score: float
    threshold: float
    passed: bool
    factors: Dict[str, float] = Field(default_factory=dict)
    justification: str = ""
