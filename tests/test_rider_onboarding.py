"""Tests for Task D: Rider Onboarding, Profile, Consents, and Real-Time SMS."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.security import create_access_token
from app.core.sms import (
    ConsoleSMSProvider,
    Fast2SMSProvider,
    TwilioSMSProvider,
    get_sms_provider,
)
from app.modules.auth.models import Device, Session, User, UserStatus
from app.modules.rider.models import (
    City,
)


async def create_test_rider(
    db,
    interface: str = "rider_app",
    role_code: str = "RL01",
    phone: Optional[str] = None,
) -> Tuple[User, Session, str]:
    """Helper to provision a test rider and active session token."""
    if not phone:
        unique_digits = f"{uuid.uuid4().int % 100000000:08d}"
        actual_phone = f"+9198{unique_digits}"
    else:
        actual_phone = phone

    user = User(
        phone_normalized=actual_phone,
        status=UserStatus.ACTIVE.value,
        phone_verified_at=datetime.now(timezone.utc),
        locale="en-IN",
    )
    db.add(user)
    await db.flush()

    device = Device(user_id=user.id, platform="android", device_name="Test Android")
    db.add(device)
    await db.flush()

    session = Session(
        user_id=user.id,
        device_id=device.id,
        interface=interface,
        active_context={
            "workspace_id": str(user.id),
            "workspace_type": "personal",
            "role_code": role_code,
        },
        permission_version=1,
    )
    db.add(session)
    await db.commit()
    await db.refresh(user)
    await db.refresh(session)

    token = create_access_token(
        user_id=str(user.id),
        session_id=str(session.id),
        interface=interface,
        permission_version=1,
    )
    return user, session, token


@pytest.mark.asyncio
async def test_public_notices_without_auth(client: AsyncClient):
    """GET /notices/current must be public without requiring login."""
    res = await client.get("/notices/current")
    assert res.status_code == 200
    data = res.json()
    assert "terms" in data and "privacy" in data
    assert data["terms"]["version"] == "v1.0"
    assert data["privacy"]["version"] == "v1.0"

    # Also test prefixed version /api/v1/notices/current
    res2 = await client.get("/api/v1/notices/current")
    assert res2.status_code == 200


@pytest.mark.asyncio
async def test_unauthenticated_rider_endpoints_rejected(client: AsyncClient):
    """All rider endpoints must reject unauthenticated requests with 401."""
    fake_id = str(uuid.uuid4())
    routes_to_test = [
        ("GET", "/api/v1/meta/cities"),
        ("GET", "/api/v1/meta/interests"),
        ("POST", "/api/v1/me/account-setup"),
        ("GET", "/api/v1/me/consents"),
        ("GET", f"/api/v1/profiles/{fake_id}"),
        ("GET", "/api/v1/me/profile-preview"),
        ("POST", "/api/v1/me/photo/upload-intent"),
    ]
    for method, path in routes_to_test:
        if method == "GET":
            res = await client.get(path)
        else:
            res = await client.post(path, json={})
        assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}"


@pytest.mark.asyncio
async def test_staff_token_gets_403_on_rider_endpoints(client: AsyncClient):
    """Staff token (interface=staff_console) gets 403 on rider profile endpoints."""
    async with AsyncSessionLocal() as db:
        user, session, token = await create_test_rider(
            db, interface="staff_console", role_code="RL14"
        )

    headers = {"Authorization": f"Bearer {token}"}
    res = await client.get("/api/v1/meta/cities", headers=headers)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_INTERFACE"

    res2 = await client.post(
        "/api/v1/me/account-setup",
        headers=headers,
        json={"display_name": "Staff Rider", "adult_declaration": True},
    )
    assert res2.status_code == 403


@pytest.mark.asyncio
async def test_metadata_cities_and_interests(client: AsyncClient):
    """Rider token can retrieve list of active cities and multilingual interests."""
    async with AsyncSessionLocal() as db:
        user, session, token = await create_test_rider(db, interface="rider_app")

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Cities
    res_cities = await client.get("/api/v1/meta/cities", headers=headers)
    assert res_cities.status_code == 200
    cities = res_cities.json()
    assert len(cities) >= 5
    city_names = [c["name"] for c in cities]
    assert "Bengaluru" in city_names
    assert "Mumbai" in city_names

    # 2. Interests
    res_int = await client.get("/api/v1/meta/interests", headers=headers)
    assert res_int.status_code == 200
    interests = res_int.json()
    assert len(interests) >= 5
    codes = [i["code"] for i in interests]
    assert "cruising" in codes
    assert "touring" in codes

    # Check multilingual names
    cruising = next(i for i in interests if i["code"] == "cruising")
    assert cruising["name_en"]
    assert cruising["name_te"]
    assert cruising["name_hi"]


@pytest.mark.asyncio
async def test_account_setup_adult_declaration_false_rejected(client: AsyncClient):
    """POST /me/account-setup with adult_declaration=False is rejected with 422."""
    async with AsyncSessionLocal() as db:
        user, session, token = await create_test_rider(db, interface="rider_app")

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "display_name": "Young Rider",
        "adult_declaration": False,
        "accepted_terms_version": "v1.0",
        "accepted_privacy_version": "v1.0",
    }
    res = await client.post("/api/v1/me/account-setup", headers=headers, json=payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_account_setup_stale_notices_rejected(client: AsyncClient):
    """POST /me/account-setup with outdated notice version is rejected."""
    async with AsyncSessionLocal() as db:
        user, session, token = await create_test_rider(db, interface="rider_app")

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "display_name": "Rider One",
        "adult_declaration": True,
        "accepted_terms_version": "v0.5",  # stale
        "accepted_privacy_version": "v1.0",
    }
    res = await client.post("/api/v1/me/account-setup", headers=headers, json=payload)
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_account_setup_success_and_get_me(client: AsyncClient):
    """Completes full account setup, verifies Profile, consents, and extended GET /me."""
    async with AsyncSessionLocal() as db:
        user, session, token = await create_test_rider(db, interface="rider_app")
        # Get a city id
        c_res = await db.execute(select(City.id).limit(1))
        city_id = str(c_res.scalar_one())

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "display_name": "Royal Enfield Rider",
        "city_id": city_id,
        "locale": "en-IN",
        "adult_declaration": True,
        "accepted_terms_version": "v1.0",
        "accepted_privacy_version": "v1.0",
        "marketing_consent": True,
        "interests": ["cruising", "touring"],
    }
    res = await client.post("/api/v1/me/account-setup", headers=headers, json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["account_setup_completed"] is True
    assert data["onboarding_required"] is False
    assert data["profile"]["display_name"] == "Royal Enfield Rider"
    assert data["consents"]["terms"] == "granted"
    assert data["consents"]["privacy"] == "granted"
    assert data["consents"]["marketing"] == "granted"
    assert "phone verified" in data["verified_badges"]

    # Extended GET /me route returns identical complete details
    me_res = await client.get("/api/v1/me", headers=headers)
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["account_setup_completed"] is True
    assert me_data["profile"]["display_name"] == "Royal Enfield Rider"


@pytest.mark.asyncio
async def test_public_profile_never_leaks_phone_or_private_data(client: AsyncClient):
    """Public profile NEVER contains phone number, email, or legal name."""
    phone_a = f"+9198{uuid.uuid4().int % 100000000:08d}"
    phone_b = f"+9198{uuid.uuid4().int % 100000000:08d}"
    async with AsyncSessionLocal() as db:
        rider_a, sess_a, token_a = await create_test_rider(db, phone=phone_a)
        rider_b, sess_b, token_b = await create_test_rider(db, phone=phone_b)

    # Setup profile for B
    headers_b = {"Authorization": f"Bearer {token_b}"}
    await client.post(
        "/api/v1/me/account-setup",
        headers=headers_b,
        json={
            "display_name": "Secret Rider B",
            "adult_declaration": True,
            "accepted_terms_version": "v1.0",
            "accepted_privacy_version": "v1.0",
        },
    )
    # Also add private details for B
    await client.patch(
        "/api/v1/me",
        headers=headers_b,
        json={"legal_name": "Private Legal Name", "email": "confidential@bykers.app"},
    )

    # Rider A views Rider B's public profile
    headers_a = {"Authorization": f"Bearer {token_a}"}
    res = await client.get(f"/api/v1/profiles/{rider_b.id}", headers=headers_a)
    assert res.status_code == 200
    public_data = res.json()

    assert public_data["display_name"] == "Secret Rider B"
    assert "phone" not in public_data
    assert "phone_normalized" not in public_data
    assert "legal_name" not in public_data
    assert "email" not in public_data
    # Assert string representation of raw json doesn't contain the phone digits or private name
    raw_text = res.text
    assert phone_b[3:] not in raw_text
    assert "Private Legal Name" not in raw_text
    assert "confidential@bykers.app" not in raw_text


@pytest.mark.asyncio
async def test_private_visibility_hides_from_others(client: AsyncClient):
    """Private visibility masks the profile from other riders while visible to owner."""
    async with AsyncSessionLocal() as db:
        rider_a, sess_a, token_a = await create_test_rider(db)
        rider_b, sess_b, token_b = await create_test_rider(db)

    headers_b = {"Authorization": f"Bearer {token_b}"}
    await client.post(
        "/api/v1/me/account-setup",
        headers=headers_b,
        json={
            "display_name": "Ghost Rider",
            "adult_declaration": True,
            "accepted_terms_version": "v1.0",
            "accepted_privacy_version": "v1.0",
        },
    )
    # Set visibility to private
    await client.patch("/api/v1/me", headers=headers_b, json={"visibility": "private"})

    # Rider A looks up Rider B: details masked
    headers_a = {"Authorization": f"Bearer {token_a}"}
    res_a = await client.get(f"/api/v1/profiles/{rider_b.id}", headers=headers_a)
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["visibility"] == "private"
    assert data_a["message"] == "This profile is private."
    assert data_a["bio"] is None
    assert len(data_a["interests"]) == 0

    # Rider B previews own profile: full view is returned
    res_b = await client.get("/api/v1/me/profile-preview", headers=headers_b)
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["display_name"] == "Ghost Rider"
    assert data_b["visibility"] == "private"


@pytest.mark.asyncio
async def test_consent_changes_append_only(client: AsyncClient):
    """Consent updates create new history rows and never overwrite past events."""
    async with AsyncSessionLocal() as db:
        rider, sess, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/api/v1/me/account-setup",
        headers=headers,
        json={
            "display_name": "Consent Rider",
            "adult_declaration": True,
            "accepted_terms_version": "v1.0",
            "accepted_privacy_version": "v1.0",
        },
    )

    # 1. Grant ride recording
    res1 = await client.post(
        "/api/v1/me/consents",
        headers=headers,
        json={"purpose": "ride_recording", "action": "granted"},
    )
    assert res1.status_code == 200

    # 2. Withdraw ride recording
    res2 = await client.post(
        "/api/v1/me/consents",
        headers=headers,
        json={"purpose": "ride_recording", "action": "withdrawn"},
    )
    assert res2.status_code == 200

    # 3. Check history: must have both events recorded
    history_res = await client.get("/api/v1/me/consents", headers=headers)
    assert history_res.status_code == 200
    events = history_res.json()
    rr_events = [e for e in events if e["purpose"] == "ride_recording"]
    assert len(rr_events) == 2
    assert rr_events[0]["action"] == "granted"
    assert rr_events[1]["action"] == "withdrawn"

    # Effective status on /me shows withdrawn
    me_res = await client.get("/api/v1/me", headers=headers)
    assert me_res.json()["consents"]["ride_recording"] == "withdrawn"


@pytest.mark.asyncio
async def test_photo_upload_validations_and_lifecycle(client: AsyncClient):
    """Photo upload intent enforces MIME and size checks, and clean scan check."""
    async with AsyncSessionLocal() as db:
        rider, sess, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/api/v1/me/account-setup",
        headers=headers,
        json={
            "display_name": "Photo Rider",
            "adult_declaration": True,
            "accepted_terms_version": "v1.0",
            "accepted_privacy_version": "v1.0",
        },
    )

    # 1. Invalid MIME type rejected
    bad_mime = await client.post(
        "/api/v1/me/photo/upload-intent",
        headers=headers,
        json={"filename": "doc.pdf", "mime_type": "application/pdf", "bytes": 1000},
    )
    assert bad_mime.status_code == 422

    # 2. Oversized file (> 5MB) rejected
    too_big = await client.post(
        "/api/v1/me/photo/upload-intent",
        headers=headers,
        json={"filename": "photo.jpg", "mime_type": "image/jpeg", "bytes": 6 * 1024 * 1024},
    )
    assert too_big.status_code == 422

    # 3. Valid photo intent
    intent_res = await client.post(
        "/api/v1/me/photo/upload-intent",
        headers=headers,
        json={"filename": "avatar.jpg", "mime_type": "image/jpeg", "bytes": 1024 * 500},
    )
    assert intent_res.status_code == 200
    intent_data = intent_res.json()
    media_id = intent_data["media_asset_id"]

    # 4. Complete photo upload
    complete_res = await client.post(
        "/api/v1/me/photo/complete",
        headers=headers,
        json={"media_asset_id": media_id},
    )
    assert complete_res.status_code == 200
    complete_data = complete_res.json()
    assert complete_data["scan_state"] == "clean"
    assert complete_data["photo_url"] is not None


@pytest.mark.asyncio
async def test_realtime_sms_providers():
    """Validates Console, Fast2SMS, and Twilio SMS providers format and dispatch."""
    # 1. Console provider
    console_p = ConsoleSMSProvider()
    ok_console = await console_p.send_otp("+919876543210", "654321")
    assert ok_console is True

    # 2. Fast2SMS Provider with mocked httpx
    f2s = Fast2SMSProvider(api_key="test_dummy_key")
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"return": True, "message": ["SMS sent successfully"]}
        mock_post.return_value = mock_resp

        ok_f2s = await f2s.send_otp("+919876543210", "123456")
        assert ok_f2s is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args.kwargs["json"]["numbers"] == "9876543210"
        assert call_args.kwargs["json"]["variables_values"] == "123456"

    # 3. Twilio Provider with mocked httpx
    twilio = TwilioSMSProvider(
        account_sid="AC_test",
        auth_token="auth_test",
        from_number="+1234567890",
    )
    with patch("httpx.AsyncClient.post") as mock_twilio_post:
        mock_tresp = AsyncMock()
        mock_tresp.status_code = 201
        mock_tresp.text = "Success"
        mock_twilio_post.return_value = mock_tresp

        ok_tw = await twilio.send_otp("+919876543210", "987654")
        assert ok_tw is True
        mock_twilio_post.assert_called_once()
        t_data = mock_twilio_post.call_args.kwargs["data"]
        assert t_data["To"] == "+919876543210"
        assert "987654" in t_data["Body"]

    # 4. get_sms_provider factory fallback
    assert isinstance(get_sms_provider("console"), ConsoleSMSProvider)
    # When api key missing, falls back cleanly to console
    with patch.object(settings, "FAST2SMS_API_KEY", None):
        assert isinstance(get_sms_provider("fast2sms"), ConsoleSMSProvider)
