"""Usage events and per-job budgets: counted for visibility and to stop runaway
jobs, not for billing.

`record_usage` writes the event and adds to `job.usage` in the caller's transaction, so both commit or neither does.
Callers check `budget_remaining` before expensive work. A budget is advisory across workers: two that check at once
may both go ahead, so a job can overshoot by the work in flight.
"""

from collections.abc import Mapping
from typing import Any, Final, Literal

from sqlalchemy import BigInteger, ColumnElement, cast, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Job, JobId, Project, UrlTask, UsageEvent, UsageResource

# `job.request.budget` keys. `pages` is counted from the job's tasks, not from usage events.
BudgetResource = Literal["llm_calls", "browser_seconds", "pages"]

# The `last_error` of a task that stopped because its job's budget ran out. A handler returns
# `Failed(BUDGET_EXHAUSTED, transient=False)` rather than raising, so the usage it recorded commits with the failure.
BUDGET_EXHAUSTED: Final = "budget_exhausted"


async def record_usage(
    conn: AsyncConnection,
    job_id: JobId,
    resource: UsageResource,
    *,
    provider: str | None,
    model_or_pool: str | None,
    quantity: int,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    await conn.execute(
        insert(UsageEvent).values(
            job_id=job_id,
            resource=resource,
            provider=provider,
            model_or_pool=model_or_pool,
            quantity=quantity,
            metadata_=dict(metadata or {}),
        )
    )
    # One UPDATE reads and writes the counter under the row lock, so concurrent recordings never lose an increment.
    await conn.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(usage=Job.usage.op("||")(func.jsonb_build_object(resource, _used(resource) + quantity)))
    )


def _used(resource: str) -> ColumnElement[int]:
    """The job's counter for `resource`; 0 before its first use."""
    return func.coalesce(cast(Job.usage[resource].astext, BigInteger), 0)


async def budget_remaining(conn: AsyncConnection, job_id: JobId, resource: BudgetResource) -> int | None:
    """What the job may still use of `resource`, never below 0; `None` when its request sets no budget for it. A job
    whose request sets no `llm_calls` budget takes its project's `llm_call_cap`, as it stands when asked; a project
    without one leaves the job's LLM calls unbounded (owner, 2026-10-16)."""
    limit: ColumnElement[int] = cast(Job.request["budget"][resource].astext, BigInteger)
    if resource == "llm_calls":
        cap = select(Project.llm_call_cap).where(Project.id == Job.project_id).scalar_subquery()
        limit = func.coalesce(limit, cast(cap, BigInteger))
    used: ColumnElement[int]
    if resource == "pages":
        # A page is used once its task has ended, whether it extracted or failed; cancelled tasks never ran.
        used = (
            select(func.count())
            .where(UrlTask.job_id == job_id, UrlTask.status.in_(("done", "failed")))
            .scalar_subquery()
        )
    else:
        used = _used(resource)
    # max(0, limit - used), and NULL without a budget: `least` ignores a NULL limit, the subtraction keeps it.
    remaining: int | None = (
        await conn.execute(select(limit - func.least(used, limit)).where(Job.id == job_id))
    ).scalar_one()
    return remaining
