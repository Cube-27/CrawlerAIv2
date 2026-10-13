"""Usage events (SPEC-01 PR 7), and CHECK names of 0002-0004 prefixed once.

0002-0004 passed full CHECK names (`ck_job_kind`) without `op.f()`, so the metadata naming convention prefixed them
again (`ck_job_ck_job_kind`). This revision renames them to the names the models give them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, name as the models give it) for every CHECK that 0002-0004 created.
_PREFIXED_TWICE = [
    ("site", "ck_site_host_lowercase"),
    ("site", "ck_site_fetch_method"),
    ("site", "ck_site_crawl_delay_ms_non_negative"),
    ("schema_def", "ck_schema_def_version_positive"),
    ("schema_def", "ck_schema_def_page_kind"),
    ("schema_def", "ck_schema_def_origin"),
    ("schema_def", "ck_schema_def_status"),
    ("job", "ck_job_kind"),
    ("job", "ck_job_status"),
    ("url_task", "ck_url_task_page_kind"),
    ("url_task", "ck_url_task_status"),
    ("url_task", "ck_url_task_outcome"),
    ("url_task", "ck_url_task_attempts_non_negative"),
    ("url_task", "ck_url_task_depth_non_negative"),
]


def _rename(table: str, old: str, new: str) -> None:
    op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")


def upgrade() -> None:
    for table, name in _PREFIXED_TWICE:
        _rename(table, f"ck_{table}_{name}", name)

    job = sa.table("job", sa.column("id"))
    op.create_table(
        "usage_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model_or_pool", sa.Text(), nullable=True),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_usage_event"),
        sa.ForeignKeyConstraint(["job_id"], [job.c.id], name="fk_usage_event_job_id_job"),
        sa.CheckConstraint(
            "resource IN ('llm_calls', 'llm_tokens_in', 'llm_tokens_out', 'browser_seconds', 'proxy_bytes',"
            " 'http_requests')",
            name=op.f("ck_usage_event_resource"),
        ),
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_usage_event_quantity_non_negative")),
    )


def downgrade() -> None:
    op.drop_table("usage_event")
    for table, name in _PREFIXED_TWICE:
        _rename(table, name, f"ck_{table}_{name}")
