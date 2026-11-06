"""SQLAlchemy Models for Authorization, Roles, Organizations, Memberships, and Audit.

Tables:
- roles: The 14 platform roles (RL01..RL14)
- permissions: Granular permission codes
- role_permissions: Mapping of roles to permissions with optional conditions
- organizations: Legal/operational entities (clubs, event organizers, tour operators, businesses)
- organization_memberships: User memberships in organizations with assigned roles
- club_memberships: Rider memberships in motorcycle clubs
- activity_assignments: Scoped ride/event marshal/captain duty assignments
- role_invitations: Secure invitations to join organizations with specific roles
- applications: Applications for club/organizer/partner status
- approval_requests: Maker-checker approval requests
- audit_events: Append-only immutable security and compliance audit log
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class RoleScopeType(str, Enum):
    """Scope boundaries for platform roles."""

    PLATFORM = "platform"
    ORGANIZATION = "organization"
    CLUB = "club"
    ACTIVITY = "activity"
    PERSONAL = "personal"


class OrganizationType(str, Enum):
    """Types of operational organizations."""

    CLUB_ORG = "club_org"
    EVENT_ORG = "event_org"
    TOUR_OPERATOR = "tour_operator"
    BUSINESS = "business"
    PLATFORM = "platform"


class OrgApprovalState(str, Enum):
    """Approval lifecycle of organizations."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class MembershipStatus(str, Enum):
    """Status of user membership in organizations or clubs."""

    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class ApplicationKind(str, Enum):
    """Categories of official applications."""

    CLUB = "club"
    ORGANIZER = "organizer"
    TOUR_OPERATOR = "tour_operator"
    PARTNER = "partner"
    INSTRUCTOR = "instructor"


class ApplicationStatus(str, Enum):
    """Workflow state of user applications."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class Role(Base):
    """Platform roles (RL01..RL14)."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    role_permissions: Mapped[List["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )
    memberships: Mapped[List["OrganizationMembership"]] = relationship(
        "OrganizationMembership", back_populates="role"
    )


class Permission(Base):
    """Granular action permissions."""

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(32), default="standard", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    role_permissions: Mapped[List["RolePermission"]] = relationship(
        "RolePermission", back_populates="permission", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    """Associates roles with permitted actions."""

    __tablename__ = "role_permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conditions: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    # Relationships
    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship("Permission", back_populates="role_permissions")


class Organization(Base):
    """An organization, club, partner or platform entity."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    approval_state: Mapped[str] = mapped_column(
        String(32), default=OrgApprovalState.DRAFT.value, nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    memberships: Mapped[List["OrganizationMembership"]] = relationship(
        "OrganizationMembership", back_populates="organization", cascade="all, delete-orphan"
    )
    invitations: Mapped[List["RoleInvitation"]] = relationship(
        "RoleInvitation", back_populates="organization", cascade="all, delete-orphan"
    )


class OrganizationMembership(Base):
    """Membership of a user in an organization under an active role."""

    __tablename__ = "organization_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default=MembershipStatus.ACTIVE.value, nullable=False, index=True
    )
    branch_ids: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "organization_id", "role_id", name="uq_user_org_role_membership"
        ),
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="memberships"
    )
    role: Mapped["Role"] = relationship("Role", back_populates="memberships")


class ClubMembership(Base):
    """Rider membership in a motorcycle club."""

    __tablename__ = "club_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    club_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=MembershipStatus.ACTIVE.value, nullable=False, index=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (UniqueConstraint("club_id", "user_id", name="uq_club_user_membership"),)


class ActivityAssignment(Base):
    """Temporary event or ride staff/marshal assignment with duties and expiry."""

    __tablename__ = "activity_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    duties: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RoleInvitation(Base):
    """Time-limited invitations to assume a role in an organization."""

    __tablename__ = "role_invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inviter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recipient_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    recipient_contact: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="invitations"
    )
    role: Mapped["Role"] = relationship("Role")


class Application(Base):
    """Official application by rider/organizer for an entity or privileged role."""

    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=ApplicationStatus.SUBMITTED.value, nullable=False, index=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ApprovalRequest(Base):
    """Maker-checker requests for sensitive actions."""

    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    required_checker_role: Mapped[str] = mapped_column(String(32), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    object_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class AuditEvent(Base):
    """Append-only immutable audit events log."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    active_context: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    target: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
