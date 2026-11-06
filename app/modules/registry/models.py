"""SQLAlchemy Models for Module Registry and Interface Customization.

Tables:
- modules: Registry of all DPR modules (M01..M38)
- interface_modules: Mapping of modules to web interfaces (check constraint: rejects rider_app)
- organization_modules: Organization-specific module overrides and switches
- partner_category_modules: Modules tied to approved partner business categories
- role_module_access: Role-based module access level (none, view, manage)
- organization_categories: Approved partner business categories per organization
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ModuleRelease(str, Enum):
    """Release targets for modules."""

    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class ModuleAccessLevel(str, Enum):
    """Access level granted to a role for a module."""

    NONE = "none"
    VIEW = "view"
    MANAGE = "manage"


class PartnerCategory(str, Enum):
    """Approved partner business categories."""

    CAFE = "cafe"
    HOTEL_HOMESTAY = "hotel_homestay"
    CAMPSITE = "campsite"
    GARAGE = "garage"
    ROADSIDE = "roadside"
    RENTAL = "rental"
    GEAR = "gear"
    DEALER = "dealer"
    INSTRUCTOR_SCHOOL = "instructor_school"
    FUEL_CHARGING = "fuel_charging"


class CategoryApprovalState(str, Enum):
    """Approval status of an organization business category."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Module(Base):
    """Registry of all platform modules (M01..M38)."""

    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release: Mapped[str] = mapped_column(String(10), nullable=False, default="R1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint(
            "release IN ('R1', 'R2', 'R3')",
            name="ck_modules_release_valid",
        ),
    )


class InterfaceModule(Base):
    """Modules mapped to web interfaces. Check constraint strictly rejects rider_app."""

    __tablename__ = "interface_modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interface: Mapped[str] = mapped_column(String(32), nullable=False)
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    default_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    module: Mapped["Module"] = relationship("Module")

    __table_args__ = (
        UniqueConstraint("interface", "module_id", name="uq_interface_modules_interface_module"),
        CheckConstraint(
            "interface IN ('organizer_portal', 'partner_portal', 'staff_console')",
            name="ck_interface_modules_web_only",
        ),
    )


class OrganizationModule(Base):
    """Per-organization module switches."""

    __tablename__ = "organization_modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    set_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    module: Mapped["Module"] = relationship("Module")

    __table_args__ = (
        UniqueConstraint("organization_id", "module_id", name="uq_organization_modules_org_module"),
    )


class PartnerCategoryModule(Base):
    """Mapping of approved business categories to permitted modules."""

    __tablename__ = "partner_category_modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Relationships
    module: Mapped["Module"] = relationship("Module")

    __table_args__ = (
        UniqueConstraint("category", "module_id", name="uq_partner_category_modules_cat_module"),
        CheckConstraint(
            "category IN ("
            "'cafe', 'hotel_homestay', 'campsite', 'garage', 'roadside', "
            "'rental', 'gear', 'dealer', 'instructor_school', 'fuel_charging'"
            ")",
            name="ck_partner_category_modules_valid",
        ),
    )


class RoleModuleAccess(Base):
    """Access level (none, view, manage) granted to a role for a module within a web interface."""

    __tablename__ = "role_module_access"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    interface: Mapped[str] = mapped_column(String(32), nullable=False)
    access: Mapped[str] = mapped_column(String(20), nullable=False, default="view")

    # Relationships
    module: Mapped["Module"] = relationship("Module")

    __table_args__ = (
        UniqueConstraint(
            "role_id", "module_id", "interface", name="uq_role_module_access_role_mod_iface"
        ),
        CheckConstraint(
            "access IN ('none', 'view', 'manage')",
            name="ck_role_module_access_valid",
        ),
        CheckConstraint(
            "interface IN ('organizer_portal', 'partner_portal', 'staff_console')",
            name="ck_role_module_access_web_only",
        ),
    )


class OrganizationCategory(Base):
    """Approved partner business categories for an organization."""

    __tablename__ = "organization_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "category", name="uq_organization_categories_org_cat"),
        CheckConstraint(
            "category IN ("
            "'cafe', 'hotel_homestay', 'campsite', 'garage', 'roadside', "
            "'rental', 'gear', 'dealer', 'instructor_school', 'fuel_charging'"
            ")",
            name="ck_org_cat_category_valid",
        ),
        CheckConstraint(
            "approval_state IN ('pending', 'approved', 'rejected')",
            name="ck_org_cat_approval_state_valid",
        ),
    )
