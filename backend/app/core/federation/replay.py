"""
FEDERATION REPLAY PROTECTION & SECURITY VALIDATION (Whitesheet §18.2)
Provides stateful sliding-window replay detection, timestamp freshness validation,
and bounded cache eviction for federated cross-node wire messages.
"""
from typing import Dict, Any, Optional, Tuple, Set
from enum import Enum
from datetime import datetime, timezone, timedelta
import threading
from pydantic import BaseModel, Field

from app.core.federation.models import FederationMessage


class ReplayStatus(str, Enum):
    VALID = "VALID"
    REJECT_DUPLICATE_NONCE = "REJECT_DUPLICATE_NONCE"
    REJECT_STALE_TIMESTAMP = "REJECT_STALE_TIMESTAMP"
    REJECT_FUTURE_TIMESTAMP = "REJECT_FUTURE_TIMESTAMP"
    REJECT_MALFORMED_TIMESTAMP = "REJECT_MALFORMED_TIMESTAMP"
    REJECT_MISSING_NONCE = "REJECT_MISSING_NONCE"
    REJECT_MISSING_SOURCE_NODE = "REJECT_MISSING_SOURCE_NODE"
    REJECT_MISSING_TENANT = "REJECT_MISSING_TENANT"
    REJECT_CACHE_OVERFLOW = "REJECT_CACHE_OVERFLOW"


class ReplayCheckVerdict(BaseModel):
    """
    Structured result of stateful replay and freshness verification.
    """
    is_valid: bool
    status: ReplayStatus
    reason: str
    source_node_id: Optional[str] = None
    tenant_id: Optional[str] = None
    nonce: Optional[str] = None
    message_id: Optional[str] = None
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FederationReplayGuard:
    """
    Stateful sliding-window Replay Guard for federated nodes.
    Guarantees:
    1. Single-delivery invariant within active validity window.
    2. Timestamp freshness validation (rejects stale & future clock-skewed messages).
    3. Bounded memory consumption with automatic expired-entry pruning.
    4. Thread-safe atomic check-and-record operations.
    5. Tenant and node-isolated replay tracking.
    """

    def __init__(
        self,
        window_seconds: int = 300,  # Default: ±5 minutes (300s)
        max_future_skew_seconds: int = 60,  # Default: 60s future clock skew allowance
        max_entries: int = 50000
    ):
        self.window_seconds = window_seconds
        self.max_future_skew_seconds = max_future_skew_seconds
        self.max_entries = max_entries
        self._lock = threading.Lock()
        
        # In-memory storage: key -> recorded_timestamp_epoch
        # Key format: f"{source_node_id}:{tenant_id}:{nonce}"
        self._observed_nonces: Dict[str, float] = {}
        # Secondary index: message_id -> recorded_timestamp_epoch
        self._observed_message_ids: Dict[str, float] = {}

    def validate_and_record(
        self,
        message: FederationMessage,
        current_time: Optional[datetime] = None
    ) -> ReplayCheckVerdict:
        """
        Atomically validates timestamp freshness, checks against observed nonces,
        and records the message if valid. Fails closed on any defect.
        """
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # -------------------------------------------------------------
        # 1. FIELD INTEGRITY & FAIL-CLOSED VALIDATION
        # -------------------------------------------------------------
        if not message:
            return ReplayCheckVerdict(
                is_valid=False,
                status=ReplayStatus.REJECT_MISSING_SOURCE_NODE,
                reason="Message envelope is null."
            )

        source_node_id = message.source_node_id.strip() if message.source_node_id else ""
        if not source_node_id:
            return ReplayCheckVerdict(
                is_valid=False,
                status=ReplayStatus.REJECT_MISSING_SOURCE_NODE,
                reason="source_node_id cannot be missing or empty."
            )

        tenant_id = message.tenant_id.strip() if message.tenant_id else ""
        if not tenant_id:
            return ReplayCheckVerdict(
                is_valid=False,
                status=ReplayStatus.REJECT_MISSING_TENANT,
                source_node_id=source_node_id,
                reason="tenant_id cannot be missing or empty."
            )

        nonce = message.nonce.strip() if message.nonce else ""
        if not nonce or len(nonce) < 8:
            return ReplayCheckVerdict(
                is_valid=False,
                status=ReplayStatus.REJECT_MISSING_NONCE,
                source_node_id=source_node_id,
                tenant_id=tenant_id,
                reason="nonce must be provided and at least 8 characters."
            )

        # -------------------------------------------------------------
        # 2. TIMESTAMP PARSING & FRESHNESS VALIDATION
        # -------------------------------------------------------------
        if not message.timestamp or not message.timestamp.strip():
            return ReplayCheckVerdict(
                is_valid=False,
                status=ReplayStatus.REJECT_MALFORMED_TIMESTAMP,
                source_node_id=source_node_id,
                tenant_id=tenant_id,
                nonce=nonce,
                reason="Timestamp is missing."
            )

        try:
            msg_dt = datetime.fromisoformat(message.timestamp.replace("Z", "+00:00"))
            if msg_dt.tzinfo is None:
                msg_dt = msg_dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            return ReplayCheckVerdict(
                is_valid=False,
                status=ReplayStatus.REJECT_MALFORMED_TIMESTAMP,
                source_node_id=source_node_id,
                tenant_id=tenant_id,
                nonce=nonce,
                reason=f"Malformed ISO-8601 timestamp '{message.timestamp}': {str(e)}"
            )

        delta_seconds = (now - msg_dt).total_seconds()

        # Check for stale messages (older than sliding window)
        if delta_seconds > self.window_seconds:
            return ReplayCheckVerdict(
                is_valid=False,
                status=ReplayStatus.REJECT_STALE_TIMESTAMP,
                source_node_id=source_node_id,
                tenant_id=tenant_id,
                nonce=nonce,
                message_id=message.message_id,
                reason=f"Message timestamp is stale: age {delta_seconds:.1f}s exceeds window of {self.window_seconds}s."
            )

        # Check for future-dated messages (beyond clock skew tolerance)
        if delta_seconds < -self.max_future_skew_seconds:
            return ReplayCheckVerdict(
                is_valid=False,
                status=ReplayStatus.REJECT_FUTURE_TIMESTAMP,
                source_node_id=source_node_id,
                tenant_id=tenant_id,
                nonce=nonce,
                message_id=message.message_id,
                reason=f"Message timestamp is in the future: skew {-delta_seconds:.1f}s exceeds maximum allowed skew of {self.max_future_skew_seconds}s."
            )

        # -------------------------------------------------------------
        # 3. ATOMIC REPLAY CHECK & RECORDING
        # -------------------------------------------------------------
        nonce_key = f"{source_node_id}:{tenant_id}:{nonce}"
        msg_id = message.message_id.strip() if message.message_id else ""
        now_epoch = now.timestamp()

        with self._lock:
            # Periodic / lazy eviction of expired entries
            self._prune_expired_entries_locked(now_epoch)

            # Check capacity bounds
            if len(self._observed_nonces) >= self.max_entries:
                return ReplayCheckVerdict(
                    is_valid=False,
                    status=ReplayStatus.REJECT_CACHE_OVERFLOW,
                    source_node_id=source_node_id,
                    tenant_id=tenant_id,
                    nonce=nonce,
                    message_id=msg_id,
                    reason=f"ReplayGuard capacity limit ({self.max_entries}) reached. Rejecting fail-closed."
                )

            # Check if nonce was already observed from this source node & tenant
            if nonce_key in self._observed_nonces:
                return ReplayCheckVerdict(
                    is_valid=False,
                    status=ReplayStatus.REJECT_DUPLICATE_NONCE,
                    source_node_id=source_node_id,
                    tenant_id=tenant_id,
                    nonce=nonce,
                    message_id=msg_id,
                    reason=f"Replay detected: nonce '{nonce}' from source '{source_node_id}' for tenant '{tenant_id}' already processed."
                )

            # Check if message_id was already observed
            if msg_id and msg_id in self._observed_message_ids:
                return ReplayCheckVerdict(
                    is_valid=False,
                    status=ReplayStatus.REJECT_DUPLICATE_NONCE,
                    source_node_id=source_node_id,
                    tenant_id=tenant_id,
                    nonce=nonce,
                    message_id=msg_id,
                    reason=f"Replay detected: message_id '{msg_id}' already processed."
                )

            # Record valid observed entry
            self._observed_nonces[nonce_key] = now_epoch
            if msg_id:
                self._observed_message_ids[msg_id] = now_epoch

        return ReplayCheckVerdict(
            is_valid=True,
            status=ReplayStatus.VALID,
            source_node_id=source_node_id,
            tenant_id=tenant_id,
            nonce=nonce,
            message_id=msg_id,
            reason="Fresh valid message accepted."
        )

    def is_nonce_seen(self, source_node_id: str, tenant_id: str, nonce: str) -> bool:
        """Helper to inspect if a specific nonce is currently active in the cache."""
        nonce_key = f"{source_node_id}:{tenant_id}:{nonce}"
        with self._lock:
            return nonce_key in self._observed_nonces

    def prune_expired(self, current_time: Optional[datetime] = None) -> int:
        """Explicit maintenance cleanup of expired cache entries."""
        now = current_time or datetime.now(timezone.utc)
        now_epoch = now.timestamp()
        with self._lock:
            return self._prune_expired_entries_locked(now_epoch)

    def clear(self) -> None:
        """Clears all in-memory replay state (used for testing)."""
        with self._lock:
            self._observed_nonces.clear()
            self._observed_message_ids.clear()

    def _prune_expired_entries_locked(self, now_epoch: float) -> int:
        cutoff = now_epoch - self.window_seconds
        initial_count = len(self._observed_nonces)
        
        # Prune nonces older than sliding window
        self._observed_nonces = {
            k: ts for k, ts in self._observed_nonces.items()
            if ts >= cutoff
        }
        
        # Prune message IDs older than sliding window
        self._observed_message_ids = {
            k: ts for k, ts in self._observed_message_ids.items()
            if ts >= cutoff
        }
        
        return initial_count - len(self._observed_nonces)
