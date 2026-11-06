"""Authorization, Workspaces, Applications, Invitations, and Audit Service."""

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.core.config import settings
from app.core.dependencies import AuthenticatedUser
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.permissions import RoleCode, assert_maker_checker
from app.core.security import hash_token
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
    Permission,
    Role,
    RoleInvitation,
    RolePermission,
)
from app.modules.authz.schemas import (
    ActiveWorkspaceIn,
    ActiveWorkspaceOut,
    ApplicationCreateIn,
    ApplicationDecisionIn,
    ApplicationDecisionOut,
    ApplicationOut,
    AuditEventOut,
    CapabilitiesOut,
    DevMakeAdminIn,
    DevMakeAdminOut,
    InvitationAcceptOut,
    MemberOut,
    MemberUpdateIn,
    RoleInvitationCreateIn,
    RoleInvitationOut,
    WorkspaceOut,
)

logger = logging.getLogger("bykers.authz")

PERSONAL_MODULES = [
    "M01_auth",
    "M02_profile",
    "M03_garage",
    "M04_nearby",
    "M05_connections",
    "M06_clubs",
    "M09_rides",
]

CLUB_MODULES = [
    "M01_auth",
    "M02_profile",
    "M06_clubs",
    "M09_rides",
    "M10_checkin",
    "M13_announcements",
]

PLATFORM_MODULES = [
    "M01_auth",
    "M11_trust_moderation",
    "M12_finance",
    "M33_admin_audit",
    "M34_governance",
]


async def list_workspaces(db: AsyncSession, user: AuthenticatedUser) -> List[WorkspaceOut]:
    """Lists all approved workspaces accessible to the authenticated user."""
    active_ctx = user.session.active_context or {}
    active_ws_id = active_ctx.get("workspace_id")

    workspaces: List[WorkspaceOut] = []

    # 1. Personal Workspace (Always available for every registered rider)
    is_personal_active = (
        not active_ws_id
        or str(active_ws_id) == str(user.user_id)
        or active_ctx.get("workspace_type") == "personal"
    )
    workspaces.append(
        WorkspaceOut(
            user_id=user.user_id,
            account_status=user.user.status,
            workspace_id=user.user_id,
            workspace_type="personal",
            organization_id=None,
            organization_name="Personal Garage & Profile",
            role_codes=[RoleCode.RL01_RIDER.value],
            permission_version=user.user.version,
            authentication_assurance="otp_verified",
            enabled_module_ids=PERSONAL_MODULES,
            is_active=is_personal_active,
        )
    )

    # 2. Approved Organization / Club Workspaces
    stmt = (
        select(OrganizationMembership, Organization, Role)
        .join(Organization, OrganizationMembership.organization_id == Organization.id)
        .join(Role, OrganizationMembership.role_id == Role.id)
        .where(
            OrganizationMembership.user_id == user.user_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
            Organization.approval_state == OrgApprovalState.APPROVED.value,
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Group by organization ID
    org_map: Dict[uuid.UUID, Dict[str, Any]] = {}
    for mem, org, role in rows:
        if org.id not in org_map:
            org_map[org.id] = {
                "org": org,
                "role_codes": [],
                "version": mem.version,
            }
        org_map[org.id]["role_codes"].append(role.code)
        org_map[org.id]["version"] = max(org_map[org.id]["version"], mem.version)

    for org_id, info in org_map.items():
        org = info["org"]
        r_codes = info["role_codes"]
        ws_type = (
            "club"
            if org.type == OrganizationType.CLUB_ORG.value
            else ("staff" if org.type == OrganizationType.PLATFORM.value else "business")
        )
        mod_ids = PLATFORM_MODULES if ws_type == "staff" else CLUB_MODULES

        is_org_active = str(active_ws_id) == str(org_id)
        workspaces.append(
            WorkspaceOut(
                user_id=user.user_id,
                account_status=user.user.status,
                workspace_id=org.id,
                workspace_type=ws_type,
                organization_id=org.id,
                organization_name=org.name,
                role_codes=r_codes,
                permission_version=info["version"],
                authentication_assurance="otp_verified",
                enabled_module_ids=mod_ids,
                is_active=is_org_active,
            )
        )

    return workspaces


async def switch_active_workspace(
    db: AsyncSession,
    user: AuthenticatedUser,
    payload: ActiveWorkspaceIn,
) -> ActiveWorkspaceOut:
    """Validates target workspace membership and activates it on the current session."""
    target_id = payload.workspace_id

    # 1. Switching to Personal Workspace
    if target_id == user.user_id:
        new_personal_ctx: Dict[str, Any] = {
            "workspace_id": str(user.user_id),
            "workspace_type": "personal",
            "organization_id": None,
            "role_code": RoleCode.RL01_RIDER.value,
        }
        user.session.active_context = new_personal_ctx
        await db.commit()

        caps = await get_capabilities(db, user)
        return ActiveWorkspaceOut(
            workspace_id=user.user_id,
            workspace_type="personal",
            organization_id=None,
            role_codes=[RoleCode.RL01_RIDER.value],
            capabilities=caps.actions,
            message="Switched to Personal Workspace",
        )

    # 2. Switching to Organization / Club Workspace
    stmt = (
        select(OrganizationMembership, Organization, Role)
        .join(Organization, OrganizationMembership.organization_id == Organization.id)
        .join(Role, OrganizationMembership.role_id == Role.id)
        .where(
            OrganizationMembership.user_id == user.user_id,
            OrganizationMembership.organization_id == target_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
            Organization.approval_state == OrgApprovalState.APPROVED.value,
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        raise ForbiddenError(
            "Access denied: You do not have an active approved membership in this workspace",
            code="WORKSPACE_ACCESS_DENIED",
        )

    primary_mem, org, primary_role = rows[0]
    all_role_codes = [r.code for _, _, r in rows]

    new_ctx: Dict[str, Any] = {
        "workspace_id": str(org.id),
        "workspace_type": org.type,
        "organization_id": str(org.id),
        "role_code": primary_role.code,
        "role_codes": all_role_codes,
    }
    user.session.active_context = new_ctx
    await db.commit()

    caps = await get_capabilities(db, user)
    return ActiveWorkspaceOut(
        workspace_id=org.id,
        workspace_type=org.type,
        organization_id=org.id,
        role_codes=all_role_codes,
        capabilities=caps.actions,
        message=f"Switched to workspace: {org.name}",
    )


async def get_capabilities(db: AsyncSession, user: AuthenticatedUser) -> CapabilitiesOut:
    """Returns the effective modules and permitted action codes for the user's current context."""
    active_ctx = user.session.active_context or {}
    ws_type = active_ctx.get("workspace_type", "personal")
    org_id = active_ctx.get("organization_id")
    role_codes = active_ctx.get("role_codes") or [
        active_ctx.get("role_code", RoleCode.RL01_RIDER.value)
    ]

    # Query DB for granted permissions for these role codes
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, RolePermission.role_id == Role.id)
        .where(Role.code.in_(role_codes))
        .distinct()
    )
    res = await db.execute(stmt)
    action_codes = sorted(res.scalars().all())

    modules = (
        PLATFORM_MODULES
        if ws_type == "staff"
        else (CLUB_MODULES if ws_type in ("club", "club_org") else PERSONAL_MODULES)
    )

    org_uuid = None
    if org_id:
        try:
            org_uuid = uuid.UUID(str(org_id))
        except (ValueError, TypeError):
            pass

    return CapabilitiesOut(
        workspace_type=ws_type,
        organization_id=org_uuid,
        role_codes=role_codes,
        enabled_module_ids=modules,
        actions=action_codes,
    )


async def create_application(
    db: AsyncSession,
    user: AuthenticatedUser,
    payload: ApplicationCreateIn,
    request_id: str = "",
) -> ApplicationOut:
    """Submits an application for club, organizer, or partner status."""
    app = Application(
        applicant_id=user.user_id,
        kind=payload.kind,
        status=ApplicationStatus.SUBMITTED.value,
        payload={
            "name": payload.name,
            "city": payload.city,
            **payload.details,
        },
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    record_audit_event(
        actor=str(user.user_id),
        action="application.create",
        resource="applications",
        outcome="success",
        reason=f"Submitted application for {payload.kind}: {payload.name}",
        request_id=request_id,
    )
    return ApplicationOut.model_validate(app)


async def list_my_applications(
    db: AsyncSession,
    user: AuthenticatedUser,
) -> List[ApplicationOut]:
    """Lists applications submitted by the caller."""
    stmt = (
        select(Application)
        .where(Application.applicant_id == user.user_id)
        .order_by(desc(Application.created_at))
    )
    result = await db.execute(stmt)
    apps = result.scalars().all()
    return [ApplicationOut.model_validate(a) for a in apps]


async def decide_application(
    db: AsyncSession,
    reviewer: AuthenticatedUser,
    app_id: uuid.UUID,
    decision_in: ApplicationDecisionIn,
    request_id: str = "",
) -> ApplicationDecisionOut:
    """Reviews an application with Maker-Checker protection and provisions the entity."""
    stmt = select(Application).where(Application.id == app_id)
    res = await db.execute(stmt)
    app = res.scalar_one_or_none()

    if not app:
        raise NotFoundError("Application not found", code="APPLICATION_NOT_FOUND")

    # Maker-Checker Rule: Requester cannot approve their own application
    assert_maker_checker(app.applicant_id, reviewer.user_id)

    org_id = None
    mem_id = None

    if decision_in.decision == "approved":
        org_type = (
            OrganizationType.CLUB_ORG.value
            if app.kind == "club"
            else (
                OrganizationType.BUSINESS.value
                if app.kind == "partner"
                else OrganizationType.EVENT_ORG.value
            )
        )
        org_name = app.payload.get("name", f"Approved {app.kind.title()}")

        # 1. Create Organization
        org = Organization(
            type=org_type,
            name=org_name,
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=app.applicant_id,
        )
        db.add(org)
        await db.flush()
        org_id = org.id

        # 2. Determine and assign leadership role
        target_role_code = (
            RoleCode.RL02_CLUB_OWNER.value
            if app.kind == "club"
            else (
                RoleCode.RL07_PARTNER_OWNER.value
                if app.kind == "partner"
                else RoleCode.RL05_EVENT_ORGANIZER.value
            )
        )
        stmt_role = select(Role).where(Role.code == target_role_code)
        res_role = await db.execute(stmt_role)
        role = res_role.scalar_one_or_none()

        if not role:
            # Fallback to Rider if not found
            stmt_fallback = select(Role).where(Role.code == RoleCode.RL01_RIDER.value)
            role = (await db.execute(stmt_fallback)).scalar_one()

        # 3. Create active organization membership
        mem = OrganizationMembership(
            user_id=app.applicant_id,
            organization_id=org.id,
            role_id=role.id,
            status=MembershipStatus.ACTIVE.value,
            version=1,
        )
        db.add(mem)
        await db.flush()
        mem_id = mem.id

        # 4. If club, also create ClubMembership
        if app.kind == "club":
            club_mem = ClubMembership(
                club_id=org.id,
                user_id=app.applicant_id,
                role="owner",
                status=MembershipStatus.ACTIVE.value,
                version=1,
            )
            db.add(club_mem)

        app.status = ApplicationStatus.APPROVED.value
        app.reviewer_id = reviewer.user_id
        app.reviewer_notes = decision_in.notes
        message = (
            f"Application approved. Created organization '{org_name}' "
            f"and assigned role {target_role_code}."
        )
    else:
        app.status = decision_in.decision
        app.reviewer_id = reviewer.user_id
        app.reviewer_notes = decision_in.notes
        message = f"Application {decision_in.decision}."

    await db.commit()

    record_audit_event(
        actor=str(reviewer.user_id),
        action="application.decision",
        resource=f"application:{app.id}",
        outcome=decision_in.decision,
        reason=decision_in.notes or "Application reviewed",
        request_id=request_id,
    )

    return ApplicationDecisionOut(
        application_id=app.id,
        status=app.status,
        organization_id=org_id,
        membership_id=mem_id,
        message=message,
    )


async def create_invitation(
    db: AsyncSession,
    user: AuthenticatedUser,
    org_id: uuid.UUID,
    payload: RoleInvitationCreateIn,
    request_id: str = "",
) -> RoleInvitationOut:
    """Issues a time-limited invitation token to join an organization with a specific role."""
    # Find role
    stmt_role = select(Role).where(Role.code == payload.role_code)
    role = (await db.execute(stmt_role)).scalar_one_or_none()
    if not role:
        raise NotFoundError(f"Role code {payload.role_code} not found", code="ROLE_NOT_FOUND")

    # Generate token
    raw_token = secrets.token_urlsafe(32)
    tok_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)

    inv = RoleInvitation(
        inviter_id=user.user_id,
        recipient_user_id=payload.recipient_user_id,
        recipient_contact=payload.recipient_contact,
        organization_id=org_id,
        role_id=role.id,
        token_hash=tok_hash,
        expires_at=expires_at,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)

    contact_str = payload.recipient_contact or str(payload.recipient_user_id)
    record_audit_event(
        actor=str(user.user_id),
        action="invitation.create",
        resource=f"organization:{org_id}",
        outcome="success",
        reason=f"Invited {contact_str} as {payload.role_code}",
        request_id=request_id,
    )

    return RoleInvitationOut(
        id=inv.id,
        organization_id=inv.organization_id,
        role_code=role.code,
        recipient_contact=inv.recipient_contact,
        expires_at=inv.expires_at,
        invitation_token=raw_token,
    )


async def accept_invitation(
    db: AsyncSession,
    user: AuthenticatedUser,
    token: str,
    request_id: str = "",
) -> InvitationAcceptOut:
    """Accepts an invitation, verifies expiry, and provisions the organization membership."""
    tok_hash = hash_token(token)
    now = datetime.now(timezone.utc)

    stmt = (
        select(RoleInvitation, Organization, Role)
        .join(Organization, RoleInvitation.organization_id == Organization.id)
        .join(Role, RoleInvitation.role_id == Role.id)
        .where(RoleInvitation.token_hash == tok_hash)
    )
    res = await db.execute(stmt)
    row = res.first()

    if not row:
        raise NotFoundError("Invalid invitation token", code="INVITATION_NOT_FOUND")

    inv, org, role = row

    if inv.accepted_at is not None:
        raise ConflictError(
            "This invitation has already been accepted", code="INVITATION_ALREADY_USED"
        )

    if inv.expires_at < now:
        raise ValidationError("Invitation has expired", code="INVITATION_EXPIRED")

    # If scoped to a specific user, enforce recipient identity
    if inv.recipient_user_id and inv.recipient_user_id != user.user_id:
        raise ForbiddenError(
            "This invitation was addressed to a different user account",
            code="INVITATION_RECIPIENT_MISMATCH",
        )

    # Check if membership already exists
    stmt_mem = select(OrganizationMembership).where(
        OrganizationMembership.user_id == user.user_id,
        OrganizationMembership.organization_id == org.id,
        OrganizationMembership.role_id == role.id,
    )
    existing_mem = (await db.execute(stmt_mem)).scalar_one_or_none()

    if existing_mem:
        existing_mem.status = MembershipStatus.ACTIVE.value
        existing_mem.version += 1
        mem_id = existing_mem.id
    else:
        new_mem = OrganizationMembership(
            user_id=user.user_id,
            organization_id=org.id,
            role_id=role.id,
            status=MembershipStatus.ACTIVE.value,
            version=1,
        )
        db.add(new_mem)
        await db.flush()
        mem_id = new_mem.id

    inv.accepted_at = now
    await db.commit()

    record_audit_event(
        actor=str(user.user_id),
        action="invitation.accept",
        resource=f"organization:{org.id}",
        outcome="success",
        reason=f"Accepted role {role.code} in {org.name}",
        request_id=request_id,
    )

    return InvitationAcceptOut(
        organization_id=org.id,
        organization_name=org.name,
        role_code=role.code,
        membership_id=mem_id,
        message=f"Successfully joined {org.name} as {role.name}",
    )


async def update_member_status(
    db: AsyncSession,
    admin: AuthenticatedUser,
    org_id: uuid.UUID,
    target_user_id: uuid.UUID,
    payload: MemberUpdateIn,
    request_id: str = "",
) -> MemberOut:
    """Updates member status (suspend, activate, revoke) with optimistic lock version check."""
    stmt = (
        select(OrganizationMembership, Role)
        .join(Role, OrganizationMembership.role_id == Role.id)
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == target_user_id,
        )
    )
    res = await db.execute(stmt)
    row = res.first()

    if not row:
        raise NotFoundError("Member not found in this organization", code="MEMBER_NOT_FOUND")

    mem, role = row

    if mem.version != payload.version:
        raise ConflictError(
            f"Version conflict: current is {mem.version}, requested {payload.version}",
            code="VERSION_CONFLICT",
        )

    mem.status = payload.status
    mem.version += 1
    await db.commit()
    await db.refresh(mem)

    record_audit_event(
        actor=str(admin.user_id),
        action="member.update_status",
        resource=f"organization:{org_id}:user:{target_user_id}",
        outcome="success",
        reason=f"Updated member status to {payload.status} (version {mem.version})",
        request_id=request_id,
    )

    return MemberOut(
        id=mem.id,
        user_id=mem.user_id,
        organization_id=mem.organization_id,
        role_code=role.code,
        status=mem.status,
        version=mem.version,
    )


async def revoke_member(
    db: AsyncSession,
    admin: AuthenticatedUser,
    org_id: uuid.UUID,
    target_user_id: uuid.UUID,
    request_id: str = "",
) -> MemberOut:
    """Revokes a member immediately. Enforces that their very next request will be blocked."""
    stmt = (
        select(OrganizationMembership, Role)
        .join(Role, OrganizationMembership.role_id == Role.id)
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == target_user_id,
        )
    )
    res = await db.execute(stmt)
    row = res.first()

    if not row:
        raise NotFoundError("Member not found in this organization", code="MEMBER_NOT_FOUND")

    mem, role = row
    mem.status = MembershipStatus.REVOKED.value
    mem.version += 1
    await db.commit()
    await db.refresh(mem)

    record_audit_event(
        actor=str(admin.user_id),
        action="member.revoke",
        resource=f"organization:{org_id}:user:{target_user_id}",
        outcome="success",
        reason=f"Revoked role {role.code} for user {target_user_id}",
        request_id=request_id,
    )

    return MemberOut(
        id=mem.id,
        user_id=mem.user_id,
        organization_id=mem.organization_id,
        role_code=role.code,
        status=mem.status,
        version=mem.version,
    )


async def list_audit_events(
    db: AsyncSession,
    limit: int = 50,
) -> List[AuditEventOut]:
    """Retrieves immutable security and compliance audit log entries."""
    stmt = select(AuditEvent).order_by(desc(AuditEvent.occurred_at)).limit(min(limit, 100))
    res = await db.execute(stmt)
    events = res.scalars().all()
    return [AuditEventOut.model_validate(e) for e in events]


async def dev_make_admin(
    db: AsyncSession,
    caller: AuthenticatedUser,
    payload: DevMakeAdminIn,
    request_id: str = "",
) -> DevMakeAdminOut:
    """Dev-only helper (ENV=dev) to promote a user to Platform Administrator."""
    if settings.ENV != "dev":
        raise NotFoundError("Dev endpoint unavailable in production", code="NOT_FOUND")

    target_user_id = payload.user_id or caller.user_id
    role_code = (
        payload.role_code
        if payload.role_code
        in (RoleCode.RL13_PLATFORM_ADMIN.value, RoleCode.RL14_SUPER_ADMIN.value)
        else RoleCode.RL13_PLATFORM_ADMIN.value
    )

    # Find or create Platform Organization
    stmt_org = select(Organization).where(Organization.type == OrganizationType.PLATFORM.value)
    res_org = await db.execute(stmt_org)
    platform_org = res_org.scalar_one_or_none()

    if not platform_org:
        platform_org = Organization(
            type=OrganizationType.PLATFORM.value,
            name="BYKERS Platform Governance",
            approval_state=OrgApprovalState.APPROVED.value,
            created_by=target_user_id,
        )
        db.add(platform_org)
        await db.flush()

    # Find Role
    stmt_role = select(Role).where(Role.code == role_code)
    role = (await db.execute(stmt_role)).scalar_one()

    # Create or update membership
    stmt_mem = select(OrganizationMembership).where(
        OrganizationMembership.user_id == target_user_id,
        OrganizationMembership.organization_id == platform_org.id,
        OrganizationMembership.role_id == role.id,
    )
    mem = (await db.execute(stmt_mem)).scalar_one_or_none()

    if not mem:
        mem = OrganizationMembership(
            user_id=target_user_id,
            organization_id=platform_org.id,
            role_id=role.id,
            status=MembershipStatus.ACTIVE.value,
            version=1,
        )
        db.add(mem)
    else:
        mem.status = MembershipStatus.ACTIVE.value
        mem.version += 1

    await db.commit()

    record_audit_event(
        actor=str(caller.user_id),
        action="dev.make_admin",
        resource=f"user:{target_user_id}",
        outcome="success",
        reason=f"Promoted to {role_code} via dev helper",
        request_id=request_id,
    )

    return DevMakeAdminOut(
        user_id=target_user_id,
        role_code=role_code,
        message=f"User {target_user_id} promoted to {role.name} ({role_code})",
    )
