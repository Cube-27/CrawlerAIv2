"""The admission rule for JSON without standard keys (SPEC-05 §4.5, ARCHITECTURE §8.1): embedded JSON state
(`js_state`) and captured network bodies (`xhr`).

Their keys follow no standard, so no key is mapped to a field. Every string and number in a document is tried against
each field's normalizer, the only filter, and becomes a candidate only when:
- the field has candidates from another source kind and the value is `equal` to one of them (SPEC-04 §4.5). It is
  then owned by that candidate's entity and is not independent: it agrees with a value it was admitted for, so it
  never counts toward `agreed` (§10);
- the field has no candidate from another source kind and the value is visible in the page text. It is then owned by
  the page, like other page-level values, and is independent.

A field with candidates from other kinds admits values only by equality ("leaves are considered only for fields still
lacking a candidate or for agreement checks"), so a value both equal and visible is not independent.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.json_doc import scalars
from crawlerai.collect.locator import format_locator
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.schemas.types import FieldSpec, SchemaDef

StateKind = Literal["js_state", "xhr"]


class Admitted(BaseModel):
    """The candidates a `js_state` or `xhr` collector admitted. They name the entities of the candidates they equal,
    or `page`, so they carry no entities of their own."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidates: tuple[Candidate, ...]
    diagnostics: tuple[str, ...] = ()


class AdmittingCollector(Protocol):
    """A collector whose values are admitted against `others`: the candidates every other collector proposed for the
    page (§8.1). It reads the `ParsedPage` only (INV-26) and never raises on page content."""

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]) -> Admitted: ...


@dataclass(frozen=True, slots=True)
class Document:
    """One parsed JSON document and the locator part that addresses it (a script's XPath, a body's index)."""

    data: JsonValue
    address: str


@dataclass(frozen=True, slots=True)
class _Anchor:
    entity_id: str
    value: JsonValue


def admit(
    kind: StateKind,
    documents: Sequence[Document],
    diagnostics: Sequence[str],
    page: ParsedPage,
    schema: SchemaDef,
    ctx: Context,
    others: Sequence[Candidate],
) -> Admitted:
    """The candidates of `documents` under the rule above, in document order, then schema field order; one per value,
    field and owner."""
    anchors = _anchors(others, kind)
    candidates: list[Candidate] = []
    for document in documents:
        for path, raw in scalars(document.data):
            locator = format_locator(kind, document.address, path)
            candidates.extend(_admitted(kind, raw, locator, page, schema, ctx, anchors))
    return Admitted(candidates=tuple(candidates), diagnostics=tuple(diagnostics))


def _admitted(
    kind: StateKind,
    raw: str | int | float,
    locator: str,
    page: ParsedPage,
    schema: SchemaDef,
    ctx: Context,
    anchors: Mapping[str, list[_Anchor]],
) -> Iterator[Candidate]:
    visible: bool | None = None  # the same for every field, so computed at most once, and only when needed
    for name, spec in schema.fields.items():
        field_anchors = anchors.get(name)
        if field_anchors is None:
            visible = page.visible_values.visible(str(raw)) if visible is None else visible
            if not visible:
                continue
        normalized = normalize(raw, spec, ctx)
        if isinstance(normalized, Ok):
            for owner, independent in _owners(normalized.value, spec, field_anchors):
                yield Candidate(
                    field=name,
                    entity_id=owner,
                    source_kind=kind,
                    raw=raw,
                    normalized=normalized,
                    locator=locator,
                    independent=independent,
                )


def _owners(value: JsonValue, spec: FieldSpec, anchors: list[_Anchor] | None) -> Iterator[tuple[str, bool]]:
    """Who owns an admitted value and whether it is independent: the page for a visible value of a field without
    anchors; else each owner of an equal anchor once, in the order of `others`."""
    if anchors is None:
        yield PAGE, True
        return
    for owner in dict.fromkeys(a.entity_id for a in anchors if equal(value, a.value, spec)):
        yield owner, False


def _anchors(others: Sequence[Candidate], kind: StateKind) -> Mapping[str, list[_Anchor]]:
    """Each field's normalized values from another source kind, with their owners. A candidate that did not normalize
    still gives its field an entry, so the field admits by equality only (the conservative reading of "lacking a
    candidate")."""
    anchors: dict[str, list[_Anchor]] = {}
    for other in others:
        if other.source_kind != kind:
            field = anchors.setdefault(other.field, [])
            if isinstance(other.normalized, Ok):
                field.append(_Anchor(other.entity_id, other.normalized.value))
    return anchors
