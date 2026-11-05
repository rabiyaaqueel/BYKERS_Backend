"""Authentication and Current User Session API Endpoints."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.dependencies import AuthenticatedUser, get_current_user
from app.core.errors import get_request_id
from app.modules.auth.schemas import (
    AuthTokenOut,
    LogoutOut,
    OTPRequestIn,
    OTPRequestOut,
    OTPVerifyIn,
    RefreshTokenIn,
    SessionOut,
)
from app.modules.auth.service import (
    list_user_sessions,
    logout_current_session,
    refresh_session_tokens,
    request_otp,
    revoke_session_by_id,
    verify_otp,
)

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])
me_router = APIRouter(prefix="/me", tags=["Current User & Devices"])


@auth_router.post(
    "/otp/request",
    response_model=OTPRequestOut,
    summary="Request Phone OTP Challenge",
    description="Sends OTP verification code via SMS. Rate limited to 5 sends/hour with 60s delay.",
)
async def api_request_otp(
    payload: OTPRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> OTPRequestOut:
    client_ip = request.client.host if request.client else None
    request_id = get_request_id(request)
    return await request_otp(db, payload, ip=client_ip, request_id=request_id)


@auth_router.post(
    "/otp/verify",
    response_model=AuthTokenOut,
    summary="Verify Phone OTP & Login",
    description="Verifies the code, registers riders, and returns access & refresh tokens.",
)
async def api_verify_otp(
    payload: OTPVerifyIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthTokenOut:
    client_ip = request.client.host if request.client else None
    request_id = get_request_id(request)
    return await verify_otp(db, payload, ip=client_ip, request_id=request_id)


@auth_router.post(
    "/token/refresh",
    response_model=AuthTokenOut,
    summary="Rotate Refresh Token",
    description="Exchanges active refresh token for new pair. Revokes token family on replay.",
)
async def api_refresh_token(
    payload: RefreshTokenIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthTokenOut:
    request_id = get_request_id(request)
    return await refresh_session_tokens(db, payload, request_id=request_id)


@auth_router.post(
    "/logout",
    response_model=LogoutOut,
    summary="Logout Current Session",
    description="Revokes the active caller session and its associated refresh tokens.",
)
async def api_logout(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LogoutOut:
    request_id = get_request_id(request)
    return await logout_current_session(db, current_user, request_id=request_id)


@me_router.get(
    "/sessions",
    response_model=List[SessionOut],
    summary="List Active User Sessions",
    description="Lists all active login sessions and registered devices for the current rider.",
)
async def api_list_sessions(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[SessionOut]:
    return await list_user_sessions(db, current_user)


@me_router.delete(
    "/sessions/{session_id}",
    summary="Revoke Specific Session",
    description="Remotely revokes a specific device session belonging to the current user.",
)
async def api_revoke_session(
    session_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    request_id = get_request_id(request)
    return await revoke_session_by_id(db, current_user, session_id, request_id=request_id)
