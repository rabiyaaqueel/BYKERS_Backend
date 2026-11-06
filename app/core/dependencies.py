"""Authentication and Current User Dependencies.

This module provides the core `get_current_user` dependency used across all protected endpoints.
Every protected request:
1. Validates the JWT access token signature & expiration
2. Loads the active database session
3. Enforces that the session is not revoked
4. Enforces that the user account is not suspended or deleted
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Set

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.modules.auth.models import Session, User, UserStatus


class AppInterface(str, Enum):
    """The four distinct application interfaces in BYKERS."""

    RIDER_APP = "rider_app"
    ORGANIZER_PORTAL = "organizer_portal"
    PARTNER_PORTAL = "partner_portal"
    STAFF_CONSOLE = "staff_console"


ALL_INTERFACES: Set[str] = {
    AppInterface.RIDER_APP.value,
    AppInterface.ORGANIZER_PORTAL.value,
    AppInterface.PARTNER_PORTAL.value,
    AppInterface.STAFF_CONSOLE.value,
}

# Auto-error False so we can return standard Rule 4 errors instead of default FastAPI 403
security_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedUser:
    """Represents the validated caller context for a protected request."""

    user: User
    session: Session
    token_payload: Dict[str, Any]

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def session_id(self) -> uuid.UUID:
        return self.session.id


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """Reusable FastAPI dependency enforcing authentication and active session validity."""
    if not credentials or not credentials.credentials:
        raise UnauthorizedError("Authentication token is required")

    token = credentials.credentials

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token has expired", code="TOKEN_EXPIRED")
    except jwt.PyJWTError:
        raise UnauthorizedError("Invalid authentication token", code="INVALID_TOKEN")

    user_id_raw = payload.get("sub")
    session_id_raw = payload.get("session_id")

    if not user_id_raw or not session_id_raw:
        raise UnauthorizedError("Invalid token payload", code="INVALID_TOKEN")

    try:
        user_uuid = uuid.UUID(user_id_raw)
        session_uuid = uuid.UUID(session_id_raw)
    except (ValueError, TypeError):
        raise UnauthorizedError("Malformed token identifiers", code="INVALID_TOKEN")

    # Load session and check revocation
    stmt_session = (
        select(Session)
        .options(selectinload(Session.device))
        .where(Session.id == session_uuid, Session.user_id == user_uuid)
    )
    result_session = await db.execute(stmt_session)
    session = result_session.scalar_one_or_none()

    if not session or session.revoked_at is not None:
        raise UnauthorizedError("Session has been revoked", code="SESSION_REVOKED")

    # Load user and check account status
    stmt_user = select(User).where(User.id == user_uuid)
    result_user = await db.execute(stmt_user)
    user = result_user.scalar_one_or_none()

    if not user:
        raise UnauthorizedError("User account not found", code="USER_NOT_FOUND")

    if user.status in (UserStatus.SUSPENDED.value, UserStatus.DELETED.value):
        raise UnauthorizedError("Account is not active", code="ACCOUNT_SUSPENDED")

    return AuthenticatedUser(user=user, session=session, token_payload=payload)


def require_interface(*allowed_interfaces: str) -> Callable[..., Any]:
    """FastAPI dependency enforcing that the caller session belongs to an allowed interface.

    Task C addition:
    - Every token and session belongs to exactly one interface (rider_app, organizer_portal,
      partner_portal, staff_console).
    - Wrong interface returns 403 Forbidden.
    """
    allowed_set: Set[str] = set(allowed_interfaces)

    async def _enforce_interface(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        session_interface = current_user.session.interface
        if session_interface not in allowed_set:
            raise ForbiddenError(
                f"Interface '{session_interface}' is not permitted to access this endpoint. "
                f"Permitted interfaces: {sorted(list(allowed_set))}",
                code="FORBIDDEN_INTERFACE",
            )
        return current_user

    # Attach metadata so reflection/test scans can verify interface declarations
    setattr(_enforce_interface, "__allowed_interfaces__", allowed_set)
    return _enforce_interface


def require_recent_auth(max_age_seconds: int = 900) -> Callable[..., Any]:
    """FastAPI dependency enforcing recent authentication for sensitive operations.

    Task C2 Addition 5:
    - Verifies that the session was created or elevated within max_age_seconds (default 15 mins).
    - Passable in ENV=dev for convenience of dev admin testing (noted in docs).
    """

    async def _enforce_recent_auth(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if settings.ENV == "dev":
            return current_user

        now = datetime.now(timezone.utc)
        created_at = current_user.session.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        age = (now - created_at).total_seconds()
        if age > max_age_seconds:
            raise ForbiddenError(
                "Recent authentication is required for this administrative operation",
                code="RECENT_AUTH_REQUIRED",
                details={
                    "max_age_seconds": max_age_seconds,
                    "session_age_seconds": int(age),
                },
            )
        return current_user

    return _enforce_recent_auth
