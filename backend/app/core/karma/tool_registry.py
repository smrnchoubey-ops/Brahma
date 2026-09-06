"""
KARMA Tool Registry & Trust Model
Strictly conforms to BRAHMA COS Whitesheet §7.4 & Appendix F (SP-6).

Maintains registered execution tools, their declared capabilities, dynamic trust scores,
cost structures, and authority gates.
"""
from typing import List, Dict, Any, Optional, Set
from pydantic import BaseModel, Field
import math


class KarmaToolDefinition(BaseModel):
    """
    Formal registration envelope for a tool in the KARMA ecosystem.
    Matches Whitesheet §7.4 & Appendix F SP-6.
    """
    tool_id: str = Field(..., min_length=1, description="Unique identifier for the tool")
    name: str = Field(..., min_length=1, description="Human-readable tool name")
    description: str = Field(default="", description="Description of tool functionality")
    capabilities: List[str] = Field(..., min_length=1, description="List of action capabilities/classes supported")
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Dynamic trust score (0.0 to 1.0)")
    cost: float = Field(default=0.0, ge=0.0, description="Estimated execution cost / resource weight")
    authority_required: str = Field(default="LOW", description="Required authority tier ('LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL')")
    is_available: bool = Field(default=True, description="Whether tool is operational")
    constitutional_compliant: bool = Field(default=True, description="Whether tool complies with Constitution (SP-6)")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def cost_efficiency(self) -> float:
        """
        Calculates cost efficiency normalized in (0, 1].
        Higher cost results in lower efficiency.
        """
        return 1.0 / (1.0 + self.cost)


class KarmaToolRegistry:
    """
    Central thread-safe registry of all KARMA execution tools.
    """
    def __init__(self):
        self._tools: Dict[str, KarmaToolDefinition] = {}

    def register_tool(self, tool: KarmaToolDefinition) -> None:
        """Registers or updates a tool in the registry."""
        if not tool.tool_id:
            raise ValueError("Cannot register tool with empty tool_id.")
        self._tools[tool.tool_id] = tool

    def get_tool(self, tool_id: str) -> Optional[KarmaToolDefinition]:
        """Retrieves a tool definition by ID."""
        return self._tools.get(tool_id)

    def list_tools(self) -> List[KarmaToolDefinition]:
        """Returns all registered tools."""
        return list(self._tools.values())

    def update_trust_score(self, tool_id: str, new_score: float) -> None:
        """Updates the trust score for a tool (§7.4, SP-6)."""
        if tool_id not in self._tools:
            raise KeyError(f"Tool '{tool_id}' not found in registry.")
        if not (0.0 <= new_score <= 1.0):
            raise ValueError("Trust score must be between 0.0 and 1.0.")
        self._tools[tool_id].trust_score = new_score

    def set_availability(self, tool_id: str, available: bool) -> None:
        """Sets tool operational availability."""
        if tool_id not in self._tools:
            raise KeyError(f"Tool '{tool_id}' not found in registry.")
        self._tools[tool_id].is_available = available

    def clear(self) -> None:
        """Clears all registered tools (for testing)."""
        self._tools.clear()


# Default standard tool definitions for BRAHMA runtime
def get_default_tool_registry() -> KarmaToolRegistry:
    registry = KarmaToolRegistry()

    default_tools = [
        KarmaToolDefinition(
            tool_id="calculator",
            name="Safe AST Math Calculator",
            description="Computes safe arithmetic expressions without eval()",
            capabilities=["calculate", "math", "arithmetic", "compute"],
            trust_score=0.99,
            cost=0.01,
            authority_required="LOW"
        ),
        KarmaToolDefinition(
            tool_id="calendar_service",
            name="Corporate Calendar Lookup",
            description="Queries organizational holiday and schedule calendars",
            capabilities=["calendar_lookup", "schedule", "holidays"],
            trust_score=0.95,
            cost=0.02,
            authority_required="LOW"
        ),
        KarmaToolDefinition(
            tool_id="policy_service",
            name="Governance Policy Engine",
            description="Queries verified company governance rules and policies",
            capabilities=["policy_lookup", "governance", "guidelines"],
            trust_score=0.98,
            cost=0.05,
            authority_required="LOW"
        ),
        KarmaToolDefinition(
            tool_id="system_status",
            name="Platform Telemetry Diagnostic",
            description="Queries platform operational status and health metrics",
            capabilities=["system_status", "health_check", "telemetry"],
            trust_score=0.95,
            cost=0.01,
            authority_required="LOW"
        ),
        KarmaToolDefinition(
            tool_id="echo_formatter",
            name="Text Formatter & Echo",
            description="Formats and structures output text",
            capabilities=["echo", "format_text", "deliverable_summary"],
            trust_score=0.90,
            cost=0.01,
            authority_required="LOW"
        ),
        KarmaToolDefinition(
            tool_id="knowledge_retriever",
            name="KOSH Semantic Knowledge Retriever",
            description="Queries tenant-isolated semantic knowledge embeddings",
            capabilities=["retrieval", "search", "lookup_knowledge"],
            trust_score=0.92,
            cost=0.10,
            authority_required="MEDIUM"
        ),
        KarmaToolDefinition(
            tool_id="financial_settlement_api",
            name="Core Banking Settlement API",
            description="Executes high-risk monetary transaction settlements",
            capabilities=["settlement", "execute_trade", "wire_transfer"],
            trust_score=0.85,
            cost=2.50,
            authority_required="HIGH"
        )
    ]

    for t in default_tools:
        registry.register_tool(t)

    return registry
