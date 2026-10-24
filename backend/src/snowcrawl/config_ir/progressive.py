"""Progressive mode: the state of a (site, schema, page kind)
on its way to an active config, the scheduler's `trigger_learning`, and the `learn` job a learning run is.

A state is `cold`, `learning` or `active` (`mode`), and a learning run is in flight while `learning_started_at` is
set. `TRANSITIONS` is the authority on modes: the functions below move a row along it with a compare-and-set update
that also checks the in-flight flag, so two callers racing on one state cannot both start or end a run.

A `cold` state with 8 extracted pages starts learning, and pages keep being served cold meanwhile. A run that
activates a config makes the state `active`; one that fails leaves it `cold` until 8 more pages are extracted. An
`active` state re-learns only when forced (`POST /v1/sites/{host}/learn` with `force`, drift), and keeps serving its
config until the new run activates another. When the project requires approval, a run's validated config
waits as `pending_approval` and the run ends as a failed one does, without the retry: no run starts while a config
waits, and an approved config activates in any mode.

The `learn` job is created `queued` with its state in `request`; running it is the learning pipeline's (§4.5 to §4.7),
which ends the run with `learning_activated`, `learning_awaits_approval` or `learning_failed`.

A state is also a surface's render setting (`render_mode`): the last `render.mode` a job
set for it, which a job submitted without one inherits. A job whose mode is `locate` or `always` starts the surface's
locate run once, as a forced `learn` job whose request names the job and the
fields it asked for (`request_locate`). A custom recipe's drift starts its repair run, a forced `learn` job whose
request names the recipe (`repair`); it ends as a run awaiting approval does, its proposal stored apart from the
learned config.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ColumnElement, case, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from snowcrawl.core.engine_version import ENGINE_VERSION
from snowcrawl.db.models import (
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobId,
    PageKind,
    ProgressiveMode,
    ProgressiveState,
    Record,
    RenderMode,
    SchemaId,
    Site,
    SiteId,
)

# Learning runs once 8 pages are extracted; a failed run is retried after 8 more.
LEARN_AFTER_PAGES: Final = 8
# States per run of `trigger_learning`; the scheduler runs a full batch again at once, so a backlog drains in one turn.
TRIGGER_BATCH: Final = 100

LearnEvent = Literal[
    "start", "start_forced", "activate", "fail", "operator", "schema_edit", "await_approval", "approve", "reject"
]

TRANSITIONS: Final[Mapping[LearnEvent, Mapping[ProgressiveMode, ProgressiveMode]]] = {
    # Pages keep being served cold while a site learns.
    "start": {"cold": "learning"},
    # A forced or drift re-learn keeps the active config serving until a new one activates.
    "start_forced": {"cold": "learning", "active": "active"},
    "activate": {"learning": "active", "active": "active"},
    # A failed run leaves a cold site cold and an active one on its config.
    "fail": {"learning": "cold", "active": "active"},
    # An operator's validated config activates in any mode; a learning run in flight goes on, and may replace
    # it with the config it validates.
    "operator": {"cold": "active", "learning": "active", "active": "active"},
    # A run whose validated config waits for approval ends as a failed one does, the site serving what it
    # served; `trigger_learning` starts no run while a config waits.
    "await_approval": {"learning": "cold", "active": "active"},
    # An approved config activates in any mode, as an operator's does: a person decided.
    "approve": {"cold": "active", "learning": "active", "active": "active"},
    # A refused config leaves the state's mode as it is: the site serves what it served before.
    "reject": {"cold": "cold", "learning": "learning", "active": "active"},
    # An edited schema's states start over: what was learned is for its old document, and a run in
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
    "await_approval": True,
    "approve": None,
    "reject": None,
}


class NotLearning(Exception):
    def __init__(self, key: "StateKey", event: LearnEvent) -> None:
        super().__init__(f"progressive_state {key}: {event} with no learning run in flight")


# The stored pages of a surface a locate run renders: one to induce on, the others to hold out.
LOCATE_SAMPLES: Final = 3


class LocateRequest(BaseModel):
    """What a locate run is asked for: the job whose `render` started it (whose
    request context a recipe's referenced headers are replayed with; none for a schema edit's), and the fields it
    named (none: the fields the surface's config does not read)."""

    job_id: UUID | None = None
    fields: list[str] = []


class _LearnRequest(BaseModel):
    """The `request` of a `learn` job, as `request_learning` writes it."""

    site_id: UUID
    schema_id: UUID
    page_kind: PageKind
    locate: LocateRequest | None = None
    # A repair run's: the custom recipe whose drift it repairs.
    repair: UUID | None = None


@dataclass(frozen=True)
class StateKey:
    site_id: SiteId
    schema_id: SchemaId
    page_kind: PageKind

    def columns(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def locate_of(request: Mapping[str, Any]) -> LocateRequest | None:
        """The locate run a `learn` job's `request` asks for, if any."""
        return _LearnRequest.model_validate(request).locate

    @staticmethod
    def repair_of(request: Mapping[str, Any]) -> ExtractionConfigId | None:
        """The custom recipe a `learn` job's `request` repairs, if any."""
        repair = _LearnRequest.model_validate(request).repair
        return None if repair is None else ExtractionConfigId(repair)

    @classmethod
    def from_request(cls, request: Mapping[str, Any]) -> "StateKey":
        """The state a `learn` job's `request` names (`request_learning`). Raises pydantic's
        `ValidationError` for a request that names none."""
        named = _LearnRequest.model_validate(request)
        return cls(SiteId(named.site_id), SchemaId(named.schema_id), named.page_kind)

    def where(self) -> list[ColumnElement[bool]]:
        return [getattr(ProgressiveState, name) == value for name, value in self.columns().items()]

    def config_scope(self) -> list[ColumnElement[bool]]:
        """The state's configs, one version sequence (versions per site, schema and page kind)."""
        configs = ExtractionConfig
        return [
            configs.site_id == self.site_id,
            configs.schema_id == self.schema_id,
            configs.page_kind == self.page_kind,
        ]


async def trigger_learning(conn: AsyncConnection, *, batch: int) -> int:
    """Start learning for up to `batch` cold states with enough extracted pages, and return how many. A state whose
    learned config waits for approval is not learned again until it is approved or a run is forced. A listing
    surface none of whose pages kept a record (each listed nothing) is learned only as a locate run (`render_mode` not
    `off`): a learning run reads pages with records alone, so it would have nothing to learn from."""
    state, configs = ProgressiveState, ExtractionConfig
    waiting = select(configs.id).where(
        configs.site_id == state.site_id,
        configs.schema_id == state.schema_id,
        configs.page_kind == state.page_kind,
        configs.status == "pending_approval",
        configs.pattern_shape == "",  # a recipe's repair waits apart from the learned config
    )
    recorded = select(Record.id).where(Record.site_id == state.site_id, Record.schema_id == state.schema_id)
    due = (
        select(state.site_id, state.schema_id, state.page_kind)
        .where(
            state.mode == "cold",
            state.pages_extracted >= func.coalesce(state.retry_at_pages, LEARN_AFTER_PAGES),
            ~waiting.exists(),
            or_(state.page_kind != "listing", state.render_mode != "off", recorded.exists()),
        )
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    keys = [StateKey(*row) for row in await conn.execute(due)]
    for key in keys:
        await request_learning(conn, key)
    return len(keys)


async def request_learning(
    conn: AsyncConnection,
    key: StateKey,
    *,
    force: bool = False,
    locate: LocateRequest | None = None,
    repair: ExtractionConfigId | None = None,
) -> JobId | None:
    """Start a learning run for `key`, a state created cold if there is none yet, and return its `learn` job; None
    when a run is already in flight, or the state is active and `force` is not set. With `locate`, the run is the
    surface's locate run too; with `repair`, it repairs that custom recipe instead of learning the learned config."""
    await conn.execute(pg_insert(ProgressiveState).values(**key.columns()).on_conflict_do_nothing())
    event: LearnEvent = "start_forced" if force else "start"
    if not await _move(conn, key.where(), event, learning_started_at=func.now()):
        return None
    project = select(Site.project_id).where(Site.id == key.site_id).scalar_subquery()
    request = {**key.columns(), "site_id": str(key.site_id), "schema_id": str(key.schema_id), "force": force}
    if locate is not None:
        request["locate"] = locate.model_dump(mode="json")
    if repair is not None:
        request["repair"] = str(repair)
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


async def render_mode(conn: AsyncConnection, key: StateKey) -> RenderMode:
    """The surface's render mode; `off` for a surface no job has set one for."""
    found: RenderMode | None = (
        await conn.execute(select(ProgressiveState.render_mode).where(*key.where()))
    ).scalar_one_or_none()
    return found or "off"


async def set_render_mode(conn: AsyncConnection, key: StateKey, mode: RenderMode) -> None:
    """Store `mode` as the surface's render mode, a state created cold if there is none yet."""
    await conn.execute(
        pg_insert(ProgressiveState)
        .values(**key.columns(), render_mode=mode)
        .on_conflict_do_update(
            index_elements=[ProgressiveState.site_id, ProgressiveState.schema_id, ProgressiveState.page_kind],
            set_={"render_mode": mode},
            where=ProgressiveState.render_mode != mode,
        )
    )


async def request_locate(conn: AsyncConnection, key: StateKey, locate: LocateRequest) -> JobId | None:
    """Start the surface's locate run for `locate.job_id` once the surface has `LOCATE_SAMPLES` extracted pages to
    render, unless that job already started one for `key` or a run is in flight; its `learn` job, or None."""
    pages = select(ProgressiveState.pages_extracted).where(*key.where())
    if ((await conn.execute(pages)).scalar_one_or_none() or 0) < LOCATE_SAMPLES:
        return None
    job = Job
    started = select(job.id).where(
        job.kind == "learn",
        job.request["site_id"].astext == str(key.site_id),
        job.request["schema_id"].astext == str(key.schema_id),
        job.request["page_kind"].astext == key.page_kind,
        job.request["locate"]["job_id"].astext == str(locate.job_id),
    )
    if (await conn.execute(select(started.exists()))).scalar_one():
        return None
    return await request_learning(conn, key, force=True, locate=locate)


async def locate_added(conn: AsyncConnection, schema_id: SchemaId, fields: list[str]) -> None:
    """Start the locate run of every surface of `schema_id` whose render mode locates (`locate`, `always`) and whose
    pages were extracted, for `fields`, which an edit added to the schema."""
    state = ProgressiveState
    surfaces = await conn.execute(
        select(state.site_id, state.page_kind).where(
            state.schema_id == schema_id, state.render_mode != "off", state.pages_extracted >= LOCATE_SAMPLES
        )
    )
    for site_id, page_kind in surfaces.all():
        await request_learning(
            conn, StateKey(site_id, schema_id, page_kind), force=True, locate=LocateRequest(fields=fields)
        )


async def learning_activated(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """End `key`'s learning run with `config_id` activated. Raises `NotLearning` when no run is in flight."""
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


async def learning_awaits_approval(conn: AsyncConnection, key: StateKey) -> None:
    """End `key`'s learning run with its config stored `pending_approval`: the state serves what it served
    before the run. Raises `NotLearning` when no run is in flight."""
    if not await _move(conn, key.where(), "await_approval", learning_started_at=None):
        raise NotLearning(key, "await_approval")


async def config_approved(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """Make `config_id`, a learned config a person approved, `key`'s active config, with or without a learning run in
    flight. The state must exist."""
    if not await _move(conn, key.where(), "approve", active_config_id=config_id, last_learned_at=func.now()):
        raise LookupError(f"no progressive_state {key}")


async def config_rejected(conn: AsyncConnection, key: StateKey) -> None:
    """Record that a person refused the learned config waiting for `key`: a cold state learns again only after
    `LEARN_AFTER_PAGES` more pages, as after a failed run, so the refused document is not learned at once. The state
    must exist."""
    state = ProgressiveState
    retry = case((state.mode == "cold", state.pages_extracted + LEARN_AFTER_PAGES), else_=state.retry_at_pages)
    if not await _move(conn, key.where(), "reject", retry_at_pages=retry):
        raise LookupError(f"no progressive_state {key}")


async def lock_state(conn: AsyncConnection, key: StateKey) -> None:
    """Lock `key`'s state row for the transaction, creating it cold first if there is none; one config change per
    state at a time then takes its version after the one before."""
    await conn.execute(pg_insert(ProgressiveState).values(**key.columns()).on_conflict_do_nothing())
    await conn.execute(select(ProgressiveState.mode).where(*key.where()).with_for_update())


async def operator_activated(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """Make `config_id`, an operator's validated config, `key`'s active config, with or without a learning
    run in flight. The state must exist."""
    if not await _move(conn, key.where(), "operator", active_config_id=config_id):
        raise LookupError(f"no progressive_state {key}")


async def learning_failed(conn: AsyncConnection, key: StateKey) -> None:
    """End `key`'s learning run with nothing activated: a state that was learning goes cold, to try again after
    `LEARN_AFTER_PAGES` more pages. Raises `NotLearning` when no run is in flight."""
    state = ProgressiveState
    retry = case((state.mode == "learning", state.pages_extracted + LEARN_AFTER_PAGES), else_=state.retry_at_pages)
    if not await _move(conn, key.where(), "fail", learning_started_at=None, retry_at_pages=retry):
        raise NotLearning(key, "fail")


async def relearn_schema(conn: AsyncConnection, schema_id: SchemaId) -> None:
    """Send what was learned for an edited schema back to learning: its active configs are `suspended`,
    so pages are served cold, and its states go `cold` (`schema_edit`) with no run in flight and their configs cleared.
    The next run starts once enough pages are extracted (`trigger_learning`); `pages_extracted` is kept."""
    configs = ExtractionConfig
    await conn.execute(
        update(configs)
        # A config waiting for approval was learned for the old document too.
        .where(configs.schema_id == schema_id, configs.status.in_(("active", "pending_approval")))
        .values(status="suspended")
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
