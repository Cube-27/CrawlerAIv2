"""Captures and extraction results: capture, extraction, candidate, record, url_state, progressive_state and
extraction_config (SPEC-01 PR 6).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CHECK constraints take the short name: the naming convention of the target metadata adds `ck_<table>_`.
_PAGE_KIND = "page_kind IN ('detail', 'listing')"
_MODE = "mode IN ('adhoc', 'config')"


def upgrade() -> None:
    site = sa.table("site", sa.column("id"))
    schema_def = sa.table("schema_def", sa.column("id"), sa.column("version"))
    url_task = sa.table("url_task", sa.column("id"))
    job = sa.table("job", sa.column("id"))

    # The target of the (`schema_id`, `schema_version`) foreign keys below (ARCHITECTURE §5.2).
    op.create_unique_constraint("uq_schema_def_id_version", "schema_def", ["id", "version"])

    capture = op.create_table(
        "capture",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("block_class", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("html_sha256", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("fetch_policy", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_capture"),
        sa.ForeignKeyConstraint(["site_id"], [site.c.id], name="fk_capture_site_id_site"),
        sa.UniqueConstraint("object_key", name="uq_capture_object_key"),
        sa.CheckConstraint("method IN ('http', 'browser', 'api')", name="method"),
        sa.CheckConstraint("block_class IN ('ok', 'blocked', 'shell', 'not_found', 'error')", name="block_class"),
        sa.CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        sa.CheckConstraint("duration_ms >= 0", name="duration_ms_non_negative"),
    )
    # `expire_captures` deletes rows past `expires_at`; dev captures never expire and stay out of the index.
    op.create_index(
        "ix_capture_expires_at", "capture", ["expires_at"], postgresql_where=sa.text("expires_at IS NOT NULL")
    )

    # Captures expire after 30 days (ARCHITECTURE §15); tasks and extractions outlive them.
    op.create_foreign_key(
        "fk_url_task_capture_id_capture", "url_task", "capture", ["capture_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_url_task_capture_id", "url_task", ["capture_id"])

    extraction = op.create_table(
        "extraction",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url_task_id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=True),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_extraction"),
        sa.ForeignKeyConstraint(["url_task_id"], [url_task.c.id], name="fk_extraction_url_task_id_url_task"),
        sa.ForeignKeyConstraint(
            ["capture_id"], [capture.c.id], name="fk_extraction_capture_id_capture", ondelete="SET NULL"
        ),
        sa.CheckConstraint(_MODE, name="mode"),
        sa.CheckConstraint("llm_calls >= 0", name="llm_calls_non_negative"),
    )
    op.create_index("ix_extraction_capture_id", "extraction", ["capture_id"])

    op.create_table(
        "candidate",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("entity_ref", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("raw_value", postgresql.JSONB(), nullable=False),
        sa.Column("normalized_value", postgresql.JSONB(), nullable=True),
        sa.Column("normalize_status", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("independent", sa.Boolean(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("chosen", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_candidate"),
        sa.ForeignKeyConstraint(["extraction_id"], [extraction.c.id], name="fk_candidate_extraction_id_extraction"),
        sa.CheckConstraint("normalize_status IN ('ok', 'ambiguous', 'invalid')", name="normalize_status"),
        sa.CheckConstraint(
            "source_kind IN ('adapter', 'api', 'jsonld', 'microdata', 'og', 'js_state', 'xhr', 'config', 'llm')",
            name="source_kind",
        ),
    )
    op.create_index("ix_candidate_extraction_id", "candidate", ["extraction_id"])
    # `expire_candidates` deletes rows older than 30 days.
    op.create_index("ix_candidate_created_at", "candidate", ["created_at"])

    op.create_table(
        "record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("entity_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("field_meta", postgresql.JSONB(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("supersedes_record_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_record"),
        sa.ForeignKeyConstraint(["extraction_id"], [extraction.c.id], name="fk_record_extraction_id_extraction"),
        sa.ForeignKeyConstraint(["job_id"], [job.c.id], name="fk_record_job_id_job"),
        sa.ForeignKeyConstraint(["site_id"], [site.c.id], name="fk_record_site_id_site"),
        sa.ForeignKeyConstraint(
            ["schema_id", "schema_version"],
            [schema_def.c.id, schema_def.c.version],
            name="fk_record_schema_id_schema_def",
        ),
        sa.CheckConstraint(_MODE, name="mode"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_foreign_key("fk_record_supersedes_record_id_record", "record", "record", ["supersedes_record_id"], ["id"])
    # Recurring runs compare fingerprints per (site, entity, schema) (SPEC-11 §4.4).
    op.create_index("ix_record_site_id_entity_key_schema_id", "record", ["site_id", "entity_key", "schema_id"])

    op.create_table(
        "url_state",
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("content_fingerprint", sa.Text(), nullable=True),
        sa.Column("record_fingerprint", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missing_runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("gone_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("site_id", "canonical_url", name="pk_url_state"),
        sa.ForeignKeyConstraint(["site_id"], [site.c.id], name="fk_url_state_site_id_site"),
        sa.CheckConstraint("missing_runs >= 0", name="missing_runs_non_negative"),
    )

    op.create_table(
        "progressive_state",
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("page_kind", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), server_default=sa.text("'cold'"), nullable=False),
        sa.Column("pages_extracted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("site_id", "schema_id", "schema_version", "page_kind", name="pk_progressive_state"),
        sa.ForeignKeyConstraint(["site_id"], [site.c.id], name="fk_progressive_state_site_id_site"),
        sa.ForeignKeyConstraint(
            ["schema_id", "schema_version"],
            [schema_def.c.id, schema_def.c.version],
            name="fk_progressive_state_schema_id_schema_def",
        ),
        sa.CheckConstraint(_PAGE_KIND, name="page_kind"),
        sa.CheckConstraint("mode IN ('cold', 'learning', 'active')", name="mode"),
        sa.CheckConstraint("pages_extracted >= 0", name="pages_extracted_non_negative"),
    )

    op.create_table(
        "extraction_config",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("page_kind", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("ir", postgresql.JSONB(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("field_status", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("validation_report", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_extraction_config"),
        sa.ForeignKeyConstraint(["site_id"], [site.c.id], name="fk_extraction_config_site_id_site"),
        sa.ForeignKeyConstraint(
            ["schema_id", "schema_version"],
            [schema_def.c.id, schema_def.c.version],
            name="fk_extraction_config_schema_id_schema_def",
        ),
        sa.UniqueConstraint(
            "site_id",
            "schema_id",
            "page_kind",
            "version",
            name="uq_extraction_config_site_id_schema_id_page_kind_version",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(_PAGE_KIND, name="page_kind"),
        sa.CheckConstraint("status IN ('draft', 'active', 'suspended')", name="status"),
        sa.CheckConstraint("origin IN ('adapter', 'induced', 'llm_synth', 'operator')", name="origin"),
    )
    # ARCHITECTURE §6: one `active` config per (site, schema, page_kind).
    op.create_index(
        "uq_extraction_config_active",
        "extraction_config",
        ["site_id", "schema_id", "page_kind"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("extraction_config")
    op.drop_table("progressive_state")
    op.drop_table("url_state")
    op.drop_table("record")
    op.drop_table("candidate")
    op.drop_table("extraction")
    op.drop_index("ix_url_task_capture_id", "url_task")
    op.drop_constraint("fk_url_task_capture_id_capture", "url_task", type_="foreignkey")
    op.drop_table("capture")
    op.drop_constraint("uq_schema_def_id_version", "schema_def", type_="unique")
