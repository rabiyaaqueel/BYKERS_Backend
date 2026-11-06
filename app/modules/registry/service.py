"""Business Logic for Module Registry, Menu Generation, and Interface Customization."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.core.dependencies import AuthenticatedUser
from app.core.errors import ForbiddenError, NotFoundError
from app.modules.auth.models import Session
from app.modules.authz.models import (
    AuditEvent,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    Role,
)
from app.modules.registry.models import (
    CategoryApprovalState,
    InterfaceModule,
    Module,
    OrganizationCategory,
    OrganizationModule,
    PartnerCategoryModule,
    RoleModuleAccess,
)
from app.modules.registry.schemas import (
    InterfaceModuleOut,
    InterfaceModuleUpdateIn,
    MenuItemOut,
    MenuResponse,
    OrganizationCategoryOut,
    OrganizationModuleOut,
    OrganizationModuleToggleIn,
    RoleModuleAccessOut,
    RoleModuleAccessUpdateIn,
)

logger = logging.getLogger("bykers.registry")

WEB_INTERFACES: Set[str] = {"organizer_portal", "partner_portal", "staff_console"}


# ==============================================================================
# Helper to bump permission version on all active organization members
# ==============================================================================


async def _bump_organization_members_permission_version(
    db: AsyncSession, org_id: uuid.UUID
) -> None:
    """Increments permission_version for all active members of an organization.

    This ensures configuration changes immediately invalidate cached claims and apply
    on the user's next authenticated request.
    """
    stmt_members = select(OrganizationMembership.user_id).where(
        OrganizationMembership.organization_id == org_id,
        OrganizationMembership.status == MembershipStatus.ACTIVE.value,
    )
    res_mems = await db.execute(stmt_members)
    user_ids = res_mems.scalars().all()
    if user_ids:
        await db.execute(
            update(Session)
            .where(
                Session.user_id.in_(user_ids),
                Session.revoked_at.is_(None),
            )
            .values(permission_version=Session.permission_version + 1)
        )
        await db.flush()


# ==============================================================================
# 1. GET /me/menu
# ==============================================================================


async def get_menu_for_user(db: AsyncSession, user: AuthenticatedUser) -> MenuResponse:
    """Returns the ordered modules the user may use in their current web session and workspace.

    Rules:
    - rider_app sessions get 403 Forbidden.
    - Active modules only (R2 and R3 modules stay disabled until release flag is on).
    - Mapped to the current interface in interface_modules.
    - Organization switch enabled in organization_modules (or default_enabled in interface_modules).
    - If partner_portal: must match approved categories from organization_categories.
      If pending partner (no approved categories): returns only the application tracker.
    - Role access above 'none' in role_module_access.
    """
    session_interface = user.session.interface
    if session_interface not in WEB_INTERFACES:
        raise ForbiddenError(
            f"Interface '{session_interface}' does not support customizable menus. "
            f"Permitted: {sorted(list(WEB_INTERFACES))}",
            code="FORBIDDEN_INTERFACE",
        )

    session_ctx = user.session.active_context or {}
    org_id_raw = session_ctx.get("organization_id")
    active_role_code = session_ctx.get("role_code")
    org_uuid: Optional[uuid.UUID] = None

    if org_id_raw:
        try:
            org_uuid = uuid.UUID(str(org_id_raw))
        except (ValueError, TypeError):
            org_uuid = None

    # Load active modules for this interface
    stmt_iface = (
        select(InterfaceModule, Module)
        .join(Module, InterfaceModule.module_id == Module.id)
        .where(
            InterfaceModule.interface == session_interface,
            Module.is_active == True,  # noqa: E712
        )
        .order_by(InterfaceModule.display_order.asc())
    )
    res_iface = await db.execute(stmt_iface)
    iface_modules = res_iface.all()

    # Load organization-level switches if in an organization context
    org_switches: Dict[uuid.UUID, bool] = {}
    approved_categories: Set[str] = set()

    if org_uuid:
        stmt_org = select(OrganizationModule).where(OrganizationModule.organization_id == org_uuid)
        res_org = await db.execute(stmt_org)
        for row in res_org.scalars().all():
            org_switches[row.module_id] = row.enabled

        # If partner_portal, check approved partner categories
        if session_interface == "partner_portal":
            stmt_cats = select(OrganizationCategory.category).where(
                OrganizationCategory.organization_id == org_uuid,
                OrganizationCategory.approval_state == CategoryApprovalState.APPROVED.value,
            )
            res_cats = await db.execute(stmt_cats)
            approved_categories = set(res_cats.scalars().all())

    # Load category-module associations for partner portal
    category_modules_map: Dict[uuid.UUID, Set[str]] = {}
    if session_interface == "partner_portal":
        stmt_pcm = select(PartnerCategoryModule)
        res_pcm = await db.execute(stmt_pcm)
        for pcm in res_pcm.scalars().all():
            if pcm.module_id not in category_modules_map:
                category_modules_map[pcm.module_id] = set()
            category_modules_map[pcm.module_id].add(pcm.category)

    # Load role module access
    role_access_map: Dict[uuid.UUID, str] = {}
    if active_role_code:
        stmt_rma = (
            select(RoleModuleAccess.module_id, RoleModuleAccess.access)
            .join(Role, Role.id == RoleModuleAccess.role_id)
            .where(
                Role.code == active_role_code,
                RoleModuleAccess.interface == session_interface,
            )
        )
        res_rma = await db.execute(stmt_rma)
        for mod_id, access in res_rma.all():
            role_access_map[mod_id] = access

    menu_items: List[MenuItemOut] = []

    # If pending partner: a pending partner sees only the application tracker
    is_pending_partner = (
        session_interface == "partner_portal" and org_uuid is not None and not approved_categories
    )

    for iface_mod, mod in iface_modules:
        # 1. Check partner pending state
        if is_pending_partner:
            # Only allow M29 (Partner onboarding branches and operations) as tracker
            if mod.code != "M29":
                continue

        # 2. Check partner category requirements
        if session_interface == "partner_portal" and not is_pending_partner:
            req_cats = category_modules_map.get(mod.id)
            if req_cats:
                # Module requires at least one approved category
                if not (req_cats & approved_categories):
                    continue

        # 3. Check organization switch
        is_enabled = org_switches.get(mod.id, iface_mod.default_enabled)
        if not is_enabled:
            continue

        # 4. Check role module access
        access_level = role_access_map.get(mod.id)
        if access_level == "none":
            continue

        # Default access level if not explicitly set
        effective_access: str = access_level or (
            "manage" if active_role_code in ("RL02", "RL07", "RL13", "RL14") else "view"
        )

        menu_items.append(
            MenuItemOut(
                code=mod.code,
                name=mod.name,
                access="manage" if effective_access == "manage" else "view",
                display_order=iface_mod.display_order,
            )
        )

    return MenuResponse(
        interface=session_interface,
        organization_id=org_uuid,
        modules=menu_items,
    )


# ==============================================================================
# 2. Staff Console Module Administration
# ==============================================================================


async def list_interface_modules(db: AsyncSession, interface: str) -> List[InterfaceModuleOut]:
    """Lists modules configured for a web interface with sort order and default on/off state."""
    if interface not in WEB_INTERFACES:
        raise ForbiddenError(
            f"Interface '{interface}' is not a valid web interface",
            code="INVALID_INTERFACE",
        )

    stmt = (
        select(InterfaceModule, Module)
        .join(Module, InterfaceModule.module_id == Module.id)
        .where(InterfaceModule.interface == interface)
        .order_by(InterfaceModule.display_order.asc())
    )
    res = await db.execute(stmt)
    results = []
    for iface_mod, mod in res.all():
        results.append(
            InterfaceModuleOut(
                module_id=mod.id,
                module_code=mod.code,
                module_name=mod.name,
                release=mod.release,
                is_active=mod.is_active,
                display_order=iface_mod.display_order,
                default_enabled=iface_mod.default_enabled,
            )
        )
    return results


async def update_interface_module(
    db: AsyncSession,
    admin_user: AuthenticatedUser,
    interface: str,
    module_code: str,
    payload: InterfaceModuleUpdateIn,
    request_id: str = "",
) -> InterfaceModuleOut:
    """Updates order and default on/off state for an interface module."""
    if interface not in WEB_INTERFACES:
        raise ForbiddenError(
            f"Interface '{interface}' is not a valid web interface", code="INVALID_INTERFACE"
        )

    stmt = (
        select(InterfaceModule, Module)
        .join(Module, InterfaceModule.module_id == Module.id)
        .where(
            InterfaceModule.interface == interface,
            Module.code == module_code,
        )
    )
    res = await db.execute(stmt)
    row = res.first()
    if not row:
        raise NotFoundError(f"Module '{module_code}' not found for interface '{interface}'")

    iface_mod, mod = row
    before = {
        "display_order": iface_mod.display_order,
        "default_enabled": iface_mod.default_enabled,
    }

    if payload.display_order is not None:
        iface_mod.display_order = payload.display_order
    if payload.default_enabled is not None:
        iface_mod.default_enabled = payload.default_enabled

    await db.flush()
    after = {
        "display_order": iface_mod.display_order,
        "default_enabled": iface_mod.default_enabled,
    }

    db.add(
        AuditEvent(
            actor_id=str(admin_user.user_id),
            active_context={"interface": interface},
            target=f"interface:{interface}:module:{module_code}",
            action="interface_module.update",
            outcome="success",
            reason="Updated interface module configuration",
            request_id=request_id,
            audit_metadata={"before": before, "after": after},
        )
    )
    await db.commit()

    record_audit_event(
        actor=str(admin_user.user_id),
        action="interface_module.update",
        resource=f"interface:{interface}:module:{module_code}",
        outcome="success",
        reason="Updated interface module configuration",
        request_id=request_id,
        metadata={"before": before, "after": after},
    )

    return InterfaceModuleOut(
        module_id=mod.id,
        module_code=mod.code,
        module_name=mod.name,
        release=mod.release,
        is_active=mod.is_active,
        display_order=iface_mod.display_order,
        default_enabled=iface_mod.default_enabled,
    )


async def list_organization_modules(
    db: AsyncSession, org_id: uuid.UUID
) -> List[OrganizationModuleOut]:
    """Lists module enablement switches for an organization."""
    # Verify organization exists
    org = await db.get(Organization, org_id)
    if not org:
        raise NotFoundError(f"Organization '{org_id}' not found")

    # Determine matching interface for this organization
    target_interface = "partner_portal" if org.type == "business" else "organizer_portal"

    # Get allowed modules for this interface
    stmt_iface = (
        select(InterfaceModule, Module)
        .join(Module, InterfaceModule.module_id == Module.id)
        .where(InterfaceModule.interface == target_interface)
        .order_by(InterfaceModule.display_order.asc())
    )
    res_iface = await db.execute(stmt_iface)
    iface_mods = res_iface.all()

    # Get org-specific switches
    stmt_org = select(OrganizationModule).where(OrganizationModule.organization_id == org_id)
    res_org = await db.execute(stmt_org)
    org_switches = {row.module_id: row for row in res_org.scalars().all()}

    results = []
    for iface_mod, mod in iface_mods:
        org_mod = org_switches.get(mod.id)
        enabled = org_mod.enabled if org_mod else iface_mod.default_enabled
        results.append(
            OrganizationModuleOut(
                module_code=mod.code,
                module_name=mod.name,
                enabled=enabled,
                can_toggle=True,
                set_at=org_mod.set_at if org_mod else None,
            )
        )
    return results


async def update_organization_modules_by_staff(
    db: AsyncSession,
    admin_user: AuthenticatedUser,
    org_id: uuid.UUID,
    payload: OrganizationModuleToggleIn,
    request_id: str = "",
) -> List[OrganizationModuleOut]:
    """Staff updates module switches for an organization and invalidates cached claims."""
    org = await db.get(Organization, org_id)
    if not org:
        raise NotFoundError(f"Organization '{org_id}' not found")

    # Map module codes to IDs
    stmt_mods = select(Module).where(Module.code.in_(payload.modules.keys()))
    res_mods = await db.execute(stmt_mods)
    mods_by_code = {m.code: m for m in res_mods.scalars().all()}

    before_states = {}
    after_states = {}

    for code, enabled in payload.modules.items():
        mod = mods_by_code.get(code)
        if not mod:
            continue

        stmt_org_mod = select(OrganizationModule).where(
            OrganizationModule.organization_id == org_id,
            OrganizationModule.module_id == mod.id,
        )
        res_om = await db.execute(stmt_org_mod)
        om = res_om.scalars().first()

        before_states[code] = om.enabled if om else True
        after_states[code] = enabled

        if om:
            om.enabled = enabled
            om.set_by = admin_user.user_id
            om.set_at = datetime.now(timezone.utc)
            om.version += 1
        else:
            new_om = OrganizationModule(
                organization_id=org_id,
                module_id=mod.id,
                enabled=enabled,
                set_by=admin_user.user_id,
                set_at=datetime.now(timezone.utc),
                version=1,
            )
            db.add(new_om)

    await db.flush()

    # Rule: Changing configuration increments affected users' permission_version
    await _bump_organization_members_permission_version(db=db, org_id=org_id)

    db.add(
        AuditEvent(
            actor_id=str(admin_user.user_id),
            active_context={"org_id": str(org_id)},
            target=f"organization:{org_id}",
            action="organization_modules.staff_update",
            outcome="success",
            reason="Staff toggled organization modules",
            request_id=request_id,
            audit_metadata={"before": before_states, "after": after_states},
        )
    )
    await db.commit()

    record_audit_event(
        actor=str(admin_user.user_id),
        action="organization_modules.staff_update",
        resource=f"organization:{org_id}",
        outcome="success",
        reason="Staff toggled organization modules",
        request_id=request_id,
        metadata={"before": before_states, "after": after_states},
    )

    return await list_organization_modules(db=db, org_id=org_id)


# ==============================================================================
# 3. Organization Owner Module Toggling (PUT /organizations/{id}/modules)
# ==============================================================================


async def toggle_organization_modules_by_owner(
    db: AsyncSession,
    owner_user: AuthenticatedUser,
    org_id: uuid.UUID,
    payload: OrganizationModuleToggleIn,
    request_id: str = "",
) -> List[OrganizationModuleOut]:
    """Owner toggles modules for their own organization.

    Rules:
    - Club owner A cannot change club B's modules (isolated boundary).
    - An owner may turn off any module in their allowed set.
    - An owner may turn on a module only if staff allow it for that interface & org type.
    - Owners can never enable what staff disabled.
    - Writes audit event with before and after states.
    - Increments permission_version for all active members.
    """
    org = await db.get(Organization, org_id)
    if not org:
        raise NotFoundError(f"Organization '{org_id}' not found")

    # Verify caller is an active member with ownership role in org_id
    stmt_mem = (
        select(OrganizationMembership, Role.code)
        .join(Role, Role.id == OrganizationMembership.role_id)
        .where(
            OrganizationMembership.user_id == owner_user.user_id,
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
        )
    )
    res_mem = await db.execute(stmt_mem)
    mem_rows = res_mem.all()
    roles = [r[1] for r in mem_rows]
    if not ("RL02" in roles or "RL07" in roles or "RL13" in roles or "RL14" in roles):
        raise ForbiddenError(
            "Only the organization owner or platform administrator may toggle organization modules",
            code="FORBIDDEN_ORG_OWNER",
        )

    target_interface = "partner_portal" if org.type == "business" else "organizer_portal"

    # Get allowed interface modules
    stmt_iface = (
        select(InterfaceModule, Module)
        .join(Module, InterfaceModule.module_id == Module.id)
        .where(InterfaceModule.interface == target_interface)
    )
    res_iface = await db.execute(stmt_iface)
    allowed_iface_mods = {mod.code: (iface_mod, mod) for iface_mod, mod in res_iface.all()}

    # Check partner approved categories if partner portal
    if target_interface == "partner_portal":
        stmt_cats = select(OrganizationCategory.category).where(
            OrganizationCategory.organization_id == org_id,
            OrganizationCategory.approval_state == CategoryApprovalState.APPROVED.value,
        )
        res_cats = await db.execute(stmt_cats)
        cats = set(res_cats.scalars().all())

        stmt_pcm = select(PartnerCategoryModule.module_id).where(
            PartnerCategoryModule.category.in_(cats)
        )
        res_pcm = await db.execute(stmt_pcm)
        approved_cat_mod_ids = set(res_pcm.scalars().all())

    # Map module codes to IDs
    stmt_mods = select(Module).where(Module.code.in_(payload.modules.keys()))
    res_mods = await db.execute(stmt_mods)
    mods_by_code = {m.code: m for m in res_mods.scalars().all()}

    before_states = {}
    after_states = {}

    for code, target_enabled in payload.modules.items():
        mod = mods_by_code.get(code)
        if not mod:
            raise NotFoundError(f"Module '{code}' not found")

        # Check if module is allowed on this interface
        if code not in allowed_iface_mods:
            raise ForbiddenError(
                f"Module '{code}' is not permitted for organization type '{org.type}'",
                code="MODULE_NOT_ALLOWED_FOR_TYPE",
            )

        iface_mod, _ = allowed_iface_mods[code]

        # Check existing organization setting
        stmt_om = select(OrganizationModule).where(
            OrganizationModule.organization_id == org_id,
            OrganizationModule.module_id == mod.id,
        )
        res_om = await db.execute(stmt_om)
        om = res_om.scalars().first()

        current_enabled = om.enabled if om else iface_mod.default_enabled
        before_states[code] = current_enabled
        after_states[code] = target_enabled

        # Owner rule: if enabling, ensure staff did not explicitly lock/disable it
        if target_enabled and not current_enabled:
            # Check if staff previously disabled this module for this org
            if om and om.set_by and om.set_by != owner_user.user_id:
                # Was disabled by another user (staff)
                stmt_staff = (
                    select(Role.code)
                    .join(OrganizationMembership, OrganizationMembership.role_id == Role.id)
                    .where(
                        OrganizationMembership.user_id == om.set_by,
                        Role.code.in_(["RL13", "RL14"]),
                    )
                )
                res_staff = await db.execute(stmt_staff)
                if res_staff.scalars().first():
                    raise ForbiddenError(
                        f"Module '{code}' was disabled by platform staff "
                        "and cannot be re-enabled by organization owner",
                        code="MODULE_LOCKED_BY_STAFF",
                    )

            # For partner portal: must be in approved categories or base modules
            if target_interface == "partner_portal":
                # Base partner modules
                base_partner = {"M01", "M05", "M13", "M14", "M15", "M29", "M32", "M33", "M38"}
                if code not in base_partner and mod.id not in approved_cat_mod_ids:
                    raise ForbiddenError(
                        f"Module '{code}' requires an approved business category",
                        code="MODULE_CATEGORY_NOT_APPROVED",
                    )

        if om:
            om.enabled = target_enabled
            om.set_by = owner_user.user_id
            om.set_at = datetime.now(timezone.utc)
            om.version += 1
        else:
            new_om = OrganizationModule(
                organization_id=org_id,
                module_id=mod.id,
                enabled=target_enabled,
                set_by=owner_user.user_id,
                set_at=datetime.now(timezone.utc),
                version=1,
            )
            db.add(new_om)

    await db.flush()

    # Rule: Changing configuration increments affected users' permission_version
    await _bump_organization_members_permission_version(db=db, org_id=org_id)

    db.add(
        AuditEvent(
            actor_id=str(owner_user.user_id),
            active_context={"org_id": str(org_id)},
            target=f"organization:{org_id}",
            action="organization_modules.owner_toggle",
            outcome="success",
            reason="Organization owner toggled modules",
            request_id=request_id,
            audit_metadata={"before": before_states, "after": after_states},
        )
    )
    await db.commit()

    record_audit_event(
        actor=str(owner_user.user_id),
        action="organization_modules.owner_toggle",
        resource=f"organization:{org_id}",
        outcome="success",
        reason="Organization owner toggled modules",
        request_id=request_id,
        metadata={"before": before_states, "after": after_states},
    )

    return await list_organization_modules(db=db, org_id=org_id)


# ==============================================================================
# 4. Role Module Access Management
# ==============================================================================


async def list_role_module_access(
    db: AsyncSession, role_id: uuid.UUID
) -> List[RoleModuleAccessOut]:
    """Lists module access levels (none, view, manage) for a role."""
    role = await db.get(Role, role_id)
    if not role:
        raise NotFoundError(f"Role '{role_id}' not found")

    stmt = (
        select(RoleModuleAccess, Module)
        .join(Module, RoleModuleAccess.module_id == Module.id)
        .where(RoleModuleAccess.role_id == role_id)
    )
    res = await db.execute(stmt)
    results = []
    for rma, mod in res.all():
        results.append(
            RoleModuleAccessOut(
                role_id=role_id,
                role_code=role.code,
                module_code=mod.code,
                interface=rma.interface,
                access=rma.access,  # type: ignore[arg-type]
            )
        )
    return results


async def update_role_module_access(
    db: AsyncSession,
    admin_user: AuthenticatedUser,
    role_id: uuid.UUID,
    module_code: str,
    interface: str,
    payload: RoleModuleAccessUpdateIn,
    request_id: str = "",
) -> RoleModuleAccessOut:
    """Staff updates access level for a role on a module in an interface."""
    role = await db.get(Role, role_id)
    if not role:
        raise NotFoundError(f"Role '{role_id}' not found")

    stmt_mod = select(Module).where(Module.code == module_code)
    res_mod = await db.execute(stmt_mod)
    mod = res_mod.scalars().first()
    if not mod:
        raise NotFoundError(f"Module '{module_code}' not found")

    stmt_rma = select(RoleModuleAccess).where(
        RoleModuleAccess.role_id == role_id,
        RoleModuleAccess.module_id == mod.id,
        RoleModuleAccess.interface == interface,
    )
    res_rma = await db.execute(stmt_rma)
    rma = res_rma.scalars().first()

    before_access = rma.access if rma else "none"

    if rma:
        rma.access = payload.access
    else:
        rma = RoleModuleAccess(
            role_id=role_id,
            module_id=mod.id,
            interface=interface,
            access=payload.access,
        )
        db.add(rma)

    await db.flush()

    db.add(
        AuditEvent(
            actor_id=str(admin_user.user_id),
            active_context={"role_id": str(role_id)},
            target=f"role:{role.code}:module:{module_code}:interface:{interface}",
            action="role_module_access.update",
            outcome="success",
            reason="Staff updated role module access",
            request_id=request_id,
            audit_metadata={"before": before_access, "after": payload.access},
        )
    )
    await db.commit()

    record_audit_event(
        actor=str(admin_user.user_id),
        action="role_module_access.update",
        resource=f"role:{role.code}:module:{module_code}:interface:{interface}",
        outcome="success",
        reason="Staff updated role module access",
        request_id=request_id,
        metadata={"before": before_access, "after": payload.access},
    )

    return RoleModuleAccessOut(
        role_id=role_id,
        role_code=role.code,
        module_code=mod.code,
        interface=interface,
        access=rma.access,  # type: ignore[arg-type]
    )


# ==============================================================================
# 5. Partner Category Approval Helper
# ==============================================================================


async def approve_partner_category(
    db: AsyncSession,
    staff_user: AuthenticatedUser,
    org_id: uuid.UUID,
    category: str,
    request_id: str = "",
) -> OrganizationCategoryOut:
    """Approves a business category for a partner organization."""
    org = await db.get(Organization, org_id)
    if not org:
        raise NotFoundError(f"Organization '{org_id}' not found")

    stmt = select(OrganizationCategory).where(
        OrganizationCategory.organization_id == org_id,
        OrganizationCategory.category == category,
    )
    res = await db.execute(stmt)
    cat_row = res.scalars().first()

    now = datetime.now(timezone.utc)
    if cat_row:
        cat_row.approval_state = CategoryApprovalState.APPROVED.value
        cat_row.approved_by = staff_user.user_id
        cat_row.approved_at = now
    else:
        cat_row = OrganizationCategory(
            organization_id=org_id,
            category=category,
            approval_state=CategoryApprovalState.APPROVED.value,
            approved_by=staff_user.user_id,
            approved_at=now,
        )
        db.add(cat_row)

    await db.flush()
    await _bump_organization_members_permission_version(db=db, org_id=org_id)

    db.add(
        AuditEvent(
            actor_id=str(staff_user.user_id),
            active_context={"org_id": str(org_id)},
            target=f"organization:{org_id}:category:{category}",
            action="partner_category.approve",
            outcome="success",
            reason="Staff approved partner business category",
            request_id=request_id,
            audit_metadata={"category": category, "state": "approved"},
        )
    )
    await db.commit()

    record_audit_event(
        actor=str(staff_user.user_id),
        action="partner_category.approve",
        resource=f"organization:{org_id}:category:{category}",
        outcome="success",
        reason="Staff approved partner business category",
        request_id=request_id,
    )

    return OrganizationCategoryOut(
        category=cat_row.category,
        approval_state=cat_row.approval_state,  # type: ignore[arg-type]
        approved_at=cat_row.approved_at,
    )
