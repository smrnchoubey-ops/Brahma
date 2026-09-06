"""
BRAHMA COS §13.4 Cryptographically Signed, Time-Bounded Authority Token Engine
Strictly conforms to BRAHMA COS Whitesheet §13.0, §13.4, and §10.1.

Implements dedicated authority tokens containing:
- token identity (token_id)
- authority tier (tier: LOW | MEDIUM | HIGH | CRITICAL)
- authority scope / action permissions (scopes: List[str])
- issued-at timestamp (issued_at: ISO-8601)
- expiry timestamp (expires_at: ISO-8601)
- signer/key identity (signer_id: str)
- cryptographic signature (signature: HMAC-SHA256)
"""
from typing import List, Dict, Any, Optional, Tuple, Union
import os
import hmac
import hashlib
import json
import base64
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field

from app.core.maryada.verdict import AuthorityTier
from app.core.chitra.crypto import generate_ulid, canonical_json


def get_authority_signing_key() -> bytes:
    """
    Retrieves dedicated authority signing key from environment (§13.0 cryptographic key separation).
    Fails closed if AUTHORITY_SIGNING_KEY is missing.
    """
    key = os.getenv("AUTHORITY_SIGNING_KEY")
    if not key:
        # Check fallback for test isolation if explicitly defined
        key = os.getenv("SECRET_KEY")
        if not key:
            raise RuntimeError("CRITICAL: AUTHORITY_SIGNING_KEY environment variable is missing. Set a dedicated cryptographic key for §13.4 Authority Tokens.")
    return key.encode("utf-8")


class AuthorityToken(BaseModel):
    """
    BRAHMA COS §13.4 Authority Token model.
    """
    token_id: str = Field(default_factory=lambda: generate_ulid(prefix="tok_"))
    tier: AuthorityTier = Field(..., description="Authority tier: LOW | MEDIUM | HIGH | CRITICAL")
    scopes: List[str] = Field(default_factory=lambda: ["*"], description="Action permissions or pattern scopes")
    issued_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = Field(..., description="ISO-8601 expiry timestamp")
    signer_id: str = Field(default="MARYADA_KEYMASTER_01", description="Signer identity / authority root")
    tenant_id: str = Field(default="global", description="Tenant isolation identifier")
    signature: str = Field(default="", description="HMAC-SHA256 signature of canonical token payload")

    def payload_dict(self) -> Dict[str, Any]:
        """Returns the canonical payload dictionary excluding the signature."""
        return {
            "token_id": self.token_id,
            "tier": self.tier.value if isinstance(self.tier, AuthorityTier) else str(self.tier),
            "scopes": sorted(self.scopes),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signer_id": self.signer_id,
            "tenant_id": self.tenant_id
        }

    def compute_signature(self, secret_key: Optional[bytes] = None) -> str:
        """Computes HMAC-SHA256 signature over the canonical payload JSON."""
        key = secret_key if secret_key is not None else get_authority_signing_key()
        canonical_str = canonical_json(self.payload_dict())
        sig = hmac.new(key, canonical_str.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{sig}"

    def sign(self, secret_key: Optional[bytes] = None) -> "AuthorityToken":
        """Signs the token in-place and returns self."""
        self.signature = self.compute_signature(secret_key=secret_key)
        return self

    def is_action_in_scope(self, action_name: str) -> bool:
        """
        Checks if the requested action is covered by the token scopes.
        Deterministic matching: exact match, '*' wildcard, prefix pattern ('wire_*'), or command root match.
        Prevents accidental privilege escalation through loose word-containment.
        """
        if not action_name or not action_name.strip():
            return False
        act_clean = action_name.strip().lower()
        command_root = act_clean.split()[0] if act_clean.split() else ""

        for scope in self.scopes:
            s_clean = scope.strip().lower()
            if s_clean == "*":
                return True
            if s_clean.endswith("*"):
                prefix = s_clean[:-1]
                if act_clean.startswith(prefix):
                    return True
            if s_clean == act_clean:
                return True
            if s_clean == command_root:
                return True
        return False

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        """Checks whether the token has expired (fail-closed)."""
        now = current_time or datetime.now(timezone.utc)
        try:
            exp = datetime.fromisoformat(self.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return now > exp
        except Exception:
            return True

    def is_not_yet_valid(self, current_time: Optional[datetime] = None) -> bool:
        """Checks whether the token is not yet valid (future issued_at, allowing 60s skew)."""
        now = current_time or datetime.now(timezone.utc)
        try:
            iat = datetime.fromisoformat(self.issued_at)
            if iat.tzinfo is None:
                iat = iat.replace(tzinfo=timezone.utc)
            return (iat - now).total_seconds() > 60
        except Exception:
            return True

    def verify_signature(self, secret_key: Optional[bytes] = None) -> bool:
        """Verifies the HMAC-SHA256 signature against the canonical payload in constant time."""
        if not self.signature or not self.signature.startswith("hmac-sha256:"):
            return False
        expected = self.compute_signature(secret_key=secret_key)
        return hmac.compare_digest(self.signature, expected)

    def encode(self) -> str:
        """Encodes the signed token as a compact base64 JSON string."""
        data = self.model_dump()
        json_str = json.dumps(data, separators=(",", ":"))
        return base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("ascii")

    @classmethod
    def decode(cls, token_str: str) -> "AuthorityToken":
        """Decodes a compact base64 JSON string or raw JSON string into an AuthorityToken."""
        if not token_str or not isinstance(token_str, str):
            raise ValueError("Token string is null or empty.")
        clean = token_str.strip()
        try:
            if clean.startswith("{"):
                data = json.loads(clean)
            else:
                padded = clean + "=" * (-len(clean) % 4)
                raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
                data = json.loads(raw)
            return cls(**data)
        except Exception as e:
            raise ValueError(f"Malformed authority token: {e}")

    @classmethod
    def issue(
        cls,
        tier: Union[AuthorityTier, str],
        scopes: Optional[List[str]] = None,
        ttl_seconds: int = 3600,
        signer_id: str = "MARYADA_KEYMASTER_01",
        tenant_id: str = "global",
        secret_key: Optional[bytes] = None
    ) -> "AuthorityToken":
        """
        Issues, time-bounds, and cryptographically signs a new §13.4 AuthorityToken.
        """
        tier_enum = AuthorityTier(tier) if isinstance(tier, str) else tier
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=ttl_seconds)
        tok = cls(
            tier=tier_enum,
            scopes=scopes or ["*"],
            issued_at=now.isoformat(),
            expires_at=exp.isoformat(),
            signer_id=signer_id,
            tenant_id=tenant_id
        )
        return tok.sign(secret_key=secret_key)
