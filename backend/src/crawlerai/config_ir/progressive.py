"""Progressive mode (SPEC-08 §4.4, §4.8; ARCHITECTURE §8.3, §8.4): the state of a (site, schema, page kind)
on its way to an active config, the scheduler's `trigger_learning`, and the `learn` job a learning run is.

A state is `cold`, `learning` or `active` (`mode`), and a learning run is in flight while `learning_started_at` is
set. `TRANSITIONS` is the authority on modes: the functions below move a row along it with a compare-and-set update
that also checks the in-flight flag, so two callers racing on one state cannot both start or end a run.

A `cold` state with 8 extracted pages starts learning, and pages keep being served cold meanwhile. A run that
activates a config makes the state `active`; one that fails leaves it `cold` until 8 more pages are extracted. An
`active` state re-learns only when forced (`POST /v1/sites/{host}/learn` with `force`, drift), and keeps serving its
config until the new run activates another.

The `learn` job is created `queued` with its state in `request`; running it is the learning pipeline's (§4.5 to §4.7),
which ends the run with `learning_activated` or `learning_failed`.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ColumnElement, case, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import (
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobId,
    PageKind,
    ProgressiveMode,
    ProgressiveState,
    SchemaId,
    Site,
    SiteId,
)

# ARCHITECTURE §8.3: learning runs once 8 pages are extracted; a failed run is retried after 8 more (D-0030).
LEARN_AFTER_PAGES: Final = 8
# States per run of `trigger_learning`; the scheduler runs a full batch again at once, so a backlog drains in one turn.
TRIGGER_BATCH: Final = 100

LearnEvent = Literal["start", "start_forced", "activate", "fail", "operator", "schema_edit"]

TRANSITIONS: Final[Mapping[LearnEvent, Mapping[ProgressiveMode, ProgressiveMode]]] = {
    # Pages keep being served cold while a site learns (ARCHITECTURE §8.4).
    "start": {"cold": "learning"},
    # A forced or drift re-learn keeps the active config serving until a new one activates (SPEC-08 §4.9, §4.10).
    "start_forced": {"cold": "learning", "active": "active"},
    "activate": {"learning": "active", "active": "active"},
    # A failed run leaves a cold site cold (§4.8) and an active one on its config.
    "fail": {"learning": "cold", "active": "active"},
    # An operator's validated config activates in any mode (§4.10); a learning run in flight goes on, and may replace
    # it with the config it validates.
    "operator": {"cold": "active", "learning": "active", "active": "active"},
    # An edited schema's states start over (ARCHITECTURE §8.4): what was learned is for its old document, and a run in
    # flight is dropped, so that it can neither activate nor fail the state.
    "schema_edit": {"cold": "cold", "learning": "cold", "active": "cold"},
}


# Whether a learning run must be in flight for each event; None where either will do.
RUN_IN_FLIGHT: Final[Mapping[LearnEvent, bool | None]] = {
    "start": False,
    "start_forced": False,
    "activate": True,
    "fail": True,
    "operator": None,
    "schema_edit": None,
}


def next_mode(mode: ProgressiveMode, event: LearnEvent) -> ProgressiveMode | None:
    """The mode `event` moves a state in `mode` to, or None when `event` is refused there."""
    return TRANSITIONS[event].get(mode)


class NotLearning(Exception):
    def __init__(self, key: "StateKey", event: LearnEvent) -> None:
        super().__init__(f"progressive_state {key}: {event} with no learning run in flight")


class _LearnRequest(BaseModel):
    """The `request` of a `learn` job, as `request_learning` writes it (D-0549)."""

    site_id: UUID
    schema_id: UUID
    page_kind: PageKind


@dataclass(frozen=True)
class StateKey:
    site_id: SiteId
    schema_id: SchemaId
    page_kind: PageKind

    def columns(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_request(cls, request: Mapping[str, Any]) -> "StateKey":
        """The state a `learn` job's `request` names (`request_learning`, D-0549). Raises pydantic's
        `ValidationError` for a request that names none."""
        named = _LearnRequest.model_validate(request)
        return cls(SiteId(named.site_id), SchemaId(named.schema_id), named.page_kind)

    def where(self) -> list[ColumnElement[bool]]:
        return [getattr(ProgressiveState, name) == value for name, value in self.columns().items()]

    def config_scope(self) -> list[ColumnElement[bool]]:
        """The state's configs, one version sequence (ARCHITECTURE §6: versions per site, schema and page kind)."""
        configs = ExtractionConfig
        return [
            configs.site_id == self.site_id,
            configs.schema_id == self.schema_id,
            configs.page_kind == self.page_kind,
        ]


async def trigger_learning(conn: AsyncConnection, *, batch: int) -> int:
    """Start learning for up to `batch` cold states with enough extracted pages, and return how many."""
    state = ProgressiveState
    due = (
        select(state.site_id, state.schema_id, state.page_kind)
        .where(
            state.mode == "cold",
            state.pages_extracted >= func.coalesce(state.retry_at_pages, LEARN_AFTER_PAGES),
        )
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    keys = [StateKey(*row) for row in await conn.execute(due)]
    for key in keys:
        await request_learning(conn, key)
    return len(keys)


async def request_learning(conn: AsyncConnection, key: StateKey, *, force: bool = False) -> JobId | None:
    """Start a learning run for `key`, a state created cold if there is none yet, and return its `learn` job; None
    when a run is already in flight, or the state is active and `force` is not set."""
    await conn.execute(pg_insert(ProgressiveState).values(**key.columns()).on_conflict_do_nothing())
    event: LearnEvent = "start_forced" if force else "start"
    if not await _move(conn, key.where(), event, learning_started_at=func.now()):
        return None
    project = select(Site.project_id).where(Site.id == key.site_id).scalar_subquery()
    request = {**key.columns(), "site_id": str(key.site_id), "schema_id": str(key.schema_id), "force": force}
    job_id: JobId = (
        await conn.execute(
            insert(Job)
            .values(
                project_id=project,
                kind="learn",
                request=request,
                schema_id=key.schema_id,
                engine_version=ENGINE_VERSION,
            )
            .returning(Job.id)
        )
    ).scalar_one()
    return job_id


async def learning_activated(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """End `key`'s learning run with `config_id` activated (§4.8). Raises `NotLearning` when no run is in flight."""
    moved = await _move(
        conn,
        key.where(),
        "activate",
        active_config_id=config_id,
        last_learned_at=func.now(),
        learning_started_at=None,
    )
    if not moved:
        raise NotLearning(key, "activate")


async def lock_state(conn: AsyncConnection, key: StateKey) -> None:
    """Lock `key`'s state row for the transaction, creating it cold first if there is none; one config change per
    state at a time then takes its version after the one before."""
    await conn.execute(pg_insert(ProgressiveState).values(**key.columns()).on_conflict_do_nothing())
    await conn.execute(select(ProgressiveState.mode).where(*key.where()).with_for_update())


async def operator_activated(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """Make `config_id`, an operator's validated config, `key`'s active config (§4.10), with or without a learning
    run in flight. The state must exist."""
    if not await _move(conn, key.where(), "operator", active_config_id=config_id):
        raise LookupError(f"no progressive_state {key}")


async def learning_failed(conn: AsyncConnection, key: StateKey) -> None:
    """End `key`'s learning run with nothing activated: a state that was learning goes cold, to try again after
    `LEARN_AFTER_PAGES` more pages (§4.8). Raises `NotLearning` when no run is in flight."""
    state = ProgressiveState
    retry = case((state.mode == "learning", state.pages_extracted + LEARN_AFTER_PAGES), else_=state.retry_at_pages)
    if not await _move(conn, key.where(), "fail", learning_started_at=None, retry_at_pages=retry):
        raise NotLearning(key, "fail")


async def relearn_schema(conn: AsyncConnection, schema_id: SchemaId) -> None:
    """Send what was learned for an edited schema back to learning (SPEC-04 §4.1): its active configs are `suspended`,
    so pages are served cold, and its states go `cold` (`schema_edit`) with no run in flight and their configs cleared.
    The next run starts once enough pages are extracted (`trigger_learning`); `pages_extracted` is kept."""
    configs = ExtractionConfig
    await conn.execute(
        update(configs).where(configs.schema_id == schema_id, configs.status == "active").values(status="suspended")
    )
    scope = [ProgressiveState.schema_id == schema_id]
    await _move(conn, scope, "schema_edit", active_config_id=None, learning_started_at=None, retry_at_pages=None)


async def _move(conn: AsyncConnection, scope: list[ColumnElement[bool]], event: LearnEvent, **values: Any) -> bool:
    """Compare-and-set the states in `scope` along `event`'s edges and its `RUN_IN_FLIGHT` precondition, setting
    `values` too; whether any moved."""
    state = ProgressiveState
    edges = TRANSITIONS[event]
    in_flight = RUN_IN_FLIGHT[event]
    where = [*scope, state.mode.in_(edges)]
    if in_flight is not None:
        where.append(state.learning_started_at.is_not(None) if in_flight else state.learning_started_at.is_(None))
    mode = case(*((state.mode == source, target) for source, target in edges.items()))
    moved = await conn.execute(update(state).where(*where).values(mode=mode, **values))
    return moved.rowcount > 0
