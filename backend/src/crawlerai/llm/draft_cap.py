"""A per-key cap on uncharged role S calls: the field-name drafts of `schema.fields` and
`POST /v1/schemas/draft`, and a schema's label synonyms (`roles.s_labels`), which no job exists yet to pay for
(`LLMRequest.job_id` None), so no job budget bounds them.

`project.draft_call_cap` is the most such calls one API key may make in all; null bounds none. A key's calls are
counted in `api_key.draft_calls` as they are made, an answer or a failure alike; a stored draft needs no call, and a
process without a provider makes none, so neither counts. `KeyCapped` wraps the API's client for one request's key; a
call a job pays for passes through, as the job's own budget bounds it (`db.usage.budget_remaining`).
"""

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import ApiKey, ApiKeyId, Project
from crawlerai.llm.client import LLMClient, LLMFailure, LLMRequest, LLMResponse, ReplyCheck, Unconfigured

DRAFT_CAP_REACHED = "draft_cap_reached"
CAP_NAME = "draft_call_cap"


class DraftCapReached(LLMFailure):
    """The key has made as many uncharged role S calls as the project's `draft_call_cap` allows; none was made."""

    code = DRAFT_CAP_REACHED
    field_reason = "llm_budget"


async def take_draft_call(engine: AsyncEngine, key_id: ApiKeyId) -> None:
    """Count one uncharged call for the key, in a transaction of its own (a refused request still counts what was
    asked of the model). Raises `DraftCapReached` when the key is at the cap."""
    cap = select(Project.draft_call_cap).where(Project.name == "default").scalar_subquery()
    # One UPDATE tests and counts under the row lock, so concurrent calls cannot both take the last one.
    statement = (
        update(ApiKey)
        .where(ApiKey.id == key_id, or_(cap.is_(None), ApiKey.draft_calls < cap))
        .values(draft_calls=ApiKey.draft_calls + 1)
        .returning(ApiKey.id)
    )
    async with engine.begin() as conn:
        taken = (await conn.execute(statement)).first()
    if taken is None:
        raise DraftCapReached(
            f"API key {key_id} has made all the uncharged role S calls the project's draft_call_cap allows"
        )


class KeyCapped:
    """`inner`, with each of its calls that no job pays for counted against `key_id`'s cap."""

    def __init__(self, inner: LLMClient, engine: AsyncEngine, key_id: ApiKeyId) -> None:
        self._inner = inner
        self._engine = engine
        self._key_id = key_id

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        # A process without a provider makes no call, so it counts none.
        if req.job_id is None and not isinstance(self._inner, Unconfigured):
            await take_draft_call(self._engine, self._key_id)
        return await self._inner.complete_json(req, check)
