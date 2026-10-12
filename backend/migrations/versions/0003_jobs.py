"""Jobs: job, url_task and job_event (SPEC-01 PR 2).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    project = sa.table("project", sa.column("id"))
    schema_def = sa.table("schema_def", sa.column("id"))
    job = op.create_table(
        "job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("usage", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_job"),
        sa.ForeignKeyConstraint(["project_id"], [project.c.id], name="fk_job_project_id_project"),
        sa.ForeignKeyConstraint(["schema_id"], [schema_def.c.id], name="fk_job_schema_id_schema_def"),
        sa.CheckConstraint(
            "kind IN ('scrape', 'batch_scrape', 'map', 'crawl', 'extract', 'learn')", name="ck_job_kind"
        ),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="ck_job_status"),
    )
    op.create_table(
        "url_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("page_kind", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("parent_task_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_url_task"),
        sa.ForeignKeyConstraint(["job_id"], [job.c.id], name="fk_url_task_job_id_job"),
        sa.CheckConstraint("page_kind IN ('detail', 'listing')", name="ck_url_task_page_kind"),
        sa.CheckConstraint("status IN ('queued', 'claimed', 'done', 'failed', 'cancelled')", name="ck_url_task_status"),
        sa.CheckConstraint(
            "outcome IN ('extracted', 'partial', 'unchanged', 'links_only', 'blocked', 'shell', 'not_found',"
            " 'no_match', 'failed')",
            name="ck_url_task_outcome",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_url_task_attempts_non_negative"),
        sa.CheckConstraint("depth >= 0", name="ck_url_task_depth_non_negative"),
    )
    op.create_foreign_key("fk_url_task_parent_task_id_url_task", "url_task", "url_task", ["parent_task_id"], ["id"])
    # The claim query (SPEC-01 §4.3) filters on status and next_attempt_at and orders by priority.
    op.create_index(
        "ix_url_task_status_next_attempt_at_priority", "url_task", ["status", "next_attempt_at", "priority"]
    )
    op.create_table(
        "job_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_job_event"),
        sa.ForeignKeyConstraint(["job_id"], [job.c.id], name="fk_job_event_job_id_job"),
    )


def downgrade() -> None:
    op.drop_table("job_event")
    op.drop_table("url_task")
    op.drop_table("job")
