"""
OPERATIONAL MODES & RUNTIME MODE SELECTOR
Strictly conforms to BRAHMA COS Whitesheet §3.3 (Operational Modes) & Phase 6 (Autonomous Operations).

BRAHMA operates in one of four modes at any moment, selected by the runtime based on the
nature of the incoming task:
1. REACTIVE — Single-turn reasoning in response to a direct query. Most lightweight;
   all checkpoints still execute. (Standard / Manual mode)
2. DELIBERATIVE — Multi-step reasoning over complex problems. Engages future-state
   simulation heavily and invokes execution planning.
3. AUTONOMOUS — Long-horizon execution against a stated goal. Requires explicit
   authorization, continuous risk monitoring, and periodic human oversight checkpoints.
4. FEDERATED — Coordinating with peer agents across the Federation Layer for shared
   memory and consensus.

Mode selection is itself a decision logged in CHITRA with justification (Whitesheet §3.3).
"""
from enum import Enum
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class OperationalMode(str, Enum):
    REACTIVE = "REACTIVE"
    DELIBERATIVE = "DELIBERATIVE"
    AUTONOMOUS = "AUTONOMOUS"
    FEDERATED = "FEDERATED"

    @classmethod
    def validate_mode(cls, mode_str: Optional[str]) -> "OperationalMode":
        """
        Validates the runtime mode string. Fails safely on invalid or unknown modes.
        If None or empty, defaults to REACTIVE (standard single-turn / manual execution).
        """
        if mode_str is None or str(mode_str).strip() == "":
            return cls.REACTIVE
        
        normalized = str(mode_str).strip().upper()
        if normalized in ["MANUAL", "DEFAULT", "STANDARD", "REACTIVE"]:
            return cls.REACTIVE
        elif normalized == "DELIBERATIVE":
            return cls.DELIBERATIVE
        elif normalized == "AUTONOMOUS":
            return cls.AUTONOMOUS
        elif normalized == "FEDERATED":
            return cls.FEDERATED
        else:
            raise ValueError(
                f"Invalid operational mode '{mode_str}'. "
                f"Allowed modes per Whitesheet §3.3: {[m.value for m in cls]}"
            )

    @classmethod
    def get_mode_metadata(cls, mode: "OperationalMode") -> Dict[str, Any]:
        """Returns governance, audit retention, and execution parameters per mode."""
        if mode == cls.AUTONOMOUS:
            return {
                "mode": mode.value,
                "is_autonomous": True,
                "requires_explicit_auth": True,
                "retention_tier": "PERMANENT",  # Whitesheet §8.6
                "governance_bound": "STRICT_NON_BYPASSABLE",
                "description": "Long-horizon execution against a stated goal under continuous governance."
            }
        elif mode == cls.DELIBERATIVE:
            return {
                "mode": mode.value,
                "is_autonomous": False,
                "requires_explicit_auth": False,
                "retention_tier": "STANDARD",
                "governance_bound": "STRICT_NON_BYPASSABLE",
                "description": "Multi-step reasoning over complex problems."
            }
        elif mode == cls.FEDERATED:
            return {
                "mode": mode.value,
                "is_autonomous": False,
                "requires_explicit_auth": True,
                "retention_tier": "STANDARD",
                "governance_bound": "FEDERATED_CONSENSUS",
                "description": "Coordinating with peer agents across Federation Layer."
            }
        else:
            return {
                "mode": cls.REACTIVE.value,
                "is_autonomous": False,
                "requires_explicit_auth": False,
                "retention_tier": "STANDARD",
                "governance_bound": "STRICT_NON_BYPASSABLE",
                "description": "Single-turn reasoning in response to a direct query."
            }
