"""job.pinned: what a records job's pages run with, pinned when it was submitted (INV-28, SPEC-10 PR 2): the precedence
orders and calibration, and per host the active config. NULL for a job that extracts no records.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("pinned", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("job", "pinned")
