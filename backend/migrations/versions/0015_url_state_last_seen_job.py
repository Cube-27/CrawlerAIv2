"""The listing diff (SPEC-11 §4.5, PR 4): `url_state.last_seen_job_id`, the crawl whose listing last held the URL. A
URL no listing has held keeps NULL and is never counted missing.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("url_state", sa.Column("last_seen_job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_url_state_last_seen_job_id_job", "url_state", "job", ["last_seen_job_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_url_state_last_seen_job_id_job", "url_state", type_="foreignkey")
    op.drop_column("url_state", "last_seen_job_id")
