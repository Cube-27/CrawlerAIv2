"""Rows from the page's state JSON: a listing whose items the page holds in
embedded state (`collect.js_state`) but whose blocks give no rows still gets one row per item.

A row source is a JSON array of `MIN_ITEMS` or more objects. Each row field is read at one path relative to a row,
induced across the array's rows (`collect.array_rows`): a path a row proposes for a field when
- for the item URL (`is_item_url`): its value is the target of one of the rendered hyperlinks of the page's content
  (HTML Standard §4.6.1; `content_links`, the site's navigation, header, footer and menus left out: a state tree of
  the site's menu is grounded by the menu's links, not by any listing), or the path's own member names the field and
  its value normalizes as a URL;
- for any other field: the path's own member (its first name segment) names the field, by the field's name or the
  schema.org property its path reaches (`named_property`), compared without case or separators; and its value
  normalizes as the field's type and is shown in the page text (`content.text.VisibleIndex`); for another URL field,
  is a rendered hyperlink's target; for an image, which the text never shows, normalizes as an image URL.
Key names are the schema's own words, never a list kept for a site (C2, C4); the page's shown text and links ground
every value, so a state value is one the page renders (the rule for role C, applied to state).

A row is kept only when it is grounded: its item URL is the target of a rendered hyperlink, or its name is shown. An
array whose grounded rows are fewer than `MIN_ITEMS`, or that has no item URL path, gives none; nor does the site's
menu tree (`_menu`): an array that reads no typed value (a price, a date) and more than half of whose rows' items are
documents the site's chrome links to (`chrome_links` of `content.segment`: its navigation, header, footer, aside and
menus), which the site's sections are and a listing's items are not, whatever copy of the menu (a footer's) shows them
too.
Arrays inside a row source, or inside the menu tree, are the row's own data (its submenus), not further sources; a row
whose item URL an earlier row has is not read again (a blob caching one list twice; a trailing slash and the order of
query parameters aside). With several arrays read, the rows
are those of the array or arrays whose items the page's first item group links to most (`_grid_sources`): a recently
viewed or recommended array is not the page's list. Each row is an `array_row` entity
`js_state:<script xpath>@<document position>:<row path>`, and each value a
`js_state` candidate, whose evidence bucket is `state`.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.collect import json_doc
from crawlerai.collect.admission import Document
from crawlerai.collect.array_rows import Scalar, row_of, row_paths
from crawlerai.collect.base import ARRAY_ROW, Candidate, Entity
from crawlerai.collect.items.align import field_roles
from crawlerai.collect.schema_org_map import candidate, is_item_url
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import block_links, chrome_links, content_links
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.normalize.strings import fold
from crawlerai.normalize.url import canonical_url
from crawlerai.normalize.url_key import ItemKey, item_key
from crawlerai.schemas.paths import named_property, parse_paths
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

_KIND: Final = "js_state"
# A member name's letters and digits: `product_url`, `productUrl` and `ProductURL` name one thing.
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
    read = [found for number, document in enumerate(documents) for found in _sources(reader, number, document)]
    read = _once(_grid_sources(page, ctx, url_fields[0], read), url_fields[0])
    return StateRows(
        tuple(row for found in read for row in found.rows),
        tuple(c for found in read for c in found.candidates),
        tuple(note for found in read for note in found.diagnostics),
    )


def _grid_sources(page: ParsedPage, ctx: Context, url_field: str, read: list[StateRows]) -> list[StateRows]:
    """With several arrays read, the one or ones with the most rows whose item URL a block of the page's first item
    group (`ParsedPage.item_groups`, the segment step's ranking) links to: the page's own list, a recently viewed or
    recommended array rendered as a strip beside it being no rows of it. All of them when no row's item is linked
    from that group."""
    if len(read) < 2 or not page.item_groups:
        return read
    grid = {url for block in page.item_groups[0] for url in block_links(block, ctx.base_url)}
    shown = [
        sum(
            c.field == url_field and isinstance(c.normalized, Ok) and c.normalized.value in grid
            for c in found.candidates
        )
        for found in read
    ]
    most = max(shown)
    return [found for found, count in zip(read, shown, strict=True) if count == most] if most else read


def _once(read: list[StateRows], url_field: str) -> list[StateRows]:
    """The arrays with each item read once, in order: a row whose item an earlier array's row names is not read again,
    and an array left with fewer than `MIN_ITEMS` rows gives none (module docstring)."""
    seen: set[ItemKey] = set()
    kept: list[StateRows] = []
    for found in read:
        keys = _row_keys(found, url_field)
        rows = [row for row in found.rows if keys.get(row.id) not in seen]
        if len(rows) < MIN_ITEMS:
            continue
        seen.update(keys[row.id] for row in rows if row.id in keys)
        ids = {row.id for row in rows}
        candidates = tuple(c for c in found.candidates if c.entity_id in ids)
        kept.append(StateRows(tuple(rows), candidates, found.diagnostics))
    return kept


def _row_keys(found: StateRows, url_field: str) -> dict[str, ItemKey]:
    """Each row's item key (`normalize.url_key.item_key`), by row entity."""
    urls = ((c.entity_id, c.normalized) for c in found.candidates if c.field == url_field)
    keys = {row: item_key(url.value) for row, url in urls if isinstance(url, Ok) and isinstance(url.value, str)}
    return {row: key for row, key in keys.items() if key is not None}


def _sources(reader: "_Reader", number: int, document: Document) -> Iterator[StateRows]:
    """The rows of each array of `document` that is a row source, arrays inside a source left out."""
    sources: list[str] = []
    for path, value in json_doc.nodes(document.data):
        if not isinstance(value, list) or any(path.startswith(f"{source}[") for source in sources):
            continue
        objects: list[tuple[str, JsonValue]] = [
            (f"{path}[{i}]", item) for i, item in enumerate(value) if isinstance(item, dict)
        ]
        if len(objects) >= MIN_ITEMS and (read := reader.read(number, document, objects)) is not None:
            sources.append(path)
            yield read


class _Reader:
    """One page's state arrays read as rows."""

    def __init__(self, page: ParsedPage, schema: SchemaDef, ctx: Context, url_field: str) -> None:
        self.page = page
        self.schema = schema
        self.ctx = ctx
        self.url_field = url_field
        self.roles = field_roles(schema)
        self.names = {name for name, role in self.roles.items() if role == "name"}
        self.row_fields = {name: spec for name, spec in schema.fields.items() if spec.scope == "row"}
        self.links = content_links(page.lxml_tree, ctx.base_url, page.revealed)
        self.chrome = frozenset(url for _, url in chrome_links(page.lxml_tree, ctx.base_url))
        self._words = {name: _field_words(name, spec) for name, spec in self.row_fields.items()}

    def read(self, number: int, document: Document, objects: Sequence[tuple[str, JsonValue]]) -> StateRows | None:
        rows = [(path, row_of(item)) for path, item in objects]
        keys = row_paths([row for _, row in rows], self.row_fields, self._reads)
        if self.url_field not in keys:
            return None
        made: list[tuple[Entity, list[Candidate]]] = []
        notes: list[str] = []
        for path, row in rows:
            found = self._row((number, document), path, row, keys, notes)
            if found is not None:
                made.append(found)
        fresh = self._fresh(made)
        if len(fresh) < MIN_ITEMS:
            return None
        if self._menu(keys, [item for _, item in fresh]):
            # The menu tree is a source of no rows: its submenus, arrays inside it, are not read either.
            return StateRows()
        notes.append(f"item layer: {len(fresh)} rows from page state, fields: {sorted(keys)}")
        return StateRows(
            tuple(entity for _, (entity, _) in fresh),
            tuple(c for _, (_, values) in fresh for c in values),
            tuple(notes),
        )

    def _menu(self, keys: Mapping[str, str], rows: Sequence[tuple[Entity, list[Candidate]]]) -> bool:
        """Whether the array is the site's menu tree (module docstring): it reads no typed value, and more than half of
        its rows' items are documents the site's chrome links to."""
        if any(self.roles.get(name) == "typed" for name in keys):
            return False
        led = sum(
            c.field == self.url_field and isinstance(c.normalized, Ok) and c.normalized.value in self.chrome
            for _, values in rows
            for c in values
        )
        return 2 * led > len(rows)

    def _reads(self, name: str, path: str, raw: Scalar) -> bool:
        """Whether a row's `raw` at `path` is a grounded value of the field `name` (module docstring)."""
        spec = self.row_fields[name]
        if name == self.url_field and self._linked(raw):
            return True
        if not self._named(name, path) or not isinstance(normalize(raw, spec, self.ctx), Ok):
            return False
        if spec.type is FieldType.URL:
            # Another URL field's value is grounded only as a rendered link's target, as the item URL is.
            return name == self.url_field or self._linked(raw)
        return spec.type is FieldType.IMAGE_URL or self.page.visible_values.visible(str(raw))

    def _linked(self, raw: Scalar) -> bool:
        return isinstance(raw, str) and canonical_url(raw, self.ctx.base_url) in self.links

    def _named(self, name: str, path: str) -> bool:
        first = _FIRST_MEMBER.match(path, len(json_doc.ROOT))
        return first is not None and fold(first.group(1)) in self._words[name]

    def _row(
        self,
        document: tuple[int, Document],
        path: str,
        row: Mapping[str, Scalar],
        keys: Mapping[str, str],
        notes: list[str],
    ) -> tuple[Entity, list[Candidate]] | None:
        """The row's entity and its grounded values; None when the row is not grounded (module docstring). The
        entity id holds the document's position, as one script can hold several documents."""
        number, read = document
        owner = f"{_KIND}:{read.address}@{number}:{path}"
        values: list[Candidate] = []
        grounded = False
        for name, key in keys.items():
            raw = row.get(key)
            if raw is None or not self._reads(name, key, raw):
                continue
            locator = read.locator(_KIND, path + key[len(json_doc.ROOT) :])
            made = candidate(name, self.row_fields[name], owner, _KIND, raw, locator, self.ctx, notes)
            if made is not None:
                values.append(made)
                grounded |= (name == self.url_field and self._linked(raw)) or name in self.names
        if not grounded or not any(c.field == self.url_field for c in values):
            return None
        return Entity(id=owner, types=(ARRAY_ROW,), urls=(), parent=None), values

    def _fresh(
        self, made: Sequence[tuple[Entity, list[Candidate]]]
    ) -> list[tuple[ItemKey, tuple[Entity, list[Candidate]]]]:
        """The rows each naming their item once in the array, with its item's key (`normalize.url_key.item_key`)."""
        fresh: dict[ItemKey, tuple[Entity, list[Candidate]]] = {}
        for entity, values in made:
            url = next(
                (c.normalized.value for c in values if c.field == self.url_field and isinstance(c.normalized, Ok)), None
            )
            if isinstance(url, str) and (key := item_key(url)) is not None:
                fresh.setdefault(key, (entity, values))
        return list(fresh.items())


def _field_words(name: str, spec: FieldSpec) -> frozenset[str]:
    """The words naming a field: its own name and the schema.org properties its path reaches."""
    properties = [named_property(path) for path in parse_paths(spec.schema_org)] if spec.schema_org else []
    return frozenset(fold(word) for word in (name, *properties))
