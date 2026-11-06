"""Tests for Task C2: Module Registry and Customization for Web Interfaces."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.security import create_access_token
from app.main import create_app
from app.modules.auth.models import Device, Session, User, UserStatus
from app.modules.authz.models import (
    AuditEvent,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationType,
    OrgApprovalState,
    Role,
)
from app.modules.registry.models import (
    InterfaceModule,
    Module,
    OrganizationCategory,
    OrganizationModule,
)


@pytest.fixture(autouse=True)
async def registry_test_setup():
    """Sets ENV to dev for tests and cleans up test records."""
    original_env = settings.ENV
    settings.ENV = "dev"
    try:
        yield
    finally:
        settings.ENV = original_env
        async with AsyncSessionLocal() as db:
            stmt = select(Organization.id).where(Organization.name.like("TEST_MOD_%"))
            res = await db.execute(stmt)
            org_ids = res.scalars().all()
            if org_ids:
                await db.execute(
                    delete(OrganizationModule).where(
                        OrganizationModule.organization_id.in_(org_ids)
                    )
                )
                await db.execute(
                    delete(OrganizationCategory).where(
                        OrganizationCategory.organization_id.in_(org_ids)
                    )
                )
                await db.execute(
                    delete(OrganizationMembership).where(
                        OrganizationMembership.organization_id.in_(org_ids)
                    )
                )
                await db.execute(delete(Organization).where(Organization.id.in_(org_ids)))
            await db.commit()


async def create_test_actor(
    db,
    interface: str,
    role_code: str,
    org_id: Optional[uuid.UUID] = None,
    phone: Optional[str] = None,
) -> Tuple[User, Session, str]:
    """Helper to provision a test user and session with active context."""
    if not phone:
        unique_digits = f"{uuid.uuid4().int % 100000000:08d}"
        actual_phone = f"+9199{unique_digits}"
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

    device = Device(user_id=user.id, platform="android", device_name="Test Device")
    db.add(device)
    await db.flush()

    active_ctx: Dict[str, Any] = {
        "workspace_id": str(org_id or user.id),
        "workspace_type": "organization" if org_id else "personal",
        "role_code": role_code,
    }
    if org_id:
        active_ctx["organization_id"] = str(org_id)

    session = Session(
        user_id=user.id,
        device_id=device.id,
        interface=interface,
        active_context=active_ctx,
        permission_version=1,
    )
    db.add(session)
    await db.flush()

    # Assign membership if org_id is provided
    if org_id:
        stmt_role = select(Role).where(Role.code == role_code)
        role = (await db.execute(stmt_role)).scalars().first()
        if role:
            mem = OrganizationMembership(
                user_id=user.id,
                organization_id=org_id,
                role_id=role.id,
                status=MembershipStatus.ACTIVE.value,
                version=1,
            )
            db.add(mem)
            await db.flush()

    token = create_access_token(
        user_id=str(user.id),
        session_id=str(session.id),
        permission_version=session.permission_version,
        interface=session.interface,
    )
    await db.commit()
    return user, session, token


async def create_test_org_with_owner(
    db,
    org_name: str,
    org_type: str = OrganizationType.CLUB_ORG.value,
    role_code: str = "RL02",
    interface: str = "organizer_portal",
) -> Tuple[User, Session, str, Organization]:
    """Helper to provision an organization and an active owner user."""
    user, session, _ = await create_test_actor(db, interface=interface, role_code=role_code)
    org = Organization(
        type=org_type,
        name=org_name,
        approval_state=OrgApprovalState.APPROVED.value,
        created_by=user.id,
    )
    db.add(org)
    await db.flush()

    stmt_role = select(Role).where(Role.code == role_code)
    role = (await db.execute(stmt_role)).scalars().first()
    if role:
        mem = OrganizationMembership(
            user_id=user.id,
            organization_id=org.id,
            role_id=role.id,
            status=MembershipStatus.ACTIVE.value,
            version=1,
        )
        db.add(mem)

    session.active_context = {
        "workspace_id": str(org.id),
        "workspace_type": "organization",
        "organization_id": str(org.id),
        "role_code": role_code,
    }
    await db.commit()

    token = create_access_token(
        user_id=str(user.id),
        session_id=str(session.id),
        permission_version=session.permission_version,
        interface=session.interface,
    )
    return user, session, token, org


# ==============================================================================
# 1. rider_app Token Refusal on /me/menu
# ==============================================================================


@pytest.mark.asyncio
async def test_rider_app_token_gets_403_on_me_menu(client: AsyncClient):
    """Rider mobile app token receives 403 Forbidden on web menu endpoint."""
    async with AsyncSessionLocal() as db:
        user, session, token = await create_test_actor(db, interface="rider_app", role_code="RL01")

    headers = {"Authorization": f"Bearer {token}"}
    res = await client.get("/api/v1/me/menu", headers=headers)
    assert res.status_code == 403
    data = res.json()
    assert data["code"] == "FORBIDDEN_INTERFACE"


# ==============================================================================
# 2. Web Interface Menu & Staff Disabling Module Demo
# ==============================================================================


@pytest.mark.asyncio
async def test_demo_staff_disables_m12_for_one_organization_menu_updates(client: AsyncClient):
    """Demo test: Staff disables M12 for an organization; that organization's owner calls

    GET /me/menu and no longer sees M12.
    """
    async with AsyncSessionLocal() as db:
        # Create Club Organization with Owner
        owner, owner_sess, owner_token, club = await create_test_org_with_owner(
            db, org_name="TEST_MOD_Club_Falcon", role_code="RL02"
        )

        # Create Staff Admin on staff_console
        stmt_plat = select(Organization).where(Organization.type == OrganizationType.PLATFORM.value)
        plat_org = (await db.execute(stmt_plat)).scalars().first()
        admin, admin_sess, admin_token = await create_test_actor(
            db, interface="staff_console", role_code="RL13", org_id=plat_org.id
        )

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Step 1: Club owner calls /me/menu -> sees M12 (Tours)
    res_before = await client.get("/api/v1/me/menu", headers=owner_headers)
    assert res_before.status_code == 200
    menu_codes_before = [m["code"] for m in res_before.json()["modules"]]
    assert "M12" in menu_codes_before
    assert "M06" in menu_codes_before

    # Step 2: Staff admin disables M12 for this club
    res_toggle = await client.put(
        f"/api/v1/admin/organizations/{club.id}/modules",
        json={"modules": {"M12": False}},
        headers=admin_headers,
    )
    assert res_toggle.status_code == 200

    # Step 3: Club owner calls /me/menu again -> M12 is absent!
    res_after = await client.get("/api/v1/me/menu", headers=owner_headers)
    assert res_after.status_code == 200
    menu_codes_after = [m["code"] for m in res_after.json()["modules"]]
    assert "M12" not in menu_codes_after
    assert "M06" in menu_codes_after


# ==============================================================================
# 3. Disabled Module Refused on Shared Permission Layer (can/require)
# ==============================================================================


@pytest.mark.asyncio
async def test_disabled_module_denied_on_api_even_with_right_role(client: AsyncClient):
    """When a module is disabled for an organization, calling an endpoint protected

    by require(..., module_code) returns 403 Forbidden.
    """
    async with AsyncSessionLocal() as db:
        owner, _, owner_token, club = await create_test_org_with_owner(
            db, org_name="TEST_MOD_Club_Disabled_Check", role_code="RL02"
        )

        # Disable M06 (Clubs) for this organization
        stmt_m06 = select(Module).where(Module.code == "M06")
        m06 = (await db.execute(stmt_m06)).scalars().first()
        om = OrganizationModule(
            organization_id=club.id,
            module_id=m06.id,
            enabled=False,
            version=1,
        )
        db.add(om)
        await db.commit()

    headers = {"Authorization": f"Bearer {owner_token}"}

    # Endpoint declaring module_code="M06": POST /organizations/{id}/invitations
    res = await client.post(
        f"/api/v1/organizations/{club.id}/invitations",
        json={"role_code": "RL03", "phone": "+919876543299"},
        headers=headers,
    )
    assert res.status_code == 403
    assert "disabled" in res.json()["message"].lower()


# ==============================================================================
# 4. Club Owner A Cannot Change Club B's Modules
# ==============================================================================


@pytest.mark.asyncio
async def test_club_owner_a_cannot_change_club_b_modules(client: AsyncClient):
    """Owner of Club A is refused with 403 when attempting to toggle Club B's modules."""
    async with AsyncSessionLocal() as db:
        owner_a, _, token_a, club_a = await create_test_org_with_owner(
            db, org_name="TEST_MOD_Club_A", role_code="RL02"
        )
        _, _, _, club_b = await create_test_org_with_owner(
            db, org_name="TEST_MOD_Club_B", role_code="RL02"
        )

    headers = {"Authorization": f"Bearer {token_a}"}

    res = await client.put(
        f"/api/v1/organizations/{club_b.id}/modules",
        json={"modules": {"M12": False}},
        headers=headers,
    )
    assert res.status_code == 403
    assert res.json()["code"] in ("FORBIDDEN", "FORBIDDEN_ORG_OWNER")


# ==============================================================================
# 5. Owner Cannot Enable What Staff Disabled
# ==============================================================================


@pytest.mark.asyncio
async def test_owner_cannot_enable_module_disabled_by_staff(client: AsyncClient):
    """An owner cannot re-enable a module that was explicitly locked/disabled by staff."""
    async with AsyncSessionLocal() as db:
        owner, _, owner_token, club = await create_test_org_with_owner(
            db, org_name="TEST_MOD_Staff_Locked", role_code="RL02"
        )

        stmt_plat = select(Organization).where(Organization.type == OrganizationType.PLATFORM.value)
        plat_org = (await db.execute(stmt_plat)).scalars().first()
        admin, _, admin_token = await create_test_actor(
            db, interface="staff_console", role_code="RL13", org_id=plat_org.id
        )

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    # Staff disables M12
    res_staff = await client.put(
        f"/api/v1/admin/organizations/{club.id}/modules",
        json={"modules": {"M12": False}},
        headers=admin_headers,
    )
    assert res_staff.status_code == 200

    # Owner attempts to re-enable M12 -> 403 Forbidden!
    res_owner = await client.put(
        f"/api/v1/organizations/{club.id}/modules",
        json={"modules": {"M12": True}},
        headers=owner_headers,
    )
    assert res_owner.status_code == 403
    assert res_owner.json()["code"] == "MODULE_LOCKED_BY_STAFF"


# ==============================================================================
# 6. Partner Category Gating & Approval
# ==============================================================================


@pytest.mark.asyncio
async def test_partner_category_gating_and_approval_flow(client: AsyncClient):
    """Pending partner sees only tracker (M29). Once category approved, category modules appear."""
    async with AsyncSessionLocal() as db:
        owner, _, owner_token, partner_org = await create_test_org_with_owner(
            db,
            org_name="TEST_MOD_Partner_Cafe",
            org_type=OrganizationType.BUSINESS.value,
            role_code="RL07",
            interface="partner_portal",
        )

        stmt_plat = select(Organization).where(Organization.type == OrganizationType.PLATFORM.value)
        plat_org = (await db.execute(stmt_plat)).scalars().first()
        admin, _, admin_token = await create_test_actor(
            db, interface="staff_console", role_code="RL13", org_id=plat_org.id
        )

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Step 1: Pending partner (no approved category in organization_categories) -> only M29
    res_pending = await client.get("/api/v1/me/menu", headers=owner_headers)
    assert res_pending.status_code == 200
    pending_codes = [m["code"] for m in res_pending.json()["modules"]]
    assert pending_codes == ["M29"]

    # Step 2: Staff approves 'cafe' category
    res_app = await client.post(
        f"/api/v1/admin/organizations/{partner_org.id}/categories/cafe/approve",
        headers=admin_headers,
    )
    assert res_app.status_code == 200
    assert res_app.json()["approval_state"] == "approved"

    # Step 3: Partner calls /me/menu -> sees base partner modules + cafe category module M13
    res_approved = await client.get("/api/v1/me/menu", headers=owner_headers)
    assert res_approved.status_code == 200
    approved_codes = [m["code"] for m in res_approved.json()["modules"]]
    assert "M13" in approved_codes
    assert "M01" in approved_codes
    assert "M29" in approved_codes


# ==============================================================================
# 7. Configuration Changes Increment permission_version & Auditing
# ==============================================================================


@pytest.mark.asyncio
async def test_configuration_change_applies_on_next_request_and_is_audited(client: AsyncClient):
    """Configuration updates bump permission_version and write before/after audit entries."""
    async with AsyncSessionLocal() as db:
        owner, owner_sess, owner_token, club = await create_test_org_with_owner(
            db, org_name="TEST_MOD_Audit_Club", role_code="RL02"
        )
        initial_version = owner_sess.permission_version

        stmt_plat = select(Organization).where(Organization.type == OrganizationType.PLATFORM.value)
        plat_org = (await db.execute(stmt_plat)).scalars().first()
        admin, _, admin_token = await create_test_actor(
            db, interface="staff_console", role_code="RL13", org_id=plat_org.id
        )

    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Request-ID": "test-req-audit-123"}

    # Staff changes configuration
    res = await client.put(
        f"/api/v1/admin/organizations/{club.id}/modules",
        json={"modules": {"M06": False}},
        headers=admin_headers,
    )
    assert res.status_code == 200

    # Verify session's permission_version was incremented
    async with AsyncSessionLocal() as db:
        db_session = await db.get(Session, owner_sess.id)
        assert db_session is not None
        assert db_session.permission_version == initial_version + 1

        # Verify audit event with before and after state
        stmt_audit = select(AuditEvent).where(
            AuditEvent.action == "organization_modules.staff_update",
            AuditEvent.target == f"organization:{club.id}",
        )
        audit_event = (await db.execute(stmt_audit)).scalars().first()
        assert audit_event is not None
        assert audit_event.audit_metadata["before"]["M06"] is True
        assert audit_event.audit_metadata["after"]["M06"] is False


# ==============================================================================
# 8. Database Rejects rider_app in interface_modules
# ==============================================================================


@pytest.mark.asyncio
async def test_database_rejects_rider_app_in_interface_modules():
    """Database check constraint strictly forbids rider_app in interface_modules."""
    async with AsyncSessionLocal() as db:
        stmt_m01 = select(Module).where(Module.code == "M01")
        m01 = (await db.execute(stmt_m01)).scalars().first()

        invalid_row = InterfaceModule(
            interface="rider_app",
            module_id=m01.id,
            display_order=10,
            default_enabled=True,
        )
        db.add(invalid_row)
        with pytest.raises(DBAPIError) as exc_info:
            await db.commit()
        await db.rollback()
        assert "ck_interface_modules_web_only" in str(exc_info.value)


# ==============================================================================
# 9. Route Scanner: All Web Interface Routes Declare Module Code
# ==============================================================================


def test_all_web_routes_declare_module_code():
    """Rule Scanner: Scans all registered routes and verifies that every web-interface

    endpoint explicitly declares its module code.
    """
    app = create_app()
    web_interfaces = {"organizer_portal", "partner_portal", "staff_console"}
    public_paths = {
        "/api/v1/auth/otp/request",
        "/api/v1/auth/otp/verify",
        "/api/v1/auth/token/refresh",
        "/health",
        "/api/v1/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    missing_module_code = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in public_paths or route.path.startswith("/api/v1/dev"):
            continue

        # Inspect route dependencies to see allowed interfaces
        route_interfaces = set()
        declared_module_code = None

        def inspect_dependant(dep):
            nonlocal declared_module_code
            if hasattr(dep.call, "__allowed_interfaces__"):
                route_interfaces.update(getattr(dep.call, "__allowed_interfaces__"))
            if hasattr(dep.call, "__module_code__"):
                declared_module_code = getattr(dep.call, "__module_code__")

            for sub_dep in dep.dependencies:
                inspect_dependant(sub_dep)

        inspect_dependant(route.dependant)

        # Check if route allows any web interface
        is_web_route = bool(route_interfaces & web_interfaces)
        # Note: routes like /me/workspaces allow ALL_INTERFACES including rider_app
        # Only routes that are web-exclusive or have web interface access require a module code
        if is_web_route and not (
            route_interfaces == {"rider_app"} or "rider_app" in route_interfaces
        ):
            if not declared_module_code:
                missing_module_code.append(f"{route.methods} {route.path}")

    assert not missing_module_code, (
        f"The following web-interface routes do not declare a module code: {missing_module_code}"
    )
