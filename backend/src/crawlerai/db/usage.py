"""Usage events and per-job budgets (SPEC-01 §4.6, ARCHITECTURE §17): counted for visibility and to stop runaway
jobs, not for billing.

`record_usage` writes the event and adds to `job.usage` in the caller's transaction, so both commit or neither does.
Callers check `budget_remaining` before expensive work. A budget is advisory across workers: two that check at once
may both go ahead, so a job can overshoot by the work in flight.
"""

from collections.abc import Mapping
from typing import Any, Final, Literal

from sqlalchemy import BigInteger, cast, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Job, JobId, UrlTask, UsageEvent, UsageResource

# `job.request.budget` keys (SPEC-01 §4.6). `pages` is counted from the job's tasks, not from usage events.
BudgetResource = Literal["llm_calls", "browser_seconds", "pages"]

# The `last_error` of a task that stopped because its job's budget ran out (§4.6). A handler returns
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
    used = func.coalesce(cast(Job.usage[resource].astext, BigInteger), 0)
    await conn.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(usage=Job.usage.op("||")(func.jsonb_build_object(resource, used + quantity)))
    )


async def budget_remaining(conn: AsyncConnection, job_id: JobId, resource: BudgetResource) -> int | None:
    """What the job may still use of `resource`, never below 0; `None` when its request sets no budget for it."""
    budget = Job.request["budget"][resource].astext
    row = (await conn.execute(select(cast(budget, BigInteger).label("limit"), Job.usage).where(Job.id == job_id))).one()
    limit: int | None = row.limit
    if limit is None:
        return None
    used: int
    if resource == "pages":
        # A page is used once its task has ended, whether it extracted or failed; cancelled tasks never ran.
        ended = select(func.count()).where(UrlTask.job_id == job_id, UrlTask.status.in_(("done", "failed")))
        used = (await conn.execute(ended)).scalar_one()
    else:
        used = row.usage.get(resource, 0)
    return max(0, limit - used)
