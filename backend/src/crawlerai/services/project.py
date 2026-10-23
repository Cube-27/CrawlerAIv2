"""The project's settings (single tenant: the `default` project migrations create).

`llm_call_cap` bounds the LLM calls of every job whose request sets no `budget.llm_calls`; null bounds none (owner,
2026-10-16). It is read when a job checks its budget (`db.usage.budget_remaining`), so a change applies to running
jobs too. `draft_call_cap` bounds the uncharged role S calls (field-name drafts) of each API key; null bounds none
(`crawlerai.llm.draft_cap`). `require_config_approval` makes a learned config wait for a person's approval
before it serves (`store_pending` in `config_ir.activation`); off, it activates once validated.
"""

from typing import Annotated

from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.core.validation import PG_INTEGER_MAX
from crawlerai.db.models import Project
from crawlerai.services.scrape_request import Input

# A cap is stored in an `integer` column.
_Cap = Annotated[int, Field(ge=0, le=PG_INTEGER_MAX)]


class ProjectSettings(Input):
    """`llm_call_cap`: the most LLM calls a job may make when its request sets no `budget.llm_calls`; null: no cap.
    `draft_call_cap`: the most uncharged role S calls (field-name drafts) one API key may make, in all; null: no cap.
    `require_config_approval`: whether a learned config waits for approval (`POST /v1/configs/{id}/approve`) before it
    serves."""

    llm_call_cap: _Cap | None
    draft_call_cap: _Cap | None
    require_config_approval: bool


_DEFAULT = Project.name == "default"


async def project_settings(conn: AsyncConnection) -> ProjectSettings:
    columns = (Project.llm_call_cap, Project.draft_call_cap, Project.require_config_approval)
    row = (await conn.execute(select(*columns).where(_DEFAULT))).one()
    return ProjectSettings(
        llm_call_cap=row.llm_call_cap,
        draft_call_cap=row.draft_call_cap,
        require_config_approval=row.require_config_approval,
    )


async def update_project_settings(conn: AsyncConnection, settings: ProjectSettings) -> ProjectSettings:
    await conn.execute(update(Project).where(_DEFAULT).values(**settings.model_dump()))
    return settings
