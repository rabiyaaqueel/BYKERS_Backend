"""Tests for Task C: Authorization, Roles, Organizations, Permissions, and Workspaces."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.permissions import RoleCode
from app.core.security import create_access_token, hash_token
from app.modules.auth.models import Device, Session, User, UserStatus
from app.modules.authz.models import (
    Application,
    ApplicationStatus,
    AuditEvent,
    ClubMembership,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationType,
    OrgApprovalState,
    Role,
    RoleInvitation,
)


@pytest.fixture(autouse=True)
async def authz_test_setup():
    """Sets ENV to dev for tests and cleans up test records."""
    original_env = settings.ENV
    settings.ENV = "dev"
    try:
        yield
    finally:
        settings.ENV = original_env
        async with AsyncSessionLocal() as db:
            # Clean up test organizations created with prefix 'TEST_'
            stmt = select(Organization.id).where(Organization.name.like("TEST_%"))
            res = await db.execute(stmt)
            org_ids = res.scalars().all()
            if org_ids:
                await db.execute(
                    delete(OrganizationMembership).where(
                        OrganizationMembership.organization_id.in_(org_ids)
                    )
                )
                await db.execute(
                    delete(RoleInvitation).where(RoleInvitation.organization_id.in_(org_ids))
                )
                await db.execute(delete(ClubMembership).where(ClubMembership.club_id.in_(org_ids)))
                await db.execute(delete(Organization).where(Organization.id.in_(org_ids)))

            # Clean up test applications
            stmt_app = select(Application.id).where(
                Application.payload["name"].astext.like("TEST_%")
            )
            res_app = await db.execute(stmt_app)
            app_ids = res_app.scalars().all()
            if app_ids:
                await db.execute(delete(Application).where(Application.id.in_(app_ids)))

            await db.commit()


async def create_test_user_session(
    db,
    phone: str | None = None,
    status: str = UserStatus.ACTIVE.value,
    active_context: dict | None = None,
    interface: str = "rider_app",
) -> tuple[User, Session, str]:
    """Helper to provision a test user, device, session, and JWT access token."""
    # Generate unique phone number so repeated test executions never collide on unique constraint
    unique_digits = f"{uuid.uuid4().int % 100000000:08d}"
    actual_phone = f"+9199{unique_digits}"

    user = User(
        phone_normalized=actual_phone,
        status=status,
        phone_verified_at=datetime.now(timezone.utc),
        locale="en-IN",
    )
    db.add(user)
    await db.flush()

    device = Device(
        user_id=user.id,
        platform="android",
        device_name="Test Phone",
    )
    db.add(device)
    await db.flush()

    session = Session(
        user_id=user.id,
        device_id=device.id,
        interface=interface,
        active_context=active_context
        or {"workspace_id": str(user.id), "workspace_type": "personal", "role_code": "RL01"},
        permission_version=1,
    )
    db.add(session)
    await db.flush()

    token = create_access_token(
        user_id=str(user.id),
        session_id=str(session.id),
        permission_version=session.permission_version,
        interface=session.interface,
    )
    await db.commit()
    return user, session, token


@pytest.mark.asyncio
async def test_default_deny_rider_cannot_access_admin_or_club_manage(client: AsyncClient):
    """A normal rider is default-denied when trying to call privileged actions."""
    async with AsyncSessionLocal() as db:
        user, session, token = await create_test_user_session(db, phone="+919999000010")

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Rider cannot view platform audit events (requires audit.read and staff_console interface)
    res_audit = await client.get("/api/v1/admin/audit-events", headers=headers)
    assert res_audit.status_code == 403
    assert res_audit.json()["code"] in ("FORBIDDEN", "FORBIDDEN_INTERFACE")

    # 2. Rider cannot decide on applications (requires application.review and staff_console)
    random_app_id = uuid.uuid4()
    res_dec = await client.post(
        f"/api/v1/applications/{random_app_id}/decision",
        json={"decision": "approved", "notes": "Hacked"},
        headers=headers,
    )
    assert res_dec.status_code == 403
    assert res_dec.json()["code"] in ("FORBIDDEN", "FORBIDDEN_INTERFACE")


@pytest.mark.asyncio
async def test_workspaces_listing_rider_vs_club_owner(client: AsyncClient):
    """Riders see only Personal workspace; Club Owners on portal see their Club workspace."""
    async with AsyncSessionLocal() as db:
        rider, _, rider_token = await create_test_user_session(
            db, phone="+919999000021", interface="rider_app"
        )
        owner, _, owner_token = await create_test_user_session(
            db, phone="+919999000022", interface="organizer_portal"
        )

        # Create approved test club
        club = Organization(
            type=OrganizationType.CLUB_ORG.value,
            name="TEST_Apex Predators Club",
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=owner.id,
        )
        db.add(club)
        await db.flush()

        role_owner = (
            await db.execute(select(Role).where(Role.code == RoleCode.RL02_CLUB_OWNER.value))
        ).scalar_one()
        db.add(
            OrganizationMembership(
                user_id=owner.id,
                organization_id=club.id,
                role_id=role_owner.id,
                status=MembershipStatus.ACTIVE.value,
                version=1,
            )
        )
        await db.commit()

    # 1. Rider workspaces on mobile app (only personal workspace)
    res_r = await client.get(
        "/api/v1/me/workspaces", headers={"Authorization": f"Bearer {rider_token}"}
    )
    assert res_r.status_code == 200
    r_ws = res_r.json()
    assert len(r_ws) == 1
    assert r_ws[0]["workspace_type"] == "personal"
    assert r_ws[0]["role_codes"] == ["RL01"]

    # 2. Club owner workspaces on organizer portal (only club workspace)
    res_o = await client.get(
        "/api/v1/me/workspaces", headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert res_o.status_code == 200
    o_ws = res_o.json()
    assert len(o_ws) >= 1
    types = {w["workspace_type"] for w in o_ws}
    assert "club" in types


@pytest.mark.asyncio
async def test_switch_active_workspace_updates_session_and_capabilities(client: AsyncClient):
    """Switching active workspace updates session active context and returns capabilities."""
    async with AsyncSessionLocal() as db:
        owner, session, owner_token = await create_test_user_session(
            db, phone="+919999000030", interface="organizer_portal"
        )

        club = Organization(
            type=OrganizationType.CLUB_ORG.value,
            name="TEST_Monsoon Riders Club",
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=owner.id,
        )
        db.add(club)
        await db.flush()

        role_owner = (
            await db.execute(select(Role).where(Role.code == RoleCode.RL02_CLUB_OWNER.value))
        ).scalar_one()
        db.add(
            OrganizationMembership(
                user_id=owner.id,
                organization_id=club.id,
                role_id=role_owner.id,
                status=MembershipStatus.ACTIVE.value,
                version=1,
            )
        )
        await db.commit()
        club_id = club.id

    headers = {"Authorization": f"Bearer {owner_token}"}

    # Switch to Club workspace
    switch_res = await client.post(
        "/api/v1/me/active-workspace",
        json={"workspace_id": str(club_id)},
        headers=headers,
    )
    assert switch_res.status_code == 200
    switch_data = switch_res.json()
    assert switch_data["workspace_type"] == "club_org"
    assert "club.manage" in switch_data["capabilities"]

    # Fetch capabilities to verify persistence
    cap_res = await client.get("/api/v1/me/capabilities", headers=headers)
    assert cap_res.status_code == 200
    assert "club.manage" in cap_res.json()["actions"]


@pytest.mark.asyncio
async def test_switch_workspace_to_unauthorized_org_denied(client: AsyncClient):
    """A user cannot switch to a workspace for an organization they don't belong to."""
    async with AsyncSessionLocal() as db:
        portal_user, _, portal_token = await create_test_user_session(
            db, phone="+919999000040", interface="organizer_portal"
        )
        other_user, _, _ = await create_test_user_session(db, phone="+919999000041")

        club = Organization(
            type=OrganizationType.CLUB_ORG.value,
            name="TEST_Private Brotherhood Club",
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=other_user.id,
        )
        db.add(club)
        await db.commit()
        club_id = club.id

    res = await client.post(
        "/api/v1/me/active-workspace",
        json={"workspace_id": str(club_id)},
        headers={"Authorization": f"Bearer {portal_token}"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "WORKSPACE_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_maker_checker_applicant_cannot_approve_own_application(client: AsyncClient):
    """Maker-Checker Rule: An applicant with admin rights cannot approve their own application."""
    async with AsyncSessionLocal() as db:
        # Create a user who is BOTH an applicant AND promoted to platform admin on staff_console
        user, _, token = await create_test_user_session(
            db, phone="+919999000050", interface="staff_console"
        )

        # Promote user to platform admin
        plat_org = (
            await db.execute(
                select(Organization).where(Organization.type == OrganizationType.PLATFORM.value)
            )
        ).scalar_one_or_none()
        if not plat_org:
            plat_org = Organization(
                type=OrganizationType.PLATFORM.value,
                name="TEST_Platform Org",
                approval_state=OrgApprovalState.APPROVED.value,
                created_by=user.id,
            )
            db.add(plat_org)
            await db.flush()

        role_admin = (
            await db.execute(select(Role).where(Role.code == RoleCode.RL13_PLATFORM_ADMIN.value))
        ).scalar_one()
        db.add(
            OrganizationMembership(
                user_id=user.id,
                organization_id=plat_org.id,
                role_id=role_admin.id,
                status=MembershipStatus.ACTIVE.value,
                version=1,
            )
        )

        # User submits an application
        app = Application(
            applicant_id=user.id,
            kind="club",
            status=ApplicationStatus.SUBMITTED.value,
            payload={"name": "TEST_Conflict of Interest Club"},
        )
        db.add(app)
        await db.commit()
        app_id = app.id

    # The user tries to approve their own application
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        f"/api/v1/applications/{app_id}/decision",
        json={"decision": "approved", "notes": "Self-approval attempt"},
        headers=headers,
    )
    assert res.status_code == 403
    data = res.json()
    assert data["code"] == "MAKER_CHECKER_VIOLATION"


@pytest.mark.asyncio
async def test_application_approval_creates_organization_and_owner_membership(client: AsyncClient):
    """Approving an application by a reviewer creates the organization and owner role."""
    async with AsyncSessionLocal() as db:
        applicant, _, applicant_token = await create_test_user_session(
            db, phone="+919999000060", interface="organizer_portal"
        )
        admin, _, admin_token = await create_test_user_session(
            db, phone="+919999000061", interface="staff_console"
        )

        # Assign admin RL13
        plat_org = (
            await db.execute(
                select(Organization).where(Organization.type == OrganizationType.PLATFORM.value)
            )
        ).scalar_one_or_none()
        if not plat_org:
            plat_org = Organization(
                type=OrganizationType.PLATFORM.value,
                name="TEST_Platform Org",
                approval_state=OrgApprovalState.APPROVED.value,
                created_by=admin.id,
            )
            db.add(plat_org)
            await db.flush()

        role_admin = (
            await db.execute(select(Role).where(Role.code == RoleCode.RL13_PLATFORM_ADMIN.value))
        ).scalar_one()
        db.add(
            OrganizationMembership(
                user_id=admin.id,
                organization_id=plat_org.id,
                role_id=role_admin.id,
                status=MembershipStatus.ACTIVE.value,
                version=1,
            )
        )
        await db.commit()

    # 1. Applicant submits application
    res_submit = await client.post(
        "/api/v1/applications",
        json={"kind": "club", "name": "TEST_Coastal Riders Club", "city": "Visakhapatnam"},
        headers={"Authorization": f"Bearer {applicant_token}"},
    )
    assert res_submit.status_code == 201
    app_id = res_submit.json()["id"]

    # 2. Admin reviews and approves
    res_dec = await client.post(
        f"/api/v1/applications/{app_id}/decision",
        json={"decision": "approved", "notes": "Verified community"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_dec.status_code == 200
    dec_data = res_dec.json()
    assert dec_data["status"] == "approved"
    assert dec_data["organization_id"] is not None

    # 3. Applicant now sees the new club workspace!
    res_ws = await client.get(
        "/api/v1/me/workspaces", headers={"Authorization": f"Bearer {applicant_token}"}
    )
    assert res_ws.status_code == 200
    workspaces = res_ws.json()
    assert len(workspaces) >= 1
    club_ws = next(w for w in workspaces if w["workspace_type"] == "club")
    assert club_ws["organization_name"] == "TEST_Coastal Riders Club"
    assert "RL02" in club_ws["role_codes"]


@pytest.mark.asyncio
async def test_role_invitation_lifecycle_and_acceptance(client: AsyncClient):
    """Invitations can be created by authorized leaders and accepted by recipients."""
    async with AsyncSessionLocal() as db:
        owner, _, owner_token = await create_test_user_session(
            db, phone="+919999000070", interface="organizer_portal"
        )
        invitee, _, invitee_token = await create_test_user_session(
            db, phone="+919999000071", interface="organizer_portal"
        )

        club = Organization(
            type=OrganizationType.CLUB_ORG.value,
            name="TEST_Deccan Throttle Club",
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=owner.id,
        )
        db.add(club)
        await db.flush()

        role_owner = (
            await db.execute(select(Role).where(Role.code == RoleCode.RL02_CLUB_OWNER.value))
        ).scalar_one()
        db.add(
            OrganizationMembership(
                user_id=owner.id,
                organization_id=club.id,
                role_id=role_owner.id,
                status=MembershipStatus.ACTIVE.value,
                version=1,
            )
        )
        # Activate club workspace for owner session
        stmt_s = select(Session).where(Session.user_id == owner.id)
        s = (await db.execute(stmt_s)).scalar_one()
        s.active_context = {
            "workspace_id": str(club.id),
            "workspace_type": "club_org",
            "organization_id": str(club.id),
            "role_code": "RL02",
        }

        await db.commit()
        club_id = club.id

    # 1. Owner creates invitation for moderator role (RL03)
    res_inv = await client.post(
        f"/api/v1/organizations/{club_id}/invitations",
        json={"role_code": "RL03", "recipient_contact": "+919999000071"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_inv.status_code == 201
    inv_data = res_inv.json()
    token = inv_data["invitation_token"]
    assert token is not None

    # 2. Invitee accepts invitation
    res_acc = await client.post(
        f"/api/v1/invitations/{token}/accept",
        headers={"Authorization": f"Bearer {invitee_token}"},
    )
    assert res_acc.status_code == 200
    assert "Successfully joined" in res_acc.json()["message"]

    # 3. Invitee now has club workspace
    res_ws = await client.get(
        "/api/v1/me/workspaces", headers={"Authorization": f"Bearer {invitee_token}"}
    )
    assert res_ws.status_code == 200
    assert any(w["workspace_type"] == "club" for w in res_ws.json())


@pytest.mark.asyncio
async def test_expired_or_tampered_invitation_denied(client: AsyncClient):
    """Expired or invalid invitation tokens are rejected."""
    async with AsyncSessionLocal() as db:
        user, _, user_token = await create_test_user_session(db, phone="+919999000080")

        club = Organization(
            type=OrganizationType.CLUB_ORG.value,
            name="TEST_Expired Club",
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=user.id,
        )
        db.add(club)
        await db.flush()

        role = (await db.execute(select(Role).where(Role.code == "RL03"))).scalar_one()

        expired_token = "expired_dummy_token_12345"
        inv = RoleInvitation(
            inviter_id=user.id,
            organization_id=club.id,
            role_id=role.id,
            token_hash=hash_token(expired_token),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Expired 1 hour ago
        )
        db.add(inv)
        await db.commit()

    # 1. Calling with invalid token -> 404
    res_invalid = await client.post(
        "/api/v1/invitations/completely_bogus_token/accept",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert res_invalid.status_code == 404

    # 2. Calling with expired token -> 422
    res_exp = await client.post(
        f"/api/v1/invitations/{expired_token}/accept",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert res_exp.status_code == 422
    assert res_exp.json()["code"] == "INVITATION_EXPIRED"


@pytest.mark.asyncio
async def test_immediate_revocation_blocks_next_request(client: AsyncClient):
    """When a membership is revoked, the user's very next request is immediately blocked."""
    async with AsyncSessionLocal() as db:
        admin, _, admin_token = await create_test_user_session(
            db, phone="+919999000090", interface="organizer_portal"
        )
        member, _, member_token = await create_test_user_session(
            db, phone="+919999000091", interface="organizer_portal"
        )

        club = Organization(
            type=OrganizationType.CLUB_ORG.value,
            name="TEST_Expulsion Club",
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=admin.id,
        )
        db.add(club)
        await db.flush()

        role_owner = (
            await db.execute(select(Role).where(Role.code == RoleCode.RL02_CLUB_OWNER.value))
        ).scalar_one()
        role_mod = (
            await db.execute(select(Role).where(Role.code == RoleCode.RL03_CLUB_MODERATOR.value))
        ).scalar_one()

        db.add(
            OrganizationMembership(
                user_id=admin.id,
                organization_id=club.id,
                role_id=role_owner.id,
                status="active",
                version=1,
            )
        )
        mem = OrganizationMembership(
            user_id=member.id,
            organization_id=club.id,
            role_id=role_mod.id,
            status="active",
            version=1,
        )
        db.add(mem)

        # Set admin active context to club
        stmt_sa = select(Session).where(Session.user_id == admin.id)
        sa = (await db.execute(stmt_sa)).scalar_one()
        sa.active_context = {
            "workspace_id": str(club.id),
            "workspace_type": "club_org",
            "organization_id": str(club.id),
            "role_code": "RL02",
        }

        # Set member active context to club
        stmt_sm = select(Session).where(Session.user_id == member.id)
        sm = (await db.execute(stmt_sm)).scalar_one()
        sm.active_context = {
            "workspace_id": str(club.id),
            "workspace_type": "club_org",
            "organization_id": str(club.id),
            "role_code": "RL03",
        }

        await db.commit()
        club_id = club.id
        member_id = member.id

    # Member can initially perform club action (e.g. check capabilities)
    res_cap1 = await client.get(
        "/api/v1/me/capabilities", headers={"Authorization": f"Bearer {member_token}"}
    )
    assert res_cap1.status_code == 200

    # Admin revokes member
    res_rev = await client.delete(
        f"/api/v1/organizations/{club_id}/members/{member_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_rev.status_code == 200
    assert res_rev.json()["status"] == "revoked"

    # Member's VERY NEXT request in that workspace is blocked!
    # Even though their JWT token has not expired
    res_inv = await client.post(
        f"/api/v1/organizations/{club_id}/invitations",
        json={"role_code": "RL04", "recipient_contact": "+919999000099"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert res_inv.status_code == 403
    assert res_inv.json()["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_audit_events_immutable_trigger_forbids_update_and_delete():
    """PostgreSQL database trigger enforces that audit_events table is strictly append-only."""
    async with AsyncSessionLocal() as db:
        # Insert test audit event
        ev_id = uuid.uuid4()
        event = AuditEvent(
            id=ev_id,
            actor_id="test_system",
            active_context={"workspace": "test"},
            target="test_target",
            action="test.immutable_check",
            outcome="success",
            reason="Trigger validation",
            request_id="req_immutable_1",
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(event)
        await db.commit()

        # 1. Attempt UPDATE -> must raise database trigger exception
        with pytest.raises(DBAPIError) as exc_update:
            await db.execute(
                text("UPDATE audit_events SET reason = 'tampered' WHERE id = :id"),
                {"id": ev_id},
            )
            await db.commit()
        assert "audit_events is an append-only log" in str(exc_update.value)
        await db.rollback()

        # 2. Attempt DELETE -> must raise database trigger exception
        with pytest.raises(DBAPIError) as exc_delete:
            await db.execute(
                text("DELETE FROM audit_events WHERE id = :id"),
                {"id": ev_id},
            )
            await db.commit()
        assert "audit_events is an append-only log" in str(exc_delete.value)
        await db.rollback()


@pytest.mark.asyncio
async def test_capabilities_contains_no_secrets(client: AsyncClient):
    """The /me/capabilities response exposes only UI module and action codes."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_user_session(db, phone="+919999000100")

    res = await client.get("/api/v1/me/capabilities", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()

    # Verify structure
    assert "workspace_type" in data
    assert "role_codes" in data
    assert "enabled_module_ids" in data
    assert "actions" in data

    # Verify no secret keywords leaked
    raw_text = res.text.lower()
    for forbidden in ["password", "secret", "token_hash", "private_key", "secret_key"]:
        assert forbidden not in raw_text


@pytest.mark.asyncio
async def test_dev_make_admin_promotes_user(client: AsyncClient):
    """Dev helper promotes a test user to Platform Admin in dev environment."""
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_user_session(
            db, phone="+919999000110", interface="staff_console"
        )

    headers = {"Authorization": f"Bearer {token}"}

    res = await client.post(
        "/api/v1/dev/make-admin",
        json={"role_code": "RL13"},
        headers=headers,
    )
    assert res.status_code == 200
    assert "promoted to" in res.json()["message"]

    # User can now read audit events on staff console
    res_audit = await client.get("/api/v1/admin/audit-events", headers=headers)
    assert res_audit.status_code == 200
    assert isinstance(res_audit.json(), list)


@pytest.mark.asyncio
async def test_interface_guard_rider_cannot_access_staff_endpoint(client: AsyncClient):
    """Interface Rule: A rider_app token must get 403 on staff_console endpoints."""
    async with AsyncSessionLocal() as db:
        rider, _, rider_token = await create_test_user_session(
            db, phone="+919999000120", interface="rider_app"
        )

    headers = {"Authorization": f"Bearer {rider_token}"}

    # Rider attempts to access staff console audit events
    res = await client.get("/api/v1/admin/audit-events", headers=headers)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_INTERFACE"


@pytest.mark.asyncio
async def test_interface_guard_switching_workspace_of_wrong_interface_refused(client: AsyncClient):
    """Interface Rule: Switching to a workspace of another interface is refused with 403."""
    async with AsyncSessionLocal() as db:
        rider, _, rider_token = await create_test_user_session(
            db, phone="+919999000130", interface="rider_app"
        )

        club = Organization(
            type=OrganizationType.CLUB_ORG.value,
            name="TEST_Rider Attempted Club",
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=rider.id,
        )
        db.add(club)
        await db.commit()
        club_id = club.id

    # Rider app session attempts to switch to club organization workspace
    res = await client.post(
        "/api/v1/me/active-workspace",
        json={"workspace_id": str(club_id)},
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "WORKSPACE_INTERFACE_MISMATCH"


@pytest.mark.asyncio
async def test_all_non_public_routes_declare_require_interface():
    """Route Scanning Rule: Every non-public endpoint MUST declare require_interface."""
    from fastapi.routing import APIRoute

    from app.main import app

    public_paths = {
        "/health",
        "/api/v1/health",
        "/api/v1/auth/otp/request",
        "/api/v1/auth/otp/verify",
        "/api/v1/auth/token/refresh",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    unprotected_routes = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in public_paths:
            continue

        # Inspect route dependencies for __allowed_interfaces__
        has_interface_guard = False
        all_deps = list(route.dependant.dependencies)
        for dep in all_deps:
            if hasattr(dep.call, "__allowed_interfaces__"):
                has_interface_guard = True
                break
            # Check sub-dependencies
            for sub_dep in dep.dependencies:
                if hasattr(sub_dep.call, "__allowed_interfaces__"):
                    has_interface_guard = True
                    break

        if not has_interface_guard:
            unprotected_routes.append(f"{route.methods} {route.path}")

    assert not unprotected_routes, (
        f"The following routes are missing require_interface: {unprotected_routes}"
    )


@pytest.mark.asyncio
async def test_get_me_unauthenticated_and_authenticated(client: AsyncClient):
    """GET /me requires authentication and returns account summary."""
    # 1. Unauthenticated call -> 401
    res_unauth = await client.get("/api/v1/me")
    assert res_unauth.status_code == 401
    assert res_unauth.json()["code"] == "UNAUTHORIZED"

    # 2. Authenticated call -> 200
    async with AsyncSessionLocal() as db:
        user, _, token = await create_test_user_session(db, phone="+919999000140")

    res_auth = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert res_auth.status_code == 200
    data = res_auth.json()
    assert data["id"] == str(user.id)
    assert data["status"] == "active"
    assert "onboarding_required" in data
    assert data["locale"] == "en-IN"
