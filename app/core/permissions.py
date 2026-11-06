"""Shared Authorization & Permissions Layer.

Non-Negotiable Rules 2 & 3:
- Roles are stored per organization/club/activity (memberships),
  NEVER as a single role flag on the user.
- 14 Roles: RL01..RL14.
- ONE shared permission layer with default-deny evaluation.
- Maker-checker guard (requester cannot approve own request).
- Revocation must block user's NEXT request immediately.

Evaluation order (from docs/CONTEXT.md):
1. Authenticate session
2. Check account and session status
3. Load active context
4. Verify membership (and permission_version)
5. Check feature release flag
6. Evaluate permission + ownership + object state
7. Require stronger auth if needed
8. Redact fields
9. Run transaction
10. Write audit log
"""

import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.core.db import get_db
from app.core.dependencies import AuthenticatedUser, get_current_user
from app.core.errors import ForbiddenError
from app.modules.auth.models import UserStatus
from app.modules.authz.models import (
    MembershipStatus,
    OrganizationMembership,
    Permission,
    Role,
    RolePermission,
)

logger = logging.getLogger("bykers.permissions")


class RoleCode(str, Enum):
    """The 14 authenticated role codes in BYKERS."""

    RL01_RIDER = "RL01"
    RL02_CLUB_OWNER = "RL02"
    RL03_CLUB_MODERATOR = "RL03"
    RL04_RIDE_CAPTAIN_MARSHAL = "RL04"
    RL05_EVENT_ORGANIZER = "RL05"
    RL06_TOUR_OPERATOR = "RL06"
    RL07_PARTNER_OWNER = "RL07"
    RL08_PARTNER_STAFF = "RL08"
    RL09_INSTRUCTOR = "RL09"
    RL10_SUPPORT_AGENT = "RL10"
    RL11_TRUST_MODERATOR = "RL11"
    RL12_FINANCE_OPERATOR = "RL12"
    RL13_PLATFORM_ADMIN = "RL13"
    RL14_SUPER_ADMIN = "RL14"


@dataclass
class EvaluationResult:
    """Outcome of an authorization evaluation."""

    allowed: bool
    reason: str
    code: str = "FORBIDDEN"


def assert_maker_checker(requester_id: uuid.UUID | str, checker_id: uuid.UUID | str) -> None:
    """Enforces maker-checker separation: the requester can never approve their own request."""
    if str(requester_id).strip().lower() == str(checker_id).strip().lower():
        raise ForbiddenError(
            "Maker-checker rule violation: requester cannot approve their own request",
            code="MAKER_CHECKER_VIOLATION",
        )


async def can(
    db: AsyncSession,
    user: AuthenticatedUser,
    action: str,
    resource: Optional[Any] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Evaluates whether the user can perform the specified action in their active context.

    Default: DENY.
    """
    # 1. Authenticate session & 2. Check account status
    if not user or not user.user:
        return False, "Unauthenticated session"

    if user.user.status in (UserStatus.SUSPENDED.value, UserStatus.DELETED.value):
        return False, "User account is suspended or deleted"

    # 3. Load active context
    session_ctx = user.session.active_context or {}
    active_ctx = context or session_ctx

    workspace_type = active_ctx.get("workspace_type", "personal")
    org_id_raw = active_ctx.get("organization_id")
    active_role_code = active_ctx.get("role_code")

    # 4. Check for Platform Administrator / Super Admin privileges (RL13, RL14)
    # Check if user has an active platform role
    stmt_platform = (
        select(Role.code)
        .join(OrganizationMembership, OrganizationMembership.role_id == Role.id)
        .where(
            OrganizationMembership.user_id == user.user_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE.value,
            Role.code.in_([RoleCode.RL13_PLATFORM_ADMIN.value, RoleCode.RL14_SUPER_ADMIN.value]),
        )
    )
    res_platform = await db.execute(stmt_platform)
    platform_role = res_platform.scalars().first()

    # Super Admin and Platform Admin always have access to platform operations
    if platform_role in (RoleCode.RL14_SUPER_ADMIN.value, RoleCode.RL13_PLATFORM_ADMIN.value):
        return True, f"Allowed by platform administrative role {platform_role}"

    # 5. Evaluate role within active context
    effective_role_codes: List[str] = []

    if workspace_type == "personal" or not org_id_raw:
        # Personal workspace: user acts in the capacity of a Rider (RL01)
        effective_role_codes.append(RoleCode.RL01_RIDER.value)
    else:
        # Organization or club workspace: load active membership from DB
        try:
            org_uuid = uuid.UUID(str(org_id_raw))
        except (ValueError, TypeError):
            return False, "Invalid organization identifier in active context"

        # Verify membership status in database (checks live revocation!)
        stmt_mem = (
            select(OrganizationMembership, Role.code)
            .join(Role, OrganizationMembership.role_id == Role.id)
            .where(
                OrganizationMembership.user_id == user.user_id,
                OrganizationMembership.organization_id == org_uuid,
            )
        )
        res_mem = await db.execute(stmt_mem)
        mem_rows = res_mem.all()

        active_mems = [row for row in mem_rows if row[0].status == MembershipStatus.ACTIVE.value]

        if not active_mems:
            # Immediate revocation enforcement on NEXT request:
            # If the user held this role but it was suspended or revoked, deny!
            return False, "Membership in the active organization is revoked or not active"

        for mem, r_code in active_mems:
            if not active_role_code or active_role_code == r_code:
                effective_role_codes.append(r_code)

    if not effective_role_codes:
        return False, "No active role matched in the current context"

    # 6. Check resource isolation / ownership if applicable
    if resource is not None:
        # Cross-organization boundary isolation:
        # If resource belongs to an organization, active org must match
        res_org_id = getattr(resource, "organization_id", None) or getattr(
            resource, "club_id", None
        )
        if res_org_id and org_id_raw:
            if str(res_org_id).strip().lower() != str(org_id_raw).strip().lower():
                return False, "Resource belongs to another organization"

        # If resource has an applicant or creator, maker-checker rule
        applicant_id = getattr(resource, "applicant_id", None) or getattr(
            resource, "created_by", None
        )
        if applicant_id and action in ("application.review", "approval.decide"):
            if str(applicant_id).strip().lower() == str(user.user_id).strip().lower():
                return False, "Maker-checker rule violation: applicant cannot approve own request"

    # 7. Query database for granted permissions across effective roles
    stmt_perms = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, RolePermission.role_id == Role.id)
        .where(Role.code.in_(effective_role_codes))
    )
    res_perms = await db.execute(stmt_perms)
    granted_permissions = set(res_perms.scalars().all())

    if action in granted_permissions:
        return True, f"Permission {action} granted by role(s) {effective_role_codes}"

    # Default deny
    return (
        False,
        f"Default deny: action '{action}' is not permitted for role(s) {effective_role_codes}",
    )


def require(
    permission_code: str,
    resource_loader: Optional[Callable[..., Any]] = None,
) -> Callable:
    """FastAPI dependency factory enforcing that the authenticated user possesses the permission."""

    async def _permission_dependency(
        user: AuthenticatedUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> AuthenticatedUser:
        resource = None
        if resource_loader:
            resource = await resource_loader(db=db, user=user)

        allowed, reason = await can(db=db, user=user, action=permission_code, resource=resource)

        if not allowed:
            logger.warning(
                f"[AUTHZ DENIED] user={user.user_id} action={permission_code} reason={reason}"
            )
            record_audit_event(
                actor=str(user.user_id),
                action=permission_code,
                resource="authz",
                outcome="deny",
                reason=reason,
                request_id=getattr(user.session, "request_id", ""),
            )
            raise ForbiddenError(reason, code="FORBIDDEN")

        return user

    return _permission_dependency
