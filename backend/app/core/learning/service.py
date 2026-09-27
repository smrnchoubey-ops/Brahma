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
        description: Optional[str] = None,
        k_min: int = F14PatternExtractor.DEFAULT_K_MIN
    ) -> LearningCandidate:
        """
        F14 Pattern Extraction entrypoint.
        """
        return F14PatternExtractor.extract_pattern(
            tenant_id=tenant_id,
            episodes=episodes,
            pattern_type=pattern_type,
            name=name,
            description=description,
            k_min=k_min
        )

    @classmethod
    def process_candidate_lifecycle(
        cls,
        candidate: LearningCandidate,
        baseline_evaluator: Optional[Callable[..., Dict[str, Any]]] = None,
        candidate_evaluator: Optional[Callable[..., Dict[str, Any]]] = None,
        benchmark_runners: Optional[List[Callable[[], bool]]] = None,
        eval_episodes: Optional[List[Dict[str, Any]]] = None,
        held_out_episodes: Optional[List[Dict[str, Any]]] = None,
        le_threshold: float = 0.70,
        lambda_reg: float = 0.50,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> Tuple[bool, str, LearningCandidate]:
        """
        Runs the full F15 evolutionary stewardship lifecycle:
        1. Constitutional validation (MARYADA).
        2. Shadow deployment and comparative evaluation over held-out episodes.
        3. Regression test evaluation on held-out evaluation set E.
        4. Learning Effectiveness (LE) score calculation per Whitesheet §19.5.
        5. Promotion or Rejection with PostgreSQL persistence.
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

        # 3. Construct or evaluate held-out evaluation episodes
        evaluated_episodes = eval_episodes or []
        shadow_res = None

        if not evaluated_episodes and held_out_episodes:
            # Run shadow comparative evaluation over real held-out episodes
            evaluated_episodes, shadow_res = ShadowEvaluator.evaluate_held_out_episodes(
                candidate=candidate,
                held_out_episodes=held_out_episodes,
                baseline_evaluator=baseline_evaluator,
                candidate_evaluator=candidate_evaluator
            )
        elif not evaluated_episodes:
            # Evaluate using shadow evaluator if custom evaluators provided
            shadow_res = ShadowEvaluator.evaluate_shadow(
                candidate=candidate,
                baseline_evaluator=baseline_evaluator,
                candidate_evaluator=candidate_evaluator
            )

        # 4. Regression Evaluation over held-out episodes E
        regr_res = RegressionEvaluator.evaluate_regressions(
            candidate=candidate,
            benchmark_runners=benchmark_runners,
            eval_episodes=evaluated_episodes if evaluated_episodes else None
        )

        # 5. LE Calculation per Whitesheet §19.5
        le_res = LearningEffectivenessEngine.calculate_le(
            candidate=candidate,
            shadow_result=shadow_res,
            regression_result=regr_res,
            eval_episodes=evaluated_episodes if evaluated_episodes else None,
            lambda_reg=lambda_reg,
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
    def evaluate_live_shadow_promotion(
        cls,
        candidate: LearningCandidate,
        live_observations: Optional[List[Dict[str, Any]]] = None,
        le_threshold: float = 0.50,
        lambda_reg: float = 0.50,
        min_live_observations: int = 1,
        benchmark_runners: Optional[List[Callable[[], bool]]] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None
    ) -> Tuple[bool, str, LearningCandidate]:
        """
        Coordinates the final evolutionary promotion evaluation for a candidate
        accumulating live non-authoritative shadow observations (§17.3, §17.4, §19.5, §20.3).
        Reuses exact existing verifiers, LE calculation engine, and stewardship gates.
        """
        if candidate.status != PatternStatus.SHADOW:
            return False, f"Candidate '{candidate.pattern_id}' must be in SHADOW status (current: {candidate.status.value}).", candidate

        # Extract live observations from parameter or candidate metadata
        obs = live_observations or (candidate.metadata.get("live_shadow_evaluations") if candidate.metadata else None) or []
        if len(obs) < min_live_observations:
            return False, f"INSUFFICIENT_LIVE_OBSERVATIONS: Candidate has {len(obs)} observations, minimum required is {min_live_observations}.", candidate

        # 1. Regression Evaluation over live shadow observations and benchmark suite
        regr_res = RegressionEvaluator.evaluate_regressions(
            candidate=candidate,
            benchmark_runners=benchmark_runners,
            eval_episodes=obs
        )

        # 2. Format ShadowEvaluationResult from live observations
        n = len(obs)
        base_successes = sum(1 for o in obs if float(o.get("baseline_outcome_score", 0.0)) == 1.0)
        cand_successes = sum(1 for o in obs if float(o.get("candidate_outcome_score", 0.0)) == 1.0)
        base_succ_rate = base_successes / n if n > 0 else 1.0
        cand_succ_rate = cand_successes / n if n > 0 else 1.0
        err_delta = max(0.0, base_succ_rate - cand_succ_rate)
        shadow_passed = (cand_succ_rate >= base_succ_rate) and (err_delta == 0.0)

        shadow_res = ShadowEvaluationResult(
            candidate_id=candidate.pattern_id,
            baseline_success_rate=round(base_succ_rate, 4),
            candidate_success_rate=round(cand_succ_rate, 4),
            baseline_latency_ms=0.0,
            candidate_latency_ms=0.0,
            error_delta=round(err_delta, 4),
            passed=shadow_passed,
            evidence={
                "evaluated_episode_count": n,
                "shadow_mode": "LIVE_NON_AUTHORITATIVE",
                "comparative_provenance": obs
            }
        )

        # 3. LE Calculation strictly conforming to §19.5
        le_res = LearningEffectivenessEngine.calculate_le(
            candidate=candidate,
            shadow_result=shadow_res,
            regression_result=regr_res,
            eval_episodes=obs,
            lambda_reg=lambda_reg,
            threshold=le_threshold
        )

        # 4. Promotion / Rejection Decision via F15 Stewardship Gate
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
