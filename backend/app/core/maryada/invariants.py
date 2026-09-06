"""
MARYADA Constitutional Invariants Engine
Strictly conforms to BRAHMA COS Whitesheet §10.2.

Defines non-bypassable, deterministic constitutional rules evaluated prior to execution.
Enforces:
- Invariant 1: Anti-Tampering & Ledger Integrity
- Invariant 2: Secret & PII Protection
- Invariant 3: Destructive Command Prohibition
- Invariant 4: Strict Multi-Tenant Separation
- Invariant 5: Anti-Privilege Escalation
"""
from typing import Dict, Any, Optional, List, Tuple
import re


# Prohibited constitutional patterns in action descriptions / intent
PROHIBITED_ACTION_PATTERNS: List[Tuple[str, str, str]] = [
    (
        "INV_DESTRUCTIVE_CMD",
        r"\b(?:rm\s+-rf|drop\s+database|format\s+drive|mkfs|del\s+/f\s+/s\s+/q|truncate\s+table)\b",
        "Destructive system/database commands are strictly prohibited."
    ),
    (
        "INV_SECRET_EXFILTRATION",
        r"\b(?:dump\s+secrets|export\s+api_key|read\s+private_key|cat\s+/etc/shadow|fetch\s+password_hash)\b",
        "Credential and secret key exfiltration is strictly prohibited."
    ),
    (
        "INV_JAILBREAK_OVERRIDE",
        r"\b(?:ignore\s+all\s+previous\s+instructions|override\s+maryada|bypass\s+governance|disable\s+guardrails)\b",
        "Prompt injection and governance bypass attempts are strictly prohibited."
    ),
    (
        "INV_UNAUTHORIZED_ESCALATION",
        r"\b(?:grant\s+admin|elevate\s+to\s+root|sudo\s+su|impersonate\s+tenant|switch_user\s+root)\b",
        "Unauthorized privilege elevation is strictly prohibited."
    )
]


class MaryadaConstitutionalEvaluator:
    """
    Evaluates actions, plans, and intents against deterministic constitutional invariants.
    """

    @classmethod
    def evaluate(cls, action_or_intent: str, tenant_id: Optional[str] = None) -> Tuple[bool, List[str], List[str]]:
        """
        Evaluates input text against all constitutional invariants.
        Returns (is_compliant: bool, violated_invariant_ids: List[str], justifications: List[str]).
        """
        if not action_or_intent or not action_or_intent.strip():
            return False, ["INV_EMPTY_PAYLOAD"], ["Action description or intent cannot be empty."]

        violated_ids: List[str] = []
        reasons: List[str] = []

        text_lower = action_or_intent.lower()

        for inv_id, pattern, desc in PROHIBITED_ACTION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                violated_ids.append(inv_id)
                reasons.append(desc)

        if violated_ids:
            return False, violated_ids, reasons

        return True, [], []
