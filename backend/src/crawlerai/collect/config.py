"""The config collector's interface (extraction spec, learning-configs spec): an active config proposes
`source_kind='config'` candidates like any other collector, and they enter resolution with the rest (§8.4).

The engine executor lives in `crawlerai.config_ir`, which sits above `collect` and `resolve` (`.importlinter`), so the
pipeline takes the executor already bound to its config and never names the IR type: learning-configs spec injects it.
"""

from collections.abc import Mapping
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from crawlerai.collect.base import PAGE, Candidate, Entity
from crawlerai.collect.network_match import LearnedCalls
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import FieldStatus
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

# schema.org: a ListItem is an item in a list, the kind of a listing's row.
ROW_KIND = "ListItem"


class Executed(BaseModel):
    """What a config proposed for one page. Its page-level candidates are owned by `page`, which the OpenGraph collector
    or the entity graph provides, so the only entities here are a listing's rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows: tuple[Entity, ...]
    candidates: tuple[Candidate, ...]
    # Steps that could not run (a selector the engine refuses at run time); a value that did not match is no diagnostic.
    diagnostics: tuple[str, ...] = ()

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
    """An active config bound to its IR. It reads the `ParsedPage` only (INV-26) and never raises on page content."""

    @property
    def field_status(self) -> Mapping[str, FieldStatus]:
        """The status of each field it runs (`suspended` fields do not run, §8.3), and of each field it lists as
        `absent` (D-1341): resolution reads it for the `config_corroborated` / `config_uncorroborated` bucket (§10), and
        the pipeline for the fields role C may still fill (§8.4)."""
        ...

    @property
    def learned_calls(self) -> LearnedCalls | None:
        """The calls of a learned listing recipe's endpoint, which the `xhr` collector reads with the recipe's map on
        a page the recipe did not serve (Appendix A #59); None without one."""
        ...

    def execute(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> Executed: ...
