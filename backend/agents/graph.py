from typing import Dict, Any, Literal
# pyrefly: ignore [missing-import]
from langgraph.graph import StateGraph, END
from .state import AgentState
from .nodes.karma import karma_node
from .nodes.smriti import smriti_node
from .nodes.pragya import pragya_node
from .nodes.murphy import murphy_node
from .nodes.maryada import maryada_node
from .nodes.rachit import rachit_node
from .nodes.kosh import kosh_node

def route_after_maryada(state: AgentState) -> Literal["rachit", "__end__"]:
    """
    Conditional routing logic:
    If the policy verdict is approved, route to RACHIT for execution.
    Otherwise, end the graph (escalate to human).
    """
    verdict = state.get("policy_verdict", {})
    if verdict.get("approved") is True:
        return "rachit"
    return "__end__"

# Build the Graph
workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("karma", karma_node)
workflow.add_node("smriti", smriti_node)
workflow.add_node("kosh", kosh_node)
workflow.add_node("pragya", pragya_node)
workflow.add_node("murphy", murphy_node)
workflow.add_node("maryada", maryada_node)
workflow.add_node("rachit", rachit_node)

# Define Edges
workflow.set_entry_point("karma")
workflow.add_edge("karma", "smriti")
workflow.add_edge("smriti", "kosh")
workflow.add_edge("kosh", "pragya")
workflow.add_edge("pragya", "murphy")
workflow.add_edge("murphy", "maryada")

# Conditional Edge
workflow.add_conditional_edges(
    "maryada",
    route_after_maryada,
    {
        "rachit": "rachit",
        "__end__": END
    }
)
workflow.add_edge("rachit", END)

# Compile the final application
brahma_app = workflow.compile()
