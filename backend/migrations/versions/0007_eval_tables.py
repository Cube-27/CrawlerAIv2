"""Dev eval tables: eval_page and eval_run (SPEC-03 PR 1). Hidden and fresh cases live in the private database,
whose revisions are in `private_versions` (C1).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The target of eval_page's (schema_id, schema_name) foreign key.
    op.create_unique_constraint(op.f("uq_schema_def_id_name"), "schema_def", ["id", "name"])
    op.create_table(
        "eval_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("git_sha", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("split = 'dev'", name=op.f("ck_eval_run_split")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_run")),
    )
    op.create_table(
        "eval_page",
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.Column("schema_name", sa.Text(), nullable=False),
        sa.Column("page_kind", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("labels", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("labeler", sa.Text(), nullable=True),
        sa.Column("checker", sa.Text(), nullable=True),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "category IN ('platform_store', 'custom_store', 'api_backed', 'job_board', 'mixed')",
            name=op.f("ck_eval_page_category"),
        ),
        sa.CheckConstraint("page_kind IN ('detail', 'listing')", name=op.f("ck_eval_page_page_kind")),
        sa.CheckConstraint("split = 'dev'", name=op.f("ck_eval_page_split")),
        sa.CheckConstraint(
            "checker IS NULL OR (labeler IS NOT NULL AND checker <> labeler)", name=op.f("ck_eval_page_two_people")
        ),
        sa.ForeignKeyConstraint(["capture_id"], ["capture.id"], name=op.f("fk_eval_page_capture_id_capture")),
        sa.ForeignKeyConstraint(
            ["schema_id", "schema_name"],
            ["schema_def.id", "schema_def.name"],
            name=op.f("fk_eval_page_schema_id_schema_def"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_page")),
    )
    op.create_index(op.f("ix_eval_page_capture_id"), "eval_page", ["capture_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_eval_page_capture_id"), table_name="eval_page")
    op.drop_table("eval_page")
    op.drop_table("eval_run")
    op.drop_constraint(op.f("uq_schema_def_id_name"), "schema_def", type_="unique")
