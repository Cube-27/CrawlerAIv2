"""Progressive mode (learning-configs spec): the state of a (site, schema, page kind)
on its way to an active config, the scheduler's `trigger_learning`, and the `learn` job a learning run is.

A state is `cold`, `learning` or `active` (`mode`), and a learning run is in flight while `learning_started_at` is
set. `TRANSITIONS` is the authority on modes: the functions below move a row along it with a compare-and-set update
that also checks the in-flight flag, so two callers racing on one state cannot both start or end a run.

A `cold` state with 8 extracted pages starts learning, and pages keep being served cold meanwhile. A run that
activates a config makes the state `active`; one that fails leaves it `cold` until 8 more pages are extracted. An
`active` state re-learns only when forced (`POST /v1/sites/{host}/learn` with `force`, drift), and keeps serving its
config until the new run activates another. When the project requires approval (D-1342), a run's validated config
waits as `pending_approval` and the run ends as a failed one does, without the retry: no run starts while a config
waits, and an approved config activates in any mode.

The `learn` job is created `queued` with its state in `request`; running it is the learning pipeline's (§4.5 to §4.7),
which ends the run with `learning_activated`, `learning_awaits_approval` or `learning_failed`.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, case, func, insert, or_, select, update
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

# Learning runs once 8 pages are extracted; a failed run is retried after 8 more (D-0030).
LEARN_AFTER_PAGES: Final = 8
# States per run of `trigger_learning`; the scheduler runs a full batch again at once, so a backlog drains in one turn.
TRIGGER_BATCH: Final = 100

LearnEvent = Literal[
    "start",
    "start_forced",
    "activate",
    "fail",
    "operator",
    "schema_edit",
    "await_approval",
    "approve",
    "reject",
    "find",
]

TRANSITIONS: Final[Mapping[LearnEvent, Mapping[ProgressiveMode, ProgressiveMode]]] = {
    # Pages keep being served cold while a site learns.
    "start": {"cold": "learning"},
    # A forced or drift re-learn keeps the active config serving until a new one activates (learning-configs spec).
    "start_forced": {"cold": "learning", "active": "active"},
    "activate": {"learning": "active", "active": "active"},
    # A failed run leaves a cold site cold (§4.8) and an active one on its config.
    "fail": {"learning": "cold", "active": "active"},
    # An operator's validated config activates in any mode (§4.10); a learning run in flight goes on, and may replace
    # it with the config it validates.
    "operator": {"cold": "active", "learning": "active", "active": "active"},
    # A run whose validated config waits for approval (D-1342) ends as a failed one does, the site serving what it
    # served; `trigger_learning` starts no run while a config waits.
    "await_approval": {"learning": "cold", "active": "active"},
    # An approved config activates in any mode, as an operator's does: a person decided.
    "approve": {"cold": "active", "learning": "active", "active": "active"},
    # A role C find's validated steps (`config_ir.finds`) activate with no run in flight; a cold state's then still
    # learns in full (`trigger_learning`).
    "find": {"cold": "active", "active": "active"},
    # A refused config leaves the state's mode as it is: the site serves what it served before (D-1391).
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
    "find": False,
}


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
        """The state's configs, one version sequence (versions per site, schema and page kind)."""
        configs = ExtractionConfig
        return [
            configs.site_id == self.site_id,
            configs.schema_id == self.schema_id,
            configs.page_kind == self.page_kind,
        ]


async def trigger_learning(conn: AsyncConnection, *, batch: int) -> int:
    """Start learning for up to `batch` states with enough extracted pages, and return how many: cold ones, and active
    ones whose config holds only role C finds (origin `role_c`, `config_ir.finds`), which no run has learned yet. A
    state whose learned config waits for approval (D-1342) is not learned again until it is approved or a run is
    forced."""
    state, configs = ProgressiveState, ExtractionConfig
    waiting = select(configs.id).where(
        configs.site_id == state.site_id,
        configs.schema_id == state.schema_id,
        configs.page_kind == state.page_kind,
        configs.status == "pending_approval",
    )
    finds_only = select(configs.id).where(configs.id == state.active_config_id, configs.origin == "role_c")
    due = (
        select(state.site_id, state.schema_id, state.page_kind, state.mode)
        .where(
            or_(state.mode == "cold", and_(state.mode == "active", finds_only.exists())),
            state.learning_started_at.is_(None),  # an active state's forced run keeps its mode while in flight
            state.pages_extracted >= func.coalesce(state.retry_at_pages, LEARN_AFTER_PAGES),
            ~waiting.exists(),
        )
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    rows = [(StateKey(site, schema, kind), mode) for site, schema, kind, mode in await conn.execute(due)]
    for key, mode in rows:
        await request_learning(conn, key, force=mode == "active")
    return len(rows)


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


async def find_activated(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """Make `config_id`, a config with a role C find's validated steps (`config_ir.finds`), `key`'s active config, with
    no learning run in flight. Raises `LookupError` when the state is not there or a run is in flight."""
    if not await _move(conn, key.where(), "find", active_config_id=config_id):
        raise LookupError(f"progressive_state {key}: no find without a learning run in flight")


async def learning_awaits_approval(conn: AsyncConnection, key: StateKey) -> None:
    """End `key`'s learning run with its config stored `pending_approval` (D-1342): the state serves what it served
    before the run. Raises `NotLearning` when no run is in flight."""
    if not await _move(conn, key.where(), "await_approval", learning_started_at=None):
        raise NotLearning(key, "await_approval")


async def config_approved(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """Make `config_id`, a learned config a person approved, `key`'s active config, with or without a learning run in
    flight. The state must exist."""
    if not await _move(conn, key.where(), "approve", active_config_id=config_id, last_learned_at=func.now()):
        raise LookupError(f"no progressive_state {key}")


async def config_rejected(conn: AsyncConnection, key: StateKey) -> None:
    """Record that a person refused the learned config waiting for `key` (D-1391): a cold state learns again only after
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
    """Make `config_id`, an operator's validated config, `key`'s active config (§4.10), with or without a learning
    run in flight. The state must exist."""
    if not await _move(conn, key.where(), "operator", active_config_id=config_id):
        raise LookupError(f"no progressive_state {key}")


async def learning_failed(conn: AsyncConnection, key: StateKey) -> None:
    """End `key`'s learning run with nothing activated: a state that was learning goes cold, and an active one stays on
    its config, each to try again after `LEARN_AFTER_PAGES` more pages (§4.8; an active state learns again unforced only
    while its config holds role C finds alone). Raises `NotLearning` when no run is in flight."""
    state = ProgressiveState
    retry = state.pages_extracted + LEARN_AFTER_PAGES
    if not await _move(conn, key.where(), "fail", learning_started_at=None, retry_at_pages=retry):
        raise NotLearning(key, "fail")


async def relearn_schema(conn: AsyncConnection, schema_id: SchemaId) -> None:
    """Send what was learned for an edited schema back to learning (schemas spec): its active configs are `suspended`,
    so pages are served cold, and its states go `cold` (`schema_edit`) with no run in flight and their configs cleared.
    The next run starts once enough pages are extracted (`trigger_learning`); `pages_extracted` is kept."""
    configs = ExtractionConfig
    await conn.execute(
        update(configs)
        # A config waiting for approval was learned for the old document too (D-1342).
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
