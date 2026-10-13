"""Private eval database (SPEC-03 PR 1): eval_capture, eval_page, eval_run and eval_llm_cache for hidden and fresh
cases. Run by the custodian with `alembic -n private upgrade head` (C1).

Revision ID: p0001
Revises:
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_capture",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("block_class", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("html_sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("fetch_policy", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.CheckConstraint(
            "block_class IN ('ok', 'blocked', 'shell', 'not_found', 'error')", name=op.f("ck_eval_capture_block_class")
        ),
        sa.CheckConstraint(
            "category IN ('platform_store', 'custom_store', 'api_backed', 'job_board', 'mixed')",
            name=op.f("ck_eval_capture_category"),
        ),
        sa.CheckConstraint("method IN ('http', 'browser', 'api')", name=op.f("ck_eval_capture_method")),
        sa.CheckConstraint("split IN ('hidden', 'fresh')", name=op.f("ck_eval_capture_split")),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_eval_capture_duration_ms_non_negative")),
        sa.CheckConstraint("host = lower(host)", name=op.f("ck_eval_capture_host_lowercase")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_eval_capture_size_bytes_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_capture")),
        sa.UniqueConstraint("id", "split", name=op.f("uq_eval_capture_id_split")),
        sa.UniqueConstraint("object_key", name=op.f("uq_eval_capture_object_key")),
    )
    op.create_table(
        "eval_llm_cache",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("key ~ '^[0-9a-f]{64}$'", name=op.f("ck_eval_llm_cache_key_sha256")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_eval_llm_cache_size_bytes_non_negative")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_eval_llm_cache")),
        sa.UniqueConstraint("object_key", name=op.f("uq_eval_llm_cache_object_key")),
    )
    op.create_table(
        "eval_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("git_sha", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("split IN ('hidden', 'fresh')", name=op.f("ck_eval_run_split")),
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
        sa.CheckConstraint("split IN ('hidden', 'fresh')", name=op.f("ck_eval_page_split")),
        sa.CheckConstraint(
            "checker IS NULL OR (labeler IS NOT NULL AND checker <> labeler)", name=op.f("ck_eval_page_two_people")
        ),
        sa.ForeignKeyConstraint(
            ["capture_id", "split"],
            ["eval_capture.id", "eval_capture.split"],
            name=op.f("fk_eval_page_capture_id_eval_capture"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_page")),
    )
    op.create_index(op.f("ix_eval_page_capture_id"), "eval_page", ["capture_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_eval_page_capture_id"), table_name="eval_page")
    op.drop_table("eval_page")
    op.drop_table("eval_run")
    op.drop_table("eval_llm_cache")
    op.drop_table("eval_capture")
