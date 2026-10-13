"""capture (site_id, fetched_at): a site's recent captures, for `scrape`'s `max_age` reuse (SPEC-07 §4.4, PR 5).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_capture_site_id_fetched_at", "capture", ["site_id", "fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_capture_site_id_fetched_at", table_name="capture")
