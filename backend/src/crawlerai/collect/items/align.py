"""The item layer's align step (listings spec, "Rows from blocks"; owner #67): a listing's rows from the blocks of one
group of repeated items (`ParsedPage.item_groups`, the segment step), each field read at a place the blocks share,
declining rather than guessing (DEPTA's partial alignment, Zhai and Liu 2005: only what aligns with certainty is
committed).

A value's place in its block is the tag path from the block down to its element (the blocks' trees aligned, positions
aside), or for a name, an image and the item URL, the rule that reads it. A place is a source of a field only when the
field's normalizer accepts a value there in at least `quorum` of the group's blocks (`MIN_ITEMS`, and 60% of them).
What each field reads follows from its type and schema.org property, never from a class name, a word or a site (C2,
C4):
- **item URL** (`is_item_url` of `collect.schema_org_map`): the one document the block's hyperlinks lead to (HTML
  Standard §4.6.1), leaving out the page itself in any state of its query (a pager, a sort; RFC 3986 §3.3), image files
  (RFC 6838 `image/*`: a larger copy of the block's image) and the links of the item's own lists (`_sublist_links`).
  When they lead to several: the one without a query that every other refines with one (RFC 3986 §3.4), else the one
  the block's headings link to, else the one whose links hold most of the block's text (`one_link`). Else, at group
  level (DEPTA alignment, `item_links`): the documents two or more blocks link to are the template's (a vendor's, an
  author's, a category's page: an item is listed once), and the block's item is the one other document its links lead
  to at the tag path where a quorum of the blocks link to one such document. A block without one such document is no
  row.
- **name** (a row text field whose path names schema.org `name`, or JobPosting `title`): the shown content of the
  block's first hyperlink to its item when that is one line of text (HTML Standard §4.5.1), the block's one heading
  (HTML Standard §4.3.6, WAI-ARIA role `heading`), or the name the item's attributes state (`Stated`): an item link's
  `aria-labelledby`, `aria-label` or `title`, an image's `alt` (WAI-ARIA Accessible Name and Description Computation
  1.2), kept where the block shows it (WCAG 2.1 SC 2.5.3 Label in Name, over one or several whole lines, a line cut
  short by an ellipsis standing for the rest), its leading and trailing words the block does not show dropped when
  every block states the same ones (the template's `Details of`). Content of several lines is the whole card, not its
  name. Of the three, the one whose values differ most across the blocks: text every block repeats is the template's
  (a call to action), not an item's. A block the chosen rule gives no name reads the one line at the tag path the
  rule's names have in a quorum of blocks (DEPTA alignment: a sold-out card's extra heading, a stale `alt`); a child
  element of the name whose text every block repeats is the template's (screen-reader-only helper text) and is left
  out of the name.
- **image** (a row image_url field whose path names schema.org `image`): the block's first shown image that is not
  decorative (`collect.dom.image_source`, `collect.dom.decorative`).
- **typed values** (a row money, date or datetime field, or an identifier under a scheme with a check digit): typed
  value spotting. The block's shown elements whose text, on one line, the field's normalizer parses (a syntax it
  checks: an ISO 4217 or CLDR amount, an ISO 8601 or CLDR date, a check digit), and, for an element holding others,
  each of its own text nodes; a line where two text nodes run digits together (`ParsedPage.digit_joins`) is two
  numbers, not one. Of an element and one inside it reading the same value, the inner one. Text the HTML Standard
  marks as no longer accurate (`s`, §4.5.4) or removed (`del`, §4.7.2), the obsolete `strike` and text an inline
  `line-through` decoration strikes (`collect.dom.struck`) is no current value: a struck-through former price, which
  only a list price field reads; a money field reads by its price role (`collect.items.spot.reads`: no amount written
  per unit or per period for the price). A place every block gives the same value at is the
  template's (a shipping threshold) when another place gives the field differing values. A block whose places give one
  value publishes it; one whose places give several (a price and an instalment) gives an `ambiguous_in_block`
  candidate, which publishes nothing unless a structured row bound to the block agrees with one of them
  (`collect.items.bind`).

A group one of whose blocks stands for the page itself (`_current_page`: `aria-current="page"`, or links to this very
URL only) is the site's navigation (a category or city hub listing the page among its documents) and gives no rows.

Shown means rendered by the cleaned text's rules (`content.text.hidden`): a hidden subtree of a block is not read. The
group whose blocks align the most fields is the listing's, the segment step's order breaking ties: profile cards align
a name and a link but no price, a product grid all three. Each block with an item URL is an `item_block` entity, and
each of its values a `dom` candidate with the XPath of its element.
"""

import bisect
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal
from urllib.parse import urlsplit

from lxml.html import HtmlElement
from pydantic import ValidationError

from crawlerai.acquire.items import MIN_ITEMS, Group, is_hyperlink
from crawlerai.collect.base import ITEM_BLOCK, Candidate, Entity
from crawlerai.collect.dom import decorative, image_source, is_image_url
from crawlerai.collect.dom import struck as is_struck
from crawlerai.collect.items.spot import Spot, is_typed, reads, spots
from crawlerai.collect.items.stated import Stated, Word, same, words
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, is_item_url
from crawlerai.content.dom import tokens
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import hyperlinks, shows_more, text_path
from crawlerai.content.text import completed, hidden, xpath_step
from crawlerai.normalize.base import Ambiguous, Context, raw_key
from crawlerai.normalize.dispatch import equality_key
from crawlerai.normalize.url import canonical_url, is_absolute
from crawlerai.schemas.paths import named_property, parse_paths
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaContent

# The share of a group's blocks a place must give a field's value in, besides `MIN_ITEMS` (master plan §3.2).
QUORUM_SHARE: Final = 0.6
# The groups tried, in the segment step's order: the ones after them are a page's minor lists.
_GROUPS_TRIED: Final = 8
# The reason of a block's typed field whose places give several values.
AMBIGUOUS_IN_BLOCK: Final = "ambiguous_in_block"
# schema.org Thing's `name` ("The name of the item"), JobPosting's `title` ("The title of the job"), Thing's `image`.
_NAMES: Final = frozenset({"name", "title"})
_IMAGE: Final = "image"
# HTML Standard §4.3.6: heading content; WAI-ARIA 1.2 role `heading`.
_HEADINGS: Final = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_HEADING_ROLE: Final = "heading"
# WAI-ARIA 1.2 `aria-current` token: "represents the current page within a set of pages".
_CURRENT_PAGE: Final = "page"
# The places of the rules that read one value per block.
_LINK, _LINK_NAME, _HEADING, _STATED, _PICTURE = "@link", "@link-name", "@heading", "@stated-name", "@image"


Role = Literal["url", "name", "image", "typed"]


@dataclass(frozen=True, slots=True)
class Block:
    """One block of the listing's group with an item URL: its element, row entity, that URL (canonical) and each
    aligned field's values (one, or several for a typed field whose places disagree in the block)."""

    element: HtmlElement
    entity: Entity
    link: str
    spots: Mapping[str, tuple[Spot, ...]]


@dataclass(frozen=True, slots=True)
class Items:
    """The listing's blocks, the candidates their values give (owned by their `item_block` entities), the group they
    are of, the fields it aligns and what the step reports."""

    blocks: tuple[Block, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    group: Group = ()
    diagnostics: tuple[str, ...] = ()
    fields: frozenset[str] = frozenset()

    @property
    def entities(self) -> tuple[Entity, ...]:
        return tuple(block.entity for block in self.blocks)


def quorum(blocks: int) -> int:
    """How many of a group's `blocks` a place must give a field's value in."""
    return max(MIN_ITEMS, math.ceil(QUORUM_SHARE * blocks))


def align(page: ParsedPage, schema: SchemaContent, ctx: Context) -> tuple[Items, ...]:
    """Every group of the page's repeated items that aligns, as rows, best first (module docstring): the most fields
    aligned, then the segment step's order. None for a detail schema, a schema without an item URL field, or a page
    none of whose groups links its items."""
    roles = field_roles(schema)
    if schema.page_kind != "listing" or "url" not in roles.values():
        return ()
    groups = page.item_groups[:_GROUPS_TRIED]
    sublists = _sublist_links(page.item_groups)
    aligned = [a for group in groups if (a := _Aligned.of(page, group, schema, roles, ctx, sublists)) is not None]
    order = sorted(range(len(aligned)), key=lambda i: (-len(aligned[i].fields), i))
    return tuple(aligned[i].items(schema, ctx, number) for number, i in enumerate(order))


def _sublist_links(groups: Sequence[Group]) -> frozenset[HtmlElement]:
    """The hyperlinks of items' own lists (their share buttons, their colour swatches), whose links lead to an item's
    related documents, not to the item (`_View.of`): groups that each lie inside one block of another group, where two
    or more of that group's blocks hold one (the structure repeats per item; a grid inside one section of a page is
    not an item's list) and each such block also links outside it (the item's own link; a section holding a list of
    items is no item)."""
    owner_of = {block: number for number, group in enumerate(groups) for block in group}
    nested: dict[int, list[tuple[HtmlElement, frozenset[HtmlElement]]]] = {}
    for number, group in enumerate(groups):
        if (found := _item_list(group, number, owner_of)) is not None:
            nested.setdefault(owner_of[found[0]], []).append(found)
    repeated = (lists for lists in nested.values() if len({owner for owner, _ in lists}) >= 2)
    return frozenset(anchor for lists in repeated for _, inner in lists for anchor in inner)


def _item_list(
    group: Group, number: int, owner_of: Mapping[HtmlElement, int]
) -> tuple[HtmlElement, frozenset[HtmlElement]] | None:
    """The one block of another group that the group lies in, and the group's hyperlinks, when that block also links
    outside the group; else None."""
    owners = {_owning_block(block, owner_of, number) for block in group}
    owner = owners.pop() if len(owners) == 1 else None
    if owner is None:
        return None
    inner = frozenset(anchor for block in group for anchor in hyperlinks(block))
    return (owner, inner) if any(anchor not in inner for anchor in hyperlinks(owner)) else None


def _owning_block(block: HtmlElement, owner_of: Mapping[HtmlElement, int], group: int) -> HtmlElement | None:
    """The nearest ancestor of `block` that is a block of a group other than `group`."""
    node = block.getparent()
    while node is not None:
        if owner_of.get(node, group) != group:
            return node
        node = node.getparent()
    return None


def field_roles(schema: SchemaContent) -> dict[str, Role]:
    """The row fields the align step reads, each with what it reads (module docstring)."""
    roles: dict[str, Role] = {}
    for name, spec in schema.fields.items():
        if spec.scope == "row" and (role := _role(spec)) is not None:
            roles[name] = role
    return roles


def _role(spec: FieldSpec) -> Role | None:
    if is_item_url(spec):
        return "url"
    properties = {named_property(p) for p in parse_paths(spec.schema_org)} if spec.schema_org is not None else set()
    if spec.type is FieldType.TEXT:
        return "name" if not _NAMES.isdisjoint(properties) else None
    if spec.type is FieldType.IMAGE_URL:
        return "image" if _IMAGE in properties else None
    if is_typed(spec):
        return "typed"
    return None


@dataclass
class _Aligned:
    """One group's blocks with an item URL, and each aligned field's spots in each of them."""

    group: Group
    views: list["_View"]
    fields: dict[str, list[tuple[Spot, ...]]] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        page: ParsedPage,
        group: Group,
        schema: SchemaContent,
        roles: Mapping[str, Role],
        ctx: Context,
        sublists: frozenset[HtmlElement],
    ) -> "_Aligned | None":
        """The group's alignment; None when a block of it is the current page (`_current_page`: the group is the
        site's navigation), when fewer than a quorum of its blocks lead to one item, or fewer than
        `MIN_ITEMS` show more than their link (an image, or text in two or more runs: a pager, a tag cloud or a list of
        related searches shows a link and its label only, while a grid whose later cards a script fills still shows
        its first ones)."""
        here = canonical_url(ctx.page_url, None) if ctx.page_url is not None else None
        if any(_current_page(block, ctx.base_url, here) for block in group):
            return None
        needed = quorum(len(group))
        links = item_links(group, ctx.base_url, here, sublists, page.text_spans)
        views = [_View.of(page, block, found, ctx.base_url, sublists) for block, found in links if found is not None]
        if len(views) < needed or sum(shows_more(view.block) for view in views) < MIN_ITEMS:
            return None
        aligned = cls(group, views)
        for name, role in roles.items():
            if (kept := _field(views, role, schema.fields[name], ctx, needed)) is not None:
                aligned.fields[name] = kept
        return aligned

    def items(self, schema: SchemaContent, ctx: Context, number: int) -> Items:
        """The group's rows, its entities numbered `item_block:<number>:<block>`."""
        blocks: list[Block] = []
        candidates: list[Candidate] = []
        diagnostics: list[str] = []
        ambiguous: Counter[str] = Counter()
        seen: set[str] = set()
        for i, view in enumerate(self.views):
            # A row is keyed by its item URL: a second block leading to the same item shows it again (a featured copy).
            if view.link in seen:
                continue
            seen.add(view.link)
            entity = Entity(id=f"{ITEM_BLOCK}:{number}:{i}", types=(ITEM_BLOCK,), urls=(view.link,), parent=None)
            spots = {name: found[i] for name, found in self.fields.items() if found[i]}
            blocks.append(Block(view.block, entity, view.link, spots))
            for name, found in spots.items():
                made = _candidate(name, schema.fields[name], entity.id, found, view, ctx, diagnostics)
                if made is not None:
                    candidates.append(made)
                    ambiguous[name] += isinstance(made.normalized, Ambiguous)
        diagnostics.append(f"item layer: group {number}: {len(blocks)} blocks, aligned: {sorted(self.fields)}")
        diagnostics.extend(
            f"item layer: {name}: {AMBIGUOUS_IN_BLOCK} in {n} rows" for name, n in ambiguous.items() if n
        )
        return Items(tuple(blocks), tuple(candidates), self.group, tuple(diagnostics), frozenset(self.fields))


def _field(
    views: Sequence["_View"], role: Role, spec: FieldSpec, ctx: Context, needed: int
) -> list[tuple[Spot, ...]] | None:
    """Each block's spots of a field at its aligned places (module docstring); None when no place aligns."""
    found = [view.read(role, spec, ctx) for view in views]
    if role != "name":
        return _aligned(found, needed, spec, one_place=False)
    stated = [view.stated() for view in views]
    own = [_completed(spots_, name, spec, ctx) for spots_, name in zip(found, stated, strict=True)]
    more = _stated_names(views, stated, spec, ctx, needed)
    names = [tuple(s for s in (*a, *b) if not is_absolute(s.raw)) for a, b in zip(own, more, strict=True)]
    kept = _aligned(names, needed, spec, one_place=True)
    return None if kept is None else _untemplated(views, _filled(views, kept, spec, ctx, needed), spec, ctx)


def _completed(found: tuple[Spot, ...], stated: Stated | None, spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
    """The block's names, one cut short by an ellipsis read as the stated name it begins (`content.text.completed`)."""
    if stated is None:
        return found
    return tuple(
        next(iter(spots(full, spec, ctx, spot.xpath, spot.place)), spot)
        if (full := completed(spot.raw, stated.text))
        else spot
        for spot in found
    )


def _stated_names(
    views: Sequence["_View"], found: Sequence[Stated | None], spec: FieldSpec, ctx: Context, needed: int
) -> list[tuple[Spot, ...]]:
    """Each block's attribute-stated name (`Stated`). Where a quorum of blocks show theirs, only a shown one is kept,
    without the leading and trailing words the block does not show that every such block states alike (a template's);
    a block whose leading words differ from the others' is not named by its attributes (WCAG 2.1 SC 2.5.3 has the
    visible label start the name). Where they do not (an image-only grid), a block whose item links show no one-line
    content is named whole by its first stated name, as its accessible name."""
    shown = [s for s in found if s is not None and s.shown]
    if len(shown) < needed:
        return [
            spots(s.text, spec, ctx, s.xpath, _STATED) if s is not None and view.link_line() is None else ()
            for view, s in zip(views, found, strict=True)
        ]
    lead, trail = same(s.lead for s in shown), same(s.trail for s in shown)
    return [() if s is None else _trimmed(s, lead, trail, spec, ctx) for s in found]


def _trimmed(stated: Stated, lead: str, trail: str, spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
    """A shown stated name without the group's common unshown `lead` and `trail` (the trail kept after a line an
    ellipsis cut); none for one not shown or whose
    unshown leading words are its own."""
    if not stated.shown or (stated.lead and stated.lead != lead):
        return ()
    # A run an ellipsis cut short goes on in the unshown words, so they stay even when every block states them.
    keep_trail = not trail or stated.cut
    return spots(stated.trimmed(lead=bool(stated.lead), trail=not keep_trail), spec, ctx, stated.xpath, _STATED)


def _filled(
    views: Sequence["_View"], kept: list[tuple[Spot, ...]], spec: FieldSpec, ctx: Context, needed: int
) -> list[tuple[Spot, ...]]:
    """The names, a block the chosen rule gives none read at the tag path a quorum of the rule's names are one line at
    (DEPTA partial alignment: the blocks' trees aligned, the name's node is the one at that path), when the block
    shows one line of text there."""
    place = next((spot.place for found in kept for spot in found), None)
    lines = Counter(
        path for view, found in zip(views, kept, strict=True) if (path := view.line_place(found)) is not None
    )
    common = lines.most_common(1)
    if place is None or not common or common[0][1] < needed:
        return kept
    path = common[0][0]
    return [found or _at_place(view, path, spec, ctx, place) for view, found in zip(views, kept, strict=True)]


def _at_place(view: "_View", path: str, spec: FieldSpec, ctx: Context, place: str) -> tuple[Spot, ...]:
    """The block's one line of text at the tag path `path`, as a spot of `place`; none when the block shows none or
    several there."""
    at = [(element, text) for element in view.elements if view.places[element] == path and (text := view.line(element))]
    if len({text for _, text in at}) != 1 or is_absolute(at[0][1]):
        return ()
    element, text = at[0]
    return spots(text, spec, ctx, view.paths[element], place)


def _untemplated(
    views: Sequence["_View"], kept: list[tuple[Spot, ...]], spec: FieldSpec, ctx: Context
) -> list[tuple[Spot, ...]]:
    """The names without a child element's text that every named block shows alike at the same tag path inside its
    name (DEPTA: a node whose value never varies across the records is the template's, such as helper text a
    stylesheet hides from sight but the HTML shows); a name that would be left empty stays whole."""
    named = [
        (view, found[0], element)
        for view, found in zip(views, kept, strict=True)
        if (element := view.named(found)) is not None
    ]
    if len(named) < MIN_ITEMS or len(named) < sum(1 for found in kept if found):
        return kept
    template = _template([view.children_text(element) for view, _, element in named])
    if not template:
        return kept
    renamed = {
        id(spot): spots(text, spec, ctx, spot.xpath, spot.place)
        if (text := view.without(element, template))
        else (spot,)
        for view, spot, element in named
    }
    return [renamed.get(id(found[0]), found) if found else found for found in kept]


def _template(children: Sequence[Mapping[str, tuple[str, int, int]]]) -> set[str]:
    """The tag paths at which every name's child shows the same text."""
    first, *others = children
    return {rel for rel, (text, _, _) in first.items() if all(rel in c and c[rel][0] == text for c in others)}


def _aligned(
    spots: Sequence[tuple[Spot, ...]], needed: int, spec: FieldSpec, *, one_place: bool
) -> list[tuple[Spot, ...]] | None:
    """Each block's spots at the places that give a value in at least `needed` blocks, a template's place left out
    (module docstring); with `one_place`, at the one such place whose values differ most (the first on a tie). None
    when no place is left."""
    distinct = _distinct_values(spots, needed, spec)
    varied = [place for place, count in distinct.items() if count > 1]
    most = [max(varied, key=distinct.__getitem__)] if varied else []
    places = most if one_place else varied or list(distinct)
    if not places:
        return None
    return [tuple(spot for spot in found if spot.place in places) for found in spots]


def _distinct_values(spots: Sequence[tuple[Spot, ...]], needed: int, spec: FieldSpec) -> dict[str, int]:
    """How many distinct values each place gives that gives one in at least `needed` blocks, in the order the rules
    read (the order of `_View`'s rules), so that on a tie the first rule's place is first."""
    counts = Counter(place for found in spots for place in dict.fromkeys(spot.place for spot in found))
    values: dict[str, set[object]] = {place: set() for place, count in counts.items() if count >= needed}
    for found in spots:
        for spot in found:
            if spot.place in values:
                values[spot.place].add(_key(spot, spec))
    return {place: len(found) for place, found in values.items()}


def _candidate(
    name: str, spec: FieldSpec, entity_id: str, spots: tuple[Spot, ...], view: "_View", ctx: Context, notes: list[str]
) -> Candidate | None:
    """The block's candidate for a field: its one value, or an `ambiguous_in_block` one listing its values."""
    distinct = _distinct(spots, spec)
    if len(distinct) == 1:
        spot = distinct[0]
        return candidate(name, spec, entity_id, "dom", spot.raw, format_locator("dom", spot.xpath), ctx, notes)
    try:
        return Candidate(
            field=name,
            entity_id=entity_id,
            source_kind="dom",
            raw=[spot.raw for spot in distinct],
            normalized=Ambiguous(AMBIGUOUS_IN_BLOCK, tuple(spot.normalized.value for spot in distinct)),
            locator=format_locator("dom", view.path),
            independent=True,
        )
    except ValidationError as e:  # a value the candidate model refuses is skipped, as `candidate` does
        notes.append(f"item layer: {name}: {e.error_count()} invalid values")
        return None


def _distinct(spots: Iterable[Spot], spec: FieldSpec) -> list[Spot]:
    """The spots with one of each normalized value (the type's equality, normalization spec), in order."""
    seen: dict[object, Spot] = {}
    for spot in spots:
        seen.setdefault(_key(spot, spec), spot)
    return list(seen.values())


def _key(spot: Spot, spec: FieldSpec) -> object:
    key = equality_key(spot.normalized.value, spec)
    return raw_key(spot.normalized.value) if key is None else key


@dataclass
class _View:
    """One block as the align step reads it: its shown elements in document order with their XPath and place, which of
    them are struck through, and its item URL."""

    page: ParsedPage
    block: HtmlElement
    path: str
    href: str
    link: str
    anchors: list[HtmlElement]  # the hyperlinks leading to the item URL, in document order
    elements: list[HtmlElement] = field(default_factory=list)
    paths: dict[HtmlElement, str] = field(default_factory=dict)
    places: dict[HtmlElement, str] = field(default_factory=dict)
    struck: set[HtmlElement] = field(default_factory=set)
    holding_struck: set[HtmlElement] = field(default_factory=set)
    by_path: dict[str, HtmlElement] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        page: ParsedPage,
        block: HtmlElement,
        found: tuple[str, str],
        base: str | None,
        sublists: frozenset[HtmlElement],
    ) -> "_View":
        href, link = found
        anchors = [
            a for a in hyperlinks(block) if a not in sublists and canonical_url(a.get("href") or "", base) == link
        ]
        view = cls(page, block, text_path(block), href, link, anchors)
        view.walk()
        return view

    def walk(self) -> None:
        """The block's elements outside hidden subtrees, each with its XPath (as `text_path` writes it) and its tag
        path from the block. Children are numbered among their same-tag siblings, hidden ones included."""
        stack: list[tuple[HtmlElement, str, str, bool]] = [(self.block, self.path, "", False)]
        while stack:
            element, path, place, struck = stack.pop()
            if hidden(str(element.tag), dict(element.attrib)):
                continue
            struck = struck or is_struck(str(element.tag), dict(element.attrib))
            self.elements.append(element)
            self.paths[element] = path
            self.places[element] = place
            if struck:
                self.struck.add(element)
                self._hold_struck(element)
            stack.extend(reversed(_children(element, path, place, struck)))

    def _hold_struck(self, element: HtmlElement) -> None:
        """Note the ancestors of a struck element up to the block: their lines show its former value."""
        node = element.getparent()
        while node is not None and node not in self.holding_struck and node is not self.block.getparent():
            self.holding_struck.add(node)
            node = node.getparent()

    def line(self, element: HtmlElement) -> str | None:
        """The element's shown text when it is on one line (`ParsedPage.text_spans`), white space collapsed."""
        span = self.page.text_spans.get(self.paths.get(element) or text_path(element))
        if span is None:
            return None
        text = self.page.cleaned_text.text[span[0] : span[1]]
        return None if "\n" in text else " ".join(text.split()) or None

    def read(self, role: Role, spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
        """The field's values in the block, at every place its rule reads."""
        if role == "url":
            anchor_path = self.paths.get(self.anchors[0], self.path) if self.anchors else self.path
            return spots(self.href, spec, ctx, anchor_path, _LINK)
        if role == "name":
            # A URL is not prose (RFC 3986 §4.3, an absolute URI): a link whose label is its own address names nothing;
            # `_field` drops such names.
            return (*self._link_name(spec, ctx), *self._heading(spec, ctx))
        if role == "image":
            return self._image(spec, ctx)
        return self._typed(spec, ctx)

    def _link_name(self, spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
        found = self.link_line()
        return () if found is None else spots(found[1], spec, ctx, self.paths[found[0]], _LINK_NAME)

    def link_line(self) -> tuple[HtmlElement, str] | None:
        """The first shown hyperlink to the item whose content is one line, with that line (HTML Standard §4.5.1: an
        `a` element's content labels its link)."""
        return next(((a, text) for a in self.anchors if a in self.paths and (text := self.line(a)) is not None), None)

    def _heading(self, spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
        headings = [(e, text) for e in self.elements if _is_heading(e) and (text := self.line(e)) is not None]
        if not headings or len({text for _, text in headings}) != 1:
            return ()
        element, text = headings[0]
        return spots(text, spec, ctx, self.paths[element], _HEADING)

    def stated(self) -> Stated | None:
        """The block's attribute-stated name the block shows most words of (the first on a tie), else its first
        stated name (`Stated`); None when it states none."""
        shown = self._words()
        best: Stated | None = None
        for text, element in self._stated_texts():
            found = Stated.of(text, self.paths[element], shown, self.holding)
            if best is None or found.covered > best.covered:
                best = found
        return best

    def _stated_texts(self) -> list[tuple[str, HtmlElement]]:
        """The names the item's attributes state, with their elements: each shown item link's `aria-labelledby`,
        `aria-label` and `title` (Accessible Name Computation 1.2, steps 2B, 2C, 2I), then each shown image's `alt`
        (HTML Standard §4.8.4.4: the image's text alternative), decorative ones aside."""
        texts: list[tuple[str, HtmlElement]] = []
        for anchor in (a for a in self.anchors if a in self.paths):
            stated = (self._labelled_by(anchor), anchor.get("aria-label"), anchor.get("title"))
            texts.extend((text, anchor) for value in stated if (text := _squeezed_text(value)))
        images = (e for e in self.elements if e.tag == "img" and not decorative(dict(e.attrib)))
        texts.extend((text, e) for e in images if (text := _squeezed_text(e.get("alt"))))
        return texts

    def _words(self) -> list[Word]:
        span = self.page.text_spans.get(self.path)
        return [] if span is None else words(self.page.cleaned_text.text, *span)

    def holding(self, start: int, end: int) -> str:
        """The XPath of the innermost shown element whose text holds the cleaned text's `start` to `end`."""
        best = (math.inf, self.path)
        for element in self.elements:
            span = self.page.text_spans.get(self.paths[element])
            if span is not None and span[0] <= start and end <= span[1] and span[1] - span[0] <= best[0]:
                best = (span[1] - span[0], self.paths[element])
        return best[1]

    def line_place(self, found: tuple[Spot, ...]) -> str | None:
        """The tag path of the element a block's name is read at, when that element shows one line of text."""
        element = self.named(found) if found else None
        return self.places[element] if element is not None else None

    def named(self, found: tuple[Spot, ...]) -> HtmlElement | None:
        """The element a block's one name is read at, when the name is that element's one line of text."""
        if len(found) != 1:
            return None
        element = self.at(found[0].xpath)
        return element if element is not None and self.line(element) is not None else None

    def at(self, xpath: str) -> HtmlElement | None:
        if not self.by_path:
            self.by_path = {path: element for element, path in self.paths.items()}
        return self.by_path.get(xpath)

    def children_text(self, element: HtmlElement) -> dict[str, tuple[str, int, int]]:
        """The text and cleaned-text span of each shown element inside `element`, keyed by its tag path below it, for
        the paths one element has."""
        depth = len(self.places[element])
        found: dict[str, list[tuple[str, int, int]]] = {}
        for child in element.iterdescendants():
            span = self.page.text_spans.get(self.paths[child]) if child in self.paths else None
            if span is not None:
                text = " ".join(self.page.cleaned_text.text[span[0] : span[1]].split())
                found.setdefault(self.places[child][depth:], []).append((text, *span))
        return {rel: texts[0] for rel, texts in found.items() if len(texts) == 1 and texts[0][0]}

    def without(self, element: HtmlElement, template: frozenset[str] | set[str]) -> str:
        """The element's one line of text without its children's at the tag paths `template`."""
        span = self.page.text_spans[self.paths[element]]
        children = self.children_text(element)
        cuts = sorted((children[rel][1], children[rel][2]) for rel in template if rel in children)
        text = self.page.cleaned_text.text
        parts, at = [], span[0]
        for start, end in cuts:
            parts.append(text[at : max(at, start)])
            at = max(at, end)
        parts.append(text[at : span[1]])
        return " ".join(" ".join(parts).split())

    def _labelled_by(self, anchor: HtmlElement) -> str | None:
        """WAI-ARIA `aria-labelledby`: the text of the elements its ID references name, joined with spaces."""
        root = anchor.getroottree().getroot()
        texts: list[str] = []
        for ref in tokens(anchor.get("aria-labelledby")):
            element = root.get_element_by_id(ref, None)
            text = None if element is None else " ".join(element.text_content().split())
            texts.extend((text,) if text else ())
        return " ".join(texts) or None

    def _image(self, spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
        for element in self.elements:
            if element.tag != "img":
                continue
            attributes = dict(element.attrib)
            if not decorative(attributes) and (source := image_source(attributes)) is not None:
                return spots(source, spec, ctx, self.paths[element], _PICTURE)
        return ()

    def _typed(self, spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
        hits: list[tuple[HtmlElement, Spot]] = []
        for element in self.elements:
            for text, place in self._typed_texts(element):
                if reads(spec, text, ctx, struck=element in self.struck):
                    hits.extend((element, spot) for spot in spots(text, spec, ctx, self.paths[element], place))
        return tuple(spot for element, spot in hits if not _inner_hit(element, spot, hits, spec))

    def _typed_texts(self, element: HtmlElement) -> list[tuple[str, str]]:
        """The texts of an element a typed value is read from, with their places: its line, unless it shows a struck
        element's text or runs two elements' digits together (`ParsedPage.digit_joins`: `$12` and a `20` badge are not
        `$1220`); and, for an element holding other elements, each of its own text nodes (`ab 12 €` after a child's
        former price)."""
        path = self.paths[element]
        texts: list[tuple[str, str]] = []
        span = None if element in self.holding_struck else self.page.text_spans.get(path)
        if span is not None and not _joins_digits(self.page.digit_joins, span) and (line := self.line(element)):
            texts.append((line, self.places[element]))
        if len(element):
            text = self.page.cleaned_text.text
            own = (" ".join(text[start:end].split()) for start, end in self.page.own_runs.get(path, ()))
            # The runs are keyed by the selectolax tree's paths; a run is this element's only if its lxml text holds it
            # (the two parsers repair malformed markup differently).
            written = " ".join(" ".join(t for t in (element.text, *(c.tail for c in element)) if t).split())
            texts.extend((run, f"{self.places[element]}/text()") for run in own if run and run in written)
        return texts


def _joins_digits(joins: Sequence[int], span: tuple[int, int]) -> bool:
    """Whether a digit join (`ParsedPage.digit_joins`, sorted) lies inside the span."""
    at = bisect.bisect_right(joins, span[0])
    return at < len(joins) and joins[at] < span[1]


def _children(element: HtmlElement, path: str, place: str, struck: bool) -> list[tuple[HtmlElement, str, str, bool]]:
    """The element's child elements with their XPath steps (positions among same-tag siblings) and tag paths."""
    counts: Counter[str] = Counter()
    children: list[tuple[HtmlElement, str, str, bool]] = []
    for child in element:
        if isinstance(child.tag, str):
            counts[child.tag] += 1
            step = xpath_step(child.tag, counts[child.tag])
            children.append((child, f"{path}/{step}", f"{place}/{child.tag}" if place else child.tag, struck))
    return children


def _inner_hit(element: HtmlElement, spot: Spot, hits: Sequence[tuple[HtmlElement, Spot]], spec: FieldSpec) -> bool:
    """Whether an element inside `element` reads the same value: the inner one is the value's element."""
    key = _key(spot, spec)
    return any(other is not element and _contains(element, other) and _key(s, spec) == key for other, s in hits)


def _contains(outer: HtmlElement, inner: HtmlElement) -> bool:
    node = inner.getparent()
    while node is not None:
        if node is outer:
            return True
        node = node.getparent()
    return False


def _current_page(block: HtmlElement, base: str | None, here: str | None) -> bool:
    """Whether the block stands for the page itself in a set of pages: a hyperlink of it is marked as the current page
    (WAI-ARIA 1.2 `aria-current="page"`), or every one of its hyperlinks leads to this very URL, query included (a
    same-document `#` reference aside: HTML Standard, navigating to a fragment). A listing's items never include the
    listing, so a group holding such a block lists documents of the page's own kind: the other categories, cities or
    sorts of a link hub, the site's navigation rather than the page's items."""
    anchors = [a for a in hyperlinks(block) if not (a.get("href") or "").strip().startswith("#")]
    if any((a.get("aria-current") or "").strip().lower() == _CURRENT_PAGE for a in anchors):
        return True
    return here is not None and bool(anchors) and all(canonical_url(a.get("href") or "", base) == here for a in anchors)


def _heading_links(block: HtmlElement, sublists: frozenset[HtmlElement]) -> list[HtmlElement]:
    """The block's hyperlinks inside its headings: a heading labels the content it heads (HTML Standard §4.3.6), so
    its link is the item's, not the other documents the block links to (its seller, its employer)."""
    headings = [element for element in block.iter() if isinstance(element.tag, str) and _is_heading(element)]
    return [a for heading in headings for a in hyperlinks(heading) if a not in sublists]


def _content_links(
    block: HtmlElement, anchors: Sequence[HtmlElement], base: str | None, spans: Mapping[str, tuple[int, int]]
) -> list[HtmlElement]:
    """The block's hyperlinks to the one document whose hyperlinks hold more than half of the block's shown text (by
    their spans of the cleaned text); none when no document's do."""
    block_span = spans.get(text_path(block))
    if block_span is None:
        return []
    held: Counter[str] = Counter()
    for anchor in anchors:
        target = canonical_url(anchor.get("href") or "", base)
        if target is not None and (span := spans.get(text_path(anchor))) is not None:
            held[target] += span[1] - span[0]
    top = held.most_common(1)
    if not top or 2 * top[0][1] <= block_span[1] - block_span[0]:
        return []
    return [anchor for anchor in anchors if canonical_url(anchor.get("href") or "", base) == top[0][0]]


def _squeezed_text(text: str | None) -> str:
    return " ".join((text or "").split())


def _is_heading(element: HtmlElement) -> bool:
    return element.tag in _HEADINGS or _HEADING_ROLE in tokens(element.get("role"))


def one_link(
    block: HtmlElement,
    base: str | None,
    here: str | None,
    sublists: frozenset[HtmlElement] = frozenset(),
    spans: Mapping[str, tuple[int, int]] | None = None,
) -> tuple[str, str] | None:
    """The `href` and canonical URL of the one document the block's hyperlinks lead to, those of its
    own lists (`sublists`) aside (module docstring). When they lead to several: the one without a query the others
    refine, else the one its headings link to, else, with the cleaned text's `spans`, the one whose hyperlinks hold
    more than half of the block's shown text (HTML Standard §4.5.1: an `a` element's content labels its link, so the
    link the block's content labels is the block's; a logo's link to the seller labels little). None when there is no
    such one document."""
    anchors = [a for a in hyperlinks(block) if a not in sublists]
    targets = link_targets(anchors, base, here)
    if len(targets) > 1:
        targets = without_queries(targets) or link_targets(_heading_links(block, sublists), base, here)
    if len(targets) != 1 and spans is not None:
        targets = link_targets(_content_links(block, anchors, base, spans), base, here)
    if len(targets) != 1:
        return None
    ((url, (href, _)),) = targets.items()
    return href, url


def item_links(
    group: Group,
    base: str | None,
    here: str | None,
    sublists: frozenset[HtmlElement],
    spans: Mapping[str, tuple[int, int]],
) -> list[tuple[HtmlElement, tuple[str, str] | None]]:
    """Each block of the group with the `href` and canonical URL of its item (`one_link`), else of the document its
    links at the group's item link place lead to (`_group_place`); None for a block with neither."""
    found = [one_link(block, base, here, sublists, spans) for block in group]
    if all(found):
        return list(zip(group, found, strict=True))
    placed = [_placed_targets(block, base, here, sublists) for block in group]
    shared = _shared_targets(placed)
    own = [_without(block, shared) for block in placed]
    pictured = [_pictured_places(block, sublists) for block in group]
    place = _group_place(own, pictured, quorum(len(group)))
    for i, targets in enumerate(own):
        at = targets.get(place) if place is not None and found[i] is None else None
        if at is not None and len(at) == 1:
            ((url, href),) = at.items()
            found[i] = href, url
    return list(zip(group, found, strict=True))


def _placed_targets(
    block: HtmlElement, base: str | None, here: str | None, sublists: frozenset[HtmlElement]
) -> dict[str, dict[str, str]]:
    """The documents the block's hyperlinks lead to (`link_targets`) by the links' tag paths from the block, each with
    its first `href`, places in document order."""
    placed: dict[str, dict[str, str]] = {}
    for anchor in hyperlinks(block):
        if anchor in sublists:
            continue
        for url, (href, _) in link_targets((anchor,), base, here).items():
            placed.setdefault(_tag_path(block, anchor), {}).setdefault(url, href)
    return placed


def _shared_targets(placed: Sequence[Mapping[str, Mapping[str, str]]]) -> frozenset[str]:
    """The documents two or more blocks link to: the template's (a vendor's, an author's, a category's page), as an
    item is listed once (DEPTA: what repeats across records is the template, not a record's data)."""
    counts = Counter(url for block in placed for url in {u for targets in block.values() for u in targets})
    return frozenset(url for url, count in counts.items() if count >= 2)


def _without(placed: Mapping[str, Mapping[str, str]], shared: frozenset[str]) -> dict[str, dict[str, str]]:
    """The block's placed targets without the `shared` ones, places left with none dropped."""
    kept = {
        place: {url: href for url, href in targets.items() if url not in shared} for place, targets in placed.items()
    }
    return {place: targets for place, targets in kept.items() if targets}


def _group_place(
    own: Sequence[Mapping[str, Mapping[str, str]]], pictured: Sequence[set[str]], needed: int
) -> str | None:
    """The tag path at which a quorum of the blocks link to one document no other block links to: the group's item
    link place, where the template puts each item's link (DEPTA alignment). Of several, the one that comes first in
    the most blocks, a place whose link holds an image before the others (HTML Standard §4.8.4: an `img` in a
    hyperlink is the link's content; a card pictures its item, not its author or seller); None when no place does."""
    counts = Counter(place for block in own for place, targets in block.items() if len(targets) == 1)
    qualified = {place for place, count in counts.items() if count >= needed}
    firsts = Counter(_first_place(block, held, qualified) for block, held in zip(own, pictured, strict=True))
    firsts.pop(None, None)
    return firsts.most_common(1)[0][0] if firsts else None


def _first_place(places: Iterable[str], pictured: set[str], qualified: set[str]) -> str | None:
    """The block's first qualified place, those whose link holds an image first."""
    return next(
        (place for place in sorted(places, key=lambda place: place not in pictured) if place in qualified), None
    )


def _pictured_places(block: HtmlElement, sublists: frozenset[HtmlElement]) -> set[str]:
    """The tag paths of the block's hyperlinks that hold an image."""
    return {
        _tag_path(block, anchor)
        for anchor in hyperlinks(block)
        if anchor not in sublists and next(anchor.iter("img"), None) is not None
    }


def _tag_path(block: HtmlElement, element: HtmlElement) -> str:
    """The tag path from `block` down to `element` (the align step's place: positions aside)."""
    tags: list[str] = []
    node: HtmlElement | None = element
    while node is not None and node is not block:
        tags.append(str(node.tag))
        node = node.getparent()
    return "/".join(reversed(tags))


def link_targets(
    anchors: Iterable[HtmlElement], base: str | None, here: str | None
) -> dict[str, tuple[str, HtmlElement]]:
    """The documents `anchors` lead to other than this page (in any state of its query: RFC 3986 §3.3, the path names
    the resource, so a pager's or a sort's link is the page again) and image files, each with its first anchor's
    `href` and that anchor."""
    page = _resource(here) if here is not None else None
    targets: dict[str, tuple[str, HtmlElement]] = {}
    for anchor in anchors:
        if not is_hyperlink(anchor):
            continue
        href = anchor.get("href") or ""
        target = canonical_url(href, base)
        if target is not None and _resource(target) != page and not is_image_url(target):
            targets.setdefault(target, (href, anchor))
    return targets


def _resource(url: str) -> tuple[str, str, str]:
    """The scheme, authority and path of a URL, the path's trailing slash aside (RFC 3986 §6.2.4)."""
    split = urlsplit(url)
    return split.scheme, split.netloc, split.path.rstrip("/")


def without_queries(targets: dict[str, tuple[str, HtmlElement]]) -> dict[str, tuple[str, HtmlElement]]:
    """The one target without a query when every other target is that document's URL with a query added: the block
    links to one path (RFC 3986 §3.3: the path names the resource within its authority), which some of its links
    refine with a query (§3.4), such as a variant chosen by a swatch; else empty."""
    bare = [url for url in targets if not urlsplit(url).query]
    if len(bare) != 1:
        return {}
    (one,) = bare
    if all(url == one or url.startswith(f"{one}?") for url in targets):
        return {one: targets[one]}
    return {}
