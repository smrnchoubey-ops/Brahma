"""
LEARNING SERVICE: High-Level Learning Faculty Coordinator
Strictly conforms to BRAHMA COS Whitesheet Learning System (F14 & F15).
"""
from typing import Dict, Any, Optional, List, Callable, Tuple
from sqlalchemy.orm import Session

from app.core.learning.models import (
    LearningCandidate,
    PatternStatus,
    PatternType,
    ShadowEvaluationResult,
    RegressionTestResult,
    LEResult
)
from app.core.learning.pattern_extractor import F14PatternExtractor
from app.core.learning.effectiveness import LearningEffectivenessEngine
from app.core.learning.shadow_evaluator import ShadowEvaluator
from app.core.learning.regression_evaluator import RegressionEvaluator
from app.core.learning.stewardship import F15EvolutionarySteward


class LearningService:
    """
    Central orchestration service for BRAHMA COS Learning System.
    """

    @classmethod
    def extract_pattern(
        cls,
        tenant_id: str,
        episodes: List[Dict[str, Any]],
        pattern_type: PatternType = PatternType.PLAN_OPTIMIZATION,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> LearningCandidate:
        """
        F14 Pattern Extraction entrypoint.
        """
        return F14PatternExtractor.extract_pattern(
            tenant_id=tenant_id,
            episodes=episodes,
            pattern_type=pattern_type,
            name=name,
            description=description
        )

    @classmethod
    def process_candidate_lifecycle(
        cls,
        candidate: LearningCandidate,
        baseline_evaluator: Optional[Callable[[], Dict[str, Any]]] = None,
        candidate_evaluator: Optional[Callable[[], Dict[str, Any]]] = None,
        benchmark_runners: Optional[List[Callable[[], bool]]] = None,
        le_threshold: float = 0.70,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> Tuple[bool, str, LearningCandidate]:
        """
        Runs the full F15 evolutionary stewardship lifecycle:
        1. Constitutional validation (MARYADA).
        2. Shadow deployment and comparative evaluation.
        3. Regression test evaluation.
        4. Learning Effectiveness (LE) score calculation.
        5. Promotion or Rejection.
        """
        # 1. Constitutional Validation
        val_ok = F15EvolutionarySteward.validate_candidate(
            candidate=candidate,
            db_session=db_session,
            user_id=user_id,
            task_id=task_id
        )
        if not val_ok:
            return False, "Failed constitutional validation.", candidate

        # 2. Deploy to Shadow
        F15EvolutionarySteward.deploy_to_shadow(
            candidate=candidate,
            db_session=db_session,
            user_id=user_id,
            task_id=task_id
        )

        # 3. Shadow Evaluation
        shadow_res = ShadowEvaluator.evaluate_shadow(
            candidate=candidate,
            baseline_evaluator=baseline_evaluator,
            candidate_evaluator=candidate_evaluator
        )

        # 4. Regression Evaluation
        regr_res = RegressionEvaluator.evaluate_regressions(
            candidate=candidate,
            benchmark_runners=benchmark_runners
        )

        # 5. LE Calculation
        le_res = LearningEffectivenessEngine.calculate_le(
            candidate=candidate,
            shadow_result=shadow_res,
            regression_result=regr_res,
            threshold=le_threshold
        )

        # 6. Promotion / Rejection Decision
        promoted, msg = F15EvolutionarySteward.evaluate_and_promote(
            candidate=candidate,
            le_result=le_res,
            regression_result=regr_res,
            shadow_result=shadow_res,
            db_session=db_session,
            user_id=user_id,
            task_id=task_id
        )

        return promoted, msg, candidate

    @classmethod
    def rollback_pattern(
        cls,
        candidate: LearningCandidate,
        reason: str,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> None:
        """
        Rolls back a promoted candidate.
        """
        F15EvolutionarySteward.rollback(
            candidate=candidate,
            reason=reason,
            db_session=db_session,
            user_id=user_id,
            task_id=task_id
        )
