"""Private eval database (SPEC-03 PR 1): eval_capture, eval_page, eval_run and eval_llm_cache for hidden and fresh
cases. Run by the custodian with `alembic -n private upgrade head` (C1).

Revision ID: p0001
Revises:
Create Date: 2026-10-13
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Literal like every revision, written compactly: most columns are NOT NULL, and CHECK names are final (`op.f`).
_CATEGORY = "category IN ('platform_store', 'custom_store', 'api_backed', 'job_board', 'mixed')"
_SPLIT = "split IN ('hidden', 'fresh')"


def _col(name: str, type_: sa.types.TypeEngine[Any], **kw: Any) -> sa.Column[Any]:
    return sa.Column(name, type_, nullable=kw.pop("nullable", False), **kw)


def _check(table: str, name: str, expression: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(expression, name=op.f(f"ck_{table}_{name}"))


def _jsonb(name: str, default: str | None = None, *, nullable: bool = False) -> sa.Column[Any]:
    server_default = sa.text(default) if default else None
    return _col(name, postgresql.JSONB(), server_default=server_default, nullable=nullable)


def _created_at() -> sa.Column[Any]:
    return _col("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"))


def upgrade() -> None:
    op.create_table(
        "eval_capture",
        _col("id", sa.Uuid()),
        *(_col(name, sa.Text()) for name in ("split", "host", "category", "url")),
        _col("fetched_at", sa.DateTime(timezone=True)),
        _col("method", sa.Text()),
        _col("status_code", sa.Integer()),
        *(_col(name, sa.Text()) for name in ("final_url", "block_class", "object_key", "html_sha256")),
        _col("size_bytes", sa.BigInteger()),
        _col("duration_ms", sa.Integer()),
        _jsonb("fetch_policy", "'{}'::jsonb"),
        _check("eval_capture", "block_class", "block_class IN ('ok', 'blocked', 'shell', 'not_found', 'error')"),
        _check("eval_capture", "category", _CATEGORY),
        _check("eval_capture", "method", "method IN ('http', 'browser', 'api')"),
        _check("eval_capture", "split", _SPLIT),
        _check("eval_capture", "duration_ms_non_negative", "duration_ms >= 0"),
        _check("eval_capture", "host_lowercase", "host = lower(host)"),
        _check("eval_capture", "size_bytes_non_negative", "size_bytes >= 0"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_capture")),
        sa.UniqueConstraint("id", "split", name=op.f("uq_eval_capture_id_split")),
        sa.UniqueConstraint("object_key", name=op.f("uq_eval_capture_object_key")),
    )
    op.create_table(
        "eval_llm_cache",
        _col("key", sa.Text()),
        _col("object_key", sa.Text()),
        _col("size_bytes", sa.BigInteger()),
        _created_at(),
        _check("eval_llm_cache", "key_sha256", "key ~ '^[0-9a-f]{64}$'"),
        _check("eval_llm_cache", "size_bytes_non_negative", "size_bytes >= 0"),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_eval_llm_cache")),
        sa.UniqueConstraint("object_key", name=op.f("uq_eval_llm_cache_object_key")),
    )
    op.create_table(
        "eval_run",
        _col("id", sa.Uuid()),
        *(_col(name, sa.Text()) for name in ("split", "engine_version", "git_sha")),
        _jsonb("metrics"),
        _created_at(),
        _check("eval_run", "split", _SPLIT),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_run")),
    )
    op.create_table(
        "eval_page",
        _col("capture_id", sa.Uuid()),
        _col("id", sa.Uuid()),
        _col("split", sa.Text()),
        _col("schema_id", sa.Uuid()),
        *(_col(name, sa.Text()) for name in ("schema_name", "page_kind", "category")),
        _jsonb("labels", "'{}'::jsonb"),
        *(_col(name, sa.Text(), nullable=True) for name in ("labeler", "checker")),
        _jsonb("config_snapshot", nullable=True),
        _created_at(),
        _check("eval_page", "category", _CATEGORY),
        _check("eval_page", "page_kind", "page_kind IN ('detail', 'listing')"),
        _check("eval_page", "split", _SPLIT),
        _check("eval_page", "two_people", "checker IS NULL OR (labeler IS NOT NULL AND checker <> labeler)"),
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
