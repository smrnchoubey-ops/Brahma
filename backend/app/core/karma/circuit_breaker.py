"""
KARMA Circuit Breaker Engine
Strictly conforms to BRAHMA COS Whitesheet §7.5.

Manages CLOSED, OPEN, and HALF_OPEN states for tools with sliding failure windows,
preventing cascading failure loops while maintaining strict tenant/tool isolation.
"""
from typing import Dict, Tuple, Optional, List
from enum import Enum
import time
import threading


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class KarmaCircuitBreaker:
    """
    Per-tool circuit breaker tracking failure history within a sliding window.
    """
    def __init__(
        self,
        tool_id: str,
        failure_threshold: int = 5,
        recovery_window_seconds: float = 60.0,
        time_fn: Optional[callable] = None
    ):
        self.tool_id = tool_id
        self.failure_threshold = failure_threshold
        self.recovery_window_seconds = recovery_window_seconds
        self._time_fn = time_fn or time.time
        
        self.state = CircuitState.CLOSED
        self.failure_timestamps: List[float] = []
        self.last_state_change: float = self._time_fn()
        self._lock = threading.Lock()

    def _now(self) -> float:
        return self._time_fn()

    def is_call_permitted(self) -> Tuple[bool, str]:
        """
        Determines whether a tool invocation is permitted through the circuit.
        Returns (permitted: bool, reason: str).
        """
        with self._lock:
            now = self._now()

            if self.state == CircuitState.CLOSED:
                return True, "Circuit is CLOSED (healthy)."

            if self.state == CircuitState.OPEN:
                # Check if recovery window has elapsed to transition to HALF_OPEN
                if now - self.last_state_change >= self.recovery_window_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.last_state_change = now
                    return True, "Circuit transitioned to HALF_OPEN; probing single request."
                return False, f"Circuit for tool '{self.tool_id}' is OPEN. Rejection active until cooldown."

            if self.state == CircuitState.HALF_OPEN:
                # In HALF_OPEN, permit single test probe
                return True, "Circuit is HALF_OPEN (probing recovery)."

            return False, "Unknown circuit state."

    def record_success(self) -> None:
        """Records a successful invocation, resetting circuit to CLOSED."""
        with self._lock:
            self.failure_timestamps.clear()
            self.state = CircuitState.CLOSED
            self.last_state_change = self._now()

    def record_failure(self) -> CircuitState:
        """Records an invocation failure and potentially trips the circuit to OPEN."""
        with self._lock:
            now = self._now()
            self.failure_timestamps.append(now)

            # Prune failures outside the sliding window
            cutoff = now - self.recovery_window_seconds
            self.failure_timestamps = [ts for ts in self.failure_timestamps if ts >= cutoff]

            if self.state == CircuitState.HALF_OPEN:
                # Failed probe in HALF_OPEN trips immediately back to OPEN
                self.state = CircuitState.OPEN
                self.last_state_change = now
            elif len(self.failure_timestamps) >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.last_state_change = now

            return self.state

    def reset(self) -> None:
        """Manually resets the circuit breaker to clean CLOSED state."""
        with self._lock:
            self.failure_timestamps.clear()
            self.state = CircuitState.CLOSED
            self.last_state_change = self._now()


class KarmaCircuitBreakerRegistry:
    """
    Thread-safe registry of isolated circuit breakers partitioned by scope and tool.
    Guarantees that one tenant's or task's circuit breaker state cannot bleed into another.
    """
    def __init__(self, time_fn: Optional[callable] = None):
        self._breakers: Dict[Tuple[str, str], KarmaCircuitBreaker] = {}
        self._lock = threading.Lock()
        self._time_fn = time_fn or time.time

    def get_breaker(
        self,
        tool_id: str,
        scope: str = "global",
        failure_threshold: int = 5,
        recovery_window_seconds: float = 60.0
    ) -> KarmaCircuitBreaker:
        """Retrieves or instantiates an isolated circuit breaker."""
        key = (scope, tool_id)
        with self._lock:
            if key not in self._breakers:
                self._breakers[key] = KarmaCircuitBreaker(
                    tool_id=tool_id,
                    failure_threshold=failure_threshold,
                    recovery_window_seconds=recovery_window_seconds,
                    time_fn=self._time_fn
                )
            return self._breakers[key]

    def clear(self) -> None:
        """Clears all circuit breakers (for testing)."""
        with self._lock:
            self._breakers.clear()
