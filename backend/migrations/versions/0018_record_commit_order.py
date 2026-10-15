"""Recurring runs (SPEC-11 §4.2, §4.4): when a task stood for a record, and a record's `created_at` as the time it
committed.

`task_record.created_at` is when the task stood for the record; links made before this revision keep NULL, as their
time is not known. `record.created_at` is set again as the record's transaction commits (a deferred constraint
trigger, PostgreSQL §43.10: it fires at commit), holding a shared advisory lock until the commit is visible, so that
`changed_since` (`services.records.list_records`), which waits for that lock, never misses a record that committed
after a poll had begun.

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
    # Added without a default and then given one, so that existing links stay NULL rather than take this moment.
    op.add_column("task_record", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("task_record", "created_at", server_default=sa.text("now()"))
    # The lock is `services.records.RECORD_FEED_LOCK`: blake2b("record_feed", digest_size=8) as a signed bigint.
    op.execute(
        """
        CREATE FUNCTION record_committed() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock_shared(-7838622165994782610);
            UPDATE record SET created_at = clock_timestamp() WHERE id = NEW.id;
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
    op.drop_column("task_record", "created_at")
