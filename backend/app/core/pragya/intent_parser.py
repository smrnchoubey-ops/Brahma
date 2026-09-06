"""
PRAGYA Deterministic Intent Parser & Constraint Decomposition
Strictly conforms to BRAHMA COS Whitesheet §6.1 & §15.1.
"""
from typing import Dict, Any, Optional, List, Set
import re
from pydantic import BaseModel, Field

from app.core.karma.tool_registry import KarmaToolRegistry


class IntentDecomposition(BaseModel):
    """
    Formal representation of parsed intent, constraints, and requested capabilities.
    """
    raw_intent: str
    main_goal: str
    sub_goals: List[str] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    requested_capabilities: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    tenant_id: str
    task_id: int


class DeterministicIntentParser:
    """
    Extracts goals, sub-goals, explicit constraints, and tool requirements from user prompts.
    """

    @classmethod
    def parse_intent(
        cls,
        intent: str,
        tenant_id: str,
        task_id: int,
        tool_registry: Optional[KarmaToolRegistry] = None
    ) -> IntentDecomposition:
        """
        Parses raw user intent string into structured IntentDecomposition fail-closed.
        """
        # 1. Strict Validation
        if not intent or not intent.strip():
            raise ValueError("Intent cannot be empty or whitespace only (EMPTY_INTENT_REJECTED).")

        if not tenant_id or not tenant_id.strip():
            raise ValueError("Authenticated Tenant ID is required (AUTHENTICATED_TENANT_REQUIRED).")

        if not isinstance(task_id, int) or task_id <= 0:
            raise ValueError("Valid positive integer Task ID is required (INVALID_TASK_ID).")

        intent_clean = intent.strip()
        main_goal = intent_clean

        # 2. Sub-goal Decomposition
        sub_goals: List[str] = []
        # Split by conjunctions or sequence markers (and, then, followed by, commas)
        split_parts = re.split(r"\b(?:and then|then|followed by|and|after that)\b|;", intent_clean, flags=re.IGNORECASE)
        for part in split_parts:
            p_clean = part.strip()
            if p_clean and len(p_clean) > 2:
                sub_goals.append(p_clean)

        if not sub_goals:
            sub_goals = [intent_clean]

        # 3. Constraint Extraction
        constraints: Dict[str, Any] = {}
        # Timeout constraints
        timeout_match = re.search(r"\b(?:within|timeout|max time)\s+(\d+)\s*(s|sec|seconds|ms|m|minutes)?\b", intent_clean, re.I)
        if timeout_match:
            val = int(timeout_match.group(1))
            unit = timeout_match.group(2) or "s"
            if "m" in unit.lower():
                constraints["timeout_sec"] = val * 60
            else:
                constraints["timeout_sec"] = val

        # Read-only constraint
        if re.search(r"\b(read[ -]?only|audit|inspect|view|verify)\b", intent_clean, re.I):
            constraints["read_only"] = True

        # High-assurance constraint
        if re.search(r"\b(critical|secure|wire|transfer|payment|fund|prod|production)\b", intent_clean, re.I):
            constraints["elevated_risk"] = True

        # 4. Capability Mapping
        requested_caps: List[str] = []
        registry = tool_registry or KarmaToolRegistry()
        known_tools = registry.list_tools()

        for tool_def in known_tools:
            if tool_def.tool_id in intent_clean.lower() or any(cap in intent_clean.lower() for cap in tool_def.capabilities):
                requested_caps.extend(tool_def.capabilities)

        # Fallback keywords if not registered
        if not requested_caps:
            if re.search(r"\b(calculate|math|multiply|sum|divide|add)\b", intent_clean, re.I):
                requested_caps.append("math_compute")
            elif re.search(r"\b(calendar|schedule|holiday|date)\b", intent_clean, re.I):
                requested_caps.append("calendar_lookup")
            elif re.search(r"\b(search|find|retrieve|query|lookup)\b", intent_clean, re.I):
                requested_caps.append("knowledge_search")
            else:
                requested_caps.append("generic_execution")

        return IntentDecomposition(
            raw_intent=intent_clean,
            main_goal=main_goal,
            sub_goals=sub_goals,
            constraints=constraints,
            requested_capabilities=list(set(requested_caps)),
            assumptions=["User intent provided in English", "Execution environment is operational"],
            tenant_id=tenant_id,
            task_id=task_id
        )
