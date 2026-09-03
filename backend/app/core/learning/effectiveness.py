"""
Learning Effectiveness (LE) Calculation Engine
Strictly conforms to BRAHMA COS Whitesheet Learning System Specification.

Calculates reproducible, deterministic LE scores based on measurable performance,
efficiency, confidence, and risk factors.
"""
from typing import Dict, Any, Optional
from app.core.learning.models import LEResult, LearningCandidate, ShadowEvaluationResult, RegressionTestResult


class LearningEffectivenessEngine:
    """
    Evaluates learning candidate performance against multi-factor effectiveness thresholds.
    """
    DEFAULT_THRESHOLD: float = 0.70

    # Weights
    W_SUCCESS: float = 0.40
    W_EFFICIENCY: float = 0.30
    W_CONFIDENCE: float = 0.20
    W_RISK: float = 0.10

    @classmethod
    def calculate_le(
        cls,
        candidate: LearningCandidate,
        shadow_result: Optional[ShadowEvaluationResult] = None,
        regression_result: Optional[RegressionTestResult] = None,
        threshold: float = DEFAULT_THRESHOLD
    ) -> LEResult:
        """
        Calculates deterministic Learning Effectiveness score:
        LE = 0.40 * success_delta + 0.30 * efficiency_delta + 0.20 * confidence - 0.10 * risk_penalty
        """
        # 1. Success factor
        if shadow_result:
            success_factor = shadow_result.candidate_success_rate
            if shadow_result.baseline_latency_ms > 0:
                if shadow_result.candidate_latency_ms <= shadow_result.baseline_latency_ms:
                    eff_factor = 1.0
                else:
                    eff_factor = max(0.1, 1.0 - ((shadow_result.candidate_latency_ms - shadow_result.baseline_latency_ms) / shadow_result.baseline_latency_ms))
            else:
                eff_factor = 0.8
        else:
            success_factor = candidate.evidence.metric_deltas.get("success_rate", 0.8)
            eff_factor = 0.8

        # 2. Confidence factor
        confidence = candidate.confidence

        # 3. Risk penalty
        risk_penalty = 0.0
        if regression_result and regression_result.regressions_detected > 0:
            risk_penalty = 0.50  # Heavy penalty on regressions
        elif not candidate.constitutional_approved:
            risk_penalty = 0.30

        # Calculate composite score
        raw_score = (
            cls.W_SUCCESS * success_factor +
            cls.W_EFFICIENCY * eff_factor +
            cls.W_CONFIDENCE * confidence -
            cls.W_RISK * risk_penalty
        )
        le_score = round(max(0.0, min(1.0, raw_score)), 4)

        # A candidate passes only if score >= threshold and zero regressions detected
        passed = (le_score >= threshold) and (regression_result is None or regression_result.passed)

        factors = {
            "success_factor": round(success_factor, 4),
            "efficiency_factor": round(eff_factor, 4),
            "confidence": round(confidence, 4),
            "risk_penalty": round(risk_penalty, 4)
        }

        justification = (
            f"LE Score {le_score} exceeds threshold {threshold}"
            if passed else
            f"LE Score {le_score} failed threshold {threshold} or regressions detected."
        )

        return LEResult(
            candidate_id=candidate.pattern_id,
            le_score=le_score,
            threshold=threshold,
            passed=passed,
            factors=factors,
            justification=justification
        )
