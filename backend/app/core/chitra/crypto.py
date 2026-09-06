import os
import json
import time
import hmac
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

# Genesis Hash for Task / Ledger Roots (Whitesheet §8.3 & Appendix D.1)
GENESIS_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

# Crockford's Base32 character set for ULID encoding (Whitesheet §8.2: evt-<ULID>)
CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_ulid(prefix: str = "evt_") -> str:
    """
    Generates a monotonic, collision-free 128-bit ULID string prefixed with `prefix`.
    Structure: 48-bit UNIX millisecond timestamp + 80-bit secure random entropy.
    Total length: 26 characters (Crockford Base32) + prefix length.
    """
    # 48-bit timestamp in milliseconds
    timestamp_ms = int(time.time() * 1000)
    
    # 80-bit secure random bytes (10 bytes)
    random_bytes = secrets.token_bytes(10)
    
    # Combine into 16-byte buffer (128 bits)
    ulid_bytes = timestamp_ms.to_bytes(6, byteorder="big") + random_bytes
    
    # Convert to Crockford Base32
    # 128 bits -> 26 characters (each 5 bits, total 130 bits with 2 leading zero bits)
    value = int.from_bytes(ulid_bytes, byteorder="big")
    chars = []
    for _ in range(26):
        chars.append(CROCKFORD_BASE32[value & 0x1F])
        value >>= 5
    
    ulid_str = "".join(reversed(chars))
    return f"{prefix}{ulid_str}"


def canonical_json(data: Any) -> str:
    """
    Serializes a dictionary/object to deterministic, compact, UTF-8 canonical JSON.
    Guarantees consistent key sorting, no superfluous whitespace, and ISO-8601 datetimes.
    """
    def default_serializer(obj):
        if isinstance(obj, (datetime,)):
            if obj.tzinfo is None:
                obj = obj.replace(tzinfo=timezone.utc)
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.hex()
        return str(obj)

    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=default_serializer
    )


def compute_sha256(content: str) -> str:
    """Computes a prefixed SHA-256 digest string: 'sha256:<hex>'"""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_content_hash(payload_and_metadata: Dict[str, Any]) -> str:
    """
    Computes the SHA-256 hash of canonical event contents excluding chain fields.
    Excludes 'prev_event_hash', 'this_event_hash', and 'signature'.
    """
    content_copy = {
        k: v for k, v in payload_and_metadata.items()
        if k not in ("prev_event_hash", "this_event_hash", "signature")
    }
    canonical_str = canonical_json(content_copy)
    return compute_sha256(canonical_str)


def compute_chained_hash(prev_event_hash: str, content_hash: str) -> str:
    """
    Computes the cryptographically chained event hash (Whitesheet §8.3):
    this_event_hash = SHA256(prev_event_hash + ":" + content_hash)
    """
    combined = f"{prev_event_hash}:{content_hash}"
    return compute_sha256(combined)


def get_signing_key() -> bytes:
    """
    Retrieves the dedicated HMAC signing key from the CHITRA_SIGNING_KEY environment variable.
    Never hardcoded: fails closed if CHITRA_SIGNING_KEY is missing.
    """
    key = os.getenv("CHITRA_SIGNING_KEY")
    if not key:
        raise RuntimeError("CRITICAL: CHITRA_SIGNING_KEY environment variable is missing. Set a dedicated cryptographic secret for the CHITRA ledger.")
    return key.encode("utf-8")


def sign_event(event_hash: str, secret_key: Optional[str] = None) -> str:
    """
    Generates an HMAC-SHA256 cryptographic signature for the chained event hash.
    Signature format: 'hmac-sha256:<hex>'
    """
    key_bytes = secret_key.encode("utf-8") if secret_key else get_signing_key()
    sig = hmac.new(key_bytes, event_hash.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{sig}"


def verify_event_signature(event_hash: str, signature: str, secret_key: Optional[str] = None) -> bool:
    """
    Verifies the HMAC signature of an event hash using constant-time comparison.
    """
    if not signature or not signature.startswith("hmac-sha256:"):
        return False
    
    expected_sig = sign_event(event_hash, secret_key=secret_key)
    return hmac.compare_digest(signature, expected_sig)


def build_chitra_envelope(
    task_id: int,
    faculty: str,
    event_type: str,
    decision: Dict[str, Any],
    prev_event_hash: str,
    session_id: Optional[str] = None,
    evidence: Optional[List[str]] = None,
    confidence: float = 1.0,
    outcome: Optional[Any] = None,
    constitutional_review: str = "passed",
    input_data: Optional[Any] = None,
    secret_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Assembles, hashes, chains, and cryptographically signs a canonical CHITRA Event Envelope
    conforming strictly to Whitesheet §8.2 and Appendix C.1.
    """
    event_id = generate_ulid(prefix="evt_")
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Calculate input hash if input data is provided
    input_hash = compute_sha256(canonical_json(input_data)) if input_data is not None else compute_sha256("{}")
    
    envelope = {
        "event_id": event_id,
        "timestamp": timestamp,
        "session_id": session_id or f"ses_{task_id}",
        "task_id": task_id,
        "faculty": faculty,
        "event_type": event_type,
        "input_hash": input_hash,
        "decision": decision,
        "evidence": evidence or [],
        "confidence": float(confidence),
        "outcome": outcome,
        "constitutional_review": constitutional_review,
        "prev_event_hash": prev_event_hash or GENESIS_HASH,
    }
    
    # Step 1: Hash the canonical event content
    content_hash = compute_content_hash(envelope)
    
    # Step 2: Calculate cryptographically chained hash
    this_event_hash = compute_chained_hash(envelope["prev_event_hash"], content_hash)
    envelope["this_event_hash"] = this_event_hash
    
    # Step 3: Sign the chained hash with HMAC-SHA256 authority key
    signature = sign_event(this_event_hash, secret_key=secret_key)
    envelope["signature"] = signature
    
    return envelope
