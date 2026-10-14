"""Run events over SSE and completion webhooks (SPEC-10 §4.2, PR 6): `job.api_key_id`, whose webhook secret signs the
job's webhook; `webhook_delivery`, one row per ended job with a webhook; and the indexes of the event stream's and the
task events' queries (`job_event (job_id, id)`, `extraction (url_task_id)`).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("api_key_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_job_api_key_id_api_key", "job", "api_key", ["api_key_id"], ["id"])
    op.create_table(
        "webhook_delivery",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')", name="status"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], name="fk_webhook_delivery_job_id_job"),
        sa.PrimaryKeyConstraint("job_id", name="pk_webhook_delivery"),
    )
    op.create_index(
        "ix_webhook_delivery_next_attempt_at",
        "webhook_delivery",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_job_event_job_id_id", "job_event", ["job_id", "id"])
    op.create_index("ix_extraction_url_task_id", "extraction", ["url_task_id"])


def downgrade() -> None:
    op.drop_index("ix_extraction_url_task_id", table_name="extraction")
    op.drop_index("ix_job_event_job_id_id", table_name="job_event")
    op.drop_index("ix_webhook_delivery_next_attempt_at", table_name="webhook_delivery")
    op.drop_table("webhook_delivery")
    op.drop_constraint("fk_job_api_key_id_api_key", "job", type_="foreignkey")
    op.drop_column("job", "api_key_id")
