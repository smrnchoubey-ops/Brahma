"""
MURPHY Risk Report & Tier Schemas
Strictly conforms to BRAHMA COS Whitesheet §11.3 & §11.4.
"""
from typing import Dict, Any, Optional, List
from enum import Enum
from pydantic import BaseModel, Field


class MurphyRiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class MurphyRecommendation(str, Enum):
    PROCEED = "PROCEED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    BLOCKED = "BLOCKED"


class MurphyRiskReport(BaseModel):
    """
    Structured machine-readable adversarial risk and simulation report.
    Matches Whitesheet §11.4.
    """
    risk_level: MurphyRiskTier
    blast_radius_score: float = Field(ge=0.0, le=1.0, description="Normalized quantitative blast-radius score [0.0, 1.0]")
    failure_modes: List[str] = Field(default_factory=list)
    security_concerns: List[str] = Field(default_factory=list)
    recommendation: MurphyRecommendation
    mitigations: List[str] = Field(default_factory=list)
    simulated_steps_count: int = 0
    chitra_event_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
