"""usage_event index by job, for the estimated LLM cost on a job's summary (SPEC-06 §4.8, SPEC-10 PR 10).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_usage_event_job_id_id", "usage_event", ["job_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_usage_event_job_id_id", table_name="usage_event")
