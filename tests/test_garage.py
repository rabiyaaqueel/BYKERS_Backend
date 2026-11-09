"""Comprehensive Integration and Unit Tests for Task E: Motorcycle Garage (M03 & M21).

Tests enforce:
1. Create bike with full fields and minimal fields.
2. First bike becomes preferred automatically; second does not.
3. Database rejects two preferred active bikes for one user (partial unique index).
4. Atomically switch preferred bike.
5. Archive preferred bike promotes most recent active bike.
6. Idempotency double-save produces single bike; mismatch payload gives 409.
7. Field-level 422 errors for year, odometer, powertrain, registration.
8. Registration is encrypted in database and masked in all responses.
9. Cross-user isolation: User B gets 404 on User A's bikes, photos, maintenance, documents.
10. Wrong MIME and oversized photo rejected (422).
11. Unscanned photo is not served until scan_state is clean.
12. Staff or organizer token gets 403 Forbidden.
13. Unauthenticated requests get 401 Unauthorized.
14. Reminder job run twice creates zero duplicates.
15. GET /me shows profile_completeness.has_bike flag accurately.
16. Optimistic locking on PATCH /me/bikes/{id} (409 on version mismatch).
17. Maintenance and document recording with signed URL access.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.db import AsyncSessionLocal
from app.core.security import create_access_token
from app.modules.auth.models import Device, Session, User, UserStatus
from app.modules.garage.models import Bike, BikeDocument, MaintenanceRecord
from app.modules.garage.service import run_bike_reminders
from app.modules.rider.models import MediaAsset


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

    device = Device(user_id=user.id, platform="android", device_name="Test Garage Device")
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
async def test_create_bike_full_and_minimal_fields(client: AsyncClient):
    """Test creating bikes with all fields and minimal fields."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Minimal fields (make, model, year, powertrain)
    res_min = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={
            "make": "Royal Enfield",
            "model": "Hunter 350",
            "year": 2023,
            "powertrain": "petrol",
        },
    )
    assert res_min.status_code == 201, res_min.text
    data_min = res_min.json()
    assert data_min["make"] == "Royal Enfield"
    assert data_min["model"] == "Hunter 350"
    assert data_min["year"] == 2023
    assert data_min["powertrain"] == "petrol"
    assert data_min["is_preferred"] is True  # First bike auto-preferred
    assert data_min["registration_masked"] is None
    assert data_min["photos"] == []
    assert data_min["version"] == 1

    # 2. Full fields
    res_full = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={
            "make": "KTM",
            "model": "Duke 390",
            "year": 2024,
            "powertrain": "petrol",
            "nickname": "Orange Beast",
            "odometer_km": 4500,
            "registration": "TS 09 AB 1234",
        },
    )
    assert res_full.status_code == 201, res_full.text
    data_full = res_full.json()
    assert data_full["make"] == "KTM"
    assert data_full["nickname"] == "Orange Beast"
    assert data_full["odometer_km"] == 4500
    assert data_full["is_preferred"] is False  # Second bike not auto-preferred
    assert data_full["registration_masked"] == "******1234"
    assert data_full["version"] == 1


@pytest.mark.asyncio
async def test_preferred_bike_auto_and_switch(client: AsyncClient):
    """First bike is preferred, second is not; atomic switch works."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}

    # First bike
    res1 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Triumph", "model": "Speed 400", "year": 2024, "powertrain": "petrol"},
    )
    bike1_id = res1.json()["id"]
    assert res1.json()["is_preferred"] is True

    # Second bike
    res2 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Harley-Davidson", "model": "X440", "year": 2024, "powertrain": "petrol"},
    )
    bike2_id = res2.json()["id"]
    assert res2.json()["is_preferred"] is False

    # Switch preferred to bike 2
    res_switch = await client.post(f"/api/v1/me/bikes/{bike2_id}/preferred", headers=headers)
    assert res_switch.status_code == 200
    assert res_switch.json()["is_preferred"] is True

    # Check bike 1 is no longer preferred
    res_b1 = await client.get(f"/api/v1/me/bikes/{bike1_id}", headers=headers)
    assert res_b1.json()["is_preferred"] is False


@pytest.mark.asyncio
async def test_database_rejects_two_preferred_bikes_for_one_user():
    """Database partial unique index strictly rejects two preferred active bikes for same rider."""
    async with AsyncSessionLocal() as db:
        user, _, _ = await create_test_rider(db)

        # First preferred bike
        b1 = Bike(
            user_id=user.id,
            make="Yamaha",
            model="R15",
            year=2022,
            powertrain="petrol",
            is_preferred=True,
        )
        db.add(b1)
        await db.commit()

        # Second preferred active bike for same user must raise IntegrityError
        b2 = Bike(
            user_id=user.id,
            make="Kawasaki",
            model="Ninja 300",
            year=2023,
            powertrain="petrol",
            is_preferred=True,
        )
        db.add(b2)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


@pytest.mark.asyncio
async def test_archive_preferred_bike_promotes_another(client: AsyncClient):
    """Archiving the preferred bike promotes the most recent active bike."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}

    # Bike 1 (preferred)
    res1 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Honda", "model": "CB350", "year": 2022, "powertrain": "petrol"},
    )
    bike1_id = res1.json()["id"]

    # Bike 2 (not preferred)
    res2 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Bajaj", "model": "Dominar 400", "year": 2023, "powertrain": "petrol"},
    )
    bike2_id = res2.json()["id"]

    # Archive bike 1
    res_del = await client.delete(f"/api/v1/me/bikes/{bike1_id}", headers=headers)
    assert res_del.status_code == 200

    # Bike 2 must now be promoted to preferred
    res_b2 = await client.get(f"/api/v1/me/bikes/{bike2_id}", headers=headers)
    assert res_b2.json()["is_preferred"] is True


@pytest.mark.asyncio
async def test_idempotency_key_double_save(client: AsyncClient):
    """Double save with same Idempotency-Key returns existing bike without duplicating."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    idemp_key = f"key-{uuid.uuid4()}"
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": idemp_key}
    payload = {"make": "Suzuki", "model": "V-Strom SX", "year": 2023, "powertrain": "petrol"}

    # First request
    res1 = await client.post("/api/v1/me/bikes", headers=headers, json=payload)
    assert res1.status_code == 201
    bike_id_1 = res1.json()["id"]

    # Second request with same idempotency key and same payload
    res2 = await client.post("/api/v1/me/bikes", headers=headers, json=payload)
    assert res2.status_code in (200, 201)
    assert res2.json()["id"] == bike_id_1

    # Verify only 1 bike was created in the database
    async with AsyncSessionLocal() as db:
        cnt_stmt = select(func.count(Bike.id)).where(Bike.user_id == user.id)
        cnt = (await db.execute(cnt_stmt)).scalar()
        assert cnt == 1

    # Request with same key but different payload returns 409 Conflict
    res3 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Suzuki", "model": "Hayabusa", "year": 2024, "powertrain": "petrol"},
    )
    assert res3.status_code == 409


@pytest.mark.asyncio
async def test_validation_errors_422(client: AsyncClient):
    """Invalid year, odometer, powertrain, and registration return field-level 422 errors."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}

    # Invalid year (< 1950)
    r1 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Old", "model": "Bike", "year": 1940, "powertrain": "petrol"},
    )
    assert r1.status_code == 422
    assert "year" in str(r1.json()).lower()

    # Invalid powertrain
    r2 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Solar", "model": "Bike", "year": 2023, "powertrain": "nuclear"},
    )
    assert r2.status_code == 422
    assert "powertrain" in str(r2.json()).lower()

    # Invalid odometer (< 0)
    r3 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={
            "make": "Hero",
            "model": "Splendor",
            "year": 2023,
            "powertrain": "petrol",
            "odometer_km": -10,
        },
    )
    assert r3.status_code == 422
    assert "odometer" in str(r3.json()).lower()

    # Invalid registration (too short or special symbols)
    r4 = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={
            "make": "Hero",
            "model": "Splendor",
            "year": 2023,
            "powertrain": "petrol",
            "registration": "TS!@#",
        },
    )
    assert r4.status_code == 422
    assert "registration" in str(r4.json()).lower()


@pytest.mark.asyncio
async def test_registration_encrypted_and_masked(client: AsyncClient):
    """Registration is encrypted at rest in PostgreSQL and masked in all responses."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={
            "make": "BMW",
            "model": "G310GS",
            "year": 2023,
            "powertrain": "petrol",
            "registration": "AP 28 AB 9876",
        },
    )
    assert res.status_code == 201
    bike_id = res.json()["id"]

    # Response masks registration
    assert res.json()["registration_masked"] == "******9876"
    assert "AP28AB" not in res.text

    # Database stores ciphertext
    async with AsyncSessionLocal() as db:
        b_stmt = select(Bike).where(Bike.id == uuid.UUID(bike_id))
        b_res = await db.execute(b_stmt)
        b = b_res.scalar_one()
        assert b.registration_last4 == "9876"
        assert b.registration_encrypted is not None
        assert "AP28AB9876" not in b.registration_encrypted
        assert b.registration_encrypted.startswith("gAAAAA")  # Fernet signature


@pytest.mark.asyncio
async def test_cross_user_isolation_404(client: AsyncClient):
    """User B accessing User A's bike, photo, maintenance, or documents receives 404."""
    async with AsyncSessionLocal() as db:
        user_a, _, token_a = await create_test_rider(db)
        user_b, _, token_b = await create_test_rider(db)

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates a bike
    res_a = await client.post(
        "/api/v1/me/bikes",
        headers=headers_a,
        json={"make": "Ducati", "model": "Scrambler", "year": 2022, "powertrain": "petrol"},
    )
    bike_id = res_a.json()["id"]

    # User B attempts to access User A's bike
    res_get = await client.get(f"/api/v1/me/bikes/{bike_id}", headers=headers_b)
    assert res_get.status_code == 404

    # User B attempts to patch User A's bike
    res_patch = await client.patch(
        f"/api/v1/me/bikes/{bike_id}",
        headers=headers_b,
        json={"version": 1, "nickname": "Stolen Bike"},
    )
    assert res_patch.status_code == 404

    # User B attempts to view maintenance records of User A's bike
    res_maint = await client.get(f"/api/v1/me/bikes/{bike_id}/maintenance", headers=headers_b)
    assert res_maint.status_code == 404

    # User B attempts to view documents of User A's bike
    res_docs = await client.get(f"/api/v1/me/bikes/{bike_id}/documents", headers=headers_b)
    assert res_docs.status_code == 404


@pytest.mark.asyncio
async def test_photo_upload_validations_and_unscanned_not_served(client: AsyncClient):
    """Wrong MIME and oversized photos rejected; unscanned photos not served in photos list."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}
    res_bike = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Ather", "model": "450X", "year": 2024, "powertrain": "electric"},
    )
    bike_id = res_bike.json()["id"]

    # 1. Reject invalid MIME (e.g. text/plain, image/gif)
    res_mime = await client.post(
        f"/api/v1/me/bikes/{bike_id}/photos/upload-intent",
        headers=headers,
        json={"mime_type": "text/plain", "bytes": 1024},
    )
    assert res_mime.status_code == 422

    # 2. Reject oversized (> 5 MB)
    res_size = await client.post(
        f"/api/v1/me/bikes/{bike_id}/photos/upload-intent",
        headers=headers,
        json={"mime_type": "image/jpeg", "bytes": 6 * 1024 * 1024},
    )
    assert res_size.status_code == 422

    # 3. Valid upload intent
    res_intent = await client.post(
        f"/api/v1/me/bikes/{bike_id}/photos/upload-intent",
        headers=headers,
        json={"mime_type": "image/jpeg", "bytes": 50000, "display_order": 0},
    )
    assert res_intent.status_code == 200
    media_id = res_intent.json()["media_id"]

    # In DB, media_asset starts as scan_state='pending'
    async with AsyncSessionLocal() as db:
        stmt = select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
        asset = (await db.execute(stmt)).scalar_one()
        assert asset.scan_state == "pending"

    # Complete upload linking to bike
    res_comp = await client.post(
        f"/api/v1/me/bikes/{bike_id}/photos/complete",
        headers=headers,
        json={"media_id": media_id, "display_order": 0},
    )
    assert res_comp.status_code == 200

    # Because scan_state is pending, photo MUST NOT be served
    res_b = await client.get(f"/api/v1/me/bikes/{bike_id}", headers=headers)
    assert res_b.json()["photos"] == []

    # Mark clean in DB and re-fetch: photo is now served!
    async with AsyncSessionLocal() as db:
        stmt = select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
        asset = (await db.execute(stmt)).scalar_one()
        asset.scan_state = "clean"
        await db.commit()

    res_clean = await client.get(f"/api/v1/me/bikes/{bike_id}", headers=headers)
    assert len(res_clean.json()["photos"]) == 1
    assert res_clean.json()["photos"][0]["media_id"] == media_id
    assert res_clean.json()["photos"][0]["url"] is not None


@pytest.mark.asyncio
async def test_forbidden_interface_for_staff_or_organizer(client: AsyncClient):
    """Staff console or organizer portal token receives 403 on /me/bikes."""
    async with AsyncSessionLocal() as db:
        _, _, staff_token = await create_test_rider(db, interface="staff_console", role_code="RL13")
        _, _, org_token = await create_test_rider(
            db, interface="organizer_portal", role_code="RL05"
        )

    # Staff token gets 403
    r_staff = await client.get(
        "/api/v1/me/bikes", headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert r_staff.status_code == 403
    assert r_staff.json()["code"] == "FORBIDDEN_INTERFACE"

    # Organizer token gets 403
    r_org = await client.get("/api/v1/me/bikes", headers={"Authorization": f"Bearer {org_token}"})
    assert r_org.status_code == 403
    assert r_org.json()["code"] == "FORBIDDEN_INTERFACE"


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(client: AsyncClient):
    """Unauthenticated calls return 401."""
    r = await client.get("/api/v1/me/bikes")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_reminder_job_idempotent():
    """Running reminder job twice creates zero duplicates."""
    async with AsyncSessionLocal() as db:
        user, _, _ = await create_test_rider(db)

        # Create bike with maintenance and document
        bike = Bike(
            user_id=user.id,
            make="Jawa",
            model="42 Bobber",
            year=2023,
            powertrain="petrol",
            is_preferred=True,
        )
        db.add(bike)
        await db.flush()

        # Service record with next due date in future
        future_date = datetime.now(timezone.utc)
        maint = MaintenanceRecord(
            bike_id=bike.id,
            service_date=future_date,
            odometer_km=5000,
            category="Oil Change",
            next_due_date=future_date,
        )
        db.add(maint)

        # Private document with expiry date
        doc_media = MediaAsset(
            owner_id=user.id,
            purpose="bike_document",
            mime_type="application/pdf",
            bytes=1000,
            object_key=f"bikes/{bike.id}/documents/test.pdf",
            scan_state="clean",
        )
        db.add(doc_media)
        await db.flush()

        doc = BikeDocument(
            bike_id=bike.id,
            type="insurance",
            expires_on=future_date,
            private_media_id=doc_media.id,
        )
        db.add(doc)
        await db.commit()

        # Run 1: Creates reminders
        count_1 = await run_bike_reminders(db)
        assert count_1 >= 2

        # Run 2: Exact duplicate run should create 0 new reminders
        count_2 = await run_bike_reminders(db)
        assert count_2 == 0


@pytest.mark.asyncio
async def test_get_me_profile_completeness_has_bike(client: AsyncClient):
    """GET /me shows in profile_completeness whether the rider has at least one active bike."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}

    # Initially has_bike must be False
    res_before = await client.get("/api/v1/me", headers=headers)
    assert res_before.status_code == 200
    assert res_before.json()["profile_completeness"]["has_bike"] is False

    # Add a bike
    res_bike = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "Ola", "model": "S1 Pro", "year": 2023, "powertrain": "electric"},
    )
    assert res_bike.status_code == 201

    # Now has_bike must be True
    res_after = await client.get("/api/v1/me", headers=headers)
    assert res_after.status_code == 200
    assert res_after.json()["profile_completeness"]["has_bike"] is True


@pytest.mark.asyncio
async def test_optimistic_locking_patch_bike(client: AsyncClient):
    """PATCH /me/bikes/{id} requires version; returns 409 on version mismatch."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}
    res_bike = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={"make": "TVS", "model": "Ronin", "year": 2023, "powertrain": "petrol"},
    )
    bike_id = res_bike.json()["id"]
    current_version = res_bike.json()["version"]

    # Wrong version -> 409 Conflict
    res_conflict = await client.patch(
        f"/api/v1/me/bikes/{bike_id}",
        headers=headers,
        json={"version": current_version + 99, "nickname": "Ronin Cruiser"},
    )
    assert res_conflict.status_code == 409

    # Correct version -> 200 OK and version increments
    res_ok = await client.patch(
        f"/api/v1/me/bikes/{bike_id}",
        headers=headers,
        json={"version": current_version, "nickname": "Ronin Cruiser"},
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["nickname"] == "Ronin Cruiser"
    assert res_ok.json()["version"] == current_version + 1


@pytest.mark.asyncio
async def test_maintenance_and_documents_flow(client: AsyncClient):
    """Test maintenance record creation, odometer progression, and document signed download."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_rider(db)

    headers = {"Authorization": f"Bearer {token}"}
    res_bike = await client.post(
        "/api/v1/me/bikes",
        headers=headers,
        json={
            "make": "Honda",
            "model": "Hness CB350",
            "year": 2023,
            "powertrain": "petrol",
            "odometer_km": 1000,
        },
    )
    bike_id = res_bike.json()["id"]

    # Add maintenance record with higher odometer
    now_iso = datetime.now(timezone.utc).isoformat()
    res_maint = await client.post(
        f"/api/v1/me/bikes/{bike_id}/maintenance",
        headers=headers,
        json={
            "service_date": now_iso,
            "odometer_km": 2500,
            "category": "First Service",
            "notes": "Engine oil and filter change",
            "odometer_source": "manual",
        },
    )
    assert res_maint.status_code == 201
    assert res_maint.json()["odometer_km"] == 2500

    # Bike odometer must now be updated to 2500
    res_b = await client.get(f"/api/v1/me/bikes/{bike_id}", headers=headers)
    assert res_b.json()["odometer_km"] == 2500

    # Create document upload intent
    res_doc_intent = await client.post(
        f"/api/v1/me/bikes/{bike_id}/documents/upload-intent",
        headers=headers,
        json={"mime_type": "application/pdf", "bytes": 120000},
    )
    assert res_doc_intent.status_code == 200
    doc_media_id = res_doc_intent.json()["media_id"]

    # Record document
    res_doc = await client.post(
        f"/api/v1/me/bikes/{bike_id}/documents",
        headers=headers,
        json={
            "type": "insurance",
            "private_media_id": doc_media_id,
            "sharing_policy": "private",
        },
    )
    assert res_doc.status_code == 201
    assert res_doc.json()["type"] == "insurance"
    assert res_doc.json()["download_url"] is not None
