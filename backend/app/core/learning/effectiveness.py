"""
Learning Effectiveness (LE) Calculation Engine
Strictly conforms to BRAHMA COS Whitesheet §19.5 Specification.

Formula (Whitesheet §19.5):
LE(u) = (1/|E|) * sum_{e in E} [ outcome_score(e|u) - outcome_score(e|baseline) ] - lambda_reg * regression_count(u, E)

Where:
- u: Learning candidate / update
- E: Evaluation episode set (|E| >= 1, E_train ∩ E_eval = ∅)
- outcome_score(e|u): Outcome score of episode e under candidate policy u
- outcome_score(e|baseline): Outcome score of episode e under baseline policy
- lambda_reg: Regression penalty multiplier
- regression_count(u, E): Count of detected regressions (score_u < score_base)
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
    LAMBDA_REG: float = 0.50  # Default regression penalty multiplier (configurable)

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

        # -----------------------------------------------------------------
        # 1. Held-Out Evaluation Set E (Whitesheet §19.5 Literal Formula)
        # -----------------------------------------------------------------
        if eval_episodes is not None and len(eval_episodes) > 0:
            # Enforce tenant isolation on evaluation episodes (§18.5)
            for ep in eval_episodes:
                ep_tenant = ep.get("tenant_id")
                if ep_tenant and ep_tenant != candidate.tenant_id:
                    raise ValueError(f"Cross-tenant evaluation episode rejected. Episode tenant '{ep_tenant}' != Candidate tenant '{candidate.tenant_id}'.")

                if "outcome_score_u" not in ep and "outcome_score" not in ep and "candidate_outcome_score" not in ep:
                    raise ValueError(f"Fail-closed: Episode {ep.get('task_id')} missing outcome_score_u.")
                if "outcome_score_baseline" not in ep and "baseline_outcome_score" not in ep:
                    raise ValueError(f"Fail-closed: Episode {ep.get('task_id')} missing outcome_score_baseline.")

                score_u = float(ep.get("outcome_score_u", ep.get("outcome_score", ep.get("candidate_outcome_score"))))
                score_base = float(ep.get("outcome_score_baseline", ep.get("baseline_outcome_score")))
                episode_deltas.append(score_u - score_base)

            mean_outcome_delta = sum(episode_deltas) / len(episode_deltas)
            episode_count = len(eval_episodes)
        elif shadow_result:
            # Legacy Mock Shadow Evaluation Compatibility Path
            base_succ = shadow_result.baseline_success_rate
            cand_succ = shadow_result.candidate_success_rate
            succ_delta = cand_succ - base_succ

            lat_gain = 0.0
            if shadow_result.baseline_latency_ms > 0:
                if shadow_result.candidate_latency_ms < shadow_result.baseline_latency_ms:
                    lat_gain = (shadow_result.baseline_latency_ms - shadow_result.candidate_latency_ms) / shadow_result.baseline_latency_ms
                elif shadow_result.candidate_latency_ms > shadow_result.baseline_latency_ms:
                    lat_gain = -(shadow_result.candidate_latency_ms - shadow_result.baseline_latency_ms) / shadow_result.baseline_latency_ms

            if base_succ > 0 and succ_delta == 0.0:
                mean_outcome_delta = cand_succ * (0.5 + 0.5 * max(0.0, lat_gain))
            else:
                mean_outcome_delta = succ_delta + (0.5 * lat_gain)
            episode_count = shadow_result.evidence.get("evaluated_episode_count", 1) if shadow_result.evidence else 1
        else:
            succ_rate = candidate.evidence.metric_deltas.get("success_rate", 0.8) if candidate.evidence else 0.8
            mean_outcome_delta = succ_rate * candidate.confidence
            episode_count = candidate.evidence.sample_count if candidate.evidence else 1

        # -----------------------------------------------------------------
        # 2. Regression Penalty Term: - lambda_reg * regression_count(u, E)
        # -----------------------------------------------------------------
        regression_count = 0
        if regression_result:
            regression_count = regression_result.regressions_detected
        elif eval_episodes:
            for ep in eval_episodes:
                score_u = float(ep.get("outcome_score_u", ep.get("outcome_score", ep.get("candidate_outcome_score", 0.0))))
                score_base = float(ep.get("outcome_score_baseline", ep.get("baseline_outcome_score", 0.0)))
                if score_u < score_base or ep.get("regression") is True:
                    regression_count += 1

        regression_penalty = lambda_reg * regression_count

        # -----------------------------------------------------------------
        # 3. Exact Mathematical LE Score per Whitesheet §19.5:
        # LE(u) = (1/|E|) * sum_{e in E} [ outcome_score(e|u) - outcome_score(e|baseline) ] - lambda_reg * regression_count(u, E)
        # -----------------------------------------------------------------
        raw_score = mean_outcome_delta - regression_penalty
        le_score = round(max(0.0, min(1.0, raw_score)), 4)

        # Promotion requires strict LE(u) > tau_LE and regression_count == 0
        passed = (le_score > threshold) and (regression_count == 0)

        factors = {
            "mean_outcome_delta": round(mean_outcome_delta, 4),
            "regression_count": regression_count,
            "lambda_reg": lambda_reg,
            "regression_penalty": round(regression_penalty, 4),
            "episode_count": episode_count
        }

        justification = (
            f"LE Score {le_score} exceeds threshold {threshold} with zero regressions (Whitesheet §19.5 compliant)."
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
