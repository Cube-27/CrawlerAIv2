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
  the block's headings link to, else the one whose links hold most of the block's text (`one_link`). Else, at
  group level (DEPTA alignment, `item_links`; both in `collect/items/links.py`): the documents two or more blocks link
  to are the template's (a vendor's, an author's, a category's page: an item is listed once), and the block's item is
  the one other document its links lead to at the place where a quorum of the blocks link to one such document (a
  link's place: its tag path and its parent's rank among those of the block's links at that path, `_link_places`).
  A block without one such document is no row.
- **name** (a row text field whose path names schema.org `name`, or JobPosting `title`): the shown content of a
  hyperlink to the block's item when that is one line of text holding no typed value the block aligns (HTML Standard
  §4.5.1; each such link of the block at its own place, so the image link's helper text and the title link's text are
  rival sources), the block's one heading
  (HTML Standard §4.3.6, WAI-ARIA role `heading`), or the name the item's attributes state (`Stated`): an item link's
  `aria-labelledby`, `aria-label` or `title`, an image's `alt` (WAI-ARIA Accessible Name and Description Computation
  1.2), kept where the block shows it (WCAG 2.1 SC 2.5.3 Label in Name, over one or several whole lines, a line cut
  short by an ellipsis standing for the rest), its leading and trailing words the block does not show dropped when
  every block states the same ones (the template's `Details of`). Content of several lines is the whole card, not its
  name; so is a stated name whose shown run holds a typed value the block shows (`_View.stated`: a name holds no
  price). A name read from the item link's content runs on over the block's next whole lines while an image's text
  alternative goes on with them (`_View.continued`: a model name in the link, its variant on the line below). The
  item's links are those leading to its URL, or, for a URL without a query, to it refined with one (`leads_to`).
  Of the three, the one whose values differ most across the blocks: text every block repeats is the template's (a
  call to action), not an item's. A block the chosen rule gives no name reads the one line at the tag path the
  rule's names have in a quorum of blocks (DEPTA alignment: a sold-out card's extra heading, a stale `alt`); a child
  element of the name whose text every block repeats is the template's (screen-reader-only helper text) and is left
  out of the name. A link's one line whose words run on from one element into the next with no white space between
  (`ParsedPage.word_joins`: a title and a location set apart by layout alone) is not one name: its outermost elements
  no join splits are the link's parts, each a place of its own, so the title is read alone. A link that shows its one
  line itself is named by it, never by the name its attributes state (WAI-ARIA's `aria-labelledby` may point at text
  the block hides, such as a price).
- **image** (a row image_url field whose path names schema.org `image`): the block's first shown image that is not
  decorative (`collect.dom_images.image_source`, `collect.dom_images.decorative`).
- **typed values** (a row money, date or datetime field, or an identifier under a scheme with a check digit): typed
  value spotting. The block's shown elements whose text, on one line, the field's normalizer parses (a syntax it
  checks: an ISO 4217 or CLDR amount, an ISO 8601 or CLDR date, a check digit), and, for an element holding others,
  each of its own text nodes; a line where two text nodes run digits together (`ParsedPage.digit_joins`) is two
  numbers, not one. Of an element and one inside it reading the same value, the inner one. Text the HTML Standard
  marks as no longer accurate (`s`, §4.5.4) or removed (`del`, §4.7.2), the obsolete `strike` and text an inline
  `line-through` decoration strikes (`collect.dom.struck`) is no current value: a struck-through former price, which
  only a list price field reads; nor is an option of a drop-down `select` that is not selected (HTML Standard
  §4.10.7: a box of one row shows only its selected option, an add-on's other prices); a money field reads by its price
  role (`collect.items.spot.reads`: no amount written
  per unit or per period for the price). A place every block gives the same value at is the
  template's (a shipping threshold) when another place gives the field differing values. A block whose places give one
  value publishes it; one whose places give several (a price and an instalment) gives an `ambiguous_in_block`
  candidate, which publishes nothing unless a structured row bound to the block agrees with one of them
  (`collect.items.bind`). So does a block showing, beside its aligned value, another value of the field in the same
  currency at a place too few blocks share (`_unsettled`): nothing in the markup says which is the field's.

A group one of whose blocks stands for the page itself (`current_page`: `aria-current="page"`, or links to this very
URL only) is the site's navigation (a category or city hub listing the page among its documents) and gives no rows. So
is a group that aligns no typed value and more than half of whose blocks lead to documents the site's chrome links to
outside the group, or another group apart from it does (`acquire.items.copies_navigation`; chrome as `in_chrome` of
`acquire.items` reads it: the HTML Standard's `nav`, `header`, `footer`, `aside`, `search` and their WAI-ARIA
landmarks, the `menubar` and `menu` roles): the site's navigation repeated in the content (a category carousel, a
menu's tiles, a list of a sidebar's links, the same links in a desktop and a mobile copy), whose destinations are the
site's sections, not the page's items. A typed value (a price, a date) is what an item shows and a
section's link does not: a shop whose menu links its few products still lists them with their prices.

Shown means rendered by the cleaned text's rules (`content.text.hidden`): a hidden subtree of a block is not read. The
group whose blocks align the most fields, of the segment step's first `_MAIN_GROUPS`, is the listing's, that order
breaking ties: profile cards align a name and a link but no price, a product grid all three. Every other group that
aligns follows, for the bind step's sections (a job board's many departments). Each block with an item URL is an
`item_block` entity, and each of its values a `dom` candidate with the XPath of its element.
"""

import bisect
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from lxml.html import HtmlElement
from pydantic import ValidationError

from crawlerai.acquire.items import MIN_ITEMS, Group, copies_navigation, hyperlinks, shows_items
from crawlerai.collect.base import ITEM_BLOCK, Candidate, Entity
from crawlerai.collect.dom import struck as is_struck
from crawlerai.collect.dom_images import decorative, image_source
from crawlerai.collect.items.links import current_page, is_heading, item_links, leads_to, tag_path
from crawlerai.collect.items.spot import Spot, is_typed, reads, spots
from crawlerai.collect.items.stated import Stated, Word, continues, same, words
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, is_item_url
from crawlerai.content.dom import tokens
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import block_links, chrome_links, text_path
from crawlerai.content.text import completed, hidden, xpath_step
from crawlerai.normalize.base import Ambiguous, Context, raw_key
from crawlerai.normalize.dispatch import equality_key
from crawlerai.normalize.strings import collapse
from crawlerai.normalize.url import canonical_url, is_absolute
from crawlerai.schemas.paths import named_property, parse_paths
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaContent

# The share of a group's blocks a place must give a field's value in, besides `MIN_ITEMS` (master plan §3.2).
QUORUM_SHARE: Final = 0.6
# The groups the listing's own is chosen among, in the segment step's order: the ones after them are a page's minor
# lists or its further sections (a job board's departments), read only beside the listing's own (`collect.items.bind`).
_MAIN_GROUPS: Final = 8
# The reason of a block's typed field whose places give several values.
AMBIGUOUS_IN_BLOCK: Final = "ambiguous_in_block"
# schema.org Thing's `name` ("The name of the item"), JobPosting's `title` ("The title of the job"), Thing's `image`.
_NAMES: Final = frozenset({"name", "title"})
_IMAGE: Final = "image"
# The places of the rules that read one value per block.
_LINK, _LINK_NAME, _LINK_PART = "@link", "@link-name", "@link-part"
_HEADING, _STATED, _PICTURE = "@heading", "@stated-name", "@image"


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
    are of, the fields it aligns, what the step reports and whether the group may be the listing's own (one of the
    segment step's first `_MAIN_GROUPS`; the others are read only as its further sections)."""

    blocks: tuple[Block, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    group: Group = ()
    diagnostics: tuple[str, ...] = ()
    fields: frozenset[str] = frozenset()
    main: bool = True

    @property
    def entities(self) -> tuple[Entity, ...]:
        return tuple(block.entity for block in self.blocks)


def quorum(blocks: int) -> int:
    """How many of a group's `blocks` a place must give a field's value in."""
    return max(MIN_ITEMS, math.ceil(QUORUM_SHARE * blocks))


def align(page: ParsedPage, schema: SchemaContent, ctx: Context) -> tuple[Items, ...]:
    """Every group of the page's repeated items that aligns, as rows, best first (module docstring): of the first
    `_MAIN_GROUPS` of the segment step's order, the most fields aligned, then that order; then the others, in that
    order. None for a detail schema, a schema without an item URL field, or a page none of whose first `_MAIN_GROUPS`
    groups links its items."""
    roles = field_roles(schema)
    if schema.page_kind != "listing" or "url" not in roles.values():
        return ()
    sublists = _sublist_links(page.item_groups)
    chrome = chrome_links(page.lxml_tree, ctx.base_url)
    aligned = [
        (rank, a)
        for rank, group in enumerate(page.item_groups)
        if (a := _Aligned.of(page, group, schema, roles, ctx, sublists)) is not None
        and not a.copies_navigation(page.item_groups, roles, chrome, ctx.base_url)
    ]
    order = sorted(aligned, key=lambda found: (found[0] >= _MAIN_GROUPS, -len(found[1].fields), found[0]))
    if not order or order[0][0] >= _MAIN_GROUPS:
        return ()
    return tuple(a.items(schema, ctx, number, rank < _MAIN_GROUPS) for number, (rank, a) in enumerate(order))


def _sublist_links(groups: Sequence[Group]) -> frozenset[HtmlElement]:
    """The hyperlinks of items' own lists (their share buttons, their colour swatches), whose links lead to an item's
    related documents, not to the item (`_View.of`): groups that each lie inside one block of another group, where two
    or more of that group's blocks hold one at one tag path (the structure repeats per item, DEPTA: one template
    renders every item's list alike; a grid inside one section of a page is not an item's list, nor are the different
    lists the page's sections hold) and each such block also links outside it (the item's own link; a section holding
    a list of items is no item)."""
    owner_of = {block: number for number, group in enumerate(groups) for block in group}
    nested: dict[tuple[int, str], list[tuple[HtmlElement, frozenset[HtmlElement]]]] = {}
    for number, group in enumerate(groups):
        if (found := _item_list(group, number, owner_of)) is not None:
            owner, _ = found
            nested.setdefault((owner_of[owner], tag_path(owner, group[0])), []).append(found)
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
        """The group's alignment; None when a block of it is the current page (`current_page`: the group is the
        site's navigation), when fewer than a quorum of its blocks lead to one item, or too few of those show more
        than their link (`acquire.items.shows_items`)."""
        here = canonical_url(ctx.page_url, None) if ctx.page_url is not None else None
        if any(current_page(block, ctx.base_url, here) for block in group):
            return None
        needed = quorum(len(group))
        links = item_links(group, ctx.base_url, here, sublists, page.text_spans, needed)
        views = [_View.of(page, block, found, ctx.base_url, sublists) for block, found in links if found is not None]
        if len(views) < needed or not shows_items(view.block for view in views):
            return None
        return cls(group, views, _fields(views, schema, roles, ctx, needed))

    def copies_navigation(
        self,
        groups: Sequence[Group],
        roles: Mapping[str, Role],
        chrome: Sequence[tuple[HtmlElement, str]],
        base: str | None,
    ) -> bool:
        """Whether the group is a copy of the site's navigation (module docstring): it aligns no typed value, and its
        blocks' item URLs are the documents of the chrome or of another group (`acquire.items.copies_navigation`,
        blocks without an item URL counting against it)."""
        if any(roles[name] == "typed" for name in self.fields):
            return False
        leads = (view.link for view in self.views)
        return copies_navigation(self.group, leads, groups, chrome, lambda block: block_links(block, base))

    def items(self, schema: SchemaContent, ctx: Context, number: int, main: bool) -> Items:
        """The group's rows, its entities numbered `item_block:<number>:<block>`; `main`: it may be the listing's own
        (`Items.main`)."""
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
        return Items(tuple(blocks), tuple(candidates), self.group, tuple(diagnostics), frozenset(self.fields), main)


def _fields(
    views: Sequence["_View"], schema: SchemaContent, roles: Mapping[str, Role], ctx: Context, needed: int
) -> dict[str, list[tuple[Spot, ...]]]:
    """Each aligned field's spots in each block (`_field`), typed values read first: a name holds none of them
    (`_View.stated`)."""
    found: dict[str, list[tuple[Spot, ...]]] = {}
    for name in sorted(roles, key=lambda name: roles[name] == "name"):
        if (kept := _field(views, roles[name], schema.fields[name], ctx, needed)) is not None:
            found[name] = kept
        if kept is not None and roles[name] == "typed":
            for view, spots_ in zip(views, kept, strict=True):
                view.note_values(spots_)
    return {name: found[name] for name in roles if name in found}


def _field(
    views: Sequence["_View"], role: Role, spec: FieldSpec, ctx: Context, needed: int
) -> list[tuple[Spot, ...]] | None:
    """Each block's spots of a field at its aligned places (module docstring); None when no place aligns."""
    if role == "name":
        _note_parts(views)
    found = [view.read(role, spec, ctx) for view in views]
    if role == "typed":
        return _unsettled(found, _aligned(found, needed, spec, one_place=False), needed, spec)
    if role != "name":
        return _aligned(found, needed, spec, one_place=False)
    stated = [view.stated() for view in views]
    own = [_completed(spots_, name, spec, ctx) for spots_, name in zip(found, stated, strict=True)]
    more = _stated_names(views, stated, spec, ctx, needed)
    names = [tuple(s for s in (*a, *b) if not is_absolute(s.raw)) for a, b in zip(own, more, strict=True)]
    kept = _aligned(names, needed, spec, one_place=True)
    if kept is None:
        return None
    named = _untemplated(views, _filled(views, kept, spec, ctx, needed), spec, ctx)
    return [view.continued(found, spec, ctx) for view, found in zip(views, named, strict=True)]


def _note_parts(views: Sequence["_View"]) -> None:
    """Note on each view the group's parts of an item link: the steps from a link to the parts of `MIN_ITEMS` or more
    blocks' links that run two elements' words together (`_View.joined_parts`). One template renders every block, so
    where it runs a title and a location together in some blocks, a layout the cleaned text does not apply sets them
    apart in every block, also where a trailing space happens to separate them."""
    counts = Counter(path for view in views for path in view.joined_parts())
    paths = frozenset(path for path, n in counts.items() if n >= MIN_ITEMS)
    for view in views:
        view.part_paths = paths


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


def _unsettled(
    found: Sequence[tuple[Spot, ...]], kept: list[tuple[Spot, ...]] | None, needed: int, spec: FieldSpec
) -> list[tuple[Spot, ...]] | None:
    """The aligned spots, a block's own values at places too few blocks share added where they differ from its aligned
    ones: nothing in the markup says which of the amounts a block shows is the field's (an offer price in one tile's
    button, a "worth" amount in the place the others show their price), so the block's value is `ambiguous_in_block`
    rather than the aligned place's guess (C7). A place a quorum of blocks share is aligned or the template's. An
    amount in another currency than the aligned ones (ISO 4217) is no rival: a conversion, or a code read in a name.
    """
    if kept is None:
        return None
    shared = set(_distinct_values(found, needed, spec))
    settled: list[tuple[Spot, ...]] = []
    for spots_, aligned in zip(found, kept, strict=True):
        values = {_key(spot, spec) for spot in aligned}
        currencies = {_currency(spot) for spot in aligned}
        strays = tuple(
            s for s in spots_ if s.place not in shared and _key(s, spec) not in values and _currency(s) in currencies
        )
        settled.append((*aligned, *strays) if aligned and strays else aligned)
    return settled


def _currency(spot: Spot) -> object:
    """A money spot's currency (None where the page leaves it unclear); None for another type."""
    value = spot.normalized.value
    return value.get("currency") if isinstance(value, dict) else None


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
    anchors: list[HtmlElement]  # the hyperlinks leading to the item (`leads_to`), in document order
    elements: list[HtmlElement] = field(default_factory=list)
    paths: dict[HtmlElement, str] = field(default_factory=dict)
    places: dict[HtmlElement, str] = field(default_factory=dict)
    struck: set[HtmlElement] = field(default_factory=set)
    holding_unshown: set[HtmlElement] = field(default_factory=set)
    by_path: dict[str, HtmlElement] = field(default_factory=dict)
    values: list[tuple[int, int]] = field(default_factory=list)  # where the block's typed values are (`note_values`)
    part_paths: frozenset[str] = frozenset()  # the group's parts of an item link (`_note_parts`)

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
        anchors = [a for a in hyperlinks(block) if a not in sublists and leads_to(a, link, base)]
        view = cls(page, block, text_path(block), href, link, anchors)
        view.walk()
        return view

    def walk(self) -> None:
        """The block's elements outside hidden subtrees and the options a drop-down list does not display
        (`_undisplayed`), each with its XPath (as `text_path` writes it) and its tag path from the block. Children are
        numbered among their same-tag siblings, hidden ones included."""
        stack: list[tuple[HtmlElement, str, str, bool]] = [(self.block, self.path, "", False)]
        closed: set[HtmlElement] = set()
        while stack:
            element, path, place, struck = stack.pop()
            if element in closed or hidden(str(element.tag), dict(element.attrib)):
                continue
            for option in _undisplayed(element):
                closed.add(option)
                self._hold(option)
            struck = struck or is_struck(str(element.tag), dict(element.attrib))
            self.elements.append(element)
            self.paths[element] = path
            self.places[element] = place
            if struck:
                self.struck.add(element)
                self._hold(element)
            stack.extend(reversed(_children(element, path, place, struck)))

    def _hold(self, element: HtmlElement) -> None:
        """Note the ancestors of a struck element or an undisplayed option up to the block: their lines show its text,
        a former value or a choice."""
        node = element.getparent()
        while node is not None and node not in self.holding_unshown and node is not self.block.getparent():
            self.holding_unshown.add(node)
            node = node.getparent()

    def line(self, element: HtmlElement) -> str | None:
        """The element's shown text when it is on one line (`ParsedPage.text_spans`), white space collapsed."""
        span = self.page.text_spans.get(self.paths.get(element) or text_path(element))
        if span is None:
            return None
        text = self.page.cleaned_text.text[span[0] : span[1]]
        return None if "\n" in text else collapse(text) or None

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
        """Each shown item link's one-line content holding no typed value of the block, at a place of its own: its tag
        path and its rank among the block's item links there. A link holding the group's link parts (`_note_parts`) is
        read as those parts instead, each at a place of its own."""
        found: list[Spot] = []
        ranks: Counter[str] = Counter()
        for anchor in self.anchors:
            text = self.line(anchor) if anchor in self.paths else None
            if text is None or self._holds_value(anchor):
                continue
            ranks[self.places[anchor]] += 1
            place = f"{self.places[anchor]}#{ranks[self.places[anchor]]}"
            parts = self._parts(anchor)
            found.extend(spots(text, spec, ctx, self.paths[anchor], f"{_LINK_NAME}:{place}") if not parts else ())
            for relative, element, part in parts:
                found.extend(spots(part, spec, ctx, self.paths[element], f"{_LINK_PART}:{place}{relative}"))
        return tuple(found)

    def _holds_value(self, element: HtmlElement) -> bool:
        """Whether the element's text holds a typed value read in the block (`note_values`): a name holds none."""
        span = self.page.text_spans.get(self.paths[element])
        return span is not None and any(_overlap(span, at) for at in self.values)

    def joined_parts(self) -> set[str]:
        """The XPath steps, from their link, of the parts of the block's item links whose one line runs two elements'
        words together (`ParsedPage.word_joins`): the outermost shown elements inside such a link whose text no join
        splits."""
        joins = self.page.word_joins
        found: set[str] = set()
        for anchor in (a for a in self.anchors if a in self.paths and self.line(a) is not None):
            if _joined(joins, self.page.text_spans[self.paths[anchor]]):
                start = len(self.paths[anchor])
                found.update(self.paths[element][start:] for element in self._unjoined(anchor, joins))
        return found

    def _unjoined(self, anchor: HtmlElement, joins: Sequence[int]) -> list[HtmlElement]:
        """The outermost shown elements inside `anchor` whose text no join splits."""
        found: list[HtmlElement] = []
        inside: set[HtmlElement] = set()
        for element in anchor.iterdescendants():
            if element.getparent() in inside:
                inside.add(element)
                continue
            at = self.page.text_spans.get(self.paths[element]) if element in self.paths else None
            if at is not None and not _joined(joins, at):
                inside.add(element)
                found.append(element)
        return found

    def _parts(self, anchor: HtmlElement) -> list[tuple[str, HtmlElement, str]]:
        """The link's elements at the group's link parts (`part_paths`) that show one line, with their steps from it."""
        if not self.part_paths:
            return []
        start = len(self.paths[anchor])
        return [
            (relative, element, text)
            for element in anchor.iterdescendants()
            if element in self.paths
            and (relative := self.paths[element][start:]) in self.part_paths
            and (text := self.line(element)) is not None
        ]

    def link_line(self) -> tuple[HtmlElement, str] | None:
        """The first shown hyperlink to the item whose content is one line, with that line (HTML Standard §4.5.1: an
        `a` element's content labels its link)."""
        return next(((a, text) for a in self.anchors if a in self.paths and (text := self.line(a)) is not None), None)

    def _heading(self, spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
        headings = [(e, text) for e in self.elements if is_heading(e) and (text := self.line(e)) is not None]
        if not headings or len({text for _, text in headings}) != 1:
            return ()
        element, text = headings[0]
        return spots(text, spec, ctx, self.paths[element], _HEADING)

    def stated(self) -> Stated | None:
        """The block's attribute-stated name the block shows most words of (the first on a tie), else its first
        stated name (`Stated`); None when it states none. A stated name whose shown run holds a typed value the block
        shows (`note_values`) is left out: a name holds no price or date, so one running on over the card's price is the
        whole card's text, as an accessible name computed from a link's content reads it (Accessible Name Computation
        1.2, step 2F), not the item's name."""
        shown = self._words()
        best: Stated | None = None
        for text, element in self._stated_texts():
            found = Stated.of(text, self.paths[element], shown, self.holding)
            if found.shown and any(_overlap(found.shown_at, at) for at in self.values):
                continue
            if best is None or found.covered > best.covered:
                best = found
        return best

    def note_values(self, found: Iterable[Spot]) -> None:
        """Note the spans of the cleaned text that typed values of the block were read at."""
        text = self.page.cleaned_text.text
        for spot in found:
            element = self.at(spot.xpath)
            span = None if element is None else self.page.text_spans.get(self.paths[element])
            at = -1 if span is None else text.find(spot.raw, *span)
            if at >= 0:
                self.values.append((at, at + len(spot.raw)))

    def continued(self, found: tuple[Spot, ...], spec: FieldSpec, ctx: Context) -> tuple[Spot, ...]:
        """A name read from an item link's content, run on over the block's next whole lines while an image's text
        alternative goes on with them (`_pictured`, `stated.continues`; WCAG 2.1 SC 2.5.3: the stated name holds the
        visible label): a model name in the link and its variant on the line below are the item's name. Unchanged
        otherwise."""
        whole = len(found) == 1 and found[0].place.startswith(f"{_LINK_NAME}:")
        element = self.at(found[0].xpath) if whole else None
        span = None if element is None else self.page.text_spans.get(self.paths[element])
        block = self.page.text_spans.get(self.path)
        stated = self._pictured() if span is not None else []
        if span is None or block is None or not stated:
            return found
        rest = self.page.cleaned_text.text[span[1] : block[1]]
        name = found[0].raw
        for line in rest.split("\n")[1:] if rest.startswith("\n") else ():
            longer = f"{name} {' '.join(line.split())}"
            if not line.strip() or not any(continues(text, longer) for text in stated):
                break
            name = longer
        return found if name == found[0].raw else spots(name, spec, ctx, found[0].xpath, found[0].place) or found

    def _stated_texts(self) -> list[tuple[str, HtmlElement]]:
        """The names the item's attributes state, with their elements: each shown item link's `aria-labelledby`,
        `aria-label` and `title` (Accessible Name Computation 1.2, steps 2B, 2C, 2I), then each shown image's `alt`
        (HTML Standard §4.8.4.4: the image's text alternative), decorative ones aside. A link showing one line of its
        own states none: its content is its label (HTML Standard §4.5.1), and the name its attributes state holds that
        label (WCAG 2.1 SC 2.5.3) and what the link does not show (an `aria-labelledby` naming the card's hidden prices
        too)."""
        texts: list[tuple[str, HtmlElement]] = []
        for anchor in (a for a in self.anchors if a in self.paths and self.line(a) is None):
            stated = (self._labelled_by(anchor), anchor.get("aria-label"), anchor.get("title"))
            texts.extend((text, anchor) for value in stated if (text := _squeezed_text(value)))
        images = (e for e in self.elements if e.tag == "img" and not decorative(dict(e.attrib)))
        texts.extend((text, e) for e in images if (text := _squeezed_text(e.get("alt"))))
        return texts

    def _pictured(self) -> list[str]:
        """The text alternatives of the block's images (HTML Standard §4.8.4.4: an image's `alt` names what it
        pictures, here the item), decorative ones aside, hidden ones too: a carousel a script reveals still pictures
        the item, and its `alt` is read only against the lines the block shows. A link's computed name may join other
        statements to the name (`aria-labelledby` naming the name and an availability badge), so it is not read."""
        images = (e for e in self.block.iter("img") if not decorative(dict(e.attrib)))
        return [text for e in images if (text := _squeezed_text(e.get("alt")))]

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
                text = collapse(self.page.cleaned_text.text[span[0] : span[1]])
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
        return collapse(" ".join(parts))

    def _labelled_by(self, anchor: HtmlElement) -> str | None:
        """WAI-ARIA `aria-labelledby`: the text of the elements its ID references name, joined with spaces."""
        root = anchor.getroottree().getroot()
        texts: list[str] = []
        for ref in tokens(anchor.get("aria-labelledby")):
            element = root.get_element_by_id(ref, None)
            text = None if element is None else collapse(element.text_content())
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
        element's or an undisplayed option's text or runs two elements' digits together (`ParsedPage.digit_joins`:
        `$12` and a `20` badge are not `$1220`); and, for an element holding other elements, each of its own text nodes
        (`ab 12 €` after a child's former price)."""
        path = self.paths[element]
        texts: list[tuple[str, str]] = []
        span = None if element in self.holding_unshown else self.page.text_spans.get(path)
        if span is not None and not _joined(self.page.digit_joins, span) and (line := self.line(element)):
            texts.append((line, self.places[element]))
        if len(element):
            text = self.page.cleaned_text.text
            own = (collapse(text[start:end]) for start, end in self.page.own_runs.get(path, ()))
            texts.extend((run, f"{self.places[element]}/text()") for run in own if run)
        return texts


def _undisplayed(element: HtmlElement) -> set[HtmlElement]:
    """The options of a `select` that it does not display: a select without `multiple` whose display size is 1 renders
    as a drop-down box showing only its selected option, the last one marked `selected`, else its first option that is
    not disabled, by itself or its `optgroup` (HTML Standard §4.10.7, the selectedness setting algorithm; §4.10.10,
    disabled options; Rendering §15.5.15); the others are a form control's choices (an add-on plan, a gift box), not
    what the block shows. None for any other element."""
    if element.tag != "select" or element.get("multiple") is not None or _display_size(element) != 1:
        return set()
    options = list(element.iter("option"))
    selected = [option for option in options if option.get("selected") is not None]
    enabled = [option for option in options if not _disabled(option)]
    shown = selected[-1:] or enabled[:1] or options[:1]
    return set(options) - set(shown)


def _disabled(option: HtmlElement) -> bool:
    """An option is disabled by its `disabled` attribute or its parent `optgroup`'s (HTML Standard §4.10.10)."""
    parent = option.getparent()
    group_disabled = parent is not None and parent.tag == "optgroup" and parent.get("disabled") is not None
    return option.get("disabled") is not None or group_disabled


def _display_size(select: HtmlElement) -> int:
    """A `select`'s display size (HTML Standard §4.10.7): its `size` when that is a valid non-negative integer above
    zero, else 1."""
    size = (select.get("size") or "").strip()
    return int(size) if size.isdigit() and int(size) > 0 else 1


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _joined(joins: Sequence[int], span: tuple[int, int]) -> bool:
    """Whether a join (`ParsedPage.digit_joins`, `ParsedPage.word_joins`; sorted) lies inside the span."""
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


def _squeezed_text(text: str | None) -> str:
    return collapse(text or "")
