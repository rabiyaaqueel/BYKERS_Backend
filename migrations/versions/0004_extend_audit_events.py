"""Extend audit_events table with ip_hash and metadata columns.

Revision ID: 0004_extend_audit_events
Revises: 0003_authz_tables
Create Date: 2026-11-06 10:45:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_extend_audit_events"
down_revision: Union[str, None] = "0003_authz_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add ip_hash (nullable string for hashed client IP)
    op.add_column(
        "audit_events",
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
    )
    # Add metadata (JSONB object defaulting to empty dict)
    op.add_column(
        "audit_events",
        sa.Column(
            "metadata",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("audit_events", "metadata")
    op.drop_column("audit_events", "ip_hash")
