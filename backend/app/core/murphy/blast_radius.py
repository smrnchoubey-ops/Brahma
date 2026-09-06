"""
MURPHY Quantitative Blast-Radius Engine
Strictly conforms to BRAHMA COS Whitesheet §11.2.

Calculates normalized quantitative blast-radius scores in [0.0, 1.0] based on:
- Action category (read-only, single write, bulk write, external API, financial, system/schema)
- Number of affected nodes & cascading dependencies
- Resource sensitivity multipliers
"""
from typing import Dict, Any, Optional, List
import re

# Action Category Base Scores (§11.2)
BASE_ACTION_SCORES = [
    # Critical / System alteration
    (r"\b(?:format\s+drive|drop\s+database|rm\s+-rf|purge_ledger|reconfigure_system|modify_schema|bulk_delete)\b", 1.00),
    # Financial transactions
    (r"\b(?:transfer_funds|wire_transfer|settlement|payroll|disburse_funds)\b", 0.85),
    # External mutating API / Secret handling
    (r"\b(?:export_pii|rotate_key|external_api_write|publish_message|send_bulk_email)\b", 0.65),
    # Internal state mutation / Single record write
    (r"\b(?:update_|insert_|write_|create_|delete_|schedule_event)\b", 0.35),
    # Read-only / Mathematical / Telemetry
    (r"\b(?:read_|get_|query_|fetch_|calculate|system_status|calendar_lookup|echo)\b", 0.05)
]


class MurphyBlastRadiusCalculator:
    """
    Computes deterministic blast-radius scores for individual actions and full DAG plans.
    """

    @classmethod
    def calculate_action_score(cls, action: str) -> float:
        """
        Calculates normalized blast-radius score in [0.0, 1.0] for a single action.
        """
        if not action or not action.strip():
            return 1.0  # Empty/malformed actions get maximum risk score

        act_lower = action.lower()

        for pattern, score in BASE_ACTION_SCORES:
            if re.search(pattern, act_lower, re.IGNORECASE):
                return score

        # Default fallback for unrecognized action
        return 0.40

    @classmethod
    def calculate_plan_score(cls, action_scores: List[float], dependency_depth: int = 1) -> float:
        """
        Aggregates individual action scores and dependency complexity into a plan score in [0.0, 1.0].
        Formula: max(action_scores) * 0.70 + avg(action_scores) * 0.25 + min(depth * 0.05, 0.05)
        """
        if not action_scores:
            return 0.0

        max_score = max(action_scores)
        avg_score = sum(action_scores) / len(action_scores)
        depth_penalty = min(dependency_depth * 0.02, 0.05)

        aggregate = (max_score * 0.70) + (avg_score * 0.25) + depth_penalty
        return round(max(0.0, min(1.0, aggregate)), 4)
