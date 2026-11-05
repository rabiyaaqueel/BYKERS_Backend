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
from typing import Any, Dict

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.modules.auth.models import Session, User, UserStatus

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
