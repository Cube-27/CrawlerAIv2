"""extraction_config.drift_window: per field, whether a step matched and the value was valid on each of the config's
last pages (SPEC-08 §4.9, PR 9).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extraction_config",
        sa.Column("drift_window", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("extraction_config", "drift_window")
