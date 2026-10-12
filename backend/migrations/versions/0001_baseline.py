"""Baseline: an empty schema. SPEC-01 adds the first tables on top of it.

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass  # The baseline creates nothing; it is the root every later revision builds on.


def downgrade() -> None:
    pass  # Nothing to undo.
