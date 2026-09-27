"""
LEARNING SYSTEM Core Package (Whitesheet Learning System / Phase 5 Learning Roadmap: F14 & F15)
"""
from app.core.learning.models import (
    PatternStatus,
    PatternType,
    LearningEvidence,
    LearningCandidate,
    ShadowEvaluationResult,
    RegressionTestResult,
    LEResult
)
from app.core.learning.pattern_extractor import F14PatternExtractor
from app.core.learning.effectiveness import LearningEffectivenessEngine
from app.core.learning.shadow_evaluator import ShadowEvaluator
from app.core.learning.regression_evaluator import RegressionEvaluator
from app.core.learning.stewardship import F15EvolutionarySteward, StewardshipError
from app.core.learning.service import LearningService
from app.core.learning.ingestion import LearningIngestionService
from app.core.learning.verifiers import BaseDomainVerifier, VerifierOutcome, IndependentCalculatorVerifier
from app.core.learning.policies import (
    BaseExecutionPolicy,
    IncumbentBaselinePolicy,
    CandidateExecutionPolicy,
    PolicyExecutionResult,
    IncumbentCalculatorBaselinePolicy,
    CalculatorCandidatePolicy
)

__all__ = [
    "PatternStatus",
    "PatternType",
    "LearningEvidence",
    "LearningCandidate",
    "ShadowEvaluationResult",
    "RegressionTestResult",
    "LEResult",
    "F14PatternExtractor",
    "LearningEffectivenessEngine",
    "ShadowEvaluator",
    "RegressionEvaluator",
    "F15EvolutionarySteward",
    "StewardshipError",
    "LearningService",
    "LearningIngestionService",
    "BaseDomainVerifier",
    "VerifierOutcome",
    "IndependentCalculatorVerifier",
    "BaseExecutionPolicy",
    "IncumbentBaselinePolicy",
    "CandidateExecutionPolicy",
    "PolicyExecutionResult",
    "IncumbentCalculatorBaselinePolicy",
    "CalculatorCandidatePolicy"
]
