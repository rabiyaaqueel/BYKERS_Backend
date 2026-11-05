"""Authentication, OTP, and Session Management Service."""

import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import record_audit_event
from app.core.config import settings
from app.core.dependencies import AuthenticatedUser
from app.core.errors import (
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
    ValidationError,
)
from app.core.security import (
    create_access_token,
    generate_secure_token,
    hash_token,
    mask_phone,
    verify_hash,
)
from app.modules.auth.models import (
    AuthIdentity,
    Device,
    InterfaceType,
    OTPChallenge,
    RefreshToken,
    Session,
    User,
    UserStatus,
)
from app.modules.auth.schemas import (
    AuthTokenOut,
    LogoutOut,
    OTPRequestIn,
    OTPRequestOut,
    OTPVerifyIn,
    RefreshTokenIn,
    SessionOut,
)

logger = logging.getLogger("bykers.auth")


def normalize_phone(country_code: str, phone: str) -> str:
    """Cleans and standardizes phone number into E.164 international format."""
    clean_code = country_code.strip()
    if not clean_code.startswith("+"):
        clean_code = f"+{clean_code}"

    # Remove all non-digits from phone
    digits_only = re.sub(r"\D", "", phone)
    if not digits_only:
        raise ValidationError("Invalid phone number provided")

    # If the user already provided country code digits in the phone input
    if phone.strip().startswith("+"):
        return f"+{digits_only}"

    # Strip single leading zero common in national dialing
    if digits_only.startswith("0"):
        digits_only = digits_only[1:]

    return f"{clean_code}{digits_only}"


async def request_otp(
    db: AsyncSession,
    payload: OTPRequestIn,
    ip: Optional[str] = None,
    request_id: str = "",
) -> OTPRequestOut:
    """Issues an OTP verification challenge with rate limiting and privacy guarantees."""
    phone_norm = normalize_phone(payload.country_code, payload.phone)
    phone_h = hash_token(phone_norm)
    now = datetime.now(timezone.utc)

    # 1. Check existing challenge for this phone
    stmt = select(OTPChallenge).where(OTPChallenge.phone_hash == phone_h)
    result = await db.execute(stmt)
    challenge = result.scalar_one_or_none()

    if challenge:
        # Enforce 60-second cooldown
        elapsed_seconds = (now - challenge.last_sent_at).total_seconds()
        if elapsed_seconds < settings.OTP_RESEND_SECONDS:
            remaining = int(settings.OTP_RESEND_SECONDS - elapsed_seconds)
            raise RateLimitError(
                f"Please wait {remaining} seconds before requesting a new code.",
                details={"retry_after_seconds": remaining},
            )

        # Enforce hourly send quota
        time_since_first = (now - challenge.last_sent_at).total_seconds()
        if time_since_first < 3600 and challenge.send_count >= settings.OTP_MAX_SENDS_PER_HOUR:
            raise RateLimitError(
                "Maximum verification requests exceeded for this hour. Please try again later.",
                details={"max_hourly_sends": settings.OTP_MAX_SENDS_PER_HOUR},
            )

    # 2. Determine OTP code (Dev Fixed vs Random)
    if settings.ENV == "dev" and phone_norm in settings.ALLOWED_TEST_PHONES:
        otp_code = settings.DEV_FIXED_OTP
        logger.info(
            "[DEV OTP] Generated fixed test code for %s: %s",
            mask_phone(phone_norm),
            otp_code,
        )
    else:
        otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
        if settings.ENV == "dev":
            logger.info(
                "[DEV OTP] Generated random code for %s: %s",
                mask_phone(phone_norm),
                otp_code,
            )

    expires_at = now + timedelta(minutes=settings.OTP_EXPIRES_MINUTES)
    otp_h = hash_token(otp_code)

    # 3. Upsert challenge record
    if challenge:
        challenge.otp_hash = otp_h
        challenge.expires_at = expires_at
        challenge.attempts = 0
        challenge.send_count = (
            challenge.send_count + 1 if (now - challenge.last_sent_at).total_seconds() < 3600 else 1
        )
        challenge.last_sent_at = now
        challenge.ip = ip
        if payload.device:
            challenge.device_id = payload.device.name
    else:
        new_challenge = OTPChallenge(
            phone_hash=phone_h,
            otp_hash=otp_h,
            expires_at=expires_at,
            attempts=0,
            send_count=1,
            last_sent_at=now,
            ip=ip,
            device_id=payload.device.name if payload.device else None,
        )
        db.add(new_challenge)

    await db.commit()

    return OTPRequestOut(
        message="If the phone number is valid, a verification code has been sent.",
        resend_in_seconds=settings.OTP_RESEND_SECONDS,
    )


async def verify_otp(
    db: AsyncSession,
    payload: OTPVerifyIn,
    ip: Optional[str] = None,
    request_id: str = "",
) -> AuthTokenOut:
    """Verifies a phone OTP challenge, provision user/device/session, and returns JWT tokens."""
    phone_norm = normalize_phone("+91", payload.phone)
    phone_h = hash_token(phone_norm)
    now = datetime.now(timezone.utc)

    stmt = select(OTPChallenge).where(OTPChallenge.phone_hash == phone_h)
    result = await db.execute(stmt)
    challenge = result.scalar_one_or_none()

    if not challenge:
        record_audit_event(
            actor=mask_phone(phone_norm),
            action="login_failure",
            resource="auth",
            reason="challenge_not_found",
            request_id=request_id,
        )
        raise UnauthorizedError("Invalid or expired verification code.", code="INVALID_OTP")

    # Check maximum attempts (6th attempt fails)
    if challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
        record_audit_event(
            actor=mask_phone(phone_norm),
            action="login_failure",
            resource="auth",
            reason="max_attempts_exceeded",
            request_id=request_id,
        )
        raise UnauthorizedError(
            "Maximum verification attempts exceeded. Please request a new code.",
            code="MAX_ATTEMPTS_EXCEEDED",
        )

    # Increment attempt count
    challenge.attempts += 1
    await db.flush()

    # Check expiration
    if now > challenge.expires_at:
        record_audit_event(
            actor=mask_phone(phone_norm),
            action="login_failure",
            resource="auth",
            reason="otp_expired",
            request_id=request_id,
        )
        await db.commit()
        raise UnauthorizedError(
            "Verification code has expired. Please request a new code.",
            code="OTP_EXPIRED",
        )

    # Check code validity
    is_valid = False
    if (
        settings.ENV == "dev"
        and phone_norm in settings.ALLOWED_TEST_PHONES
        and payload.otp == settings.DEV_FIXED_OTP
    ):
        is_valid = True
    else:
        is_valid = verify_hash(payload.otp, challenge.otp_hash)

    if not is_valid:
        record_audit_event(
            actor=mask_phone(phone_norm),
            action="login_failure",
            resource="auth",
            reason="invalid_code",
            request_id=request_id,
        )
        await db.commit()
        raise UnauthorizedError("Invalid verification code.", code="INVALID_OTP")

    # OTP is verified! Invalidate challenge immediately so it cannot be reused
    await db.delete(challenge)

    # Find or create user
    user_stmt = select(User).where(
        User.phone_normalized == phone_norm, User.status != UserStatus.DELETED.value
    )
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    if not user:
        user = User(
            phone_normalized=phone_norm,
            phone_verified_at=now,
            status=UserStatus.PENDING_VERIFICATION.value,
            locale="en-IN",
        )
        db.add(user)
        await db.flush()

        identity = AuthIdentity(
            user_id=user.id,
            provider="phone",
            subject=phone_norm,
            verified_at=now,
        )
        db.add(identity)
    else:
        if user.status in (UserStatus.SUSPENDED.value, UserStatus.DELETED.value):
            record_audit_event(
                actor=str(user.id),
                action="login_blocked",
                resource="auth",
                reason="account_suspended",
                request_id=request_id,
            )
            await db.commit()
            raise ForbiddenError("Account is suspended or deactivated.", code="ACCOUNT_SUSPENDED")

        if not user.phone_verified_at:
            user.phone_verified_at = now

    # Upsert Device
    device_platform = payload.device.platform if payload.device else "android"
    device_name = payload.device.name if payload.device else "Mobile Device"
    push_token = payload.device.push_token if payload.device else None

    dev_stmt = select(Device).where(
        Device.user_id == user.id,
        Device.device_name == device_name,
        Device.platform == device_platform,
    )
    dev_res = await db.execute(dev_stmt)
    device = dev_res.scalar_one_or_none()

    if device:
        device.last_active_at = now
        if push_token:
            device.push_token = push_token
        device.revoked_at = None
    else:
        device = Device(
            user_id=user.id,
            platform=device_platform,
            device_name=device_name,
            push_token=push_token,
            last_active_at=now,
        )
        db.add(device)
        await db.flush()

    # Create new active Session
    session = Session(
        user_id=user.id,
        device_id=device.id,
        interface=InterfaceType.RIDER_APP.value,
        active_context={},
        permission_version=1,
        auth_assurance="aal1_otp",
    )
    db.add(session)
    await db.flush()

    # Generate Access Token & Rotating Refresh Token
    access_token = create_access_token(
        user_id=str(user.id),
        session_id=str(session.id),
        permission_version=session.permission_version,
        interface=session.interface,
    )

    raw_refresh = generate_secure_token(32)
    refresh_record = RefreshToken(
        session_id=session.id,
        family_id=uuid.uuid4(),
        token_hash=hash_token(raw_refresh),
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_DAYS),
    )
    db.add(refresh_record)

    record_audit_event(
        actor=str(user.id),
        action="login_success",
        resource="auth",
        reason="otp_verified",
        request_id=request_id,
    )

    await db.commit()

    return AuthTokenOut(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
        account_status=user.status,
        onboarding_required=(user.status == UserStatus.PENDING_VERIFICATION.value),
    )


async def refresh_session_tokens(
    db: AsyncSession,
    payload: RefreshTokenIn,
    request_id: str = "",
) -> AuthTokenOut:
    """Rotates refresh token family; revokes family if reuse is detected."""
    token_h = hash_token(payload.refresh_token)
    now = datetime.now(timezone.utc)

    stmt = (
        select(RefreshToken)
        .options(selectinload(RefreshToken.session).selectinload(Session.user))
        .where(RefreshToken.token_hash == token_h)
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if not token:
        record_audit_event(
            actor="unknown",
            action="token_refresh_failed",
            resource="auth",
            reason="token_not_found",
            request_id=request_id,
        )
        raise UnauthorizedError("Invalid refresh token.", code="INVALID_REFRESH_TOKEN")

    # TOKEN REPLAY ATTACK DETECTION
    if token.used_at is not None:
        # Revoke the whole family and the session!
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id)
            .values(revoked_at=now)
        )
        await db.execute(
            update(Session).where(Session.id == token.session_id).values(revoked_at=now)
        )
        record_audit_event(
            actor=str(token.session.user_id),
            action="token_reuse_detected",
            resource="auth",
            reason="reused_refresh_token_family_revoked",
            request_id=request_id,
        )
        await db.commit()
        raise UnauthorizedError(
            "Security violation: Token was already used. All sessions revoked.",
            code="TOKEN_REUSE_DETECTED",
        )

    if token.revoked_at is not None:
        raise UnauthorizedError("Refresh token has been revoked.", code="TOKEN_REVOKED")

    if now > token.expires_at:
        raise UnauthorizedError("Refresh token has expired.", code="TOKEN_EXPIRED")

    session = token.session
    if not session or session.revoked_at is not None:
        raise UnauthorizedError("Session has been revoked.", code="SESSION_REVOKED")

    user = session.user
    if not user or user.status in (UserStatus.SUSPENDED.value, UserStatus.DELETED.value):
        raise UnauthorizedError("User account is not active.", code="ACCOUNT_SUSPENDED")

    # Mark old token used
    token.used_at = now

    # Issue new token in the SAME family
    new_raw_refresh = generate_secure_token(32)
    new_refresh = RefreshToken(
        session_id=session.id,
        family_id=token.family_id,
        token_hash=hash_token(new_raw_refresh),
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_DAYS),
    )
    db.add(new_refresh)

    # Issue fresh access token
    new_access_token = create_access_token(
        user_id=str(user.id),
        session_id=str(session.id),
        permission_version=session.permission_version,
        interface=session.interface,
    )

    await db.commit()

    return AuthTokenOut(
        access_token=new_access_token,
        refresh_token=new_raw_refresh,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
        account_status=user.status,
        onboarding_required=(user.status == UserStatus.PENDING_VERIFICATION.value),
    )


async def logout_current_session(
    db: AsyncSession,
    current_user: AuthenticatedUser,
    request_id: str = "",
) -> LogoutOut:
    """Revokes the active caller session and its associated refresh tokens."""
    now = datetime.now(timezone.utc)
    session = current_user.session
    session.revoked_at = now

    await db.execute(
        update(RefreshToken).where(RefreshToken.session_id == session.id).values(revoked_at=now)
    )

    record_audit_event(
        actor=str(current_user.user_id),
        action="logout",
        resource="auth",
        reason="user_requested_logout",
        request_id=request_id,
    )

    await db.commit()
    return LogoutOut()


async def list_user_sessions(
    db: AsyncSession,
    current_user: AuthenticatedUser,
) -> List[SessionOut]:
    """Retrieves active sessions with redacted metadata for the current user."""
    stmt = (
        select(Session)
        .options(selectinload(Session.device))
        .where(
            Session.user_id == current_user.user_id,
            Session.revoked_at.is_(None),
        )
        .order_by(Session.created_at.desc())
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    output: List[SessionOut] = []
    for s in sessions:
        dev_platform = s.device.platform if s.device else "unknown"
        dev_name = s.device.device_name if s.device else "Unknown Device"
        last_act = s.device.last_active_at if s.device else s.created_at
        output.append(
            SessionOut(
                id=s.id,
                interface=s.interface,
                platform=dev_platform,
                device_name=dev_name,
                created_at=s.created_at,
                last_active_at=last_act,
                is_current=(s.id == current_user.session_id),
            )
        )
    return output


async def revoke_session_by_id(
    db: AsyncSession,
    current_user: AuthenticatedUser,
    session_id: uuid.UUID,
    request_id: str = "",
) -> dict:
    """Revokes a specific session belonging to the caller."""
    stmt = select(Session).where(
        Session.id == session_id,
        Session.user_id == current_user.user_id,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise NotFoundError("Session not found", code="SESSION_NOT_FOUND")

    now = datetime.now(timezone.utc)
    session.revoked_at = now

    await db.execute(
        update(RefreshToken).where(RefreshToken.session_id == session.id).values(revoked_at=now)
    )

    record_audit_event(
        actor=str(current_user.user_id),
        action="session_revocation",
        resource="auth",
        reason=f"revoked_session_{session_id}",
        request_id=request_id,
    )

    await db.commit()
    return {"message": "Session successfully revoked"}
