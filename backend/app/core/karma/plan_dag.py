"""
KARMA Plan DAG & Step Model
Strictly conforms to BRAHMA COS Whitesheet §7.1, §7.2, §7.5 & §7.9.

Represents formal, executable directed acyclic graphs of steps with explicit dependencies,
retry policies, authority scopes, and topological validation.
"""
from typing import List, Dict, Any, Optional, Set
from pydantic import BaseModel, Field, model_validator
from collections import deque
import uuid


class KarmaRetryPolicy(BaseModel):
    """
    Per-step retry policy with exponential backoff and circuit breaker.
    Matches Whitesheet §7.5.
    """
    max_attempts: int = Field(default=3, ge=1, le=10, description="Max retry attempts for step")
    backoff: str = Field(default="exponential", description="Backoff strategy ('exponential' | 'constant' | 'linear')")
    base_delay_ms: int = Field(default=200, ge=0, description="Base delay in milliseconds")
    jitter: bool = Field(default=True, description="Whether to apply randomized jitter")
    circuit_break_after: int = Field(default=5, ge=1, description="Failure threshold before circuit break")
    circuit_break_window_seconds: int = Field(default=60, ge=1, description="Sliding window for circuit breaker")


class KarmaStep(BaseModel):
    """
    Individual node in the KARMA Plan DAG.
    Matches Whitesheet §7.2 & §7.9 (No Silent Actions).
    """
    step_id: str = Field(..., min_length=1, description="Unique identifier for the step (e.g. 'step_1')")
    action: str = Field(..., min_length=1, description="Description of the action to execute")
    tool: str = Field(default="generic_executor", description="Target tool or subsystem to invoke")
    reason: str = Field(default="", description="Why this action is needed (provenance/intent)")
    expected_outcome: str = Field(..., min_length=1, description="Declarative description of expected success criteria")
    dependencies: List[str] = Field(default_factory=list, description="List of upstream step_ids that must complete before this step")
    retry_policy: KarmaRetryPolicy = Field(default_factory=KarmaRetryPolicy, description="Per-step retry configuration")
    authority_required: str = Field(default="LOW", description="Required authority / risk tier ('LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL')")
    
    # State tracking
    status: str = Field(default="PENDING", description="Status ('PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'BLOCKED')")
    actual_outcome: Optional[Any] = Field(default=None, description="Populated post-execution")
    ledger_entry_ref: Optional[str] = Field(default=None, description="Referenced CHITRA event ID")


class KarmaPlanDAG(BaseModel):
    """
    Executable Directed Acyclic Graph (DAG) for a task plan.
    Matches Whitesheet §7.2.
    """
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    task_id: int = Field(..., description="Foreign key to owning Task")
    summary: str = Field(..., min_length=1, description="Overall summary of the plan")
    steps: List[KarmaStep] = Field(..., min_length=1, description="List of plan DAG step nodes")
    assumptions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dag(self) -> "KarmaPlanDAG":
        """
        Validates graph integrity:
        1. No duplicate step_ids.
        2. All dependency references exist.
        3. No self-dependencies.
        4. Cycle detection via Kahn's algorithm (topological sort).
        """
        if not self.steps:
            raise ValueError("KARMA Plan DAG must contain at least one step.")

        step_ids: Set[str] = set()
        for step in self.steps:
            if step.step_id in step_ids:
                raise ValueError(f"Duplicate step_id '{step.step_id}' found in Plan DAG.")
            step_ids.add(step.step_id)

        # Check dependency references
        for step in self.steps:
            for dep in step.dependencies:
                if dep == step.step_id:
                    raise ValueError(f"Self-dependency detected: Step '{step.step_id}' cannot depend on itself.")
                if dep not in step_ids:
                    raise ValueError(f"Missing dependency: Step '{step.step_id}' depends on non-existent step '{dep}'.")

        # Cycle detection using Kahn's algorithm
        in_degree: Dict[str, int] = {s.step_id: 0 for s in self.steps}
        adj_list: Dict[str, List[str]] = {s.step_id: [] for s in self.steps}

        for step in self.steps:
            for dep in step.dependencies:
                adj_list[dep].append(step.step_id)
                in_degree[step.step_id] += 1

        queue = deque([s_id for s_id, deg in in_degree.items() if deg == 0])
        visited_count = 0

        while queue:
            node = queue.popleft()
            visited_count += 1
            for neighbor in adj_list[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(self.steps):
            raise ValueError("Cycle detected: Plan DAG contains circular dependencies.")

        return self

    def get_topological_order(self) -> List[KarmaStep]:
        """
        Returns steps in deterministic topological execution order.
        """
        in_degree: Dict[str, int] = {s.step_id: len(s.dependencies) for s in self.steps}
        adj_list: Dict[str, List[str]] = {s.step_id: [] for s in self.steps}
        steps_map = {s.step_id: s for s in self.steps}

        for step in self.steps:
            for dep in step.dependencies:
                adj_list[dep].append(step.step_id)

        # Use deterministic alphabetical/index sorting for nodes with degree 0
        queue = deque(sorted([s_id for s_id, deg in in_degree.items() if deg == 0]))
        ordered_steps: List[KarmaStep] = []

        while queue:
            node = queue.popleft()
            ordered_steps.append(steps_map[node])
            for neighbor in sorted(adj_list[node]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return ordered_steps

    def get_roots(self) -> List[KarmaStep]:
        """Returns all entrypoint steps (steps with 0 dependencies)."""
        return [s for s in self.steps if len(s.dependencies) == 0]

    def get_dependents(self, step_id: str) -> List[KarmaStep]:
        """Returns direct downstream steps that depend on step_id."""
        return [s for s in self.steps if step_id in s.dependencies]
