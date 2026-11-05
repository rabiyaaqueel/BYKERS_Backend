"""Tests for Task B: Authentication, OTP, Tokens, Sessions, and Device Management."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.security import hash_token
from app.modules.auth.models import (
    OTPChallenge,
    User,
)


@pytest.fixture(autouse=True)
async def cleanup_auth_test_data():
    """Cleans up test records and preserves environment setting across tests."""
    original_env = settings.ENV
    settings.ENV = "dev"

    async with AsyncSessionLocal() as db:
        await db.execute(delete(OTPChallenge))
        # Find test users
        stmt = select(User.id).where(
            User.phone_normalized.like("+91987654321%") | User.phone_normalized.like("+9199999%")
        )
        res = await db.execute(stmt)
        user_ids = res.scalars().all()
        if user_ids:
            await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()

    try:
        yield
    finally:
        settings.ENV = original_env
        async with AsyncSessionLocal() as db:
            await db.execute(delete(OTPChallenge))
            stmt = select(User.id).where(
                User.phone_normalized.like("+91987654321%")
                | User.phone_normalized.like("+9199999%")
            )
            res = await db.execute(stmt)
            user_ids = res.scalars().all()
            if user_ids:
                await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()


@pytest.mark.asyncio
async def test_unauthenticated_protected_endpoint_returns_401(client: AsyncClient):
    """Calling a protected route without a token returns 401 in Rule 4 format."""
    response = await client.get("/api/v1/me/sessions")
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "UNAUTHORIZED"
    assert "details" in data
    assert "request_id" in data


@pytest.mark.asyncio
async def test_otp_request_and_verify_flow_success(client: AsyncClient):
    """Requesting OTP and verifying it creates user, device, session, and returns token pair."""
    settings.ENV = "dev"
    test_phone = "+919876543210"

    # 1. Request OTP
    req_res = await client.post(
        "/api/v1/auth/otp/request",
        json={
            "country_code": "+91",
            "phone": "9876543210",
            "device": {"platform": "android", "name": "Pixel 8"},
        },
    )
    assert req_res.status_code == 200
    assert req_res.json()["resend_in_seconds"] == 60

    # 2. Verify OTP with DEV_FIXED_OTP
    verify_res = await client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": test_phone,
            "otp": settings.DEV_FIXED_OTP,
            "device": {"platform": "android", "name": "Pixel 8"},
        },
    )
    assert verify_res.status_code == 200
    data = verify_res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900
    assert data["account_status"] == "pending_verification"
    assert data["onboarding_required"] is True


@pytest.mark.asyncio
async def test_same_response_for_known_and_unknown_numbers(client: AsyncClient):
    """OTP request returns identical neutral response for known and unknown phone numbers."""
    settings.ENV = "dev"

    # Number 1: Brand new / unknown
    res_unknown = await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9999900001"},
    )
    assert res_unknown.status_code == 200

    # Create known user
    await client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": "+919999900001",
            "otp": "999999",
        },  # Will fail verification but challenge existed
    )
    # Register a user directly in DB
    async with AsyncSessionLocal() as db:
        user = User(phone_normalized="+919876543211", status="active")
        db.add(user)
        await db.commit()

    # Number 2: Known existing user
    res_known = await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9876543211"},
    )
    assert res_known.status_code == 200

    # Response bodies must be indistinguishable
    assert res_unknown.json() == res_known.json()


@pytest.mark.asyncio
async def test_resend_before_60_seconds_fails_with_429(client: AsyncClient):
    """Requesting an OTP again before the 60s cooldown expires returns 429."""
    settings.ENV = "dev"
    payload = {"country_code": "+91", "phone": "9999900002"}

    # First request
    res1 = await client.post("/api/v1/auth/otp/request", json=payload)
    assert res1.status_code == 200

    # Immediate second request
    res2 = await client.post("/api/v1/auth/otp/request", json=payload)
    assert res2.status_code == 429
    assert res2.json()["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_invalid_otp_fails(client: AsyncClient):
    """Submitting an incorrect OTP code returns 401 INVALID_OTP."""
    settings.ENV = "dev"
    phone = "+919876543212"

    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9876543212"},
    )

    res = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "otp": "000000"},
    )
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_OTP"


@pytest.mark.asyncio
async def test_expired_otp_fails(client: AsyncClient):
    """Submitting an expired OTP returns 401 OTP_EXPIRED."""
    settings.ENV = "dev"
    phone = "+919999900003"

    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9999900003"},
    )

    # Fast forward expiration in database
    async with AsyncSessionLocal() as db:
        phone_h = hash_token(phone)
        stmt = select(OTPChallenge).where(OTPChallenge.phone_hash == phone_h)
        res = await db.execute(stmt)
        challenge = res.scalar_one()
        challenge.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()

    res = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "otp": "123456"},
    )
    assert res.status_code == 401
    assert res.json()["code"] == "OTP_EXPIRED"


@pytest.mark.asyncio
async def test_reused_otp_fails(client: AsyncClient):
    """An OTP cannot be verified twice (one-time use guarantee)."""
    settings.ENV = "dev"
    phone = "+919876543213"

    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9876543213"},
    )

    # First verification succeeds
    res1 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "otp": settings.DEV_FIXED_OTP},
    )
    assert res1.status_code == 200

    # Second verification fails
    res2 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "otp": settings.DEV_FIXED_OTP},
    )
    assert res2.status_code == 401
    assert res2.json()["code"] == "INVALID_OTP"


@pytest.mark.asyncio
async def test_sixth_attempt_fails_with_max_attempts_exceeded(client: AsyncClient):
    """The 6th verification attempt triggers MAX_ATTEMPTS_EXCEEDED."""
    settings.ENV = "dev"
    phone = "+919999900004"

    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9999900004"},
    )

    # Attempts 1 through 5 fail with INVALID_OTP
    for _ in range(5):
        res = await client.post(
            "/api/v1/auth/otp/verify",
            json={"phone": phone, "otp": "000000"},
        )
        assert res.status_code == 401
        assert res.json()["code"] == "INVALID_OTP"

    # Attempt 6 fails with MAX_ATTEMPTS_EXCEEDED
    res6 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "otp": "000000"},
    )
    assert res6.status_code == 401
    assert res6.json()["code"] == "MAX_ATTEMPTS_EXCEEDED"


@pytest.mark.asyncio
async def test_fixed_dev_otp_works_only_for_allowed_phones_and_only_in_dev(
    client: AsyncClient,
):
    """DEV_FIXED_OTP only works if ENV=dev and the phone is in ALLOWED_TEST_PHONES."""
    # 1. Allowed phone in dev -> Works
    settings.ENV = "dev"
    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9876543214"},
    )
    res_dev = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": "+919876543214", "otp": settings.DEV_FIXED_OTP},
    )
    assert res_dev.status_code == 200

    # 2. Non-allowed phone in dev -> Fixed OTP fails
    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9999900005"},
    )
    res_non_allowed = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": "+919999900005", "otp": settings.DEV_FIXED_OTP},
    )
    assert res_non_allowed.status_code == 401

    # 3. Allowed phone in non-dev (ENV=prod) -> Fixed OTP fails
    settings.ENV = "prod"
    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9876543215"},
    )
    res_prod = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": "+919876543215", "otp": settings.DEV_FIXED_OTP},
    )
    assert res_prod.status_code == 401


@pytest.mark.asyncio
async def test_token_refresh_rotation_and_family_revocation_on_reuse(
    client: AsyncClient,
):
    """Refreshing rotates the token; replaying an old refresh token revokes the entire family."""
    settings.ENV = "dev"
    phone = "+919876543210"

    # Login to get initial pair
    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9876543210"},
    )
    login_res = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "otp": settings.DEV_FIXED_OTP},
    )
    token1 = login_res.json()["refresh_token"]

    # Refresh 1: Valid rotation
    ref1_res = await client.post(
        "/api/v1/auth/token/refresh",
        json={"refresh_token": token1},
    )
    assert ref1_res.status_code == 200
    token2 = ref1_res.json()["refresh_token"]
    assert token2 != token1

    # Replay Attack: Using token1 again triggers family revocation
    replay_res = await client.post(
        "/api/v1/auth/token/refresh",
        json={"refresh_token": token1},
    )
    assert replay_res.status_code == 401
    assert replay_res.json()["code"] == "TOKEN_REUSE_DETECTED"

    # Token 2 is now revoked as part of the compromised family
    ref2_res = await client.post(
        "/api/v1/auth/token/refresh",
        json={"refresh_token": token2},
    )
    assert ref2_res.status_code == 401


@pytest.mark.asyncio
async def test_revoked_session_denied_on_next_request(client: AsyncClient):
    """Logging out revokes the session; subsequent calls with that access token fail."""
    settings.ENV = "dev"
    phone = "+919876543210"

    await client.post(
        "/api/v1/auth/otp/request",
        json={"country_code": "+91", "phone": "9876543210"},
    )
    login_res = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "otp": settings.DEV_FIXED_OTP},
    )
    access_token = login_res.json()["access_token"]
    auth_header = {"Authorization": f"Bearer {access_token}"}

    # Session is active
    s_res = await client.get("/api/v1/me/sessions", headers=auth_header)
    assert s_res.status_code == 200

    # Logout
    logout_res = await client.post("/api/v1/auth/logout", headers=auth_header)
    assert logout_res.status_code == 200

    # Calling again is immediately denied
    s_res_after = await client.get("/api/v1/me/sessions", headers=auth_header)
    assert s_res_after.status_code == 401
    assert s_res_after.json()["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_session_management_and_remote_revocation(client: AsyncClient):
    """Users can list active sessions and revoke a specific remote device session."""
    settings.ENV = "dev"
    phone = "+919876543210"

    # Login Device 1
    await client.post(
        "/api/v1/auth/otp/request",
        json={
            "country_code": "+91",
            "phone": "9876543210",
            "device": {"platform": "android", "name": "Device A"},
        },
    )
    dev1_res = await client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": phone,
            "otp": settings.DEV_FIXED_OTP,
            "device": {"platform": "android", "name": "Device A"},
        },
    )
    dev1_token = dev1_res.json()["access_token"]

    # Wait or reset challenge, then Login Device 2
    async with AsyncSessionLocal() as db:
        await db.execute(delete(OTPChallenge))
        await db.commit()

    await client.post(
        "/api/v1/auth/otp/request",
        json={
            "country_code": "+91",
            "phone": "9876543210",
            "device": {"platform": "ios", "name": "Device B"},
        },
    )
    dev2_res = await client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": phone,
            "otp": settings.DEV_FIXED_OTP,
            "device": {"platform": "ios", "name": "Device B"},
        },
    )
    dev2_token = dev2_res.json()["access_token"]

    # List sessions from Device 2
    list_res = await client.get(
        "/api/v1/me/sessions", headers={"Authorization": f"Bearer {dev2_token}"}
    )
    assert list_res.status_code == 200
    sessions = list_res.json()
    assert len(sessions) == 2

    # Identify Device 1 session ID
    dev1_session = next(s for s in sessions if not s["is_current"])
    assert any(s["is_current"] for s in sessions)

    # Revoke Device 1 remotely from Device 2
    del_res = await client.delete(
        f"/api/v1/me/sessions/{dev1_session['id']}",
        headers={"Authorization": f"Bearer {dev2_token}"},
    )
    assert del_res.status_code == 200

    # Device 1 is now revoked
    d1_check = await client.get(
        "/api/v1/me/sessions", headers={"Authorization": f"Bearer {dev1_token}"}
    )
    assert d1_check.status_code == 401
    assert d1_check.json()["code"] == "SESSION_REVOKED"

    # Device 2 remains active
    d2_check = await client.get(
        "/api/v1/me/sessions", headers={"Authorization": f"Bearer {dev2_token}"}
    )
    assert d2_check.status_code == 200
    assert len(d2_check.json()) == 1
