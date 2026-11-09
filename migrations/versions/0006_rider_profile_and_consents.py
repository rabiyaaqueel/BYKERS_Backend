"""0006: Create Rider Profile, Onboarding, Consents and Media Assets tables.

Revision ID: 0006_rider_profile_and_consents
Revises: 0005_module_registry
Create Date: 2026-11-06 13:30:00.000000
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0006_rider_profile_and_consents"
down_revision = "0005_module_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. cities table
    op.create_table(
        "cities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(100), nullable=False, index=True),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("country", sa.String(100), nullable=False, server_default="India"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 2. interests table
    op.create_table(
        "interests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("name_te", sa.String(100), nullable=False),
        sa.Column("name_hi", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 3. user_interests join table
    op.create_table(
        "user_interests",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "interest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # 4. notice_versions table
    op.create_table(
        "notice_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("kind", sa.String(30), nullable=False),  # terms, privacy
        sa.Column("version", sa.String(20), nullable=False),  # v1.0
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text_url", sa.String(500), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index(
        "ix_notice_versions_kind_version", "notice_versions", ["kind", "version"], unique=True
    )

    # 5. consent_events table (append-only ledger)
    op.create_table(
        "consent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("purpose", sa.String(50), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),  # granted, withdrawn
        sa.Column("notice_version", sa.String(20), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_consent_events_user_purpose_time",
        "consent_events",
        ["user_id", "purpose", "occurred_at"],
    )

    # 6. media_assets table
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("purpose", sa.String(50), nullable=False),  # profile_photo, banner, etc.
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column(
            "scan_state", sa.String(30), nullable=False, server_default="pending"
        ),  # pending, clean, rejected
        sa.Column("derivative_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
    )

    # 7. profiles table
    op.create_table(
        "profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column(
            "photo_media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "home_city_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("experience", sa.String(30), nullable=False, server_default="beginner"),
        sa.Column("visibility", sa.String(30), nullable=False, server_default="all_riders"),
        sa.Column(
            "languages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
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
    )

    # 8. private_details table
    op.create_table(
        "private_details",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("legal_name", sa.String(150), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
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
    )

    # 9. Seed Initial Data
    # 9a. Seed Cities
    cities_table = sa.table(
        "cities",
        sa.column("id", postgresql.UUID),
        sa.column("name", sa.String),
        sa.column("state", sa.String),
        sa.column("country", sa.String),
        sa.column("active", sa.Boolean),
    )
    seed_cities = [
        {
            "id": uuid.uuid4(),
            "name": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "name": "Mumbai",
            "state": "Maharashtra",
            "country": "India",
            "active": True,
        },
        {"id": uuid.uuid4(), "name": "Delhi", "state": "Delhi", "country": "India", "active": True},
        {
            "id": uuid.uuid4(),
            "name": "Hyderabad",
            "state": "Telangana",
            "country": "India",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "name": "Pune",
            "state": "Maharashtra",
            "country": "India",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "name": "Chennai",
            "state": "Tamil Nadu",
            "country": "India",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "name": "Jaipur",
            "state": "Rajasthan",
            "country": "India",
            "active": True,
        },
        {"id": uuid.uuid4(), "name": "Goa", "state": "Goa", "country": "India", "active": True},
        {
            "id": uuid.uuid4(),
            "name": "Chandigarh",
            "state": "Punjab",
            "country": "India",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "name": "Kolkata",
            "state": "West Bengal",
            "country": "India",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "name": "Dehradun",
            "state": "Uttarakhand",
            "country": "India",
            "active": True,
        },
        {"id": uuid.uuid4(), "name": "Leh", "state": "Ladakh", "country": "India", "active": True},
    ]
    op.bulk_insert(cities_table, seed_cities)

    # 9b. Seed Interests
    interests_table = sa.table(
        "interests",
        sa.column("id", postgresql.UUID),
        sa.column("code", sa.String),
        sa.column("name_en", sa.String),
        sa.column("name_te", sa.String),
        sa.column("name_hi", sa.String),
        sa.column("active", sa.Boolean),
    )
    seed_interests = [
        {
            "id": uuid.uuid4(),
            "code": "cruising",
            "name_en": "Cruising & Highway",
            "name_te": "క్రూజింగ్ మరియు హైవే",
            "name_hi": "क्रूज़िंग और हाईवे",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "code": "touring",
            "name_en": "Long Distance Touring",
            "name_te": "లాంగ్ డిస్టెన్స్ టూరింగ్",
            "name_hi": "लंबी दूरी की यात्रा",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "code": "track_racing",
            "name_en": "Track & Racing",
            "name_te": "ట్రాక్ మరియు రేసింగ్",
            "name_hi": "ट्रैक और रेसिंग",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "code": "off_roading",
            "name_en": "Off-Roading & Trail",
            "name_te": "ఆఫ్-రోడింగ్ మరియు ట్రైల్",
            "name_hi": "ऑफ-रोडिंग और ट्रेल",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "code": "vintage",
            "name_en": "Vintage & Classics",
            "name_te": "వింటేజ్ మరియు క్లాసిక్స్",
            "name_hi": "विंटेज और क्लासिक्स",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "code": "maintenance",
            "name_en": "DIY Mechanics & Maintenance",
            "name_te": "మెకానిక్స్ మరియు నిర్వహణ",
            "name_hi": "मैकेनिक्स और मेंटेनेंस",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "code": "safety_gear",
            "name_en": "Riding Gear & Safety",
            "name_te": "రైడింగ్ గేర్ మరియు భద్రత",
            "name_hi": "राइडिंग गियर और सुरक्षा",
            "active": True,
        },
        {
            "id": uuid.uuid4(),
            "code": "breakfast_rides",
            "name_en": "Weekend Breakfast Rides",
            "name_te": "వీకెండ్ బ్రేక్‌ఫాస్ట్ రైడ్స్",
            "name_hi": "वीकेंड ब्रेकफास्ट राइड्स",
            "active": True,
        },
    ]
    op.bulk_insert(interests_table, seed_interests)

    # 9c. Seed Notice Versions
    now = datetime.now(timezone.utc)
    notices_table = sa.table(
        "notice_versions",
        sa.column("id", postgresql.UUID),
        sa.column("kind", sa.String),
        sa.column("version", sa.String),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("text_url", sa.String),
        sa.column("is_current", sa.Boolean),
    )
    seed_notices = [
        {
            "id": uuid.uuid4(),
            "kind": "terms",
            "version": "v1.0",
            "published_at": now,
            "text_url": "https://bykers.app/legal/terms-v1.0.html",
            "is_current": True,
        },
        {
            "id": uuid.uuid4(),
            "kind": "privacy",
            "version": "v1.0",
            "published_at": now,
            "text_url": "https://bykers.app/legal/privacy-v1.0.html",
            "is_current": True,
        },
    ]
    op.bulk_insert(notices_table, seed_notices)


def downgrade() -> None:
    op.drop_table("private_details")
    op.drop_table("profiles")
    op.drop_table("media_assets")
    op.drop_table("consent_events")
    op.drop_table("notice_versions")
    op.drop_table("user_interests")
    op.drop_table("interests")
    op.drop_table("cities")
