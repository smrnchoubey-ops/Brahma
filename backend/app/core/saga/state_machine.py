"""
SAGA State Machine & Invariant Transitions
Strictly conforms to BRAHMA COS Whitesheet §14.1 & §14.2.

Enforces fail-closed, valid state transitions with zero silent state changes.
"""
from typing import Dict, Set, Tuple
from app.core.saga.models import SagaStatus, SagaStepStatus


class SagaInvalidStateTransitionError(Exception):
    """Raised when an illegal Saga or Step state transition is attempted."""
    pass


# Legal state transition graph for Saga
LEGAL_SAGA_TRANSITIONS: Dict[SagaStatus, Set[SagaStatus]] = {
    SagaStatus.PENDING: {SagaStatus.RUNNING, SagaStatus.ABORTED},
    SagaStatus.RUNNING: {SagaStatus.SUCCEEDED, SagaStatus.FAILED, SagaStatus.COMPENSATING, SagaStatus.ABORTED},
    SagaStatus.COMPENSATING: {SagaStatus.COMPENSATED, SagaStatus.COMPENSATION_FAILED, SagaStatus.ABORTED},
    SagaStatus.SUCCEEDED: set(),
    SagaStatus.FAILED: {SagaStatus.COMPENSATING, SagaStatus.ABORTED},
    SagaStatus.COMPENSATED: set(),
    SagaStatus.COMPENSATION_FAILED: {SagaStatus.ABORTED},
    SagaStatus.ABORTED: set()
}

# Legal state transition graph for individual SagaStep
LEGAL_STEP_TRANSITIONS: Dict[SagaStepStatus, Set[SagaStepStatus]] = {
    SagaStepStatus.PENDING: {SagaStepStatus.RUNNING, SagaStepStatus.FAILED, SagaStepStatus.SKIPPED, SagaStepStatus.ABORTED},
    SagaStepStatus.RUNNING: {SagaStepStatus.SUCCEEDED, SagaStepStatus.FAILED, SagaStepStatus.ABORTED},
    SagaStepStatus.SUCCEEDED: {SagaStepStatus.COMPENSATING},
    SagaStepStatus.FAILED: set(),
    SagaStepStatus.COMPENSATING: {SagaStepStatus.COMPENSATED, SagaStepStatus.COMPENSATION_FAILED},
    SagaStepStatus.COMPENSATED: set(),
    SagaStepStatus.COMPENSATION_FAILED: set(),
    SagaStepStatus.SKIPPED: set(),
    SagaStepStatus.ABORTED: set()
}


class SagaStateMachine:
    """
    Deterministic transition validator for Saga lifecycle.
    """

    @classmethod
    def validate_saga_transition(cls, current: SagaStatus, target: SagaStatus) -> None:
        """
        Validates transition from current to target Saga state.
        Raises SagaInvalidStateTransitionError on illegal transition.
        """
        if current == target:
            return

        allowed = LEGAL_SAGA_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise SagaInvalidStateTransitionError(
                f"Illegal Saga transition from '{current.value}' to '{target.value}'. Allowed: {[s.value for s in allowed]}"
            )

    @classmethod
    def validate_step_transition(cls, current: SagaStepStatus, target: SagaStepStatus) -> None:
        """
        Validates transition from current to target SagaStep state.
        Raises SagaInvalidStateTransitionError on illegal transition.
        """
        if current == target:
            return

        allowed = LEGAL_STEP_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise SagaInvalidStateTransitionError(
                f"Illegal SagaStep transition from '{current.value}' to '{target.value}'. Allowed: {[s.value for s in allowed]}"
            )
