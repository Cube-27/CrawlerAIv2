"""Core tables: project, api_key, site, schema_def, and the `default` project row (SPEC-01 PR 1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from crawlerai.core.ids import uuid7

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column[datetime]:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    project = op.create_table(
        "project",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_project"),
        sa.UniqueConstraint("name", name="uq_project_name"),
    )
    op.create_table(
        "api_key",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hashed_key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_secret", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_api_key"),
        sa.UniqueConstraint("hashed_key", name="uq_api_key_hashed_key"),
    )
    op.create_table(
        "site",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("fetch_method", sa.Text(), server_default=sa.text("'http'"), nullable=False),
        sa.Column("proxy_pool", sa.Text(), nullable=True),
        sa.Column("robots_snapshot", sa.Text(), nullable=True),
        sa.Column("crawl_delay_ms", sa.Integer(), nullable=True),
        _created_at(),
        sa.Column("fetch_method_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_site"),
        sa.ForeignKeyConstraint(["project_id"], [project.c.id], name="fk_site_project_id_project"),
        sa.UniqueConstraint("host", name="uq_site_host"),
        sa.CheckConstraint("host = lower(host)", name="ck_site_host_lowercase"),
        sa.CheckConstraint("fetch_method IN ('http', 'browser')", name="ck_site_fetch_method"),
        sa.CheckConstraint("crawl_delay_ms >= 0", name="ck_site_crawl_delay_ms_non_negative"),
    )
    op.create_table(
        "schema_def",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("page_kind", sa.Text(), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("required_groups", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_schema_def"),
        sa.UniqueConstraint("name", "version", name="uq_schema_def_name_version"),
        sa.CheckConstraint("version >= 1", name="ck_schema_def_version_positive"),
        sa.CheckConstraint("page_kind IN ('detail', 'listing')", name="ck_schema_def_page_kind"),
        sa.CheckConstraint("origin IN ('preset', 'user', 'prompt_draft')", name="ck_schema_def_origin"),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_schema_def_status"),
    )
    # One deployment, one organization: every site and job needs a project (SPEC-01 §4.2).
    op.bulk_insert(project, [{"id": uuid7(), "name": "default"}])


def downgrade() -> None:
    op.drop_table("schema_def")
    op.drop_table("site")
    op.drop_table("api_key")
    op.drop_table("project")
