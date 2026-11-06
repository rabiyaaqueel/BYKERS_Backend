"""FastAPI Endpoints for Workspaces, Roles, Organizations, and Permissions."""

import uuid
from typing import List

from fastapi import APIRouter, Body, Depends, Header, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.dependencies import (
    ALL_INTERFACES,
    AuthenticatedUser,
    require_interface,
)
from app.core.errors import NotFoundError
from app.core.permissions import require
from app.modules.authz import service
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

authz_router = APIRouter(tags=["Workspaces & Permissions"])
applications_router = APIRouter(prefix="/applications", tags=["Applications & Review"])
orgs_router = APIRouter(prefix="/organizations", tags=["Organizations & Members"])
invitations_router = APIRouter(prefix="/invitations", tags=["Invitations"])
admin_router = APIRouter(prefix="/admin", tags=["Platform Administration"])
dev_router = APIRouter(prefix="/dev", tags=["Development Helpers"])


# ==============================================================================
# Workspaces & Capabilities
# ==============================================================================


@authz_router.get(
    "/me/workspaces",
    response_model=List[WorkspaceOut],
    summary="List caller's approved workspaces",
    description="Returns all active workspaces the rider is authorized for.",
)
async def api_list_workspaces(
    user: AuthenticatedUser = Depends(require_interface(*ALL_INTERFACES)),
    db: AsyncSession = Depends(get_db),
) -> List[WorkspaceOut]:
    return await service.list_workspaces(db=db, user=user)


@authz_router.post(
    "/me/active-workspace",
    response_model=ActiveWorkspaceOut,
    summary="Switch active workspace",
    description="Validates workspace access, updates active session context, returns capabilities.",
)
async def api_switch_active_workspace(
    payload: ActiveWorkspaceIn,
    user: AuthenticatedUser = Depends(require_interface(*ALL_INTERFACES)),
    db: AsyncSession = Depends(get_db),
) -> ActiveWorkspaceOut:
    return await service.switch_active_workspace(db=db, user=user, payload=payload)


@authz_router.get(
    "/me/capabilities",
    response_model=CapabilitiesOut,
    summary="Get active capabilities and permissions",
    description="Returns UI modules and authorized action codes. Contains no secrets.",
)
async def api_get_capabilities(
    user: AuthenticatedUser = Depends(require_interface(*ALL_INTERFACES)),
    db: AsyncSession = Depends(get_db),
) -> CapabilitiesOut:
    return await service.get_capabilities(db=db, user=user)


# ==============================================================================
# Applications (Clubs, Organizers, Partners)
# ==============================================================================


@applications_router.post(
    "",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an application",
    description="Allows riders to submit an application to start a club or become an organizer.",
)
async def api_create_application(
    payload: ApplicationCreateIn,
    user: AuthenticatedUser = Depends(require_interface(*ALL_INTERFACES)),
    _perm: AuthenticatedUser = Depends(require("application.create")),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> ApplicationOut:
    return await service.create_application(
        db=db, user=user, payload=payload, request_id=x_request_id
    )


@applications_router.get(
    "/mine",
    response_model=List[ApplicationOut],
    summary="List caller's submitted applications",
    description="Returns all applications submitted by the authenticated rider.",
)
async def api_list_my_applications(
    user: AuthenticatedUser = Depends(require_interface(*ALL_INTERFACES)),
    _perm: AuthenticatedUser = Depends(require("application.view_own")),
    db: AsyncSession = Depends(get_db),
) -> List[ApplicationOut]:
    return await service.list_my_applications(db=db, user=user)


@applications_router.post(
    "/{id}/decision",
    response_model=ApplicationDecisionOut,
    summary="Review and decide on an application",
    description="Approves or rejects application with Maker-Checker protection.",
)
async def api_decide_application(
    id: uuid.UUID = Path(..., description="Application ID"),
    payload: ApplicationDecisionIn = Body(...),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("application.review")),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> ApplicationDecisionOut:
    return await service.decide_application(
        db=db, reviewer=user, app_id=id, decision_in=payload, request_id=x_request_id
    )


# ==============================================================================
# Organizations & Memberships
# ==============================================================================


@orgs_router.post(
    "/{id}/invitations",
    response_model=RoleInvitationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create role invitation",
    description="Issues a secure, 48-hour time-limited token inviting a user to a specific role.",
)
async def api_create_invitation(
    id: uuid.UUID = Path(..., description="Organization ID"),
    payload: RoleInvitationCreateIn = Body(...),
    user: AuthenticatedUser = Depends(
        require_interface("organizer_portal", "partner_portal", "staff_console")
    ),
    _perm: AuthenticatedUser = Depends(require("invitation.create")),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> RoleInvitationOut:
    return await service.create_invitation(
        db=db, user=user, org_id=id, payload=payload, request_id=x_request_id
    )


@invitations_router.post(
    "/{token}/accept",
    response_model=InvitationAcceptOut,
    summary="Accept an invitation",
    description="Accepts an unexpired role invitation, granting membership in the organization.",
)
async def api_accept_invitation(
    token: str = Path(..., description="Raw invitation token"),
    user: AuthenticatedUser = Depends(require_interface(*ALL_INTERFACES)),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> InvitationAcceptOut:
    return await service.accept_invitation(db=db, user=user, token=token, request_id=x_request_id)


@orgs_router.patch(
    "/{id}/members/{user_id}",
    response_model=MemberOut,
    summary="Update organization member status",
    description="Modifies a member's status with optimistic lock version checking.",
)
async def api_update_member_status(
    id: uuid.UUID = Path(..., description="Organization ID"),
    user_id: uuid.UUID = Path(..., description="Target User ID"),
    payload: MemberUpdateIn = Body(...),
    admin: AuthenticatedUser = Depends(
        require_interface("organizer_portal", "partner_portal", "staff_console")
    ),
    _perm: AuthenticatedUser = Depends(require("role.assign")),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> MemberOut:
    return await service.update_member_status(
        db=db,
        admin=admin,
        org_id=id,
        target_user_id=user_id,
        payload=payload,
        request_id=x_request_id,
    )


@orgs_router.delete(
    "/{id}/members/{user_id}",
    response_model=MemberOut,
    summary="Revoke member role",
    description="Revokes membership. The revocation takes effect on user's next request.",
)
async def api_revoke_member(
    id: uuid.UUID = Path(..., description="Organization ID"),
    user_id: uuid.UUID = Path(..., description="Target User ID"),
    admin: AuthenticatedUser = Depends(
        require_interface("organizer_portal", "partner_portal", "staff_console")
    ),
    _perm: AuthenticatedUser = Depends(require("role.assign")),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> MemberOut:
    return await service.revoke_member(
        db=db, admin=admin, org_id=id, target_user_id=user_id, request_id=x_request_id
    )


# ==============================================================================
# Admin & Audit
# ==============================================================================


@admin_router.get(
    "/audit-events",
    response_model=List[AuditEventOut],
    summary="List immutable audit events",
    description="Returns compliance audit log entries. Requires audit.read permission.",
)
async def api_list_audit_events(
    limit: int = Query(default=50, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("audit.read")),
    db: AsyncSession = Depends(get_db),
) -> List[AuditEventOut]:
    return await service.list_audit_events(db=db, limit=limit)


# ==============================================================================
# Development Helper (Promote Test Admin)
# ==============================================================================


@dev_router.post(
    "/make-admin",
    response_model=DevMakeAdminOut,
    summary="Promote user to platform admin (Dev Only)",
    description="Promotes a test user to Platform Admin (RL13). Disabled outside dev environment.",
)
async def api_dev_make_admin(
    payload: DevMakeAdminIn,
    user: AuthenticatedUser = Depends(require_interface(*ALL_INTERFACES)),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> DevMakeAdminOut:
    if settings.ENV not in ("dev", "test"):
        raise NotFoundError("Not found", code="NOT_FOUND")
    return await service.dev_make_admin(
        db=db, caller=user, payload=payload, request_id=x_request_id
    )
