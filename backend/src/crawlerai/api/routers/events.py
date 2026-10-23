"""`GET /v1/jobs/{id}/events`: a job's run events over server-sent events (WHATWG HTML §9.2), resumed
after the `Last-Event-ID` a reconnecting client sends. FastAPI's `EventSourceResponse` sends a keep-alive comment
when the stream has been idle 15 s, the heartbeat §4.2 asks for."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import not_found
from crawlerai.db.models import JobEventId, JobId
from crawlerai.services import events
from crawlerai.services.jobs import JobNotFound

router = APIRouter(
    prefix="/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 404: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


async def _job(job_id: JobId, request: Request) -> JobId:
    """The job, checked before the stream starts: once it has, the status is sent and a 404 no longer can be."""
    engine = database(request)
    async with engine.connect() as conn:
        try:
            await events.check_job(conn, job_id)
        except JobNotFound as e:
            raise not_found(str(e)) from e
    return job_id


@router.get("/{job_id}/events", response_class=EventSourceResponse)
async def job_events(
    job_id: Annotated[JobId, Depends(_job)],
    request: Request,
    last_event_id: Annotated[JobEventId | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    """The job's run events in the order they were stored, each with its id, then a `progress` event with the task
    counts after each batch, until the event of the job's end (`completed`, `failed` or `cancelled`), after which
    the stream closes. Send the last id received as `Last-Event-ID` to resume after it."""
    engine = database(request)
    async for event in events.stream(engine, job_id, last_event_id):
        yield ServerSentEvent(id=None if event.id is None else str(event.id), event=event.kind, data=event.data)
