"""The `derived` source kind (ARCHITECTURE §6, SPEC-05 §4.8, D-0355): a page-URL derivation publishes with source kind
`derived`, so the §6 enum, and the `candidate.source_kind` CHECK that spells it out, gain the member.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'adapter', 'api', 'jsonld', 'microdata', 'og', 'js_state', 'xhr', 'config', 'llm'"


def upgrade() -> None:
    _replace_check(f"{_KINDS}, 'derived'")


def downgrade() -> None:
    op.execute("DELETE FROM candidate WHERE source_kind = 'derived'")
    _replace_check(_KINDS)


def _replace_check(kinds: str) -> None:
    op.drop_constraint(op.f("ck_candidate_source_kind"), "candidate", type_="check")
    op.create_check_constraint(op.f("ck_candidate_source_kind"), "candidate", f"source_kind IN ({kinds})")
