"""Drift (SPEC-08 §4.9, ARCHITECTURE §8.3): each page an active config runs on adds, per field, whether a step
matched and whether the value was valid to a rolling window of the config's last `WINDOW_PAGES` pages. A field whose
windowed yield or validity falls below its validated one (the IR's `yield`/`validity`, the held-out values of the
validation report, §4.7) less the dev-fitted margin is `suspended`: the executor no longer runs it, so its pages fall
back to cold-mode resolution, and the site re-learns.

`record_run` does this for one page in the database, under a row lock on the config: it stores the window
(`extraction_config.drift_window`), suspends the fields that drifted in both the IR and `field_status`, logs a
`drift_suspended` job event per field and starts a forced learning run (`progressive.request_learning`).

The margins are `backend/data/drift_margins.json`, stamped `source_split: dev` (INV-02) and with how they were
obtained: until labels exist, SPEC-08 §4.9's values, stamped "spec default, unfitted" (D-0576). Without the file
nothing is suspended (C7: no default margin); windows are still recorded.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.config_ir.model import ExtractionConfigIR, FieldSteps
from crawlerai.config_ir.progressive import StateKey, request_learning
from crawlerai.db.jobs import record_event
from crawlerai.db.models import ExtractionConfig, ExtractionConfigId, JobId
from crawlerai.normalize.base import Ok

# SPEC-08 §4.9: the window is the config's last 50 pages.
WINDOW_PAGES: Final = 50
# ARCHITECTURE §8.3: the validated yield and validity are measured on at least 3 held-out pages; a window is compared
# with them once it is as large.
MIN_WINDOW_PAGES: Final = 3
MARGINS_FILE: Final = "drift_margins.json"
DRIFT_SUSPENDED: Final = "drift_suspended"


class DriftMargins(BaseModel):
    """How far below its validated yield and validity a field's windowed ones may fall (§4.9), fitted on dev."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_by_name=True)

    yield_: Annotated[float, Field(ge=0, le=1, alias="yield")]
    validity: Annotated[float, Field(ge=0, le=1)]
    source_split: Literal["dev"]
    # How the margins were obtained, so spec defaults are never taken for values fitted on labels (D-0576).
    fit: Annotated[str, Field(min_length=1)]


def load_margins(path: Path) -> DriftMargins | None:
    """The margins at `path`, stamped `source_split: dev` (INV-02); `None` when none were fitted."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return DriftMargins.model_validate_json(text)


@dataclass(frozen=True, slots=True)
class Observation:
    """One page's run of a field: a step matched, and the value it proposed was valid."""

    matched: bool
    valid: bool


Window = dict[str, list[Observation]]
_STORED: Final = TypeAdapter(dict[str, list[tuple[bool, bool]]])


@dataclass(frozen=True, slots=True)
class Drifted:
    """A field whose window fell below its validated yield or validity less the margins."""

    field: str
    pages: int
    yield_: float
    validity: float | None  # None: no page in the window matched


def _running(ir: ExtractionConfigIR) -> Iterable[tuple[str, FieldSteps, bool]]:
    """Each field the executor runs, its steps, and whether it is a listing row field."""
    listed = ir.listing.fields if ir.listing is not None else {}
    for fields, in_row in ((ir.fields, False), (listed, True)):
        for name, steps in fields.items():
            if steps.status != "suspended":
                yield name, steps, in_row


def observe(ir: ExtractionConfigIR, candidates: Sequence[Candidate]) -> dict[str, Observation]:
    """What one page's run of `ir`, the `config` candidates it proposed, shows for each field that ran. A row field
    matched when any row has its value, and is valid when every row's value is."""
    observed: dict[str, Observation] = {}
    for name, _, in_row in _running(ir):
        found = [
            c for c in candidates if c.source_kind == "config" and c.field == name and (c.entity_id != PAGE) == in_row
        ]
        observed[name] = Observation(
            matched=bool(found), valid=bool(found) and all(isinstance(c.normalized, Ok) for c in found)
        )
    return observed


def extend(window: Mapping[str, Sequence[Observation]], observed: Mapping[str, Observation]) -> Window:
    """`window` with one page's observations added, each field keeping its last `WINDOW_PAGES` pages."""
    extended = {name: list(pages) for name, pages in window.items()}
    for name, observation in observed.items():
        extended[name] = [*extended.get(name, []), observation][-WINDOW_PAGES:]
    return extended


def _measure(name: str, pages: Sequence[Observation]) -> Drifted:
    matched = sum(page.matched for page in pages)
    valid = sum(page.valid for page in pages)
    return Drifted(name, len(pages), matched / len(pages), valid / matched if matched else None)


def _below(measured: Drifted, steps: FieldSteps, margins: DriftMargins) -> bool:
    if steps.yield_ is not None and measured.yield_ < steps.yield_ - margins.yield_:
        return True
    validity = measured.validity
    return steps.validity is not None and validity is not None and validity < steps.validity - margins.validity


def drifted(
    ir: ExtractionConfigIR, window: Mapping[str, Sequence[Observation]], margins: DriftMargins
) -> list[Drifted]:
    """The running fields of `ir` whose windowed yield or validity is below the validated one less `margins`."""
    found: list[Drifted] = []
    for name, steps, _ in _running(ir):
        pages = window.get(name, ())
        if len(pages) >= MIN_WINDOW_PAGES and _below(measured := _measure(name, pages), steps, margins):
            found.append(measured)
    return found


def suspend(ir: ExtractionConfigIR, names: Iterable[str]) -> ExtractionConfigIR:
    """`ir` with the fields `names` `suspended`."""
    names = set(names)

    def _suspended(fields: Mapping[str, FieldSteps]) -> dict[str, FieldSteps]:
        return {n: s.model_copy(update={"status": "suspended"}) if n in names else s for n, s in fields.items()}

    listing = ir.listing
    if listing is not None:
        listing = listing.model_copy(update={"fields": _suspended(listing.fields)})
    return ir.model_copy(update={"fields": _suspended(ir.fields), "listing": listing})


def _load_window(stored: Mapping[str, object]) -> Window:
    return {name: [Observation(*page) for page in pages] for name, pages in _STORED.validate_python(stored).items()}


def _dump_window(window: Window) -> dict[str, list[list[bool]]]:
    return {name: [[page.matched, page.valid] for page in pages] for name, pages in window.items()}


async def record_run(
    conn: AsyncConnection,
    config_id: ExtractionConfigId,
    candidates: Sequence[Candidate],
    *,
    margins: DriftMargins | None,
    job_id: JobId,
) -> list[Drifted]:
    """Add one page's run of the active config `config_id`, the `config` candidates it proposed, to its window,
    suspend the fields that drifted, and return them. A config that is no longer active records nothing."""
    config = (
        await conn.execute(
            select(ExtractionConfig)
            .where(ExtractionConfig.id == config_id, ExtractionConfig.status == "active")
            .with_for_update()
        )
    ).one_or_none()
    if config is None:
        return []
    ir = ExtractionConfigIR.model_validate(config.ir)
    window = extend(_load_window(config.drift_window), observe(ir, candidates))
    found = drifted(ir, window, margins) if margins is not None else []
    values: dict[str, object] = {"drift_window": _dump_window(window)}
    if found:
        names = [d.field for d in found]
        values["ir"] = suspend(ir, names).model_dump(mode="json")
        values["field_status"] = {**config.field_status, **dict.fromkeys(names, "suspended")}
    await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == config_id).values(**values))
    if found:
        validated = {name: steps for name, steps, _ in _running(ir)}
        for measured in found:
            await record_event(conn, job_id, DRIFT_SUSPENDED, _event(config_id, measured, validated[measured.field]))
        key = StateKey(config.site_id, config.schema_id, config.page_kind)
        await request_learning(conn, key, force=True)
    return found


def _event(config_id: ExtractionConfigId, measured: Drifted, steps: FieldSteps) -> dict[str, object]:
    return {
        "config_id": str(config_id),
        "field": measured.field,
        "pages": measured.pages,
        "yield": measured.yield_,
        "validity": measured.validity,
        "validated_yield": steps.yield_,
        "validated_validity": steps.validity,
    }
