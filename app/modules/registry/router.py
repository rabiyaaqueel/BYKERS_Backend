"""FastAPI Endpoints for Module Registry, Menu Navigation, and Customization."""

import uuid
from typing import List

from fastapi import APIRouter, Body, Depends, Header, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.dependencies import (
    AuthenticatedUser,
    require_interface,
    require_recent_auth,
)
from app.core.permissions import require, require_module
from app.modules.registry import service
from app.modules.registry.schemas import (
    InterfaceModuleOut,
    InterfaceModuleUpdateIn,
    MenuResponse,
    OrganizationCategoryOut,
    OrganizationModuleOut,
    OrganizationModuleToggleIn,
    RoleModuleAccessOut,
    RoleModuleAccessUpdateIn,
)

menu_router = APIRouter(tags=["Menu Navigation"])
admin_modules_router = APIRouter(prefix="/admin", tags=["Staff Module Administration"])
org_modules_router = APIRouter(prefix="/organizations", tags=["Organization Modules"])


# ==============================================================================
# 1. Navigation Menu (Web Interfaces Only)
# ==============================================================================


@menu_router.get(
    "/me/menu",
    response_model=MenuResponse,
    summary="Get navigation menu for current web interface",
    description=(
        "Returns authorized, active modules for the user's active session and workspace. "
        "Returns 403 on rider_app."
    ),
)
async def api_get_menu(
    user: AuthenticatedUser = Depends(
        require_interface("organizer_portal", "partner_portal", "staff_console")
    ),
    _mod: AuthenticatedUser = Depends(require_module("M01")),
    db: AsyncSession = Depends(get_db),
) -> MenuResponse:
    return await service.get_menu_for_user(db=db, user=user)


# ==============================================================================
# 2. Staff Module Administration (Staff Console Only)
# ==============================================================================


@admin_modules_router.get(
    "/interfaces/{interface}/modules",
    response_model=List[InterfaceModuleOut],
    summary="List interface module configuration",
    description="Lists modules configured for an interface with order and default enablement.",
)
async def api_list_interface_modules(
    interface: str = Path(
        ..., description="Interface name (organizer_portal, partner_portal, staff_console)"
    ),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("module.configure", module_code="M31")),
    _auth: AuthenticatedUser = Depends(require_recent_auth()),
    db: AsyncSession = Depends(get_db),
) -> List[InterfaceModuleOut]:
    return await service.list_interface_modules(db=db, interface=interface)


@admin_modules_router.put(
    "/interfaces/{interface}/modules/{module_code}",
    response_model=InterfaceModuleOut,
    summary="Update interface module configuration",
    description="Staff re-orders or changes default on/off state for an interface module.",
)
async def api_update_interface_module(
    interface: str = Path(..., description="Interface name"),
    module_code: str = Path(..., description="Module code (e.g. M12)"),
    payload: InterfaceModuleUpdateIn = Body(...),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("module.configure", module_code="M31")),
    _auth: AuthenticatedUser = Depends(require_recent_auth()),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> InterfaceModuleOut:
    return await service.update_interface_module(
        db=db,
        admin_user=user,
        interface=interface,
        module_code=module_code,
        payload=payload,
        request_id=x_request_id,
    )


@admin_modules_router.get(
    "/organizations/{id}/modules",
    response_model=List[OrganizationModuleOut],
    summary="List organization module switches (Staff)",
    description="Staff inspects module switches configured for an organization.",
)
async def api_staff_list_org_modules(
    id: uuid.UUID = Path(..., description="Organization ID"),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("module.configure", module_code="M31")),
    _auth: AuthenticatedUser = Depends(require_recent_auth()),
    db: AsyncSession = Depends(get_db),
) -> List[OrganizationModuleOut]:
    return await service.list_organization_modules(db=db, org_id=id)


@admin_modules_router.put(
    "/organizations/{id}/modules",
    response_model=List[OrganizationModuleOut],
    summary="Staff update organization module switches",
    description="Staff turns modules on or off for a specific organization.",
)
async def api_staff_update_org_modules(
    id: uuid.UUID = Path(..., description="Organization ID"),
    payload: OrganizationModuleToggleIn = Body(...),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("module.configure", module_code="M31")),
    _auth: AuthenticatedUser = Depends(require_recent_auth()),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> List[OrganizationModuleOut]:
    return await service.update_organization_modules_by_staff(
        db=db,
        admin_user=user,
        org_id=id,
        payload=payload,
        request_id=x_request_id,
    )


@admin_modules_router.get(
    "/roles/{id}/module-access",
    response_model=List[RoleModuleAccessOut],
    summary="List role module access levels",
    description="Staff views module access levels for a role.",
)
async def api_list_role_module_access(
    id: uuid.UUID = Path(..., description="Role ID"),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("module.configure", module_code="M31")),
    _auth: AuthenticatedUser = Depends(require_recent_auth()),
    db: AsyncSession = Depends(get_db),
) -> List[RoleModuleAccessOut]:
    return await service.list_role_module_access(db=db, role_id=id)


@admin_modules_router.put(
    "/roles/{id}/module-access/{module_code}/{interface}",
    response_model=RoleModuleAccessOut,
    summary="Update role module access level",
    description=(
        "Staff configures access (none, view, manage) for a role on a module in an interface."
    ),
)
async def api_update_role_module_access(
    id: uuid.UUID = Path(..., description="Role ID"),
    module_code: str = Path(..., description="Module code (e.g. M06)"),
    interface: str = Path(..., description="Interface name"),
    payload: RoleModuleAccessUpdateIn = Body(...),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("module.configure", module_code="M31")),
    _auth: AuthenticatedUser = Depends(require_recent_auth()),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> RoleModuleAccessOut:
    return await service.update_role_module_access(
        db=db,
        admin_user=user,
        role_id=id,
        module_code=module_code,
        interface=interface,
        payload=payload,
        request_id=x_request_id,
    )


@admin_modules_router.post(
    "/organizations/{id}/categories/{category}/approve",
    response_model=OrganizationCategoryOut,
    summary="Approve partner business category",
    description="Staff approves a business category for a partner organization.",
)
async def api_approve_partner_category(
    id: uuid.UUID = Path(..., description="Organization ID"),
    category: str = Path(..., description="Partner category"),
    user: AuthenticatedUser = Depends(require_interface("staff_console")),
    _perm: AuthenticatedUser = Depends(require("module.configure", module_code="M31")),
    _auth: AuthenticatedUser = Depends(require_recent_auth()),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> OrganizationCategoryOut:
    return await service.approve_partner_category(
        db=db, staff_user=user, org_id=id, category=category, request_id=x_request_id
    )


# ==============================================================================
# 3. Organization Owner Module Toggling
# ==============================================================================


@org_modules_router.put(
    "/{id}/modules",
    response_model=List[OrganizationModuleOut],
    summary="Toggle modules for own organization",
    description="Organization owner toggles modules within platform-allowed boundaries.",
)
async def api_owner_toggle_org_modules(
    id: uuid.UUID = Path(..., description="Organization ID"),
    payload: OrganizationModuleToggleIn = Body(...),
    user: AuthenticatedUser = Depends(require_interface("organizer_portal", "partner_portal")),
    _perm: AuthenticatedUser = Depends(require("module.toggle_own", module_code="M30")),
    db: AsyncSession = Depends(get_db),
    x_request_id: str = Header(default=""),
) -> List[OrganizationModuleOut]:
    return await service.toggle_organization_modules_by_owner(
        db=db, owner_user=user, org_id=id, payload=payload, request_id=x_request_id
    )
