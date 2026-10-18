"""Activation (learning-configs spec): a validated config is stored as the next version of its (site,
schema, page kind) config, `active`, with its field statuses and `validation_report`; the config active before it is
`suspended`, and the learning run in flight ends with the state `active` on the new config.

When the project requires approval (D-1342), a learning run's validated config is stored `pending_approval` instead
(`store_pending`), and becomes the active config only when a person approves it (`approve`).

An operator's correction (§4.10) is stored as the next version whether or not it validates: active as above, without
ending any learning run, or a `draft` with the report that says why not.

Only a `Validated` with a config activates: nothing activates without validation (§4.13). Everything runs on the
caller's connection, in its transaction, so a run that cannot end (`NotLearning`) stores nothing.
"""

from collections.abc import Collection

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.executor import ConfigMismatch
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.progressive import (
    NotLearning,
    StateKey,
    config_approved,
    config_rejected,
    learning_activated,
    learning_awaits_approval,
    lock_state,
    operator_activated,
)
from crawlerai.config_ir.validation import Validated, ValidationReport
from crawlerai.db.models import (
    ConfigStatus,
    ExtractionConfig,
    ExtractionConfigId,
    ProgressiveState,
    SchemaDef,
    Site,
)
from crawlerai.schemas import registry
from crawlerai.schemas.types import document_digest


class NotValidated(ValueError):
    """Validation kept no config to activate."""


async def activate(conn: AsyncConnection, key: StateKey, validated: Validated) -> ExtractionConfigId:
    """Store `validated`'s config for `key` as active and end `key`'s learning run with it; its id. Raises
    `NotValidated` when validation refused the config, `ConfigMismatch` when the config was learned for another site,
    schema or page kind, and `NotLearning` when no learning run is in flight for `key`."""
    ir = validated.ir
    if ir is None:
        raise NotValidated(f"progressive_state {key}: validation refused the config ({validated.report.refused})")
    # One activation per state at a time: the row lock orders them, so versions are taken one after another.
    locked = select(ProgressiveState.learning_started_at).where(*key.where()).with_for_update()
    started = (await conn.execute(locked)).first()
    if started is None or started.learning_started_at is None:
        raise NotLearning(key, "activate")
    await _check_key(conn, key, ir)
    await _suspend_active(conn, key)
    config_id = await _store(conn, key, ir, validated.report, "active")
    await learning_activated(conn, key, config_id)
    return config_id


async def store_pending(conn: AsyncConnection, key: StateKey, validated: Validated) -> ExtractionConfigId:
    """Store `validated`'s config for `key` as `pending_approval` and end `key`'s learning run (D-1342): the config
    serving before the run, if any, goes on serving until a person approves the new one (`approve`). A config that
    waited before is `suspended`: the newer run replaces it. Raises like `activate`."""
    ir = validated.ir
    if ir is None:
        raise NotValidated(f"progressive_state {key}: validation refused the config ({validated.report.refused})")
    locked = select(ProgressiveState.learning_started_at).where(*key.where()).with_for_update()
    started = (await conn.execute(locked)).first()
    if started is None or started.learning_started_at is None:
        raise NotLearning(key, "await_approval")
    await _check_key(conn, key, ir)
    await _suspend_waiting(conn, key)
    config_id = await _store(conn, key, ir, validated.report, "pending_approval")
    await learning_awaits_approval(conn, key)
    return config_id


class NotPending(ValueError):
    """The config is not waiting for approval."""


async def _lock_pending(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """Lock `key`'s state, then check that `config_id` is the latest version of its scope and waiting for approval.
    Raises `NotPending` otherwise: a newer version, an operator's correction or a draft, was written knowing it."""
    await lock_state(conn, key)
    configs = ExtractionConfig
    latest = select(func.max(configs.version)).where(*key.config_scope()).scalar_subquery()
    row = select(configs.status, configs.version == latest).where(configs.id == config_id, *key.config_scope())
    found = (await conn.execute(row.with_for_update(of=configs))).first()
    if found is None or found[0] != "pending_approval" or not found[1]:
        raise NotPending(f"config {config_id} is not the latest version waiting for approval")


async def approve(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """Make `config_id`, a config of `key` waiting for approval, the active one (D-1342), suspending the config active
    before it. Raises `NotPending` when it is not `pending_approval` or not its scope's latest version."""
    await _lock_pending(conn, key, config_id)
    await _suspend_active(conn, key)
    await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == config_id).values(status="active"))
    await config_approved(conn, key, config_id)


async def reject(conn: AsyncConnection, key: StateKey, config_id: ExtractionConfigId) -> None:
    """Refuse `config_id`, a config of `key` waiting for approval (D-1391): it is `suspended`, the config active before
    it goes on serving, and the state learns again only after more pages. Raises `NotPending` as `approve` does."""
    await _lock_pending(conn, key, config_id)
    await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == config_id).values(status="suspended"))
    await config_rejected(conn, key)


async def store_correction(
    conn: AsyncConnection,
    key: StateKey,
    corrected: ExtractionConfigIR,
    validated: Validated,
    operated: Collection[str],
) -> ExtractionConfigId:
    """Store an operator's `corrected` config, validated as `validated`, as `key`'s next version, and return its id.
    It is `validated`'s config, active, only when validation kept every field in `operated` (those the operator gave
    steps or confirmed): activating without one would drop the operator's work and suspend the version that served.
    Otherwise it is `corrected` as a `draft`. The caller holds `key`'s state lock (`progressive.lock_state`). Raises
    `ConfigMismatch` like `activate`."""
    await _check_key(conn, key, corrected)
    if validated.ir is None or not set(operated) <= _field_names(validated.ir):
        return await _store(conn, key, corrected, validated.report, "draft")
    await _suspend_active(conn, key)
    await _suspend_waiting(conn, key)  # the operator's config is newer than one waiting for approval (D-1342)
    config_id = await _store(conn, key, validated.ir, validated.report, "active")
    await operator_activated(conn, key, config_id)
    return config_id


def _field_names(ir: ExtractionConfigIR) -> set[str]:
    return set(ir.fields) | (set(ir.listing.fields) if ir.listing is not None else set())


async def _check_key(conn: AsyncConnection, key: StateKey, ir: ExtractionConfigIR) -> None:
    """The config names the state's site, schema and page kind (configs are per schema)."""
    host = select(Site.host).where(Site.id == key.site_id).scalar_subquery()
    schema = select(SchemaDef.name).where(SchemaDef.id == key.schema_id)
    found = (await conn.execute(select(host, schema.scalar_subquery()))).one()
    learned = (ir.site, ir.schema_.name, ir.page_kind)
    if learned != (*found, key.page_kind):
        raise ConfigMismatch(f"config for {learned} activated for progressive_state {key}")
    # A schema is edited in place (D-0950): a config learned before an edit is for another document.
    if ir.schema_.digest != document_digest(await registry.get_by_id(conn, key.schema_id)):
        raise ConfigMismatch(f"config learned for an earlier document of schema {ir.schema_.name} activated for {key}")


async def _suspend_active(conn: AsyncConnection, key: StateKey) -> None:
    # One active config per (site, schema, page kind); the one before is suspended.
    configs = ExtractionConfig
    active = (*key.config_scope(), configs.status == "active")
    await conn.execute(update(configs).where(*active).values(status="suspended"))


async def _suspend_waiting(conn: AsyncConnection, key: StateKey) -> None:
    configs = ExtractionConfig
    waiting = (*key.config_scope(), configs.status == "pending_approval")
    await conn.execute(update(configs).where(*waiting).values(status="suspended"))


async def _store(
    conn: AsyncConnection, key: StateKey, ir: ExtractionConfigIR, report: ValidationReport, status: ConfigStatus
) -> ExtractionConfigId:
    configs = ExtractionConfig
    version = select(func.coalesce(func.max(configs.version), 0) + 1).where(*key.config_scope()).scalar_subquery()
    listed = ir.listing.fields if ir.listing is not None else {}
    statuses = {name: steps.status for name, steps in (*ir.fields.items(), *listed.items())}
    statuses |= dict.fromkeys(ir.absent, "absent")
    stored = insert(configs).values(
        **key.columns(),
        version=version,
        status=status,
        ir=ir.model_dump(mode="json", by_alias=True),
        origin=ir.provenance.origin,
        field_status=statuses,
        validation_report=report.model_dump(mode="json", by_alias=True),
    )
    config_id: ExtractionConfigId = (await conn.execute(stored.returning(configs.id))).scalar_one()
    return config_id
