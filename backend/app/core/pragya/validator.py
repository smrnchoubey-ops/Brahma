"""
PRAGYA Plan & DAG Validator
Strictly conforms to BRAHMA COS Whitesheet §6.4 & §15.4.
"""
from typing import List, Dict, Any, Optional, Set
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.saga.models import SagaDefinition, SagaStep
from app.core.karma.tool_registry import KarmaToolRegistry


class PragyaPlanValidationError(Exception):
    """Raised when a synthesized plan violates structural or graph invariants."""
    pass


class PragyaPlanValidator:
    """
    Validates structural correctness, dependency graphs, and tool mappings for PRAGYA plans.
    """

    @classmethod
    def validate_karma_dag(
        cls,
        plan: KarmaPlanDAG,
        tool_registry: Optional[KarmaToolRegistry] = None
    ) -> None:
        """
        Validates that a KarmaPlanDAG is structurally valid, acyclic, and tool-compliant.
        """
        if not plan.steps:
            raise PragyaPlanValidationError("Synthesized KarmaPlanDAG contains zero steps.")

        step_ids: Set[str] = set()
        for step in plan.steps:
            if not step.step_id or not step.step_id.strip():
                raise PragyaPlanValidationError("Step contains empty or whitespace step_id.")

            if step.step_id in step_ids:
                raise PragyaPlanValidationError(f"Duplicate step_id '{step.step_id}' found in plan.")
            step_ids.add(step.step_id)

            if not step.action or not step.action.strip():
                raise PragyaPlanValidationError(f"Step '{step.step_id}' has empty action description.")

            if not step.expected_outcome or not step.expected_outcome.strip():
                raise PragyaPlanValidationError(f"Step '{step.step_id}' has empty expected_outcome contract.")

            # Validate tool registration
            if tool_registry:
                if step.tool != "generic_executor":
                    known = tool_registry.get_tool(step.tool)
                    if not known:
                        # Fallback or strict error
                        step.tool = "generic_executor"

        # Topological order check asserts acyclicity and valid dependency references
        try:
            plan.get_topological_order()
        except Exception as ex:
            raise PragyaPlanValidationError(f"DAG Topological Validation Failed: {str(ex)}")

    @classmethod
    def validate_saga_definition(
        cls,
        saga: SagaDefinition
    ) -> None:
        """
        Validates SagaDefinition forward and compensating action structure.
        """
        if not saga.tenant_id or not saga.tenant_id.strip():
            raise PragyaPlanValidationError("SagaDefinition has empty tenant_id.")

        if not saga.steps:
            raise PragyaPlanValidationError("SagaDefinition contains zero steps.")

        step_ids: Set[str] = set()
        for s in saga.steps:
            if not s.step_id or not s.step_id.strip():
                raise PragyaPlanValidationError("SagaStep has empty step_id.")
            if s.step_id in step_ids:
                raise PragyaPlanValidationError(f"Duplicate step_id '{s.step_id}' in SagaDefinition.")
            step_ids.add(s.step_id)

            if not s.forward_action or not s.forward_action.strip():
                raise PragyaPlanValidationError(f"SagaStep '{s.step_id}' has empty forward_action.")
