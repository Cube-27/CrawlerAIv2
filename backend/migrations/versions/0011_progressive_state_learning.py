"""progressive_state learning plumbing: when a learning run started, when one last activated a config, the active
config, and the page count at which a failed run is retried (SPEC-08 §4.4, §4.8, PR 4).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS = {
    "ck_progressive_state_learning_has_started": "mode <> 'learning' OR learning_started_at IS NOT NULL",
    "ck_progressive_state_active_has_config": "mode <> 'active' OR active_config_id IS NOT NULL",
    "ck_progressive_state_retry_at_pages_non_negative": "retry_at_pages >= 0",
}


def upgrade() -> None:
    op.add_column("progressive_state", sa.Column("learning_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("progressive_state", sa.Column("last_learned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("progressive_state", sa.Column("active_config_id", sa.Uuid(), nullable=True))
    op.add_column("progressive_state", sa.Column("retry_at_pages", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_progressive_state_active_config_id_extraction_config",
        "progressive_state",
        "extraction_config",
        ["active_config_id"],
        ["id"],
    )
    for name, condition in _CHECKS.items():
        op.create_check_constraint(op.f(name), "progressive_state", condition)


def downgrade() -> None:
    for name in _CHECKS:
        op.drop_constraint(op.f(name), "progressive_state", type_="check")
    op.drop_constraint("fk_progressive_state_active_config_id_extraction_config", "progressive_state")
    for column in ("retry_at_pages", "active_config_id", "last_learned_at", "learning_started_at"):
        op.drop_column("progressive_state", column)
