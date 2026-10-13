"""Activation (SPEC-08 §4.8, ARCHITECTURE §8.3 step 5): a validated config is stored as the next version of its (site,
schema, page kind) config, `active`, with its field statuses and `validation_report`; the config active before it is
`suspended`, and the learning run in flight ends with the state `active` on the new config.

Only a `Validated` with a config activates: nothing activates without validation (§4.13). Everything runs on the
caller's connection, in its transaction, so a run that cannot end (`NotLearning`) stores nothing.
"""

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.executor import ConfigMismatch
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.progressive import NotLearning, StateKey, learning_activated
from crawlerai.config_ir.validation import Validated, ValidationReport
from crawlerai.db.models import ExtractionConfig, ExtractionConfigId, ProgressiveState, SchemaDef, Site


class NotValidated(ValueError):
    """Validation kept no config to activate."""


async def activate(conn: AsyncConnection, key: StateKey, validated: Validated) -> ExtractionConfigId:
    """Store `validated`'s config for `key` as active and end `key`'s learning run with it; its id. Raises
    `NotValidated` when validation refused the config, `ConfigMismatch` when the config was learned for another site,
    schema version or page kind, and `NotLearning` when no learning run is in flight for `key`."""
    ir = validated.ir
    if ir is None:
        raise NotValidated(f"progressive_state {key}: validation refused the config ({validated.report.refused})")
    # One activation per state at a time: the row lock orders them, so versions are taken one after another.
    locked = select(ProgressiveState.learning_started_at).where(*key.where()).with_for_update()
    started = (await conn.execute(locked)).first()
    if started is None or started.learning_started_at is None:
        raise NotLearning(key, "activate")
    await _check_key(conn, key, ir)
    config_id = await _store(conn, key, ir, validated.report)
    await learning_activated(conn, key, config_id)
    return config_id


async def _check_key(conn: AsyncConnection, key: StateKey, ir: ExtractionConfigIR) -> None:
    """The config names the state's site, schema version and page kind (ARCHITECTURE §5.2, §6: configs are per schema
    version)."""
    host = select(Site.host).where(Site.id == key.site_id).scalar_subquery()
    schema = select(SchemaDef.name).where(SchemaDef.id == key.schema_id, SchemaDef.version == key.schema_version)
    found = (await conn.execute(select(host, schema.scalar_subquery()))).one()
    learned = (ir.site, ir.schema_.name, ir.schema_.version, ir.page_kind)
    if learned != (*found, key.schema_version, key.page_kind):
        raise ConfigMismatch(f"config for {learned} activated for progressive_state {key}")


async def _store(
    conn: AsyncConnection, key: StateKey, ir: ExtractionConfigIR, report: ValidationReport
) -> ExtractionConfigId:
    configs = ExtractionConfig
    scope = (configs.site_id == key.site_id, configs.schema_id == key.schema_id, configs.page_kind == key.page_kind)
    # ARCHITECTURE §6: one active config per (site, schema, page kind); the one before is suspended.
    await conn.execute(update(configs).where(*scope, configs.status == "active").values(status="suspended"))
    version = select(func.coalesce(func.max(configs.version), 0) + 1).where(*scope).scalar_subquery()
    listed = ir.listing.fields if ir.listing is not None else {}
    statuses = {name: steps.status for name, steps in (*ir.fields.items(), *listed.items())}
    stored = insert(configs).values(
        **key.columns(),
        version=version,
        status="active",
        ir=ir.model_dump(mode="json", by_alias=True),
        origin=ir.provenance.origin,
        field_status=statuses,
        validation_report=report.model_dump(mode="json", by_alias=True),
    )
    config_id: ExtractionConfigId = (await conn.execute(stored.returning(configs.id))).scalar_one()
    return config_id
