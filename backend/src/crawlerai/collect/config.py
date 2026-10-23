"""The config collector's interface: an active config proposes
`source_kind='config'` candidates like any other collector, and they enter resolution with the rest.

The engine executor lives in `crawlerai.config_ir`, which sits above `collect` and `resolve` (`.importlinter`), so the
pipeline takes the executor already bound to its config and never names the IR type: config learning injects it.
"""

from collections.abc import Mapping
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from crawlerai.collect.base import PAGE, Candidate, Entity
from crawlerai.collect.network_match import LearnedCalls
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import FieldStatus
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

# schema.org: a ListItem is an item in a list, the kind of a listing's row.
ROW_KIND = "ListItem"

# What a refusal is about: the whole document, a field the schema does not have, one step of a field, the row selector.
RefusalKind = Literal["document", "field", "step", "row"]


class Refusal(BaseModel):
    """Something a mapped source could not run on the page: `source` is its locator scheme and address (`config`,
    `api:<recipe id>`), `field` the field a `field` or `step` refusal is about, `step` a step's index in its field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RefusalKind
    source: str
    field: str | None = None
    step: int | None = None
    reason: str

    def rendered(self) -> str:
        """`<source>: ...`, `<source>:<field>: ...`, `<source>:<field>:<step>: ...` or `<source>:row: ...`."""
        about = {"document": (), "field": (self.field,), "step": (self.field, str(self.step)), "row": ("row",)}
        return ":".join((self.source, *(part for part in about[self.kind] if part is not None))) + f": {self.reason}"


class Executed(BaseModel):
    """What a config proposed for one page. Its page-level candidates are owned by `page`, which the OpenGraph collector
    or the entity graph provides, so the only entities here are a listing's rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows: tuple[Entity, ...]
    candidates: tuple[Candidate, ...]
    # What could not run (a selector the engine refuses at run time); a value that did not match is no refusal.
    refusals: tuple[Refusal, ...] = ()
    # Other notes on the page's values (a value its normalizer declined to read).
    notes: tuple[str, ...] = ()

    @property
    def diagnostics(self) -> tuple[str, ...]:
        """The refusals rendered, then the notes."""
        return (*(refusal.rendered() for refusal in self.refusals), *self.notes)

    @model_validator(mode="after")
    def _owners_resolve(self) -> Self:
        ids = {row.id for row in self.rows}
        if len(ids) != len(self.rows) or PAGE in ids:
            raise ValueError("row ids are unique and none is the page")
        if any(row.parent is not None for row in self.rows):
            raise ValueError("a row is a root entity")
        for candidate in self.candidates:
            if candidate.entity_id != PAGE and candidate.entity_id not in ids:
                raise ValueError(f"candidate for {candidate.field!r} names unknown entity {candidate.entity_id!r}")
        return self


class ConfigExecutor(Protocol):
    """An active config bound to its IR. It reads the `ParsedPage` only and never raises on page content."""

    @property
    def field_status(self) -> Mapping[str, FieldStatus]:
        """The status of each field it runs (`suspended` fields do not run), and of each field it lists as
        `absent`: resolution reads it for the `config_corroborated` / `config_uncorroborated` bucket, and
        the pipeline for the fields role C may still fill."""
        ...

    @property
    def browser_fields(self) -> frozenset[str]:
        """The fields whose located source is the browser (`needs: browser`): a page not rendered cannot carry them, so
        each one missing from it is `interaction_required`."""
        ...

    @property
    def learned_calls(self) -> LearnedCalls | None:
        """The calls of a learned listing recipe's endpoint, which the `xhr` collector reads with the recipe's map on
        a page the recipe did not serve (Appendix A #59); None without one."""
        ...

    def execute(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> Executed: ...
