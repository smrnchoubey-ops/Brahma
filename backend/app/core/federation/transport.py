"""
FEDERATION HTTP OUTBOUND TRANSPORT (Whitesheet §18.1 - §18.6)
Provides lightweight HTTP transport client for transmitting signed FederationMessage envelopes to peer nodes.
Captures network latency, HTTP status, and handles connection failures gracefully.
"""
import time
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import httpx

from app.core.federation.models import FederationMessage, NodeIdentity
from app.core.federation.orchestrator import FederationIngressResult

logger = logging.getLogger(__name__)


class FederationTransportError(Exception):
    """Raised when an outbound HTTP federation message transmission fails."""
    pass


class FederationHttpTransport:
    """
    HTTP client for dispatching signed FederationMessage envelopes to remote peer endpoints.
    """

    def __init__(self, timeout_sec: float = 5.0):
        self.timeout_sec = timeout_sec

    def send_message(
        self,
        peer_endpoint: str,
        message: FederationMessage
    ) -> Tuple[FederationIngressResult, float]:
        """
        Sends a signed FederationMessage to a remote peer's /api/federation/messages endpoint.
        Returns:
            (FederationIngressResult, latency_ms)
        """
        if not peer_endpoint or not peer_endpoint.strip():
            raise FederationTransportError("Cannot send federation message: peer_endpoint is empty.")

        url = peer_endpoint.rstrip("/") + "/api/federation/messages"
        payload = message.model_dump()

        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.post(url, json=payload)
                t1 = time.perf_counter()
                latency_ms = round((t1 - t0) * 1000.0, 2)

                if response.status_code != 200:
                    raise FederationTransportError(
                        f"Peer at '{url}' returned HTTP {response.status_code}: {response.text}"
                    )

                result_data = response.json()
                ingress_result = FederationIngressResult.model_validate(result_data)
                return ingress_result, latency_ms
        except httpx.RequestError as ex:
            t1 = time.perf_counter()
            latency_ms = round((t1 - t0) * 1000.0, 2)
            logger.warning(f"Network error sending federation message to '{url}': {ex}")
            raise FederationTransportError(f"HTTP request to '{url}' failed: {str(ex)}") from ex

    async def send_message_async(
        self,
        peer_endpoint: str,
        message: FederationMessage
    ) -> Tuple[FederationIngressResult, float]:
        """
        Asynchronously sends a signed FederationMessage to a remote peer's endpoint.
        """
        if not peer_endpoint or not peer_endpoint.strip():
            raise FederationTransportError("Cannot send federation message: peer_endpoint is empty.")

        url = peer_endpoint.rstrip("/") + "/api/federation/messages"
        payload = message.model_dump()

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(url, json=payload)
                t1 = time.perf_counter()
                latency_ms = round((t1 - t0) * 1000.0, 2)

                if response.status_code != 200:
                    raise FederationTransportError(
                        f"Peer at '{url}' returned HTTP {response.status_code}: {response.text}"
                    )

                result_data = response.json()
                ingress_result = FederationIngressResult.model_validate(result_data)
                return ingress_result, latency_ms
        except httpx.RequestError as ex:
            t1 = time.perf_counter()
            latency_ms = round((t1 - t0) * 1000.0, 2)
            logger.warning(f"Async network error sending federation message to '{url}': {ex}")
            raise FederationTransportError(f"Async HTTP request to '{url}' failed: {str(ex)}") from ex
