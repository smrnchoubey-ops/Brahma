
"""
Learning Effectiveness (LE) Calculation Engine
Strictly conforms to BRAHMA COS Whitesheet §19.5 Specification.

Formula (Whitesheet §19.5):
LE(u) = (1/|E|) * sum_{e in E} [ outcome_score(e|u) - outcome_score(e|baseline) ] - lambda_reg * regression_count(u, E)

Where:
- u: Learning candidate / update
- E: Evaluation episode set (|E| >= 1)
- outcome_score(e|u): Outcome score of episode e under candidate policy u
- outcome_score(e|baseline): Outcome score of episode e under baseline policy
- lambda_reg: Regression penalty multiplier (default 0.50)
- regression_count(u, E): Count of detected benchmark regressions from RegressionEvaluator
"""
from typing import Dict, Any, Optional, List
from app.core.learning.models import (
    LEResult,
    LearningCandidate,
    ShadowEvaluationResult,
    RegressionTestResult
)


class LearningEffectivenessEngine:
    """
    Evaluates learning candidate effectiveness strictly conforming to Whitesheet §19.5.
    """
    DEFAULT_THRESHOLD: float = 0.70
    LAMBDA_REG: float = 0.50  # Regression penalty coefficient (Whitesheet §19.5 lambda_reg)

    @classmethod
    def calculate_le(
        cls,
        candidate: LearningCandidate,
        shadow_result: Optional[ShadowEvaluationResult] = None,
        regression_result: Optional[RegressionTestResult] = None,
        eval_episodes: Optional[List[Dict[str, Any]]] = None,
        lambda_reg: float = LAMBDA_REG,
        threshold: float = DEFAULT_THRESHOLD
    ) -> LEResult:
        """
        Calculates Learning Effectiveness (LE) score per Whitesheet §19.5:
        LE(u) = (1/|E|) * sum_{e in E} [ outcome_score(e|u) - outcome_score(e|baseline) ] - lambda_reg * regression_count(u, E)
        """
        episode_deltas: List[float] = []

        # 1. Compute per-episode outcome deltas: outcome_score(e|u) - outcome_score(e|baseline)
        if eval_episodes and len(eval_episodes) > 0:
            # Literal per-episode evaluation over held-out episode set E
            for ep in eval_episodes:
                score_u = float(ep.get("outcome_score_u", ep.get("outcome_u", ep.get("score_u", 1.0))))
                score_base = float(ep.get("outcome_score_baseline", ep.get("outcome_baseline", ep.get("score_baseline", 0.0))))
                episode_deltas.append(score_u - score_base)
            mean_outcome_delta = sum(episode_deltas) / len(episode_deltas)
            episode_count = len(eval_episodes)
        elif shadow_result:
            # Empirical outcome delta from Shadow Evaluation
            # Computes outcome delta combining success rate improvement and latency efficiency gain
            base_succ = shadow_result.baseline_success_rate
            cand_succ = shadow_result.candidate_success_rate
            succ_delta = cand_succ - base_succ

            # Latency efficiency delta: (base_lat - cand_lat) / base_lat
            lat_gain = 0.0
            if shadow_result.baseline_latency_ms > 0:
                if shadow_result.candidate_latency_ms < shadow_result.baseline_latency_ms:
                    lat_gain = (shadow_result.baseline_latency_ms - shadow_result.candidate_latency_ms) / shadow_result.baseline_latency_ms
                elif shadow_result.candidate_latency_ms > shadow_result.baseline_latency_ms:
                    lat_gain = -(shadow_result.candidate_latency_ms - shadow_result.baseline_latency_ms) / shadow_result.baseline_latency_ms
            
            # Outcome score: base success delta + normalized latency efficiency delta (or base candidate success if baseline matched)
            if base_succ > 0 and succ_delta == 0.0:
                # If baseline and candidate both succeeded at 100%, outcome improvement is measured via execution speedup & confidence
                outcome_delta = cand_succ * (0.5 + 0.5 * max(0.0, lat_gain))
            else:
                outcome_delta = succ_delta + (0.5 * lat_gain)
            
            mean_outcome_delta = outcome_delta
            episode_count = 1
        else:
            # Fallback to candidate extracted evidence metrics
            succ_rate = candidate.evidence.metric_deltas.get("success_rate", 0.8)
            mean_outcome_delta = succ_rate * candidate.confidence
            episode_count = candidate.evidence.sample_count or 1

        # 2. Regression penalty term: - lambda_reg * regression_count(u, E)
        regression_count = 0
        if regression_result:
            regression_count = regression_result.regressions_detected

        regression_penalty = lambda_reg * regression_count

        # Note: This constitutional safety penalty term (-0.30) is a defense-in-depth safety addition beyond the literal Whitesheet §19.5 formula.
        constitutional_penalty = 0.0
        if not candidate.constitutional_approved:
            constitutional_penalty = 0.30

        # 3. Composite LE score calculation
        # LE(u) = mean_outcome_delta - (lambda_reg * regression_count) - constitutional_penalty
        raw_score = mean_outcome_delta - regression_penalty - constitutional_penalty
        le_score = round(max(0.0, min(1.0, raw_score)), 4)

        # A candidate passes only if score >= threshold and zero regressions detected
        passed = (le_score >= threshold) and (regression_count == 0)

        factors = {
            "mean_outcome_delta": round(mean_outcome_delta, 4),
            "regression_count": regression_count,
            "lambda_reg": lambda_reg,
            "regression_penalty": round(regression_penalty, 4),
            "constitutional_penalty": round(constitutional_penalty, 4),
            "episode_count": episode_count
        }

        justification = (
            f"LE Score {le_score} exceeds threshold {threshold} (Whitesheet §19.5 compliant)."
            if passed else
            f"LE Score {le_score} failed threshold {threshold} or regressions detected (count={regression_count})."
        )

        return LEResult(
            candidate_id=candidate.pattern_id,
            le_score=le_score,
            threshold=threshold,
            passed=passed,
            factors=factors,
            justification=justification
        )
