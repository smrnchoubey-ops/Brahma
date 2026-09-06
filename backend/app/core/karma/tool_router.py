"""
KARMA Tool Router & Capability Matching Engine
Strictly conforms to BRAHMA COS Whitesheet §7.4 & §7.9.

Implements deterministic capability x trust x cost routing subject to constitutional
compliance and authority token validation.
"""
import re
from typing import List, Dict, Any, Optional, Tuple, Union
from pydantic import BaseModel, Field

from app.core.karma.tool_registry import KarmaToolRegistry, KarmaToolDefinition
from app.core.karma.plan_dag import KarmaStep
from app.core.maryada.token import AuthorityToken
from app.core.maryada.authority_matrix import MaryadaAuthorityMatrix

AUTHORITY_LEVELS: Dict[str, int] = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4
}


class KarmaRoutingDecision(BaseModel):
    """
    Structured, auditable output of the KARMA Tool Router.
    Matches Whitesheet §7.4.
    """
    action: str = Field(..., description="Action query requested for routing")
    status: str = Field(..., description="'ROUTED' | 'NO_CAPABLE_TOOL' | 'INSUFFICIENT_AUTHORITY' | 'UNAVAILABLE' | 'CONSTITUTIONAL_VIOLATION'")
    selected_tool_id: Optional[str] = Field(default=None, description="Primary tool selected for execution")
    selected_tool_name: Optional[str] = Field(default=None, description="Name of selected tool")
    routing_score: float = Field(default=0.0, description="Calculated routing score (capability * trust * cost_efficiency)")
    fallback_chain: List[str] = Field(default_factory=list, description="Ranked ordered list of backup tool IDs (primary -> secondary -> tertiary)")
    rationale: str = Field(default="", description="Auditable reasoning for routing decision")
    evaluated_candidates_count: int = Field(default=0, description="Number of candidate tools evaluated")
    authority_level_used: str = Field(default="LOW", description="Authority tier used for evaluation")


class KarmaToolRouter:
    """
    Deterministic Tool Router.
    Calculates route(action) = argmax(capability_match * trust_score * cost_efficiency)
    subject to constitutional_compliance == True and authority_valid == True.
    Enforces §13.4 cryptographically signed AuthorityToken validation for privileged tools.
    """
    def __init__(self, registry: KarmaToolRegistry):
        self.registry = registry

    def _calculate_capability_match(self, tool: KarmaToolDefinition, action: str) -> float:
        """
        Computes deterministic capability match score in [0.0, 1.0].
        """
        action_clean = action.lower().strip()
        action_tokens = set(re.findall(r"\w+", action_clean))

        for cap in tool.capabilities:
            cap_clean = cap.lower().strip()
            # Exact capability class match
            if cap_clean == action_clean:
                return 1.0
            # Direct keyword containment
            if cap_clean in action_clean or action_clean in cap_clean:
                return 0.9
            # Token set intersection
            cap_tokens = set(re.findall(r"\w+", cap_clean))
            if action_tokens & cap_tokens:
                return 0.75

        return 0.0

    def route(
        self,
        action: str,
        caller_authority: Union[str, AuthorityToken, Dict[str, Any]] = "LOW",
        preferred_tool_id: Optional[str] = None,
        tenant_id: str = "global",
        require_signed_token: bool = False
    ) -> KarmaRoutingDecision:
        """
        Evaluates registered tools and returns the optimal tool routing decision.
        Does NOT execute any tool. Enforces §13.4 signed tokens for privileged tool routing when require_signed_token=True.
        """
        if not action or not action.strip():
            return KarmaRoutingDecision(
                action=action or "",
                status="NO_CAPABLE_TOOL",
                rationale="Cannot route empty action."
            )

        # Parse caller authority token or legacy string
        is_token_object = isinstance(caller_authority, (AuthorityToken, dict))
        is_serialized_token = isinstance(caller_authority, str) and (
            caller_authority.startswith("eyJ") or "hmac-sha256:" in caller_authority or len(caller_authority) > 50
        )

        auth_tok_validated: Optional[AuthorityToken] = None
        auth_tok_error: Optional[str] = None
        caller_tier = 1
        caller_auth_str = "LOW"

        if is_token_object or is_serialized_token:
            is_valid, auth_tok, tok_tier, tok_reason = MaryadaAuthorityMatrix.validate_authority_token(
                token=caller_authority,
                action_name=action,
                expected_tenant_id=tenant_id
            )
            if is_valid and tok_tier:
                auth_tok_validated = auth_tok
                caller_tier = AUTHORITY_LEVELS.get(tok_tier.value, 1)
                caller_auth_str = tok_tier.value
            else:
                auth_tok_error = tok_reason
                caller_tier = 0
                caller_auth_str = "INVALID_TOKEN"
        elif require_signed_token:
            auth_tok_error = "Missing required §13.4 cryptographically signed authority token for privileged execution."
            caller_tier = 0
            caller_auth_str = "UNSIGNED_PLAIN_STRING"
        else:
            caller_auth_str = str(caller_authority or "LOW").upper()
            caller_tier = AUTHORITY_LEVELS.get(caller_auth_str, 1)

        all_tools = self.registry.list_tools()

        # Step 1: Filter and score candidates
        scored_candidates: List[Tuple[float, KarmaToolDefinition, str]] = []
        ineligible_reasons: List[str] = []

        for tool in all_tools:
            # Calculate capability match first
            cap_match = self._calculate_capability_match(tool, action)
            if tool.tool_id == preferred_tool_id:
                cap_match = max(cap_match, 0.95)

            if cap_match <= 0.0:
                continue

            # Check operational availability
            if not tool.is_available:
                ineligible_reasons.append(f"Tool '{tool.tool_id}' is currently unavailable.")
                continue

            # Check constitutional compliance (SP-6)
            if not tool.constitutional_compliant:
                ineligible_reasons.append(f"Tool '{tool.tool_id}' failed constitutional compliance checks.")
                continue

            # Check authority gate (§10.1 & §13.4)
            tool_req_tier = AUTHORITY_LEVELS.get(tool.authority_required.upper(), 1)

            if auth_tok_error:
                ineligible_reasons.append(f"Tool '{tool.tool_id}' authority token rejected: {auth_tok_error}")
                continue

            if caller_tier < tool_req_tier:
                ineligible_reasons.append(
                    f"Tool '{tool.tool_id}' requires authority tier '{tool.authority_required}', "
                    f"caller provided '{caller_authority}'."
                )
                continue

            # Whitesheet formula: capability * trust * cost_efficiency
            score = cap_match * tool.trust_score * tool.cost_efficiency
            rationale_part = (
                f"cap={cap_match:.2f}, trust={tool.trust_score:.2f}, "
                f"cost_eff={tool.cost_efficiency:.2f} -> score={score:.4f}"
            )
            scored_candidates.append((score, tool, rationale_part))

        if not scored_candidates:
            # Determine specific rejection reason
            if any("requires" in r or "token" in r for r in ineligible_reasons):
                status = "INSUFFICIENT_AUTHORITY"
                rationale = "Candidate tools rejected due to insufficient authority: " + "; ".join(ineligible_reasons)
            elif any("unavailable" in r for r in ineligible_reasons):
                status = "UNAVAILABLE"
                rationale = "Candidate tools are currently offline/unavailable."
            elif any("constitutional" in r for r in ineligible_reasons):
                status = "CONSTITUTIONAL_VIOLATION"
                rationale = "Candidate tools rejected by constitutional governance constraints."
            else:
                status = "NO_CAPABLE_TOOL"
                rationale = f"No registered tool provides matching capabilities for action '{action}'."

            return KarmaRoutingDecision(
                action=action,
                status=status,
                rationale=rationale,
                evaluated_candidates_count=len(all_tools),
                authority_level_used=caller_auth_str
            )

        # Step 2: Deterministic sorting: (-score, -trust_score, cost, tool_id)
        scored_candidates.sort(
            key=lambda item: (-item[0], -item[1].trust_score, item[1].cost, item[1].tool_id)
        )

        winner_score, winner_tool, winner_rationale = scored_candidates[0]
        fallback_chain = [item[1].tool_id for item in scored_candidates]

        return KarmaRoutingDecision(
            action=action,
            status="ROUTED",
            selected_tool_id=winner_tool.tool_id,
            selected_tool_name=winner_tool.name,
            routing_score=round(winner_score, 4),
            fallback_chain=fallback_chain,
            rationale=f"Selected '{winner_tool.tool_id}' ({winner_rationale})",
            evaluated_candidates_count=len(all_tools),
            authority_level_used=caller_auth_str
        )

    def route_step(
        self,
        step: KarmaStep,
        caller_authority: Union[str, AuthorityToken, Dict[str, Any]] = "LOW",
        tenant_id: str = "global"
    ) -> KarmaRoutingDecision:
        """
        Routes a formal Phase 5 KarmaStep to the appropriate tool.
        Ensures caller_authority is evaluated against the registered tool's authority requirement.
        """
        # Step's claimed tool is treated only as a preference; authority is enforced against registered tool definition
        preferred = step.tool if step.tool != "generic_executor" else None
        return self.route(
            action=step.action,
            caller_authority=caller_authority,
            preferred_tool_id=preferred,
            tenant_id=tenant_id
        )
