"""Queue: one task per canonical URL per job (SPEC-01 PR 3).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A crawl enqueues each canonical URL once per job (SPEC-10 §4). The index, led by `job_id`, also serves the
    # per-job task counts that settle a job (`crawlerai.db.queue`).
    op.create_unique_constraint("uq_url_task_job_id_canonical_url", "url_task", ["job_id", "canonical_url"])


def downgrade() -> None:
    op.drop_constraint("uq_url_task_job_id_canonical_url", "url_task", type_="unique")
