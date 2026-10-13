"""record indexes for `GET /v1/records` by job or schema and for a capture's replay (SPEC-07 §4.6, PR 8).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = {
    "ix_record_job_id_id": ["job_id", "id"],
    "ix_record_schema_id_id": ["schema_id", "id"],
    "ix_record_extraction_id": ["extraction_id"],
}


def upgrade() -> None:
    for name, columns in _INDEXES.items():
        op.create_index(name, "record", columns)


def downgrade() -> None:
    for name in _INDEXES:
        op.drop_index(name, table_name="record")
