"""A config's run on one page, indexed once for whoever judges it.

Held-out validation, role A's synthesis and induction (page fields and listing rows) each run a config with the
engine executor and ask the same of the result: a field's candidate on the page or on a row, each row's valid values,
how the config's rows align with the engine's (`row_alignment`), and what the executor refused. Each of them judges
the answers by its own rule; the run and its index are this one.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.collect.config import Refusal, RefusalKind
from crawlerai.config_ir.executor import EngineExecutor, row_id
from crawlerai.config_ir.model import ExtractionConfigIR, Fetch, FieldSteps, ListingSpec, Provenance, SchemaRef
from crawlerai.config_ir.row_alignment import Row, align
from crawlerai.content.page import ParsedPage
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal
from crawlerai.schemas.types import SchemaDef, document_digest


@dataclass(frozen=True, slots=True)
class PageRun:
    """The engine executor's output on one page: its candidates by owner and field, each listing row's valid values in
    document order, and its refusals."""

    candidates: Mapping[tuple[str, str], Candidate]
    row_values: Sequence[Mapping[str, JsonValue]]
    refused: Sequence[Refusal]

    @classmethod
    def of(cls, executor: EngineExecutor, page: ParsedPage, schema: SchemaDef, ctx: Context) -> "PageRun":
        executed = executor.execute(page, schema, ctx)
        candidates = {(c.entity_id, c.field): c for c in executed.candidates}
        rows = [_valid_values(candidates, row_id(n)) for n in range(len(executed.rows))]
        return cls(candidates, rows, executed.refusals)

    @property
    def rows(self) -> int:
        return len(self.row_values)

    def candidate(self, owner: str, name: str) -> Candidate | None:
        return self.candidates.get((owner, name))

    def aligned(self, engine_rows: Sequence[Row], schema: SchemaDef) -> list[int | None]:
        """For each of the engine's rows, the config row it aligns with (`row_alignment`), or None."""
        return align(engine_rows, self.row_values, agreeing(schema))

    def refusals(self, kind: RefusalKind, name: str | None = None) -> list[Refusal]:
        """The refusals of `kind`, those about the field `name` when it is given."""
        return [r for r in self.refused if r.kind == kind and (name is None or r.field == name)]


def _valid_values(candidates: Mapping[tuple[str, str], Candidate], owner: str) -> dict[str, JsonValue]:
    return {
        name: candidate.normalized.value
        for (entity, name), candidate in candidates.items()
        if entity == owner and isinstance(candidate.normalized, Ok)
    }


def agreeing(schema: SchemaDef) -> Callable[[str, JsonValue, JsonValue], bool]:
    """Whether a config's value for a field of `schema` agrees with the value the engine published (`equal`), as rows
    are aligned."""

    def agrees(name: str, value: JsonValue, published: JsonValue) -> bool:
        spec = schema.fields.get(name)
        return spec is not None and equal(value, published, spec)

    return agrees


def trial_config(
    schema: SchemaDef, fields: Mapping[str, FieldSteps], listing: ListingSpec | None = None
) -> ExtractionConfigIR:
    """A config holding only `fields` and `listing`, for the engine executor to run while induction verifies a step."""
    return ExtractionConfigIR(
        ir_version="1",
        site="induction",
        schema_=SchemaRef(name=schema.name, digest=document_digest(schema)),
        page_kind=schema.page_kind,
        fetch=Fetch(method="http"),
        fields=dict(fields),
        listing=listing,
        provenance=Provenance(
            origin="induced", validated_on=[], learned_at=datetime.now(UTC), engine_version=ENGINE_VERSION
        ),
    )
