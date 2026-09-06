"""
KARMA DAG Executor & Dependency Walker with Retry, Circuit Breaker & Verification
Strictly conforms to BRAHMA COS Whitesheet §7.1, §7.3, §7.4, §7.5, §7.6 & §7.7.

Walks validated KarmaPlanDAGs, evaluates tool routing, manages circuit breaker states,
enforces exponential retry policies, executes the 3-tier verification layer, and
dispatches recovery strategies.
"""
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import time
import random

from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep, KarmaRetryPolicy
from app.core.karma.tool_router import KarmaToolRouter, KarmaRoutingDecision
from app.core.karma.tool_registry import KarmaToolRegistry, get_default_tool_registry
from app.core.karma.circuit_breaker import KarmaCircuitBreakerRegistry, KarmaCircuitBreaker, CircuitState
from app.core.karma.verifier import KarmaStepVerifier, KarmaVerificationResult
from app.core.karma.recovery import KarmaRecoveryEngine, KarmaRecoveryDecision
from app.core.karma.completion_validator import KarmaCompletionValidator, KarmaCompletionValidationResult
from agents.execution.registry import ACTION_REGISTRY, ExecutionError, ActionSecurityError
from app.repositories.chitra_repository import chitra_repository


class KarmaStepExecutionResult(BaseModel):
    """
    Detailed execution result and evidence for a single DAG step.
    Matches Whitesheet §7.3, §7.5, §7.7, §7.8 & §7.9.
    """
    step_id: str
    action: str
    status: str = Field(description="'PENDING' | 'READY' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'BLOCKED' | 'SKIPPED' | 'ESCALATED'")
    tool_id: Optional[str] = None
    tool_name: Optional[str] = None
    output: Optional[Any] = None
    error: Optional[str] = None
    attempts_made: int = 1
    verification_status: Optional[str] = None
    verification_details: Dict[str, Any] = Field(default_factory=dict)
    recovery_decision: Optional[Dict[str, Any]] = None
    completion_validation: Optional[Dict[str, Any]] = None
    execution_evidence: Dict[str, Any] = Field(default_factory=dict)
    chitra_event_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class KarmaDAGExecutionReport(BaseModel):
    """
    Comprehensive execution report for the entire KARMA Plan DAG.
    Matches Whitesheet §7.3.
    """
    plan_id: str
    task_id: int
    status: str = Field(description="'COMPLETED' | 'FAILED' | 'PARTIALLY_COMPLETED' | 'BLOCKED' | 'ESCALATED'")
    total_steps: int
    succeeded_steps_count: int
    failed_steps_count: int
    blocked_steps_count: int
    escalated_steps_count: int = 0
    step_results: Dict[str, KarmaStepExecutionResult]
    execution_order: List[str]
    summary: str


class KarmaDAGExecutor:
    """
    Walks and executes KarmaPlanDAGs step-by-step with retry, circuit breaker,
    verification, and recovery capabilities.
    """
    def __init__(
        self,
        router: Optional[KarmaToolRouter] = None,
        registry: Optional[KarmaToolRegistry] = None,
        circuit_registry: Optional[KarmaCircuitBreakerRegistry] = None,
        custom_handlers: Optional[Dict[str, Callable]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None
    ):
        self.registry = registry or get_default_tool_registry()
        self.router = router or KarmaToolRouter(self.registry)
        self.circuit_registry = circuit_registry or KarmaCircuitBreakerRegistry()
        self.handlers = custom_handlers or {}
        self._sleep_fn = sleep_fn or time.sleep

    def _execute_tool_handler(self, tool_id: str, action: str, params: Dict[str, Any]) -> Any:
        """Invokes the actual tool handler safely."""
        if tool_id in self.handlers:
            return self.handlers[tool_id](params)

        if tool_id in ACTION_REGISTRY:
            handler = ACTION_REGISTRY[tool_id]["handler"]
            return handler(params)

        if tool_id == "calculator":
            expr = params.get("expression") or params.get("expr") or params.get("text") or action
            return ACTION_REGISTRY["calculate"]["handler"]({"expression": expr})
        elif tool_id == "calendar_service":
            return ACTION_REGISTRY["calendar_lookup"]["handler"]({})
        elif tool_id == "policy_service":
            return ACTION_REGISTRY["policy_lookup"]["handler"]({"topic": action})
        elif tool_id == "system_status":
            return ACTION_REGISTRY["system_status"]["handler"]({})
        elif tool_id == "echo_formatter":
            return ACTION_REGISTRY["echo"]["handler"]({"text": action})

        raise ExecutionError(f"No executable handler registered for tool '{tool_id}'.")

    def _calculate_backoff_delay(self, attempt: int, policy: KarmaRetryPolicy) -> float:
        """
        Calculates exponential backoff delay in seconds with jitter.
        Matches Whitesheet §7.5.
        """
        base_sec = max(policy.base_delay_ms, 0) / 1000.0
        if policy.backoff == "exponential":
            delay = base_sec * (2 ** (attempt - 1))
        elif policy.backoff == "linear":
            delay = base_sec * attempt
        else:
            delay = base_sec

        if policy.jitter:
            delay = delay * (1.0 + random.uniform(0.0, 0.2))

        return delay

    def execute_plan(
        self,
        plan: KarmaPlanDAG,
        caller_authority: str = "LOW",
        db_session: Optional[Any] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        compensating_action_map: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> KarmaDAGExecutionReport:
        """
        Executes a validated KarmaPlanDAG with full retry, circuit breaker, verification,
        and recovery handling.
        """
        if not plan or not plan.steps:
            raise ValueError("Cannot execute empty or null KARMA Plan DAG.")

        plan.validate_dag()

        step_results: Dict[str, KarmaStepExecutionResult] = {}
        for s in plan.steps:
            step_results[s.step_id] = KarmaStepExecutionResult(
                step_id=s.step_id,
                action=s.action,
                status="PENDING"
            )

        execution_order: List[str] = []
        tenant_scope = f"tenant_{user_id}" if user_id else "global"

        # Dependency resolution loop
        while True:
            pending_steps = [s for s in plan.steps if step_results[s.step_id].status == "PENDING"]
            if not pending_steps:
                break

            progress_made = False

            # Check for newly blocked steps
            for step in pending_steps:
                has_failed_dep = any(
                    step_results[dep].status in ["FAILED", "BLOCKED", "ESCALATED"]
                    for dep in step.dependencies
                )
                if has_failed_dep:
                    step_results[step.step_id].status = "BLOCKED"
                    step_results[step.step_id].error = "Execution blocked: one or more upstream dependencies failed."
                    progress_made = True

            pending_steps = [s for s in plan.steps if step_results[s.step_id].status == "PENDING"]
            if not pending_steps:
                break

            # Find ready steps (all dependencies SUCCEEDED)
            ready_steps = [
                s for s in pending_steps
                if all(step_results[dep].status == "SUCCEEDED" for dep in s.dependencies)
            ]

            if not ready_steps:
                # Stalled DAG state
                for step in pending_steps:
                    step_results[step.step_id].status = "BLOCKED"
                    step_results[step.step_id].error = "Execution stalled: dependencies could not be satisfied."
                break

            # Sort ready steps deterministically
            ready_steps.sort(key=lambda s: s.step_id)

            for step in ready_steps:
                progress_made = True
                step_res = step_results[step.step_id]
                step_res.status = "RUNNING"
                step_res.started_at = datetime.now(timezone.utc).isoformat()
                execution_order.append(step.step_id)

                # Retry configuration (§7.5)
                retry_policy = step.retry_policy or KarmaRetryPolicy()
                max_attempts = retry_policy.max_attempts
                current_attempt = 1
                step_succeeded = False

                while current_attempt <= max_attempts:
                    step_res.attempts_made = current_attempt

                    # 1. Route step to candidate tool
                    routing_decision: KarmaRoutingDecision = self.router.route_step(
                        step=step,
                        caller_authority=caller_authority,
                        tenant_id=tenant_scope
                    )

                    if routing_decision.status != "ROUTED" or not routing_decision.selected_tool_id:
                        # Non-retryable routing / governance rejection
                        step_res.status = "FAILED"
                        step_res.error = f"Tool routing rejected: {routing_decision.rationale}"
                        break

                    selected_tool_id = routing_decision.selected_tool_id
                    step_res.tool_id = selected_tool_id
                    step_res.tool_name = routing_decision.selected_tool_name

                    # 2. Check Circuit Breaker (§7.5)
                    breaker: KarmaCircuitBreaker = self.circuit_registry.get_breaker(
                        tool_id=selected_tool_id,
                        scope=tenant_scope,
                        failure_threshold=retry_policy.circuit_break_after,
                        recovery_window_seconds=retry_policy.circuit_break_window_seconds
                    )

                    is_permitted, breaker_reason = breaker.is_call_permitted()
                    if not is_permitted:
                        step_res.status = "FAILED"
                        step_res.error = f"Circuit breaker active: {breaker_reason}"
                        break

                    # 3. Invoke Tool Handler
                    try:
                        step_params = getattr(step, "parameters", None)
                        if not step_params and hasattr(step, "model_extra") and step.model_extra:
                            step_params = step.model_extra.get("parameters")
                        if not step_params and hasattr(step, "__dict__"):
                            step_params = step.__dict__.get("parameters")

                        params_to_pass = dict(step_params) if isinstance(step_params, dict) else {}
                        params_to_pass.setdefault("action", step.action)
                        params_to_pass.setdefault("text", step.action)

                        raw_output = self._execute_tool_handler(
                            tool_id=selected_tool_id,
                            action=step.action,
                            params=params_to_pass
                        )

                        # 4. Verification Layer (§7.7)
                        v_result: KarmaVerificationResult = KarmaStepVerifier.verify(
                            action=step.action,
                            expected_outcome=step.expected_outcome,
                            output=raw_output
                        )

                        step_res.verification_status = v_result.status
                        step_res.verification_details = v_result.predicate_details

                        if v_result.is_valid:
                            # Successful invocation & verification
                            step_res.status = "SUCCEEDED"
                            step_res.output = raw_output
                            step_res.error = None
                            step_res.execution_evidence = {
                                "expected_outcome": step.expected_outcome,
                                "attempts_made": current_attempt,
                                "routing_score": routing_decision.routing_score,
                                "verification": v_result.status
                            }
                            breaker.record_success()
                            step_succeeded = True
                            break
                        else:
                            # Verification failed (§7.7) -> trigger retry if attempts remain
                            step_res.error = f"Verification failed ({v_result.status}): {v_result.failure_reason}"
                            breaker.record_failure()

                    except Exception as ex:
                        # Invocation execution error
                        step_res.error = f"Tool execution failed: {str(ex)}"
                        breaker.record_failure()

                    # Schedule backoff delay if retrying (§7.5)
                    if current_attempt < max_attempts:
                        delay = self._calculate_backoff_delay(current_attempt, retry_policy)
                        if delay > 0:
                            self._sleep_fn(delay)

                    current_attempt += 1

                # 5. Recovery Layer (§7.6) if step ultimately failed
                if not step_succeeded and step_res.status != "SUCCEEDED":
                    comp_def = (compensating_action_map or {}).get(step.step_id)
                    rec_decision: KarmaRecoveryDecision = KarmaRecoveryEngine.recover(
                        step=step,
                        error_message=step_res.error or "Unknown failure",
                        caller_authority=caller_authority,
                        allow_degradation=True,
                        compensating_action_def=comp_def
                    )
                    step_res.recovery_decision = rec_decision.model_dump()

                    if rec_decision.recovery_strategy == "COMPENSATED" and rec_decision.compensating_step:
                        # Execute compensating step through router
                        try:
                            comp_action = rec_decision.compensating_step["action"]
                            comp_res = self._execute_tool_handler("echo_formatter", comp_action, {"text": comp_action})
                            step_res.output = {"compensated": True, "details": comp_res}
                            step_res.status = "SUCCEEDED"
                        except Exception as comp_ex:
                            step_res.status = "FAILED"
                            step_res.error = f"Compensating action failed: {str(comp_ex)}"
                    elif rec_decision.recovery_strategy == "DEGRADED":
                        step_res.output = rec_decision.degraded_output
                        step_res.status = "SUCCEEDED"
                    elif rec_decision.recovery_strategy == "ESCALATED":
                        step_res.status = "ESCALATED"
                    else:
                        step_res.status = "FAILED"

                step_res.completed_at = datetime.now(timezone.utc).isoformat()

                # 6. Audit Logging to CHITRA
                if db_session:
                    try:
                        chitra_evt = chitra_repository.append_event(
                            db=db_session,
                            task_id=plan.task_id,
                            faculty="RACHIT",
                            event_type="invocation" if step_res.status == "SUCCEEDED" else "escalation",
                            decision={
                                "step_id": step.step_id,
                                "action": step.action,
                                "tool": step_res.tool_id,
                                "status": step_res.status,
                                "attempts_made": step_res.attempts_made,
                                "verification_status": step_res.verification_status,
                                "error": step_res.error
                            },
                            confidence=1.0 if step_res.status == "SUCCEEDED" else 0.0,
                            outcome=str(step_res.output) if step_res.output else step_res.error,
                            session_id=session_id or f"ses_{plan.task_id}",
                            user_id=user_id
                        )
                        step_res.chitra_event_id = chitra_evt.event_id
                    except Exception:
                        pass

                # 7. Completion Validation & No-Silent-Actions Verification (§7.8, §7.9)
                if step_res.status == "SUCCEEDED":
                    c_val = KarmaCompletionValidator.validate_step_completion(
                        step_id=step.step_id,
                        action=step.action,
                        expected_outcome=step.expected_outcome,
                        actual_output=step_res.output,
                        status=step_res.status,
                        verification_status=step_res.verification_status,
                        tool_id=step_res.tool_id,
                        authority_token=str(caller_authority.tier.value) if hasattr(caller_authority, "tier") else str(caller_authority or ""),
                        ledger_entry_ref=step_res.chitra_event_id,
                        db_session=db_session,
                        expected_task_id=plan.task_id,
                        expected_user_id=user_id,
                        require_ledger_ref=(db_session is not None),
                        recovery_decision=step_res.recovery_decision
                    )
                    step_res.completion_validation = c_val.model_dump()
                    if not c_val.is_valid:
                        step_res.status = "FAILED"
                        step_res.error = f"Completion validation failed ({c_val.status}): {c_val.failure_reason}"

            if not progress_made:
                break

        # Compile final summary
        succeeded = sum(1 for r in step_results.values() if r.status == "SUCCEEDED")
        failed = sum(1 for r in step_results.values() if r.status == "FAILED")
        blocked = sum(1 for r in step_results.values() if r.status == "BLOCKED")
        escalated = sum(1 for r in step_results.values() if r.status == "ESCALATED")
        total = len(plan.steps)

        if succeeded == total:
            overall_status = "COMPLETED"
            summary_text = f"All {total} DAG steps executed & verified successfully."
        elif escalated > 0:
            overall_status = "ESCALATED"
            summary_text = f"Plan escalated to Human Oversight: {escalated} steps escalated, {succeeded} succeeded."
        elif failed > 0 and succeeded > 0:
            overall_status = "PARTIALLY_COMPLETED"
            summary_text = f"Plan partially completed: {succeeded}/{total} steps succeeded, {failed} failed, {blocked} blocked."
        elif failed > 0:
            overall_status = "FAILED"
            summary_text = f"Plan execution failed: {failed} failed, {blocked} blocked."
        else:
            overall_status = "BLOCKED"
            summary_text = f"Plan blocked: {blocked}/{total} steps blocked."

        return KarmaDAGExecutionReport(
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            status=overall_status,
            total_steps=total,
            succeeded_steps_count=succeeded,
            failed_steps_count=failed,
            blocked_steps_count=blocked,
            escalated_steps_count=escalated,
            step_results=step_results,
            execution_order=execution_order,
            summary=summary_text
        )
