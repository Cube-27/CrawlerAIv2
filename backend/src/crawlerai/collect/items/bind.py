"""The item layer's bind step (listings spec, "Stated rows and blocks"; owner #67): a listing's stated rows (structured
data's, the active config's, or else its captured calls'), its state and call array rows, and the blocks the align
step read (`collect.items.align`) meet, so that each item is one row.

**Which rows.** The stated rows are the listing's rows unless there are none or all are stubs: rows holding no
candidate of a row field but the item URL (an `ItemList` of URLs, empty `ListItem`s). Then the blocks are the rows.
Beside stated rows of which one or more is bound to a block, the group's unbound blocks are rows too: the group is the
listing, and a block no stated row names is an item the structured data left out (a list grown after its script was
written, a later batch a call loaded).

**Binding.** A row and a block are one item when the row names the block's item URL, and neither names another's (one
to one, else neither binds: C7). URLs are compared as the page's links name items: without the page's session
parameters (`normalize.url_key.session_parameters`, from the blocks' links), the path's trailing slash aside (RFC 3986
§6.2.4), and with one URL's query parameters all among the other's (a variant or tracking parameter one spelling adds,
§3.4). A stated row naming no item URL binds by its visible text instead: the one unbound block whose shown text holds
the row's name. A state or call array row (`array_row`) binds by URL to a listing row the same way.

**Values.** A bound entity's candidates join its row where the row holds no candidate of the field, or where they equal
one of the row's (agreement, normalization spec); a value that disagrees with the row's own is dropped, so the row's
source stays authoritative. A block's `ambiguous_in_block` value joins as its one option equal to the row's value. A
stated row bound by URL takes the block's link as its item URL (the page's own spelling of it), its respelled stated URL
dropped.

**Key induction.** Across the array rows bound to rows whose blocks show a field, a key of those rows (a JSON path
relative to the row) whose value equals the block's on `MIN_ITEMS` rows or more is that field's key on this page
(`collect.induce`, the rule learning applies across pages): its value is the field's candidate in each bound array row
whose block does not show the field, so that row still gets the value its data states. The value keeps its source kind
and the resolution spec's evidence rules (a call's value is `network` evidence; a lone state value has none).
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from urllib.parse import parse_qsl, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.collect import json_doc
from crawlerai.collect.admission import Document, StateKind
from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.induce import induced
from crawlerai.collect.items.align import AMBIGUOUS_IN_BLOCK, Block, Items, field_roles
from crawlerai.collect.items.spot import Spot
from crawlerai.collect.js_state import state_documents
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, item_url_fields
from crawlerai.collect.xhr import network_documents
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import text_path
from crawlerai.normalize.base import Ambiguous, Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.normalize.text import compose
from crawlerai.normalize.url_key import session_parameters, without_parameters
from crawlerai.schemas.types import SchemaDef

# The entity whose row fields a candidate fills: its owner, or the item an Offer it is in offers.
Holder = Callable[[Candidate], str]
_STATE_KINDS = ("js_state", "xhr")


@dataclass(frozen=True, slots=True)
class RowBlock:
    """A listing row's block: its position in the bound group, the block, and the row entity it is or is bound to."""

    index: int
    block: Block
    row: str


@dataclass(frozen=True, slots=True)
class Bound:
    """The listing's rows and every candidate, with bound entities' values moved to their rows, and the rows' blocks in
    the bound group's order."""

    rows: tuple[Entity, ...]
    candidates: tuple[Candidate, ...]
    diagnostics: tuple[str, ...] = ()
    blocks: tuple[RowBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class Listing:
    """What the bind step reads of a listing page: its parse and context, the schema, the page's own URLs, the align
    step's blocks, the stated rows, the state and call array rows, every candidate and who holds each."""

    page: ParsedPage
    ctx: Context
    schema: SchemaDef
    page_urls: tuple[str, ...]
    items: tuple[Items, ...]
    stated: tuple[Entity, ...]
    array_rows: tuple[Entity, ...]
    candidates: tuple[Candidate, ...]
    holder: Holder


def bind(listing: Listing) -> Bound:
    """The listing's rows and candidates (module docstring), from the aligned group the most stated rows bind to (the
    first on a tie: the align step's order), the other groups' candidates left out."""
    urls = _RowUrls(listing)
    chosen = _chosen(listing, urls)
    others = {block.entity.id for group in listing.items if group is not chosen for block in group.blocks}
    candidates = tuple(c for c in listing.candidates if c.entity_id not in others)
    binder = _Binder(replace(listing, candidates=candidates), chosen, urls)
    rows = binder.rows()
    binder.bind_array_rows(rows)
    induced_values = binder.induced_values()
    return Bound(rows, (*binder.result(), *induced_values), tuple(binder.notes), binder.row_blocks(rows))


class _RowUrls:
    """The URLs naming each entity's item: its own (`Entity.urls`) and its item URL candidates' values (a call row
    states its item's URL as a value)."""

    def __init__(self, listing: Listing) -> None:
        fields = frozenset(item_url_fields(listing.schema))
        self._values: dict[str, list[str]] = defaultdict(list)
        for c in listing.candidates:
            if c.field in fields and isinstance(c.normalized, Ok) and isinstance(c.normalized.value, str):
                self._values[listing.holder(c)].append(c.normalized.value)

    def of(self, entity: Entity) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*entity.urls, *self._values.get(entity.id, ()))))


def _chosen(listing: Listing, row_urls: _RowUrls) -> Items:
    if not listing.items:
        return Items()
    urls = [url for row in listing.stated for url in row_urls.of(row)]
    if not urls:
        return listing.items[0]
    session = session_parameters([b.link for group in listing.items for b in group.blocks], listing.page_urls)
    bound = [len(_Index([(b.entity.id, b.link) for b in group.blocks], session).find(urls)) for group in listing.items]
    return listing.items[max(range(len(bound)), key=lambda i: (bound[i], -i))]


@dataclass
class _Binder:
    listing: Listing
    items: Items
    urls: _RowUrls
    notes: list[str] = field(default_factory=list)
    # Each bound entity's id with its row's id and whether it was bound by URL.
    moves: dict[str, tuple[str, bool]] = field(default_factory=dict)
    # Each row's block, for the rows a block is or is bound to.
    blocks_of: dict[str, Block] = field(default_factory=dict)

    def __post_init__(self) -> None:
        links = [block.link for block in self.items.blocks]
        self.session = session_parameters(links, self.listing.page_urls)
        self.held: dict[str, dict[str, list[Candidate]]] = defaultdict(lambda: defaultdict(list))
        for c in self.listing.candidates:
            self.held[self.listing.holder(c)][c.field].append(c)
        self.url_fields = frozenset(item_url_fields(self.listing.schema))

    def rows(self) -> tuple[Entity, ...]:
        stated = self.listing.stated
        blocks = self.items.blocks
        if not blocks:
            return stated
        bound = self._bind_stated(stated, blocks)
        if not stated or all(self._stub(row) for row in stated):
            return self._block_rows(stated, blocks, bound)
        return self._stated_rows(stated, blocks, bound)

    def _block_rows(
        self, stated: Sequence[Entity], blocks: Sequence[Block], bound: Sequence[tuple[Entity, Block]]
    ) -> tuple[Entity, ...]:
        """The blocks as the rows, each bound stub's values moved to its block."""
        for row, block in bound:
            self.moves[row.id] = (block.entity.id, block.link in self._keys_of(row))
        self.blocks_of = {block.entity.id: block for block in blocks}
        # A stub no block takes still names an item of the list (its item URL): it stays a row.
        unbound = tuple(row for row in stated if row.id not in self.moves)
        self.notes.append(f"item layer: rows from {len(blocks)} blocks, {len(bound)} stated stubs bound")
        return (*(block.entity for block in blocks), *unbound)

    def _stated_rows(
        self, stated: Sequence[Entity], blocks: Sequence[Block], bound: Sequence[tuple[Entity, Block]]
    ) -> tuple[Entity, ...]:
        """The stated rows, each bound block's values moved to its row, and the blocks no stated row names."""
        for row, block in bound:
            self.moves[block.entity.id] = (row.id, True)
            self.blocks_of[row.id] = block
        # A block a stated row names, bound or not (two rows naming it bind neither), is no further item.
        index = _Index([(block.entity.id, block.link) for block in blocks], self.session)
        claimed = {found for row in stated for found in index.matching(self.urls.of(row))}
        taken = claimed | {block.entity.id for _, block in bound}
        extra = tuple(block.entity for block in blocks if block.entity.id not in taken) if bound else ()
        self.blocks_of |= {entity.id: next(b for b in blocks if b.entity is entity) for entity in extra}
        self.notes.append(f"item layer: {len(bound)} stated rows bound to blocks, {len(extra)} blocks added")
        return (*stated, *extra)

    def row_blocks(self, rows: Sequence[Entity]) -> tuple[RowBlock, ...]:
        """The block of each of `rows` that has one, in the group's order."""
        position = {block.entity.id: i for i, block in enumerate(self.items.blocks)}
        listed = {row.id for row in rows}
        found = (RowBlock(position[b.entity.id], b, row) for row, b in self.blocks_of.items() if row in listed)
        return tuple(sorted(found, key=lambda row_block: row_block.index))

    def _stub(self, row: Entity) -> bool:
        """Whether the row holds no candidate of a row field but the item URL."""
        fields = self.held.get(row.id, {})
        return not any(
            spec.scope == "row" and name not in self.url_fields and fields.get(name)
            for name, spec in self.listing.schema.fields.items()
        )

    def _bind_stated(self, rows: Sequence[Entity], blocks: Sequence[Block]) -> list[tuple[Entity, Block]]:
        """Each stated row bound to its block: by URL, then the rows stating none by their name's text."""
        index = _Index([(block.entity.id, block.link) for block in blocks], self.session)
        by_id = {block.entity.id: block for block in blocks}
        rows_by_id = {row.id: row for row in rows}
        pairs = _one_to_one((row.id, found) for row in rows for found in index.find(self.urls.of(row)))
        taken = set(pairs.values())
        texts = {b.entity.id: _squeezed(self._shown(b)) for b in blocks if b.entity.id not in taken}
        named = (
            (row.id, block)
            for row in rows
            if not self.urls.of(row) and row.id not in pairs
            for name in self._names(row)
            for block, text in texts.items()
            if name and name in text
        )
        pairs |= _one_to_one(named)
        return [(rows_by_id[row], by_id[block]) for row, block in pairs.items()]

    def _shown(self, block: Block) -> str:
        span = self.listing.page.text_spans.get(text_path(block.element))
        return "" if span is None else self.listing.page.cleaned_text.text[span[0] : span[1]]

    def _names(self, row: Entity) -> set[str]:
        names = {name for name, role in field_roles(self.listing.schema).items() if role == "name"}
        held = self.held.get(row.id, {})
        return {
            _squeezed(c.normalized.value)
            for name in names
            for c in held.get(name, ())
            if isinstance(c.normalized, Ok) and isinstance(c.normalized.value, str)
        }

    def _keys_of(self, row: Entity) -> set[str]:
        return {without_parameters(url, self.session) for url in self.urls.of(row)}

    def bind_array_rows(self, rows: Sequence[Entity]) -> None:
        """State and call array rows bound by URL to the listing's rows (module docstring)."""
        anchors = [(row.id, url) for row in rows for url in self.urls.of(row)]
        anchors += [(row, block.link) for row, block in self.blocks_of.items()]
        index = _Index(anchors, self.session)
        listed = {row.id for row in rows}
        found = (
            (e.id, row) for e in self.listing.array_rows if e.id not in listed for row in index.find(self.urls.of(e))
        )
        for entity, row in _one_to_one(found).items():
            self.moves[entity] = (row, False)

    def induced_values(self) -> tuple[Candidate, ...]:
        """The candidates the page's induced keys give the array rows bound to rows (module docstring)."""
        pairs = [(entity, row) for entity, (row, by_url) in self.moves.items() if not by_url and _is_array_row(entity)]
        if len(pairs) < MIN_ITEMS:
            return ()
        reader = _RowReader(self.listing.page)
        rows = {entity: found for entity, _ in pairs if (found := reader.row(entity)) is not None}
        made: list[Candidate] = []
        for name in self.listing.schema.fields:
            shown = {
                entity: spots[0]
                for entity, row in pairs
                if entity in rows and len(spots := self._spots(row, name)) == 1
            }
            key = induced([self._equal_keys(rows[e], spot, name) for e, spot in shown.items()], MIN_ITEMS)
            if key is None:
                continue
            self.notes.append(f"item layer: {name} read at a key of {len(rows)} array rows")
            made.extend(self._key_values(name, key, pairs, rows))
        return tuple(made)

    def _spots(self, row: str, name: str) -> tuple[Spot, ...]:
        block = self.blocks_of.get(row)
        return () if block is None else block.spots.get(name, ())

    def _equal_keys(self, row: "_ArrayRow", spot: Spot, name: str) -> list[str]:
        spec = self.listing.schema.fields[name]
        ctx = self.listing.ctx
        return [
            key
            for key, raw in row.scalars.items()
            if isinstance(found := normalize(raw, spec, ctx), Ok) and equal(found.value, spot.normalized.value, spec)
        ]

    def _key_values(
        self, name: str, key: str, pairs: Sequence[tuple[str, str]], rows: Mapping[str, "_ArrayRow"]
    ) -> Iterator[Candidate]:
        spec = self.listing.schema.fields[name]
        for entity, row in pairs:
            found = rows.get(entity)
            # A row whose block shows the field has its value already (its state agrees with it by equality).
            if found is None or key not in found.scalars or self._spots(row, name):
                continue
            locator = format_locator(found.kind, found.address, found.path + key[len(json_doc.ROOT) :])
            notes: list[str] = []
            made = candidate(name, spec, row, found.kind, found.scalars[key], locator, self.listing.ctx, notes)
            if made is not None:
                # Proved by the blocks' values, not stated beside them: it never counts toward agreement.
                yield made.model_copy(update={"independent": False})

    def result(self) -> tuple[Candidate, ...]:
        """Every candidate, a bound entity's moved to its row where it fills or agrees (module docstring)."""
        moved: dict[str, list[Candidate]] = defaultdict(list)
        kept: list[Candidate] = []
        for c in self.listing.candidates:
            holder = self.listing.holder(c)
            (moved[holder] if holder in self.moves else kept).append(c)
        dropped = 0
        replaced: set[int] = set()
        added: list[Candidate] = []
        for source, (row, by_url) in self.moves.items():
            own = self.held.get(row, {})
            for c in moved[source]:
                joined = self._joined(c, row, own, by_url, replaced)
                added.extend(() if joined is None else (joined,))
                dropped += joined is None
        if dropped:
            self.notes.append(f"item layer: {dropped} bound values disagreeing with their row dropped")
        return (*(c for c in kept if id(c) not in replaced), *added)

    def _joined(
        self, c: Candidate, row: str, own: Mapping[str, list[Candidate]], by_url: bool, replaced: set[int]
    ) -> Candidate | None:
        spec = self.listing.schema.fields.get(c.field)
        theirs = own.get(c.field, [])
        if spec is None or not theirs:
            return c.model_copy(update={"entity_id": row})
        values = [t.normalized.value for t in theirs if isinstance(t.normalized, Ok)]
        if isinstance(c.normalized, Ok) and any(equal(c.normalized.value, v, spec) for v in values):
            return c.model_copy(update={"entity_id": row})
        if by_url and c.field in self.url_fields and c.source_kind == "dom":
            # The stated URL respells the block's link (a slash, an added query): the page's own spelling replaces it.
            replaced.update(id(t) for t in theirs if t.source_kind != "dom")
            return c.model_copy(update={"entity_id": row})
        if isinstance(c.normalized, Ambiguous) and c.normalized.reason == AMBIGUOUS_IN_BLOCK:
            return self._agreeing_option(c, row, values)
        return None

    def _agreeing_option(self, c: Candidate, row: str, values: Sequence[JsonValue]) -> Candidate | None:
        """The block's option equal to one of the row's values, as a candidate of its own."""
        spec = self.listing.schema.fields[c.field]
        raws = c.raw if isinstance(c.raw, list) else []
        for raw in raws:
            normalized = normalize(raw, spec, self.listing.ctx)
            if isinstance(normalized, Ok) and any(equal(normalized.value, v, spec) for v in values):
                return c.model_copy(update={"entity_id": row, "raw": raw, "normalized": normalized})
        return None


@dataclass(frozen=True, slots=True)
class _ArrayRow:
    """An array row's JSON object: its source kind, its document's address, its path and its scalars by path relative
    to it."""

    kind: StateKind
    address: str
    path: str
    scalars: Mapping[str, str | int | float]


class _RowReader:
    """The JSON objects of state and call array rows, by entity id (`<kind>:<document index>:<row path>`, the ids
    `collect.admission` and the API recipe row reader, `read_rows`, give them)."""

    def __init__(self, page: ParsedPage) -> None:
        self._page = page
        self._documents: dict[str, list[Document]] = {}

    def row(self, entity: str) -> _ArrayRow | None:
        prefix, _, rest = entity.partition(":")
        index, _, path = rest.partition(":")
        if prefix not in _STATE_KINDS:
            return None
        kind: StateKind = "js_state" if prefix == "js_state" else "xhr"
        documents = self._of(kind)
        if not index.isdigit() or int(index) >= len(documents):
            return None
        document = documents[int(index)]
        selected = json_doc.select(path, document.data) if json_doc.is_query(path) else []
        if len(selected) != 1 or not isinstance(selected[0][1], dict):
            return None
        return _ArrayRow(kind, document.address, path, dict(json_doc.scalars(selected[0][1])))

    def _of(self, kind: StateKind) -> list[Document]:
        if kind not in self._documents:
            if kind == "js_state":
                self._documents[kind] = state_documents(self._page, [])
            else:
                by_index = {int(d.address): d for d in network_documents(self._page, [])}
                count = len(self._page.network)
                self._documents[kind] = [by_index.get(i, Document(None, str(i))) for i in range(count)]
        return self._documents[kind]


def _is_array_row(entity: str) -> bool:
    return entity.partition(":")[0] in _STATE_KINDS


class _Index:
    """Item URLs by the page's own key of them (module docstring), each with the entity naming it."""

    def __init__(self, named: Iterable[tuple[str, str]], session: frozenset[str]) -> None:
        self._session = session
        self._by_path: dict[str, list[tuple[str, Counter[tuple[str, str]]]]] = defaultdict(list)
        for entity, url in named:
            path, query = _parts(without_parameters(url, session))
            self._by_path[path].append((entity, query))

    def find(self, urls: Iterable[str]) -> set[str]:
        """The entities naming one of `urls`, each URL matching one entity only."""
        found: set[str] = set()
        for url in urls:
            if len(matches := self._matches(url)) == 1:
                found |= matches
        return found

    def matching(self, urls: Iterable[str]) -> set[str]:
        """Every entity naming one of `urls`, however many one URL matches."""
        return {entity for url in urls for entity in self._matches(url)}

    def _matches(self, url: str) -> set[str]:
        path, query = _parts(without_parameters(url, self._session))
        return {e for e, theirs in self._by_path.get(path, ()) if query <= theirs or theirs <= query}


def _one_to_one(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """The pairs whose two sides appear in no other pair."""
    listed = list(dict.fromkeys(pairs))
    lefts: dict[str, int] = defaultdict(int)
    rights: dict[str, int] = defaultdict(int)
    for left, right in listed:
        lefts[left] += 1
        rights[right] += 1
    return {left: right for left, right in listed if lefts[left] == 1 and rights[right] == 1}


def _parts(url: str) -> tuple[str, Counter[tuple[str, str]]]:
    """The URL without its query, one trailing slash of its path aside (RFC 3986 §6.2.4: `/a/` and `/a` may name one
    resource; `/a//` is another path), and its query parameters as a multiset (a repeated parameter is two values)."""
    split = urlsplit(url)
    path = split.path.removesuffix("/")
    return f"{split.scheme}://{split.netloc}{path}", Counter(parse_qsl(split.query, keep_blank_values=True))


def _squeezed(text: object) -> str:
    """`text` without white space, in NFC (`compose`): the cleaned text and a structured value space words alike only
    after this."""
    return "".join(compose(str(text)).split())
