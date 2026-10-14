"""`task_record`: the records each task's page stands for, including an unchanged entity's latest version, so that a
job's results list every page it extracted (SPEC-11 §4.2, §4.4; SPEC-10 §4.2). Existing records are linked to the
task of the extraction that stored them.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_record",
        sa.Column("url_task_id", sa.Uuid(), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["url_task_id"], ["url_task.id"], name="fk_task_record_url_task_id_url_task", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["record_id"], ["record.id"], name="fk_task_record_record_id_record", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("url_task_id", "record_id", name="pk_task_record"),
    )
    op.create_index("ix_task_record_record_id", "task_record", ["record_id"])
    op.execute(
        "INSERT INTO task_record (url_task_id, record_id) "
        "SELECT extraction.url_task_id, record.id FROM record JOIN extraction ON extraction.id = record.extraction_id"
    )


def downgrade() -> None:
    op.drop_index("ix_task_record_record_id", table_name="task_record")
    op.drop_table("task_record")
