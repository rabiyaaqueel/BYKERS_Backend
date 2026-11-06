"""Module registry, interface modules, organization modules, partner categories, and role access.

Revision ID: 0005_module_registry
Revises: 0004_extend_audit_events
Create Date: 2026-11-06 11:45:00

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0005_module_registry"
down_revision: Union[str, None] = "0004_extend_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MODULES_DATA = [
    (
        "M01",
        "Login identity sessions and roles",
        "Authentication, profile sessions, and interfaces",
        "R1",
        True,
    ),
    (
        "M02",
        "Rider profiles and verification labels",
        "Rider profiles and safety verifications",
        "R1",
        True,
    ),
    ("M03", "Motorcycle garage", "Garage motorcycle ownership and records", "R1", True),
    ("M04", "Nearby riders and availability", "Live radar and nearby rider visibility", "R1", True),
    ("M05", "Connections and invitations", "Followers, friends, invitations", "R1", True),
    ("M06", "Clubs membership and chapters", "Motorcycle clubs, chapters, and rosters", "R1", True),
    (
        "M07",
        "Community feed polls and moderation actions",
        "Club and community feed, discussions, moderation",
        "R1",
        True,
    ),
    ("M08", "Direct club and ride messaging", "Real-time communication and messaging", "R1", True),
    (
        "M09",
        "Ride planning schedules and recurring rides",
        "Ride planning and group schedules",
        "R1",
        True,
    ),
    (
        "M10",
        "Participation waitlist attendance and checkpoints",
        "Checkpoints, attendance tracking, roll-calls",
        "R1",
        True,
    ),
    (
        "M11",
        "Events sports calendar and tickets",
        "Events calendar, tickets, and registrations",
        "R1",
        True,
    ),
    (
        "M12",
        "Tours itineraries and departures",
        "Tours, multi-day itineraries, departures",
        "R1",
        True,
    ),
    ("M13", "Biker cafes and meetups", "Biker cafe directory and meetup spots", "R1", True),
    (
        "M14",
        "Rooms hotels homestays and campsites",
        "Accommodations and rider stay properties",
        "R1",
        True,
    ),
    (
        "M15",
        "Fuel EV charging useful stops and attractions",
        "Points of interest and refueling stops",
        "R1",
        True,
    ),
    (
        "M16",
        "Routes GPX and navigation handoff",
        "GPX route sharing and navigation export",
        "R1",
        True,
    ),
    (
        "M17",
        "Ride recording and live group sharing",
        "Live telemetry and ride tracking",
        "R1",
        True,
    ),
    (
        "M18",
        "SOS trusted contacts and check-ins",
        "Emergency SOS alerts and safety contacts",
        "R1",
        True,
    ),
    (
        "M19",
        "Monthly achievements rankings and appeals",
        "Gamification points, leaderboards, appeals",
        "R1",
        True,
    ),
    (
        "M20",
        "Badges challenges rewards and referrals",
        "Challenges, badges, referral rewards",
        "R1",
        True,
    ),
    (
        "M21",
        "Maintenance documents and expiry reminders",
        "Service logs, insurance, document alerts",
        "R1",
        True,
    ),
    (
        "M22",
        "Gear accessories and motorcycle marketplace",
        "Marketplace and classifieds for gear/motorcycles",
        "R2",
        False,
    ),
    (
        "M23",
        "Motorcycle rentals handover and return",
        "Rental fleet operations and inspections",
        "R2",
        False,
    ),
    (
        "M24",
        "Garages and roadside service operations",
        "Workshop jobs and roadside assistance",
        "R1",
        True,
    ),
    (
        "M25",
        "Trip expenses splits and repayments",
        "Group ride expense sharing and settlements",
        "R2",
        False,
    ),
    (
        "M26",
        "Learning workshops and mentorship",
        "Riding schools, academies, certified trainers",
        "R1",
        True,
    ),
    (
        "M27",
        "Journals ride stories and albums",
        "Ride journals, memories, media albums",
        "R1",
        True,
    ),
    (
        "M28",
        "Quotes inventory bookings payments and refunds",
        "Booking engine, inventory, checkout and payments",
        "R2",
        False,
    ),
    (
        "M29",
        "Partner onboarding branches and operations",
        "Partner network operations and listings",
        "R1",
        True,
    ),
    ("M30", "Organizer operations and participants", "Event organizer operations desk", "R1", True),
    (
        "M31",
        "Administration trust and governance",
        "Staff console administration and moderation",
        "R1",
        True,
    ),
    (
        "M32",
        "Reports analytics and controlled exports",
        "Analytics, data reports, compliant exports",
        "R1",
        True,
    ),
    (
        "M33",
        "Notifications templates and delivery status",
        "Multi-channel notifications and delivery logs",
        "R1",
        True,
    ),
    (
        "M34",
        "Privacy consent data export and deletion",
        "GDPR/DPDP compliance, consent, deletion requests",
        "R1",
        True,
    ),
    (
        "M35",
        "AI itinerary and planning assistant",
        "Intelligent trip suggestions and routing AI",
        "R3",
        False,
    ),
    (
        "M36",
        "Offline maps downloads and route capability",
        "Vector map packages and offline turn calculation",
        "R3",
        False,
    ),
    (
        "M37",
        "Premium plans and purchase entitlements",
        "Subscription tiers and monetization features",
        "R3",
        False,
    ),
    (
        "M38",
        "Help support disputes and recovery cases",
        "Support tickets, dispute resolution, emergency care",
        "R1",
        True,
    ),
]

ORGANIZER_MODULE_CODES = [
    "M01",
    "M05",
    "M06",
    "M07",
    "M08",
    "M09",
    "M10",
    "M11",
    "M12",
    "M16",
    "M26",
    "M30",
    "M32",
    "M33",
    "M38",
]

PARTNER_MODULE_CODES = [
    "M01",
    "M05",
    "M13",
    "M14",
    "M15",
    "M29",
    "M32",
    "M33",
    "M38",
    # Category modules enabled on partner interface
    "M21",
    "M22",
    "M23",
    "M24",
    "M26",
]

STAFF_MODULE_CODES = [
    "M01",
    "M06",
    "M07",
    "M11",
    "M12",
    "M13",
    "M14",
    "M15",
    "M19",
    "M29",
    "M31",
    "M32",
    "M33",
    "M34",
    "M38",
]

PARTNER_CATEGORY_MAP = [
    ("cafe", "M13"),
    ("hotel_homestay", "M14"),
    ("hotel_homestay", "M15"),
    ("campsite", "M14"),
    ("campsite", "M15"),
    ("garage", "M21"),
    ("garage", "M24"),
    ("roadside", "M24"),
    ("rental", "M23"),
    ("gear", "M22"),
    ("dealer", "M22"),
    ("instructor_school", "M26"),
    ("fuel_charging", "M15"),
]


def upgrade() -> None:
    # 1. modules table
    op.create_table(
        "modules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("code", sa.String(10), unique=True, index=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("release", sa.String(10), nullable=False, server_default="R1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("release IN ('R1', 'R2', 'R3')", name="ck_modules_release_valid"),
    )

    # 2. interface_modules table (check constraint rejects rider_app)
    op.create_table(
        "interface_modules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("interface", sa.String(32), nullable=False),
        sa.Column(
            "module_id",
            UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("default_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("interface", "module_id", name="uq_interface_modules_interface_module"),
        sa.CheckConstraint(
            "interface IN ('organizer_portal', 'partner_portal', 'staff_console')",
            name="ck_interface_modules_web_only",
        ),
    )

    # 3. organization_modules table
    op.create_table(
        "organization_modules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "module_id",
            UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "set_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "set_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "organization_id", "module_id", name="uq_organization_modules_org_module"
        ),
    )

    # 4. partner_category_modules table
    op.create_table(
        "partner_category_modules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column(
            "module_id",
            UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("category", "module_id", name="uq_partner_category_modules_cat_module"),
        sa.CheckConstraint(
            "category IN ("
            "'cafe', 'hotel_homestay', 'campsite', 'garage', 'roadside', "
            "'rental', 'gear', 'dealer', 'instructor_school', 'fuel_charging'"
            ")",
            name="ck_partner_category_modules_valid",
        ),
    )

    # 5. role_module_access table
    op.create_table(
        "role_module_access",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "module_id",
            UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interface", sa.String(32), nullable=False),
        sa.Column("access", sa.String(20), nullable=False, server_default="view"),
        sa.UniqueConstraint(
            "role_id", "module_id", "interface", name="uq_role_module_access_role_mod_iface"
        ),
        sa.CheckConstraint(
            "access IN ('none', 'view', 'manage')", name="ck_role_module_access_valid"
        ),
        sa.CheckConstraint(
            "interface IN ('organizer_portal', 'partner_portal', 'staff_console')",
            name="ck_role_module_access_web_only",
        ),
    )

    # 6. organization_categories table (approved partner categories)
    op.create_table(
        "organization_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("approval_state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "approved_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "organization_id", "category", name="uq_organization_categories_org_cat"
        ),
        sa.CheckConstraint(
            "category IN ("
            "'cafe', 'hotel_homestay', 'campsite', 'garage', 'roadside', "
            "'rental', 'gear', 'dealer', 'instructor_school', 'fuel_charging'"
            ")",
            name="ck_org_cat_category_valid",
        ),
        sa.CheckConstraint(
            "approval_state IN ('pending', 'approved', 'rejected')",
            name="ck_org_cat_approval_state_valid",
        ),
    )

    # 7. Seed M01..M38 modules using op.bulk_insert
    modules_tbl = sa.table(
        "modules",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("release", sa.String),
        sa.column("is_active", sa.Boolean),
    )

    module_ids = {}
    mod_rows = []
    for code, name, desc, release, is_active in MODULES_DATA:
        m_id = uuid.uuid4()
        module_ids[code] = m_id
        mod_rows.append(
            {
                "id": m_id,
                "code": code,
                "name": name,
                "description": desc,
                "release": release,
                "is_active": is_active,
            }
        )
    op.bulk_insert(modules_tbl, mod_rows)

    # 8. Seed interface_modules
    iface_tbl = sa.table(
        "interface_modules",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("interface", sa.String),
        sa.column("module_id", UUID(as_uuid=True)),
        sa.column("display_order", sa.Integer),
        sa.column("default_enabled", sa.Boolean),
    )

    iface_rows = []

    def add_iface_rows(interface_name: str, codes: list[str]) -> None:
        for order, code in enumerate(codes, start=1):
            m_id = module_ids.get(code)
            if m_id:
                iface_rows.append(
                    {
                        "id": uuid.uuid4(),
                        "interface": interface_name,
                        "module_id": m_id,
                        "display_order": order * 10,
                        "default_enabled": True,
                    }
                )

    add_iface_rows("organizer_portal", ORGANIZER_MODULE_CODES)
    add_iface_rows("partner_portal", PARTNER_MODULE_CODES)
    add_iface_rows("staff_console", STAFF_MODULE_CODES)
    op.bulk_insert(iface_tbl, iface_rows)

    # 9. Seed partner_category_modules
    pcat_tbl = sa.table(
        "partner_category_modules",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("category", sa.String),
        sa.column("module_id", UUID(as_uuid=True)),
    )
    pcat_rows = []
    for cat, code in PARTNER_CATEGORY_MAP:
        m_id = module_ids.get(code)
        if m_id:
            pcat_rows.append(
                {
                    "id": uuid.uuid4(),
                    "category": cat,
                    "module_id": m_id,
                }
            )
    op.bulk_insert(pcat_tbl, pcat_rows)

    # 10. Seed permissions: module.configure and module.toggle_own
    perm_tbl = sa.table(
        "permissions",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("resource_type", sa.String),
        sa.column("action", sa.String),
        sa.column("sensitivity", sa.String),
        sa.column("description", sa.String),
    )
    perm_cfg_id = uuid.uuid4()
    perm_toggle_id = uuid.uuid4()
    op.bulk_insert(
        perm_tbl,
        [
            {
                "id": perm_cfg_id,
                "code": "module.configure",
                "resource_type": "module",
                "action": "configure",
                "sensitivity": "high",
                "description": "Configure interface and organization module settings",
            },
            {
                "id": perm_toggle_id,
                "code": "module.toggle_own",
                "resource_type": "module",
                "action": "toggle_own",
                "sensitivity": "normal",
                "description": "Toggle allowed modules for own organization",
            },
        ],
    )

    # Assign permissions to roles
    role_perm_tbl = sa.table(
        "role_permissions",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("role_id", UUID(as_uuid=True)),
        sa.column("permission_id", UUID(as_uuid=True)),
    )

    conn = op.get_bind()
    role_res = conn.execute(sa.text("SELECT id, code FROM roles")).all()
    roles_map = {row[1]: row[0] for row in role_res}

    role_perm_rows = []
    for r_code in ("RL13", "RL14"):
        r_id = roles_map.get(r_code)
        if r_id:
            role_perm_rows.append(
                {"id": uuid.uuid4(), "role_id": r_id, "permission_id": perm_cfg_id}
            )

    for r_code in ("RL02", "RL07"):
        r_id = roles_map.get(r_code)
        if r_id:
            role_perm_rows.append(
                {"id": uuid.uuid4(), "role_id": r_id, "permission_id": perm_toggle_id}
            )

    if role_perm_rows:
        op.bulk_insert(role_perm_tbl, role_perm_rows)

    # 11. Seed default role_module_access
    rma_tbl = sa.table(
        "role_module_access",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("role_id", UUID(as_uuid=True)),
        sa.column("module_id", UUID(as_uuid=True)),
        sa.column("interface", sa.String),
        sa.column("access", sa.String),
    )
    rma_rows = []

    def add_rma(role_code: str, interface: str, mapping: dict[str, str]) -> None:
        r_id = roles_map.get(role_code)
        if not r_id:
            return
        for m_code, access in mapping.items():
            m_id = module_ids.get(m_code)
            if m_id:
                rma_rows.append(
                    {
                        "id": uuid.uuid4(),
                        "role_id": r_id,
                        "module_id": m_id,
                        "interface": interface,
                        "access": access,
                    }
                )

    add_rma("RL02", "organizer_portal", {c: "manage" for c in ORGANIZER_MODULE_CODES})
    add_rma(
        "RL03",
        "organizer_portal",
        {
            "M01": "view",
            "M05": "view",
            "M06": "view",
            "M07": "manage",
            "M08": "manage",
            "M09": "manage",
            "M10": "manage",
            "M16": "view",
            "M32": "view",
            "M33": "view",
            "M38": "view",
        },
    )
    add_rma(
        "RL04",
        "organizer_portal",
        {
            "M01": "view",
            "M05": "view",
            "M06": "view",
            "M09": "manage",
            "M10": "manage",
            "M16": "manage",
        },
    )
    add_rma("RL07", "partner_portal", {c: "manage" for c in PARTNER_MODULE_CODES})
    add_rma(
        "RL08",
        "partner_portal",
        {
            "M01": "view",
            "M05": "view",
            "M13": "manage",
            "M14": "manage",
            "M15": "manage",
            "M21": "manage",
            "M24": "manage",
            "M29": "view",
            "M38": "view",
        },
    )
    add_rma("RL13", "staff_console", {c: "manage" for c in STAFF_MODULE_CODES})
    add_rma("RL14", "staff_console", {c: "manage" for c in STAFF_MODULE_CODES})
    add_rma(
        "RL10",
        "staff_console",
        {
            "M01": "view",
            "M06": "view",
            "M07": "view",
            "M38": "manage",
            "M12": "none",
            "M31": "none",
        },
    )
    add_rma(
        "RL11",
        "staff_console",
        {
            "M01": "view",
            "M06": "view",
            "M07": "manage",
            "M11": "manage",
            "M31": "manage",
            "M38": "manage",
        },
    )
    add_rma(
        "RL12", "staff_console", {"M01": "view", "M12": "manage", "M32": "manage", "M31": "view"}
    )

    if rma_rows:
        op.bulk_insert(rma_tbl, rma_rows)


def downgrade() -> None:
    conn = op.get_bind()

    # Delete seeded role_permissions and permissions
    conn.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN ("
            "SELECT id FROM permissions WHERE code IN ('module.configure', 'module.toggle_own')"
            ")"
        )
    )
    conn.execute(
        sa.text("DELETE FROM permissions WHERE code IN ('module.configure', 'module.toggle_own')")
    )

    # Drop tables in reverse order
    op.drop_table("organization_categories")
    op.drop_table("role_module_access")
    op.drop_table("partner_category_modules")
    op.drop_table("organization_modules")
    op.drop_table("interface_modules")
    op.drop_table("modules")
