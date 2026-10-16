"""The `dom` source kind (ARCHITECTURE §8.1, §22 structural DOM collectors admitted 2026-10-16, SPEC-05 §4.5): a
label's value or the main image a detail page shows is a candidate of source kind `dom`, so the §6 enum, and the
`candidate.source_kind` CHECK that spells it out, gain the member.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'adapter', 'api', 'jsonld', 'microdata', 'og', 'js_state', 'xhr', 'config', 'llm', 'derived'"


def upgrade() -> None:
    _replace_check(f"{_KINDS}, 'dom'")


def downgrade() -> None:
    op.execute("DELETE FROM candidate WHERE source_kind = 'dom'")
    _replace_check(_KINDS)


def _replace_check(kinds: str) -> None:
    op.drop_constraint(op.f("ck_candidate_source_kind"), "candidate", type_="check")
    op.create_check_constraint(op.f("ck_candidate_source_kind"), "candidate", f"source_kind IN ({kinds})")
