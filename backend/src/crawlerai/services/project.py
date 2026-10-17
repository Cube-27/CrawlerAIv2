"""The project's settings (single tenant, ARCHITECTURE §1: the `default` project migrations create).

`llm_call_cap` bounds the LLM calls of every job whose request sets no `budget.llm_calls`; null bounds none (owner,
2026-10-16). It is read when a job checks its budget (`db.usage.budget_remaining`), so a change applies to running
jobs too. `draft_call_cap` bounds the uncharged role S calls (field-name drafts) of each API key; null bounds none
(D-1282, `crawlerai.llm.draft_cap`).
"""

from pydantic import NonNegativeInt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Project
from crawlerai.services.scrape_steps import Input


class ProjectSettings(Input):
    """`llm_call_cap`: the most LLM calls a job may make when its request sets no `budget.llm_calls`; null: no cap.
    `draft_call_cap`: the most uncharged role S calls (field-name drafts) one API key may make, in all; null: no cap."""

    llm_call_cap: NonNegativeInt | None
    draft_call_cap: NonNegativeInt | None


_DEFAULT = Project.name == "default"


async def project_settings(conn: AsyncConnection) -> ProjectSettings:
    row = (await conn.execute(select(Project.llm_call_cap, Project.draft_call_cap).where(_DEFAULT))).one()
    return ProjectSettings(llm_call_cap=row.llm_call_cap, draft_call_cap=row.draft_call_cap)


async def update_project_settings(conn: AsyncConnection, settings: ProjectSettings) -> ProjectSettings:
    await conn.execute(update(Project).where(_DEFAULT).values(**settings.model_dump()))
    return settings
