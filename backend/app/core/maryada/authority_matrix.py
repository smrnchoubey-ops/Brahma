"""
MARYADA Four-Tier Authority Matrix Engine
Strictly conforms to BRAHMA COS Whitesheet §10.1.

Evaluates:
- LOW: Read-only, mathematical, calendar, status telemetry
- MEDIUM: State-mutating non-critical operations
- HIGH: Financial transactions, external API writes, sensitive data access
- CRITICAL: System reconfiguration, credential rotation, schema modification, bulk operations
"""
from typing import Dict, Any, Optional, Tuple, Union
from datetime import datetime

from app.core.maryada.verdict import AuthorityTier, RiskTier
from app.core.maryada.token import AuthorityToken


AUTHORITY_RANK = {
    AuthorityTier.LOW: 1,
    AuthorityTier.MEDIUM: 2,
    AuthorityTier.HIGH: 3,
    AuthorityTier.CRITICAL: 4
}


class MaryadaAuthorityMatrix:
    """
    Evaluates required authority against caller authority and determines risk tier.
    Enforces §13.4 cryptographic authority token validation for privileged execution.
    """

    @classmethod
    def parse_tier(cls, tier_str: Optional[Union[str, AuthorityTier]]) -> Optional[AuthorityTier]:
        """Parses tier string into AuthorityTier enum."""
        if not tier_str:
            return None
        if isinstance(tier_str, AuthorityTier):
            return tier_str
        clean = str(tier_str).strip().upper()
        try:
            return AuthorityTier(clean)
        except ValueError:
            return None

    @classmethod
    def infer_action_authority_tier(cls, action_name: str) -> AuthorityTier:
        """
        Determines the baseline required authority tier for an action.
        """
        act_lower = action_name.lower().strip()

        # CRITICAL actions
        if any(k in act_lower for k in ["rotate_key", "reconfigure_system", "bulk_delete", "modify_schema", "purge_ledger"]):
            return AuthorityTier.CRITICAL

        # HIGH actions
        if any(k in act_lower for k in ["settlement", "wire_transfer", "transfer_funds", "payroll", "export_pii", "financial"]):
            return AuthorityTier.HIGH

        # MEDIUM actions
        if any(k in act_lower for k in ["write_", "update_", "insert_", "create_", "schedule_event", "send_email"]):
            return AuthorityTier.MEDIUM

        # Default to LOW
        return AuthorityTier.LOW

    @classmethod
    def validate_authority_token(
        cls,
        token: Any,
        action_name: str,
        expected_tenant_id: Optional[str] = None,
        secret_key: Optional[bytes] = None,
        current_time: Optional[datetime] = None
    ) -> Tuple[bool, Optional[AuthorityToken], Optional[AuthorityTier], str]:
        """
        Strictly validates an §13.4 AuthorityToken for cryptographic signature, time-bounding,
        action scope compliance, and tenant binding. Fails closed if missing, malformed, expired,
        tenant mismatched, or invalid.
        Returns: (is_valid, parsed_token, authority_tier, failure_reason)
        """
        if token is None:
            return False, None, None, "Missing §13.4 cryptographic authority token (fail-closed)."

        auth_tok: Optional[AuthorityToken] = None
        if isinstance(token, AuthorityToken):
            auth_tok = token
        elif isinstance(token, dict):
            try:
                auth_tok = AuthorityToken(**token)
            except Exception as e:
                return False, None, None, f"Malformed authority token payload: {e}"
        elif isinstance(token, str):
            clean = token.strip()
            # If caller passed a plain tier string like "HIGH", reject it on §13.4 token path
            if clean.upper() in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
                return False, None, None, f"Plain tier string '{clean}' is not a valid §13.4 cryptographically signed authority token."
            try:
                auth_tok = AuthorityToken.decode(clean)
            except Exception as e:
                return False, None, None, f"Invalid or unparseable §13.4 authority token string: {e}"
        else:
            return False, None, None, "Unsupported authority token format."

        # 1. Cryptographic Signature Verification
        if not auth_tok.verify_signature(secret_key=secret_key):
            return False, auth_tok, auth_tok.tier, "Authority token cryptographic signature verification failed (tampered or invalid key)."

        # 2. Time-Bounding: Expiry Check (§13.4)
        if auth_tok.is_expired(current_time=current_time):
            return False, auth_tok, auth_tok.tier, f"Authority token expired at {auth_tok.expires_at}."

        # 3. Time-Bounding: Not-Yet-Valid Check
        if auth_tok.is_not_yet_valid(current_time=current_time):
            return False, auth_tok, auth_tok.tier, f"Authority token not yet valid (issued_at: {auth_tok.issued_at})."

        # 4. Action Scope Compliance Check (§13.4)
        if not auth_tok.is_action_in_scope(action_name):
            return False, auth_tok, auth_tok.tier, f"Action '{action_name}' is outside authorized token scopes: {auth_tok.scopes}."

        # 5. Tenant Binding Check (§13.4)
        if expected_tenant_id and expected_tenant_id != "global":
            if auth_tok.tenant_id != expected_tenant_id and auth_tok.tenant_id != "global":
                return False, auth_tok, auth_tok.tier, f"Tenant mismatch: token tenant '{auth_tok.tenant_id}' cannot authorize action for tenant '{expected_tenant_id}' (fail-closed)."

        return True, auth_tok, auth_tok.tier, "Authority token validated successfully."

    @classmethod
    def evaluate_authority(
        cls,
        action_name: str,
        declared_tier: Optional[str],
        caller_authority: Optional[Union[str, AuthorityToken, Dict[str, Any]]],
        tool_tier: Optional[str] = None,
        authority_token: Optional[Union[str, AuthorityToken, Dict[str, Any]]] = None,
        expected_tenant_id: Optional[str] = None,
        require_signed_token: bool = False,
        secret_key: Optional[bytes] = None,
        current_time: Optional[datetime] = None
    ) -> Tuple[bool, AuthorityTier, RiskTier, bool, str]:
        """
        Evaluates caller authority against action and tool requirements.
        Supports §13.4 cryptographically signed AuthorityToken instances and fail-closed evaluation.
        Returns: (is_authorized, required_tier, risk_tier, requires_human, justification)
        """
        # 1. Infer minimum action tier
        inferred_tier = cls.infer_action_authority_tier(action_name)

        # 2. Reconcile with declared tier and tool registered tier (takes maximum)
        declared_enum = cls.parse_tier(declared_tier)
        tool_enum = cls.parse_tier(tool_tier)

        required_tier = inferred_tier
        if declared_enum and AUTHORITY_RANK[declared_enum] > AUTHORITY_RANK[required_tier]:
            required_tier = declared_enum
        if tool_enum and AUTHORITY_RANK[tool_enum] > AUTHORITY_RANK[required_tier]:
            required_tier = tool_enum

        # 3. Process Authority Token / Caller Authority
        caller_enum: Optional[AuthorityTier] = None
        effective_token = authority_token if authority_token is not None else caller_authority

        is_token_object = isinstance(effective_token, (AuthorityToken, dict))
        is_serialized_token = isinstance(effective_token, str) and (
            effective_token.startswith("eyJ") or "hmac-sha256:" in effective_token or len(effective_token) > 50
        )

        if is_token_object or is_serialized_token or (require_signed_token and effective_token is not None):
            is_valid, auth_tok, tok_tier, tok_reason = cls.validate_authority_token(
                token=effective_token,
                action_name=action_name,
                expected_tenant_id=expected_tenant_id,
                secret_key=secret_key,
                current_time=current_time
            )
            if not is_valid:
                return False, required_tier, RiskTier(required_tier.value), False, tok_reason
            caller_enum = tok_tier
        elif require_signed_token:
            return False, required_tier, RiskTier(required_tier.value), False, "Missing required §13.4 cryptographic authority token."
        else:
            # Legacy/default tier string parsing (fails closed if missing or invalid)
            caller_enum = cls.parse_tier(caller_authority)
            if not caller_enum:
                return False, required_tier, RiskTier.UNKNOWN, False, "Missing or invalid caller authority token."

        caller_rank = AUTHORITY_RANK[caller_enum]
        required_rank = AUTHORITY_RANK[required_tier]

        # 4. Authority comparison
        if caller_rank < required_rank:
            return (
                False,
                required_tier,
                RiskTier(required_tier.value),
                False,
                f"Insufficient authority: action '{action_name}' requires '{required_tier.value}', caller has '{caller_enum.value}'."
            )

        # 5. Risk and Human Oversight Evaluation (§10.1)
        if required_tier == AuthorityTier.CRITICAL:
            # CRITICAL requires human oversight approval (§10.1)
            return True, required_tier, RiskTier.CRITICAL, True, "Approved pending mandatory Human Oversight for CRITICAL tier."
        elif required_tier == AuthorityTier.HIGH:
            return True, required_tier, RiskTier.HIGH, False, "Approved with HIGH authority tier."
        elif required_tier == AuthorityTier.MEDIUM:
            return True, required_tier, RiskTier.MEDIUM, False, "Approved with MEDIUM authority tier."
        else:
            return True, required_tier, RiskTier.LOW, False, "Approved with LOW authority tier."
