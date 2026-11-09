"""0007: Motorcycle Garage, Bikes, Maintenance, Documents, and Reminders.

Revision ID: 0007_motorcycle_garage
Revises: 0006_rider_profile_and_consents
Create Date: 2026-11-06 17:00:00.000000
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0007_motorcycle_garage"
down_revision = "0006_rider_profile_and_consents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. bikes table
    op.create_table(
        "bikes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("make", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("powertrain", sa.String(20), nullable=False, server_default="petrol"),
        sa.Column("nickname", sa.String(100), nullable=True),
        sa.Column("odometer_km", sa.Integer(), nullable=True),
        sa.Column("registration_encrypted", sa.Text(), nullable=True),
        sa.Column("registration_last4", sa.String(4), nullable=True),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "powertrain IN ('petrol', 'electric', 'hybrid')", name="ck_bikes_powertrain"
        ),
        sa.CheckConstraint("year >= 1950", name="ck_bikes_year_min"),
        sa.CheckConstraint(
            "odometer_km IS NULL OR (odometer_km >= 0 AND odometer_km <= 999999)",
            name="ck_bikes_odometer_range",
        ),
    )

    # Partial unique index: only one active preferred bike per user
    op.create_index(
        "uq_bikes_user_preferred",
        "bikes",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_preferred IS TRUE AND archived_at IS NULL"),
    )

    # 2. bike_photos table
    op.create_table(
        "bike_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "bike_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bikes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("bike_id", "display_order", name="uq_bike_photos_order"),
    )

    # 3. maintenance_records table
    op.create_table(
        "maintenance_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "bike_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bikes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("service_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("odometer_km", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "invoice_media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("odometer_source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("next_due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_km", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "odometer_source IN ('manual', 'imported')", name="ck_maintenance_source"
        ),
    )

    # 4. bike_documents table
    op.create_table(
        "bike_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "bike_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bikes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("expires_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "private_media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sharing_policy", sa.String(50), nullable=False, server_default="private"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "type IN ('insurance', 'registration', 'pollution', 'licence')",
            name="ck_bike_documents_type",
        ),
        sa.CheckConstraint(
            "sharing_policy IN ('private', 'shared_for_transaction')",
            name="ck_bike_documents_sharing",
        ),
    )

    # 5. reminders table
    op.create_table(
        "reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "bike_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bikes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("due_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cycle_key", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("reminders")
    op.drop_table("bike_documents")
    op.drop_table("maintenance_records")
    op.drop_table("bike_photos")
    op.drop_index("uq_bikes_user_preferred", table_name="bikes")
    op.drop_table("bikes")
