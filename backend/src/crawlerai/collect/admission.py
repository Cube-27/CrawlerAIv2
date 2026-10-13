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
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.collect.json_doc import scalars
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import VisibleIndex
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.schemas.types import FieldSpec, SchemaDef

# The page entity, which every page-level value belongs to (SPEC-05 §4.6).
PAGE = "page"


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
    """One parsed JSON document and the locator prefix that addresses it (`js_state:<script_xpath>`, `xhr:<n>`)."""

    data: JsonValue
    prefix: str


def admit(
    documents: Sequence[Document],
    source_kind: SourceKind,
    schema: SchemaDef,
    ctx: Context,
    page: ParsedPage,
    others: Sequence[Candidate],
) -> Iterator[Candidate]:
    """The candidates of `documents` under the rule above, in document order, then schema field order; one per value,
    field and owner."""
    anchors = _anchors(others, source_kind)
    for document in documents:
        for path, raw in scalars(document.data):
            for name, spec in schema.fields.items():
                normalized = normalize(raw, spec, ctx)
                if not isinstance(normalized, Ok):
                    continue
                for owner, independent in _owners(raw, normalized.value, spec, anchors.get(name), page.visible_values):
                    yield Candidate(
                        field=name,
                        entity_id=owner,
                        source_kind=source_kind,
                        raw=raw,
                        normalized=normalized,
                        locator=f"{document.prefix}:{path}",
                        independent=independent,
                    )


def _anchors(others: Sequence[Candidate], source_kind: SourceKind) -> Mapping[str, list[Candidate]]:
    """Each field's candidates from another source kind. One that did not normalize still gives its field a
    candidate, so the field admits by equality only (the conservative reading of "lacking a candidate")."""
    anchors: dict[str, list[Candidate]] = {}
    for other in others:
        if other.source_kind != source_kind:
            anchors.setdefault(other.field, []).append(other)
    return anchors


def _owners(
    raw: str | int | float, value: JsonValue, spec: FieldSpec, anchors: list[Candidate] | None, visible: VisibleIndex
) -> Iterator[tuple[str, bool]]:
    """Who owns an admitted value, and whether it is independent; nothing when the value is not admitted."""
    if anchors is None:
        if visible.visible(str(raw)):
            yield PAGE, True
        return
    equals = (a for a in anchors if isinstance(a.normalized, Ok) and equal(value, a.normalized.value, spec))
    for owner in dict.fromkeys(a.entity_id for a in equals):  # each owner once, in the order of `others`
        yield owner, False
