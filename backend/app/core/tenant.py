"""
BRAHMA COS: Authoritative Tenant Identity & Context Management
Conforms to BRAHMA COS Whitesheet §18.0 - §18.6 (Federation & Multi-Tenancy).

Enforces server-side tenant identification derived strictly from authenticated credentials.
Client-supplied tenant_ids in request bodies or query params are strictly untrusted.
"""
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.api.auth import get_current_user


@dataclass(frozen=True)
class TenantContext:
    """
    Authoritative, immutable tenant context bound to the authenticated user.
    """
    user_id: int
    username: str
    tenant_id: str
    roles: List[str] = field(default_factory=lambda: ["tenant_user"])
    session_id: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        return self.user_id > 0


def get_tenant_context_from_user(user: User, session_id: Optional[str] = None) -> TenantContext:
    """Derives authoritative TenantContext from an authenticated User entity."""
    if not user or not user.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthenticated: Cannot construct tenant context without valid user"
        )
    return TenantContext(
        user_id=user.id,
        username=user.username,
        tenant_id=f"tenant_{user.id}",
        roles=["tenant_user"],
        session_id=session_id
    )


def get_current_tenant(
    current_user: User = Depends(get_current_user)
) -> TenantContext:
    """
    FastAPI dependency that extracts authoritative TenantContext from the verified JWT.
    """
    return get_tenant_context_from_user(current_user)
