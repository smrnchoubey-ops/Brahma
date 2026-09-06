from typing import TypedDict, Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field

# Pydantic models for Structured Agent Outputs

class PragyaPlan(BaseModel):
    summary: str = Field(description="A concise summary of the reasoning and plan.")
    steps: List[str] = Field(description="A list of specific steps to execute the plan.")
    tools_needed: List[str] = Field(description="List of tools or systems required to execute the plan.")
    assumptions: List[str] = Field(description="List of any assumptions made during planning.")

class MurphyRiskReport(BaseModel):
    risk_level: str = Field(description="The overall risk level. One of: LOW, MEDIUM, HIGH, CRITICAL.")
    failure_modes: List[str] = Field(description="Identified edge cases or failure modes in the plan.")
    security_concerns: List[str] = Field(description="Any security, compliance, or governance concerns.")
    recommendation: str = Field(description="Brief recommendation on whether to proceed, modify, or block.")

class PolicyVerdict(BaseModel):
    risk_tier: str = Field(description="The final assessed risk tier. LOW, MEDIUM, HIGH.")
    approved: bool = Field(description="True if the plan is approved for execution, False if it requires human review or is denied.")
    requires_human: bool = Field(description="True if human intervention is required.")
    justification: str = Field(description="The justification for the verdict.")

# LangGraph State Schema

class AgentState(TypedDict):
    # Tracing / Identity
    task_id: int
    user_id: Optional[int]
    tenant_id: Optional[str]
    session_id: Optional[str]
    trace_id: str
    
    # Input
    intent: str
    memory_context: Optional[str]
    knowledge_context: Optional[str]
    
    # Execution State
    current_agent: str
    status: str
    errors: List[str]
    
    # Structured Agent Outputs
    plan: Optional[Dict[str, Any]]  # PragyaPlan dumped to dict
    risk_report: Optional[Dict[str, Any]] # MurphyRiskReport dumped to dict
    policy_verdict: Optional[Dict[str, Any]] # PolicyVerdict dumped to dict
    
    # Execution Result
    execution_result: Optional[Union[str, Dict[str, Any]]]
