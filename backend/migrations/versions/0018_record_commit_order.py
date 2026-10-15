"""Recurring runs (SPEC-11 §4.2, §4.4): when a task stood for a record, and a record's `created_at` as the time it
committed, which `changed_since` reads (`services.records`, whose `_committed` says why).

`task_record.created_at` is when the task stood for the record; existing links take their record's time. A record's
`created_at` is set again as its transaction commits: a deferred constraint trigger fires at commit (PostgreSQL
§43.10), once per transaction, and holds `services.records.RECORD_FEED_LOCK` shared until the commit is visible.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("task_record", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE task_record SET created_at = record.created_at FROM record WHERE record.id = task_record.record_id"
    )
    op.alter_column("task_record", "created_at", nullable=False, server_default=sa.text("now()"))
    op.drop_index("ix_record_site_id_entity_key_schema_id", table_name="record")
    op.create_index("ix_record_site_id_entity_key_schema_id_id", "record", ["site_id", "entity_key", "schema_id", "id"])
    op.create_index("ix_record_created_at", "record", ["created_at"])
    # The transaction's records are the rows whose `created_at` is still its start, `now()` (the column's default).
    # The lock is blake2b("record_feed", digest_size=8) as a signed bigint.
    op.execute(
        """
        CREATE FUNCTION record_committed() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('crawlerai.records_committed', true) = 'on' THEN
                RETURN NULL;
            END IF;
            PERFORM set_config('crawlerai.records_committed', 'on', true);
            PERFORM pg_advisory_xact_lock_shared(-7838622165994782610);
            UPDATE record SET created_at = clock_timestamp() WHERE created_at = now();
            RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER record_committed AFTER INSERT ON record "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION record_committed()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER record_committed ON record")
    op.execute("DROP FUNCTION record_committed()")
    op.drop_index("ix_record_created_at", table_name="record")
    op.drop_index("ix_record_site_id_entity_key_schema_id_id", table_name="record")
    op.create_index("ix_record_site_id_entity_key_schema_id", "record", ["site_id", "entity_key", "schema_id"])
    op.drop_column("task_record", "created_at")
