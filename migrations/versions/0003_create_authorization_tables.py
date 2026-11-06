"""Create authorization, roles, permissions, organizations, memberships, and audit tables.

Revision ID: 0003_authz_tables
Revises: 0002_auth_tables
Create Date: 2026-11-06 09:40:00

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0003_authz_tables"
down_revision: Union[str, None] = "0002_auth_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLES_DATA = [
    ("RL01", "Rider", "personal", "Individual motorcycle rider with personal workspace"),
    ("RL02", "Club owner", "club", "Founder and executive head of a motorcycle club"),
    ("RL03", "Club moderator", "club", "Operational officer managing club rides and members"),
    (
        "RL04",
        "Ride captain/marshal",
        "activity",
        "Designated safety captain/marshal for specific rides",
    ),
    (
        "RL05",
        "Event organizer",
        "organization",
        "Commercial or non-profit motorcycle event organizer",
    ),
    ("RL06", "Tour operator", "organization", "Commercial motorcycling tour company and guides"),
    (
        "RL07",
        "Business partner owner",
        "organization",
        "Dealer, rental garage, gear brand, or workshop owner",
    ),
    (
        "RL08",
        "Partner staff",
        "organization",
        "Operational staff member of an approved commercial partner",
    ),
    ("RL09", "Instructor", "activity", "Certified riding safety or track coach"),
    ("RL10", "Support agent", "platform", "Customer service and rider support team member"),
    ("RL11", "Trust moderator", "platform", "Trust, safety, content review and dispute moderator"),
    (
        "RL12",
        "Finance operator",
        "platform",
        "Platform financial reconciliation and accounting staff",
    ),
    ("RL13", "Platform administrator", "platform", "Platform operations and ecosystem manager"),
    (
        "RL14",
        "Super Admin",
        "platform",
        "Executive platform administrator with full governance access",
    ),
]

PERMISSIONS_DATA = [
    ("profile.read_own", "profile", "read_own", "standard", "View personal rider profile"),
    (
        "profile.edit_own",
        "profile",
        "edit_own",
        "standard",
        "Update personal rider profile and garage",
    ),
    (
        "club.create_request",
        "club",
        "create_request",
        "standard",
        "Submit application to form a new club",
    ),
    ("club.manage", "club", "manage", "sensitive", "Manage club settings, branding and rules"),
    (
        "club.member_approve",
        "club",
        "member_approve",
        "standard",
        "Approve or reject rider club join requests",
    ),
    ("activity.create", "activity", "create", "standard", "Draft and create new rides and events"),
    (
        "activity.publish",
        "activity",
        "publish",
        "standard",
        "Publish scheduled ride to public / members",
    ),
    (
        "activity.checkin",
        "activity",
        "checkin",
        "standard",
        "Verify and check in participants via QR or manual",
    ),
    ("activity.close", "activity", "close", "standard", "Complete, debrief and close a ride"),
    (
        "listing.edit",
        "listing",
        "edit",
        "standard",
        "Create and edit commercial marketplace listings",
    ),
    (
        "report.resolve",
        "report",
        "resolve",
        "sensitive",
        "Review and resolve user safety/content reports",
    ),
    ("role.assign", "role", "assign", "sensitive", "Assign or revoke roles within organization"),
    ("audit.read", "audit", "read", "sensitive", "Inspect security and compliance audit logs"),
    (
        "application.review",
        "application",
        "review",
        "critical",
        "Review and approve organization applications",
    ),
    ("application.create", "application", "create", "standard", "Submit official application"),
    (
        "application.view_own",
        "application",
        "view_own",
        "standard",
        "View status of own applications",
    ),
    (
        "organization.manage",
        "organization",
        "manage",
        "sensitive",
        "Manage organizational details and staff",
    ),
    ("invitation.create", "invitation", "create", "standard", "Invite users to join organization"),
    ("invitation.manage", "invitation", "manage", "standard", "Manage pending role invitations"),
    ("workspace.switch", "workspace", "switch", "standard", "Switch active operational workspace"),
]

ROLE_PERMISSIONS_MAPPING = {
    "RL01": [
        "profile.read_own",
        "profile.edit_own",
        "club.create_request",
        "application.create",
        "application.view_own",
        "workspace.switch",
    ],
    "RL02": [
        "profile.read_own",
        "profile.edit_own",
        "club.manage",
        "club.member_approve",
        "activity.create",
        "activity.publish",
        "activity.checkin",
        "activity.close",
        "role.assign",
        "invitation.create",
        "invitation.manage",
        "organization.manage",
        "workspace.switch",
    ],
    "RL03": [
        "profile.read_own",
        "club.manage",
        "club.member_approve",
        "activity.create",
        "activity.publish",
        "activity.checkin",
        "workspace.switch",
    ],
    "RL04": ["activity.checkin", "workspace.switch"],
    "RL05": [
        "activity.create",
        "activity.publish",
        "activity.checkin",
        "activity.close",
        "organization.manage",
        "invitation.create",
        "workspace.switch",
    ],
    "RL06": [
        "activity.create",
        "activity.publish",
        "activity.checkin",
        "activity.close",
        "organization.manage",
        "invitation.create",
        "workspace.switch",
    ],
    "RL07": [
        "listing.edit",
        "organization.manage",
        "invitation.create",
        "role.assign",
        "workspace.switch",
    ],
    "RL08": ["listing.edit", "workspace.switch"],
    "RL09": ["activity.checkin", "workspace.switch"],
    "RL10": ["audit.read", "workspace.switch"],
    "RL11": ["report.resolve", "audit.read", "workspace.switch"],
    "RL12": ["audit.read", "workspace.switch"],
    "RL13": [p[0] for p in PERMISSIONS_DATA],
    "RL14": [p[0] for p in PERMISSIONS_DATA],
}


def upgrade() -> None:
    # 1. roles table
    op.create_table(
        "roles",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("code", sa.String(32), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_roles_code", "roles", ["code"])
    op.create_index("ix_roles_scope_type", "roles", ["scope_type"])

    # 2. permissions table
    op.create_table(
        "permissions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("sensitivity", sa.String(32), server_default="standard", nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"])
    op.create_index("ix_permissions_resource_type", "permissions", ["resource_type"])

    # 3. role_permissions table
    op.create_table(
        "role_permissions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "permission_id",
            UUID(as_uuid=True),
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conditions", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"])

    # 4. organizations table
    op.create_table(
        "organizations",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("approval_state", sa.String(32), server_default="draft", nullable=False),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_organizations_type", "organizations", ["type"])
    op.create_index("ix_organizations_approval_state", "organizations", ["approval_state"])

    # 5. organization_memberships table
    op.create_table(
        "organization_memberships",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("branch_ids", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "organization_id", "role_id", name="uq_user_org_role_membership"
        ),
    )
    op.create_index("ix_org_memberships_user_id", "organization_memberships", ["user_id"])
    op.create_index("ix_org_memberships_org_id", "organization_memberships", ["organization_id"])
    op.create_index("ix_org_memberships_status", "organization_memberships", ["status"])

    # 6. club_memberships table
    op.create_table(
        "club_memberships",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("club_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), server_default="member", nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.UniqueConstraint("club_id", "user_id", name="uq_club_user_membership"),
    )
    op.create_index("ix_club_memberships_club_id", "club_memberships", ["club_id"])
    op.create_index("ix_club_memberships_user_id", "club_memberships", ["user_id"])

    # 7. activity_assignments table
    op.create_table(
        "activity_assignments",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("activity_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("duties", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_activity_assignments_activity_id", "activity_assignments", ["activity_id"])
    op.create_index("ix_activity_assignments_user_id", "activity_assignments", ["user_id"])

    # 8. role_invitations table
    op.create_table(
        "role_invitations",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "inviter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipient_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("recipient_contact", sa.String(100), nullable=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_role_invitations_token_hash", "role_invitations", ["token_hash"])
    op.create_index("ix_role_invitations_org_id", "role_invitations", ["organization_id"])

    # 9. applications table
    op.create_table(
        "applications",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "applicant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="submitted", nullable=False),
        sa.Column("payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "reviewer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_applications_applicant_id", "applications", ["applicant_id"])
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_index("ix_applications_kind", "applications", ["kind"])

    # 10. approval_requests table
    op.create_table(
        "approval_requests",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column(
            "requester_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("required_checker_role", sa.String(32), nullable=False),
        sa.Column("object_ref", sa.String(100), nullable=False),
        sa.Column("object_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("decision", sa.String(32), server_default="pending", nullable=False),
        sa.Column(
            "decided_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_approval_requests_requester_id", "approval_requests", ["requester_id"])
    op.create_index("ix_approval_requests_action", "approval_requests", ["action"])

    # 11. audit_events table
    op.create_table(
        "audit_events",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column("active_context", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("target", sa.String(100), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("request_id", sa.String(100), server_default="", nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])

    # 12. Create trigger to make audit_events strictly append-only (forbid UPDATE and DELETE)
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_audit_events_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is an append-only log. UPDATE and DELETE are prohibited.';
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER audit_events_immutable_trigger
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION forbid_audit_events_mutation();
    """)

    # 13. Seed Roles and Permissions
    roles_table = sa.table(
        "roles",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("scope_type", sa.String),
        sa.column("description", sa.String),
    )
    role_id_map = {}
    for code, name, scope_type, desc in ROLES_DATA:
        r_id = uuid.uuid4()
        role_id_map[code] = r_id
        op.bulk_insert(
            roles_table,
            [
                {
                    "id": r_id,
                    "code": code,
                    "name": name,
                    "scope_type": scope_type,
                    "description": desc,
                }
            ],
        )

    permissions_table = sa.table(
        "permissions",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("resource_type", sa.String),
        sa.column("action", sa.String),
        sa.column("sensitivity", sa.String),
        sa.column("description", sa.String),
    )
    perm_id_map = {}
    for code, r_type, action, sens, desc in PERMISSIONS_DATA:
        p_id = uuid.uuid4()
        perm_id_map[code] = p_id
        op.bulk_insert(
            permissions_table,
            [
                {
                    "id": p_id,
                    "code": code,
                    "resource_type": r_type,
                    "action": action,
                    "sensitivity": sens,
                    "description": desc,
                }
            ],
        )

    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("role_id", UUID(as_uuid=True)),
        sa.column("permission_id", UUID(as_uuid=True)),
        sa.column("conditions", JSONB),
    )
    rp_rows = []
    for r_code, p_codes in ROLE_PERMISSIONS_MAPPING.items():
        r_id = role_id_map.get(r_code)
        if not r_id:
            continue
        for p_code in p_codes:
            p_id = perm_id_map.get(p_code)
            if p_id:
                rp_rows.append(
                    {"id": uuid.uuid4(), "role_id": r_id, "permission_id": p_id, "conditions": {}}
                )

    if rp_rows:
        op.bulk_insert(role_permissions_table, rp_rows)


def downgrade() -> None:
    # 1. Remove trigger and trigger function
    op.execute("DROP TRIGGER IF EXISTS audit_events_immutable_trigger ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS forbid_audit_events_mutation();")

    # 2. Drop tables in reverse order
    op.drop_table("audit_events")
    op.drop_table("approval_requests")
    op.drop_table("applications")
    op.drop_table("role_invitations")
    op.drop_table("activity_assignments")
    op.drop_table("club_memberships")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
