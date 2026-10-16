"""The admission rule for JSON without standard keys (SPEC-05 §4.5, ARCHITECTURE §8.1): embedded JSON state
(`js_state`) and captured network bodies (`xhr`).

Their keys follow no standard, so no key is mapped to a field. Every string and number in a document is tried against
each field's normalizer, the only filter, and becomes a candidate only when:
- the field has candidates from another source kind and the value is `equal` to one of them (SPEC-04 §4.5). It is
  then owned by that candidate's entity and is not independent: it agrees with a value it was admitted for, so it
  never counts toward `agreed` (§10);
- the field has no candidate from another source kind, its type has a syntax the normalizer checks
  (`normalize.dispatch.checkable`: money, enum, date, location, range, a check-digit identifier, an absolute URL), and
  the value is visible in the page text. It is then owned by the page, like other page-level values, and is
  independent. Text and other opaque types admit by equality only: any visible string normalizes as text, so
  visibility alone says nothing of which field a leaf is (owner, accuracy Q2 option a).

A field with candidates from other kinds admits values only by equality ("leaves are considered only for fields still
lacking a candidate or for agreement checks"), so a value both equal and visible is not independent.
"""

from collections.abc import Hashable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.json_doc import scalars
from crawlerai.collect.locator import format_locator
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import checkable, equal, equality_key, normalize
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


@dataclass(slots=True)
class _FieldAnchors:
    """One field's anchors, and their owners by equality key (`normalize.dispatch.equality_key`), built once per page:
    a value then finds the owners of its equal anchors with one key lookup, not one equality test per anchor. `keyed`
    is False when some anchor has no key (the field's equality is no equivalence, as location's): its values are then
    compared with every anchor."""

    anchors: list[_Anchor] = field(default_factory=list)
    owners_by_key: dict[Hashable, list[str]] = field(default_factory=dict)
    keyed: bool = True

    def add(self, anchor: _Anchor, spec: FieldSpec) -> None:
        self.anchors.append(anchor)
        if not self.keyed:
            return
        key = equality_key(anchor.value, spec)
        if key is None:
            self.keyed = False
            return
        owners = self.owners_by_key.setdefault(key, [])
        if anchor.entity_id not in owners:
            owners.append(anchor.entity_id)

    def owners(self, value: JsonValue, spec: FieldSpec) -> list[str]:
        """The owners of the anchors `equal` to `value`, each once, in anchor order."""
        key = equality_key(value, spec) if self.keyed else None
        if key is not None:
            return self.owners_by_key.get(key, [])
        return list(dict.fromkeys(a.entity_id for a in self.anchors if equal(value, a.value, spec)))


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
    anchors = _anchors(others, kind, schema)
    # What a value admits depends on the value alone, so a value repeated across the documents is read once.
    readings: dict[tuple[type, str | int | float], tuple[_Reading, ...]] = {}
    candidates: list[Candidate] = []
    for document in documents:
        for path, raw in scalars(document.data):
            key = (type(raw), raw)
            if key not in readings:
                readings[key] = tuple(_readings(raw, page, schema, ctx, anchors))
            locator = format_locator(kind, document.address, path)
            candidates.extend(
                Candidate(
                    field=reading.field,
                    entity_id=reading.owner,
                    source_kind=kind,
                    raw=raw,
                    normalized=reading.normalized,
                    locator=locator,
                    independent=reading.independent,
                )
                for reading in readings[key]
            )
    return Admitted(candidates=tuple(candidates), diagnostics=tuple(diagnostics))


@dataclass(frozen=True, slots=True)
class _Reading:
    """One admission of a value: its field, its normalized form, its owner and whether it is independent."""

    field: str
    normalized: Ok
    owner: str
    independent: bool


def _readings(
    raw: str | int | float,
    page: ParsedPage,
    schema: SchemaDef,
    ctx: Context,
    anchors: Mapping[str, _FieldAnchors],
) -> Iterator[_Reading]:
    # The same for every field, so computed at most once, and only when a field needs it.
    visible = cache(lambda: page.visible_values.visible(str(raw)))
    for name, spec in schema.fields.items():
        field_anchors = anchors.get(name)
        if field_anchors is None and not (checkable(raw, spec) and visible()):
            continue
        normalized = normalize(raw, spec, ctx)
        if isinstance(normalized, Ok):
            for owner, independent in _owners(normalized.value, spec, field_anchors):
                yield _Reading(name, normalized, owner, independent)


def _owners(value: JsonValue, spec: FieldSpec, anchors: _FieldAnchors | None) -> Iterator[tuple[str, bool]]:
    """Who owns an admitted value and whether it is independent: the page for a visible value of a field without
    anchors; else each owner of an equal anchor once, in the order of `others`."""
    if anchors is None:
        yield PAGE, True
        return
    for owner in anchors.owners(value, spec):
        yield owner, False


def _anchors(others: Sequence[Candidate], kind: StateKind, schema: SchemaDef) -> Mapping[str, _FieldAnchors]:
    """Each schema field's normalized values from another source kind, with their owners. A candidate that did not
    normalize still gives its field an entry, so the field admits by equality only (the conservative reading of
    "lacking a candidate")."""
    anchors: dict[str, _FieldAnchors] = {}
    for other in others:
        spec = schema.fields.get(other.field)
        if other.source_kind != kind and spec is not None:
            field_anchors = anchors.setdefault(other.field, _FieldAnchors())
            if isinstance(other.normalized, Ok):
                field_anchors.add(_Anchor(other.entity_id, other.normalized.value), spec)
    return anchors
