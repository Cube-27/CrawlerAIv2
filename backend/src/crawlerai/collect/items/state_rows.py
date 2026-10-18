"""Rows from the page's state JSON (listings spec, "Rows from page state"): a listing whose items the page holds in
embedded state (`collect.js_state`) but whose blocks give no rows still gets one row per item.

A row source is a JSON array of `MIN_ITEMS` or more objects. Each row field is read at one path relative to a row,
induced across the array's rows (`collect.induce`, quorum `MIN_ITEMS`): a path a row proposes for a field when
- for the item URL (`is_item_url`): its value is the target of one of the page's rendered hyperlinks (HTML Standard
  §4.6.1), or the path's own member names the field and its value normalizes as a URL;
- for any other field: the path's own member (its first name segment) names the field, by the field's name or the
  schema.org property its path reaches (`named_property`), compared without case or separators; and its value
  normalizes as the field's type and is shown in the page text (`content.text.VisibleIndex`), or, for an image, which
  the text never shows, normalizes as an image URL.
Key names are the schema's own words, never a list kept for a site (C2, C4); the page's shown text and links ground
every value, so a state value is one the page renders (INV-12's rule for role C, applied to state).

A row is kept only when it is grounded: its item URL is the target of a rendered hyperlink, or its name is shown. An
array whose grounded rows are fewer than `MIN_ITEMS`, or that has no item URL path, gives none. Arrays inside a row
source are the row's own data, not further sources; a row whose item URL an earlier row has is not read again (a blob
caching one list twice). Each row is an `array_row` entity `js_state:<script xpath>:<row path>`, and each value a
`js_state` candidate, whose evidence bucket is `state` (resolution spec).
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.collect import json_doc
from crawlerai.collect.admission import Document
from crawlerai.collect.base import ARRAY_ROW, Candidate, Entity
from crawlerai.collect.induce import induced
from crawlerai.collect.items.align import field_roles
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, is_item_url, named_property, parse_paths
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import page_links
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.normalize.url import canonical_url
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

Scalar = str | int | float
_KIND: Final = "js_state"
# A member name's letters and digits: `product_url`, `productUrl` and `ProductURL` name one thing.
_SEPARATORS = re.compile(r"[\W_]+")
_FIRST_MEMBER = re.compile(r"\['([^'\\]+)'\]")


@dataclass(frozen=True, slots=True)
class StateRows:
    """The rows read from the page's state JSON, their candidates and what the reader reports."""

    rows: tuple[Entity, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    diagnostics: tuple[str, ...] = ()


def state_rows(page: ParsedPage, documents: Sequence[Document], schema: SchemaDef, ctx: Context) -> StateRows:
    """The listing's rows held in its state `documents` (module docstring); none for a detail schema or a schema without
    an item URL field."""
    url_fields = [name for name, spec in schema.fields.items() if is_item_url(spec)]
    if schema.page_kind != "listing" or not url_fields:
        return StateRows()
    reader = _Reader(page, schema, ctx, url_fields[0])
    rows: list[Entity] = []
    candidates: list[Candidate] = []
    notes: list[str] = []
    for document in documents:
        sources: list[str] = []
        for path, value in json_doc.nodes(document.data):
            if not isinstance(value, list) or any(path.startswith(f"{source}[") for source in sources):
                continue
            objects: list[tuple[str, JsonValue]] = [
                (f"{path}[{i}]", item) for i, item in enumerate(value) if isinstance(item, dict)
            ]
            if len(objects) < MIN_ITEMS or (read := reader.read(document.address, objects)) is None:
                continue
            sources.append(path)
            rows.extend(read.rows)
            candidates.extend(read.candidates)
            notes.extend(read.diagnostics)
    return StateRows(tuple(rows), tuple(candidates), tuple(notes))


class _Reader:
    """One page's state arrays read as rows, the item URLs already read kept across them."""

    def __init__(self, page: ParsedPage, schema: SchemaDef, ctx: Context, url_field: str) -> None:
        self.page = page
        self.schema = schema
        self.ctx = ctx
        self.url_field = url_field
        self.names = {name for name, role in field_roles(schema).items() if role == "name"}
        self.row_fields = {name: spec for name, spec in schema.fields.items() if spec.scope == "row"}
        self.links = page_links(page.lxml_tree, ctx.base_url)
        self.read_urls: set[str] = set()
        self._words = {name: _field_words(name, spec) for name, spec in self.row_fields.items()}

    def read(self, address: str, objects: Sequence[tuple[str, JsonValue]]) -> StateRows | None:
        rows = [(path, dict(json_doc.scalars(item))) for path, item in objects]
        keys = {
            name: key
            for name in self.row_fields
            if (key := induced([list(self._proposed(name, row)) for _, row in rows], MIN_ITEMS)) is not None
        }
        if self.url_field not in keys:
            return None
        made: list[tuple[Entity, list[Candidate]]] = []
        notes: list[str] = []
        for path, row in rows:
            found = self._row(address, path, row, keys, notes)
            if found is not None:
                made.append(found)
        if len(made) < MIN_ITEMS:
            return None
        fresh = [(entity, values) for entity, values in made if self._new(values)]
        notes.append(f"item layer: {len(fresh)} rows from page state, fields: {sorted(keys)}")
        return StateRows(
            tuple(entity for entity, _ in fresh), tuple(c for _, values in fresh for c in values), tuple(notes)
        )

    def _proposed(self, name: str, row: Mapping[str, Scalar]) -> Iterator[str]:
        return (path for path, raw in row.items() if json_doc.is_query(path) and self._reads(name, path, raw))

    def _reads(self, name: str, path: str, raw: Scalar) -> bool:
        """Whether a row's `raw` at `path` is a grounded value of the field `name` (module docstring)."""
        spec = self.row_fields[name]
        if name == self.url_field and self._linked(raw):
            return True
        if not self._named(name, path) or not isinstance(normalize(raw, spec, self.ctx), Ok):
            return False
        return spec.type in (FieldType.URL, FieldType.IMAGE_URL) or self.page.visible_values.visible(str(raw))

    def _linked(self, raw: Scalar) -> bool:
        return isinstance(raw, str) and canonical_url(raw, self.ctx.base_url) in self.links

    def _named(self, name: str, path: str) -> bool:
        first = _FIRST_MEMBER.match(path, len(json_doc.ROOT))
        return first is not None and _word(first.group(1)) in self._words[name]

    def _row(
        self, address: str, path: str, row: Mapping[str, Scalar], keys: Mapping[str, str], notes: list[str]
    ) -> tuple[Entity, list[Candidate]] | None:
        """The row's entity and its grounded values; None when the row is not grounded (module docstring)."""
        owner = f"{_KIND}:{address}:{path}"
        values: list[Candidate] = []
        grounded = False
        for name, key in keys.items():
            raw = row.get(key)
            if raw is None or not self._reads(name, key, raw):
                continue
            locator = format_locator(_KIND, address, path + key[len(json_doc.ROOT) :])
            made = candidate(name, self.row_fields[name], owner, _KIND, raw, locator, self.ctx, notes)
            if made is not None:
                values.append(made)
                grounded |= (name == self.url_field and self._linked(raw)) or name in self.names
        if not grounded or not any(c.field == self.url_field for c in values):
            return None
        return Entity(id=owner, types=(ARRAY_ROW,), urls=(), parent=None), values

    def _new(self, values: Sequence[Candidate]) -> bool:
        urls = {c.normalized.value for c in values if c.field == self.url_field and isinstance(c.normalized, Ok)}
        url = next(iter(urls), None)
        if not isinstance(url, str) or url in self.read_urls:
            return False
        self.read_urls.add(url)
        return True


def _field_words(name: str, spec: FieldSpec) -> frozenset[str]:
    """The words naming a field: its own name and the schema.org properties its path reaches."""
    properties = [named_property(path) for path in parse_paths(spec.schema_org)] if spec.schema_org else []
    return frozenset(_word(word) for word in (name, *properties))


def _word(name: str) -> str:
    return _SEPARATORS.sub("", name).casefold()
