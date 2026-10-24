"""`/v1/schedules` (§22 "Recurring schedule storage", admitted 2026-10-17): recurring runs of a batch scrape, crawl or
extract request, on a cron expression or an interval. The scheduler submits each due run as a job; a schedule's jobs
are `GET /v1/jobs?schedule_id=`."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status

from snowcrawl.api.auth import caller, require_api_key
from snowcrawl.api.dto import PROBLEM_RESPONSE
from snowcrawl.api.problems import invalid, not_found, target_refused
from snowcrawl.api.runtime import database
from snowcrawl.api.submissions import submission_problems
from snowcrawl.db.models import ScheduleId
from snowcrawl.services import schedules
from snowcrawl.services.extract import NothingToExtract
from snowcrawl.services.fetching import TargetRejected
from snowcrawl.services.runtime import Caller
from snowcrawl.services.schedules import (
    InvalidUpdate,
    NewSchedule,
    RunStarted,
    ScheduleListQuery,
    ScheduleNotFound,
    ScheduleOut,
    SchedulePage,
    ScheduleUpdate,
    Submitting,
    Unschedulable,
)

router = APIRouter(
    prefix="/v1/schedules",
    tags=["schedules"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 404: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)
_SUBMITS: dict[int | str, dict[str, Any]] = {409: PROBLEM_RESPONSE, 502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE}


def _submitting(caller: Caller) -> Submitting:
    runtime = caller.runtime
    return Submitting(runtime.fetching, runtime.engine_data, runtime.llm)


@contextmanager
def _problems() -> Iterator[None]:
    """A submission's problems (`submission_problems`), a missing schedule's 404, and a request a schedule cannot run,
    or an update that would make an invalid schedule, as 422s."""
    with submission_problems():
        try:
            yield
        except ScheduleNotFound as e:
            raise not_found(str(e)) from e
        except Unschedulable as e:
            raise invalid(str(e), [("request", str(e))]) from e
        except InvalidUpdate as e:
            raise invalid(str(e), e.errors) from e
        except TargetRejected as e:
            raise target_refused(e.reason) from e
        except NothingToExtract as e:
            raise invalid(str(e), [("request.urls", str(e))]) from e


@router.post("", status_code=status.HTTP_201_CREATED, responses=_SUBMITS)
async def create_schedule(body: NewSchedule, caller: Annotated[Caller, Depends(caller)]) -> ScheduleOut:
    """Store a recurring run of `request` (of `kind`: a scrape runs as the batch of its URL), at each time of the
    5-field `cron` expression in `timezone`, or every `interval_s` seconds (at least 60). The request is checked as
    its submission would be (targets, schema); a `records` schema is stored by id. Its jobs are submitted as this key's,
    which signs their webhooks."""
    with _problems():
        return await schedules.create_schedule(
            caller.runtime.database, _submitting(caller), body, api_key_id=caller.api_key_id
        )


@router.get("")
async def list_schedules(query: Annotated[ScheduleListQuery, Query()], request: Request) -> SchedulePage:
    """The schedules, newest first. Pass a page's `next_cursor` as `cursor` for the page after it."""
    async with database(request).connect() as conn:
        return await schedules.list_schedules(conn, query)


@router.get("/{schedule_id}")
async def get_schedule(schedule_id: ScheduleId, request: Request) -> ScheduleOut:
    async with database(request).connect() as conn:
        with _problems():
            return await schedules.get_schedule(conn, schedule_id)


@router.patch("/{schedule_id}", responses=_SUBMITS)
async def update_schedule(
    schedule_id: ScheduleId,
    body: ScheduleUpdate,
    caller: Annotated[Caller, Depends(caller)],
) -> ScheduleOut:
    """Change the schedule's name, cadence, or run (`kind` with `request`, checked as at creation); a changed cadence
    is due at its first time after now."""
    with _problems():
        return await schedules.update_schedule(caller.runtime.database, _submitting(caller), schedule_id, body)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: ScheduleId, request: Request) -> Response:
    """Delete the schedule. Its jobs stay, with `schedule_id` null."""
    async with database(request).begin() as conn:
        with _problems():
            await schedules.delete_schedule(conn, schedule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{schedule_id}/pause")
async def pause_schedule(schedule_id: ScheduleId, request: Request) -> ScheduleOut:
    """Stop the schedule's runs until it is resumed."""
    async with database(request).begin() as conn:
        with _problems():
            return await schedules.set_paused(conn, schedule_id, paused=True)


@router.post("/{schedule_id}/resume")
async def resume_schedule(schedule_id: ScheduleId, request: Request) -> ScheduleOut:
    """Run the schedule again from its first due time after now; the runs missed while paused are not made up."""
    async with database(request).begin() as conn:
        with _problems():
            return await schedules.set_paused(conn, schedule_id, paused=False)


@router.post("/{schedule_id}/run", status_code=status.HTTP_202_ACCEPTED, responses=_SUBMITS)
async def run_schedule(schedule_id: ScheduleId, caller: Annotated[Caller, Depends(caller)]) -> RunStarted:
    """Submit the schedule's job now, paused or not; its next due time stays as it is."""
    with _problems():
        return await schedules.run_now(caller.runtime.database, _submitting(caller), schedule_id)
