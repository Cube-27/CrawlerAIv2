"""The DOM description collector (extraction spec, requirement "DOM description block"): the prose block of a detail
page that states a long_text field in full, for pages whose structured data and Open Graph metadata hold only a
summary or a cut of it.

These structures name such a block, all read from the page's main content (`collect.dom`: the `main` element, else the
`role="main"` landmark, else the one `article`, else the body) outside its tangential content, dialogs, media fallback,
reviews, related items and the blocks outside the product container (`collect.dom.product_apart`):
- **Extension.** A block of prose whose text begins with a candidate another collector proposed for the field (the
  JSON-LD, microdata or Open Graph description, or its ellipsis-cut form) and goes on: it is the whole of what that
  candidate begins. A block that equals a candidate is its corroboration. Of the blocks that begin with it, the
  outermost wins: a description's paragraphs are siblings, and the block holding them all is the description.
- **Labelled section.** The content that follows a heading (HTML Standard §4.3.6, WAI-ARIA `heading`) up to the next
  heading, or that a section names with `aria-label` or `aria-labelledby` (WAI-ARIA 1.2), when the label's words are
  one of the field's labels (`collect.labels`: its name, schema.org property, description and drafted synonyms), as
  label-value pairs are read (C4: the schema's words, never a list). For a list field of values (a job's
  requirements, a recipe's ingredients), what such a section states is the items of its lists (HTML Standard §4.4.5-
  §4.4.8: `ul`, `ol` and `menu` items, `collect.dom.list_items`): one value per item.
- **Item continuation.** A value microdata or RDFa states on an element (`itemprop`, `property`) whose following
  sibling blocks go on with prose: the element and those siblings, their headings with them, up to the first sibling
  that is no prose or that states another property or item. The siblings are inside the item's scope (HTML Standard
  §5.2.2), so they are its text; a template that marks only a description's first section is read whole.
- **Main text.** For a description that only an Open Graph summary states (or nothing does), the longest prose block.
  A summary is shorter than what it summarizes and restates it, so the block must be longer than the summary and hold
  most of the summary's words other than the title's (the page's `h1`); and it must not be the buy box: a block holding
  the page's title heading (an `h1`, or an ARIA heading of level 1) or a price the structural pass read is not text.

Prose is a block that holds no table, form control, button, image, media, frame or other element that is not running
text (HTML Standard §3.2.5: flow and phrasing content). In the extension, labelled-section and item-continuation paths
an image (`img`, `picture`) is phrasing content (HTML Standard §3.2.5.2.5), as rich text places one among its
paragraphs; the main text, which nothing stated names, holds none. A block's text is the cleaned text of its element
(`content.text`): visible text, one block box per line. Reviews and related items are the elements whose `itemprop`
is one of schema.org's `review`, `isRelatedTo` or `isSimilarTo`, and Review items (`itemtype`). Several distinct
blocks that neither contain one another's text nor continue it are ambiguous: nothing is read.

Every candidate is the page's, independent, with a `dom:` locator naming the element it came from.
"""

from collections.abc import Iterator, Sequence
from typing import NamedTuple

from pydantic import JsonValue
from selectolax.lexbor import LexborNode

from crawlerai.collect.base import PAGE, Candidate, CollectResult
from crawlerai.collect.dom import OTHER_ITEMS, content_region, list_items
from crawlerai.collect.labels import field_labels, labelled, properties, words
from crawlerai.collect.locator import InvalidLocator, format_locator, parse_locator
from crawlerai.collect.schema_org_map import candidate
from crawlerai.content.dom import tokens
from crawlerai.content.page import ParsedPage, node_xpath
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldType, SchemaDef

# HTML Standard §4.3 (sectioning content tangential to the main content) and §4.11.4 (`dialog`): not the page's prose.
_TANGENTIAL = ("nav", "header", "footer", "aside", "dialog")
# HTML Standard §4.8 (embedded content), §4.10 (forms: interactive controls), §4.9 (tabular data), §4.12 (scripting):
# elements that are no running text.
_NOT_PROSE = (
    "table",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "img",
    "picture",
    "video",
    "audio",
    "canvas",
    "svg",
    "iframe",
    "object",
    "embed",
    "script",
    "style",
    "template",
)
# HTML Standard §3.2.5.2.5: embedded content that is phrasing content, and so runs among the text of rich prose.
_PHRASING_IMAGES = frozenset({"img", "picture"})
# WAI-ARIA 1.2 §5.4: roles of content set apart from the main content.
_APART_ROLES = ("dialog", "alertdialog", "form", "navigation", "complementary", "banner", "contentinfo")
_HEADING = 'h1,h2,h3,h4,h5,h6,[role~="heading"]'
# HTML Standard §4.3.6 and WAI-ARIA 1.2 `aria-level`: the page's title heading, which opens the item, not its text.
_TITLE_HEADING = 'h1,[role~="heading"][aria-level="1"]'
# HTML Standard §5.2.2 (microdata) and RDFa Core 1.1 §7.5: attributes that state a property or an item of their own.
_ITEM_ATTRIBUTES = ("itemprop", "itemscope", "property", "typeof")
_ELEMENT_VALUED = "microdata"  # the collector of microdata and RDFa: a value states the element its locator names
_OPEN_GRAPH = "og"  # the protocol defines og:description as a one-to-two sentence summary
_DESCRIPTION = "description"  # schema.org `Thing.description`
_ELLIPSES = ("…", "...")  # Unicode U+2026, and its NFKC form: how a cut text ends


class _Block(NamedTuple):
    node: LexborNode
    raw: str  # the cleaned text, one block box per line
    form: str  # the same, white space collapsed


class _Blocks:
    """The prose elements of a region with their cleaned text, in document order."""

    def __init__(self, page: ParsedPage, region: LexborNode, outside: frozenset[int], *, images: bool = False) -> None:
        """`images`: whether an image is phrasing content (module docstring)."""
        self.page, self.region = page, region
        spans, text = page.text_spans, page.cleaned_text.text
        selector = ",".join(
            (
                *_TANGENTIAL,
                *(tag for tag in _NOT_PROSE if not (images and tag in _PHRASING_IMAGES)),
                *(f'[role~="{role}"]' for role in _APART_ROLES),
                OTHER_ITEMS,
            )
        )
        # The outermost elements outside the product container are set apart as the selected roots are.
        roots = [*region.css(selector), *(n for n in region.css("*") if _outermost(n, outside))]
        # Inside an element set apart, and around one (a block that holds a form is not prose).
        self.apart = outside | frozenset(inside.mem_id for root in roots for inside in (root, *root.css("*")))
        self.mixed = frozenset(a.mem_id for root in roots for a in _ancestors(root, region))
        # A heading names a block; it is no text of its own, nor is anything inside it.
        titles = frozenset(inside.mem_id for h in region.css(_HEADING) for inside in (h, *h.css("*")))
        # Nodes are told apart by identity (`mem_id`): selectolax's `==` compares serialized markup, which costs the
        # size of the subtree and calls two equal-looking elements one.
        skipped = self.apart | self.mixed | titles | {region.mem_id}
        self.blocks: dict[int, _Block] = {}
        for node in region.css("*"):
            if node.mem_id in skipped:
                continue
            span = spans.get(node_xpath(node))
            raw = text[span[0] : span[1]].strip() if span else ""
            if raw:
                self.blocks[node.mem_id] = _untitled(_Block(node, raw, " ".join(raw.split())))

    def prose(self, node: LexborNode) -> _Block | None:
        return self.blocks.get(node.mem_id)

    def text(self, node: LexborNode) -> str:
        """The cleaned text of an element, its headings with it: one block box per line."""
        span = self.page.text_spans.get(node_xpath(node))
        return self.page.cleaned_text.text[span[0] : span[1]].strip() if span else ""


def _ancestors(node: LexborNode, region: LexborNode) -> Iterator[LexborNode]:
    parent = node.parent
    while parent is not None:
        yield parent
        if parent.mem_id == region.mem_id:
            return
        parent = parent.parent


def _outermost(node: LexborNode, outside: frozenset[int]) -> bool:
    return node.mem_id in outside and (node.parent is None or node.parent.mem_id not in outside)


def _heading(node: LexborNode) -> bool:
    return node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} or "heading" in tokens(node.attributes.get("role"))


def _stated(candidate_: Candidate) -> str | None:
    value = candidate_.normalized.value if isinstance(candidate_.normalized, Ok) else None
    return " ".join(value.split()) if isinstance(value, str) else None


class DescriptionCollector:
    def __init__(self, outside: frozenset[int] = frozenset()) -> None:
        # The elements outside the page's product container (`collect.dom.product_apart`).
        self.outside = outside

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]) -> CollectResult:
        fields = [name for name, spec in schema.fields.items() if spec.type is FieldType.LONG_TEXT]
        lists = [name for name, spec in schema.fields.items() if spec.type is FieldType.LIST and labelled(spec)]
        wanted = fields or lists
        region = content_region(page) if schema.page_kind == "detail" and not page.json_body and wanted else None
        if region is None:
            return CollectResult(entities=(), candidates=())
        blocks = _Blocks(page, region, self.outside, images=True)
        main = _MainText(page, region, self.outside, schema, others)
        labels = field_labels(schema)
        found: list[tuple[str, _Block, JsonValue]] = [
            (name, block, None) for name in fields if (block := _described(blocks, main, labels, name, others))
        ]
        found.extend((name, *listed) for name in lists if (listed := _listed(blocks, labels, name)) is not None)
        diagnostics: list[str] = []
        candidates = [
            made
            for name, block, read in found
            if (made := _candidate(name, block, read, schema, ctx, diagnostics)) is not None
        ]
        return CollectResult(entities=(), candidates=tuple(candidates), diagnostics=tuple(diagnostics))


def _described(
    blocks: _Blocks, main: "_MainText", labels: dict[tuple[str, ...], list[str]], name: str, others: Sequence[Candidate]
) -> _Block | None:
    """A long_text field's block: the one extending a stated value or continuing an element-valued one, whichever goes
    on further, else its labelled section, else the main text."""
    stated = [(c.source_kind, form) for c in others if c.field == name and (form := _stated(c))]
    extended = _extending(blocks, stated)
    continued = _only([b for c in others if c.field == name and (b := _continued(blocks, c)) is not None])
    if continued is not None and (extended is None or _goes_on(continued, extended)):
        return continued
    return extended or _labelled(blocks, labels, name) or main.read(name, stated)


def _goes_on(block: _Block, other: _Block) -> bool:
    return len(block.form) > len(other.form) and _solid(block.form).startswith(_solid(other.form))


def _continued(blocks: _Blocks, stated: Candidate) -> _Block | None:
    """The element a microdata or RDFa value states with the prose its following siblings go on with (module
    docstring, item continuation); none when no sibling goes on."""
    element = _element(blocks, stated) if stated.source_kind == _ELEMENT_VALUED and _stated(stated) else None
    start = None if element is None else blocks.prose(element)
    if element is None or start is None:
        return None
    raws = [start.raw, *_going_on(blocks, element)]
    return _Block(element, "\n".join(raws), " ".join(" ".join(r.split()) for r in raws)) if len(raws) > 1 else None


def _going_on(blocks: _Blocks, element: LexborNode) -> Iterator[str]:
    """The texts of the element's following siblings that are prose or headings, up to the first that is neither or
    that states another property or item."""
    for sibling in _after(element):
        if not sibling.is_element_node:
            continue
        if any(a in sibling.attributes for a in _ITEM_ATTRIBUTES) or sibling.mem_id in blocks.apart:
            return
        raw = blocks.text(sibling)
        if raw and not (_heading(sibling) or blocks.prose(sibling) is not None):
            return
        if raw:
            yield raw


def _element(blocks: _Blocks, stated: Candidate) -> LexborNode | None:
    """The region's element a microdata or RDFa candidate's locator names (`microdata:<xpath>`)."""
    try:
        xpath = parse_locator(stated.locator).parts[0]
    except InvalidLocator:
        return None
    return next((n for n in blocks.region.css("[itemprop],[property]") if node_xpath(n) == xpath), None)


def _candidate(
    name: str, block: _Block, read: JsonValue, schema: SchemaDef, ctx: Context, diagnostics: list[str]
) -> Candidate | None:
    locator = format_locator("dom", node_xpath(block.node))
    return candidate(name, schema.fields[name], PAGE, "dom", block.raw, locator, ctx, diagnostics, read=read)


def _listed(blocks: _Blocks, labels: dict[tuple[str, ...], list[str]], name: str) -> tuple[_Block, JsonValue] | None:
    """The list items of the sections a heading naming the field opens (`_section_parts`), with the first block
    holding them; none when no such section holds a list, or when sections give different items."""
    named = [form for form, fields in labels.items() if name in fields]
    found = [
        listed
        for heading in blocks.region.css(_HEADING)
        if node_xpath(heading) in blocks.page.text_spans
        and words(" ".join(heading.text(deep=True, separator=" ").split())) in named
        and (listed := _section_items(blocks, heading)) is not None
    ]
    return found[0] if found and all(items == found[0][1] for _, items in found) else None


def _section_items(blocks: _Blocks, heading: LexborNode) -> tuple[_Block, JsonValue] | None:
    """The items of the lists in a heading's section, with the first block holding one."""
    listed = [
        (part, items) for part in _section_parts(blocks, heading) if (items := list_items(part.node, blocks.page))
    ]
    if not listed:
        return None
    return listed[0][0], [*(item for _, items in listed for item in items)]


class _MainText:
    """The main text of a region (module docstring), for a description that only an Open Graph summary (or nothing)
    states. Its blocks, in which an image is no prose, are read only when it is asked for."""

    def __init__(
        self,
        page: ParsedPage,
        region: LexborNode,
        outside: frozenset[int],
        schema: SchemaDef,
        others: Sequence[Candidate],
    ) -> None:
        self.page, self.region, self.outside, self.schema = page, region, outside, schema
        # The elements of the prices the structural pass read (`dom:<xpath>` locators of money fields' candidates).
        self.prices = [
            c.locator.removeprefix("dom:")
            for c in others
            if c.source_kind == "dom"
            and (spec := schema.fields.get(c.field)) is not None
            and spec.type is FieldType.MONEY
        ]

    def read(self, name: str, stated: Sequence[tuple[str, str]]) -> _Block | None:
        if _DESCRIPTION not in properties(self.schema.fields[name]) or any(kind != _OPEN_GRAPH for kind, _ in stated):
            return None
        block = _largest(_Blocks(self.page, self.region, self.outside))
        if block is None or self._buy_box(block):
            return None
        title = {w for h in self.region.css(_TITLE_HEADING) for w in words(h.text(deep=True, separator=" "))}
        return block if all(_summarizes(form, block, title) for _, form in stated) else None

    def _buy_box(self, block: _Block) -> bool:
        """Whether the block holds the page's title heading or a price the structural pass read."""
        path = node_xpath(block.node)
        return block.node.css_first(_TITLE_HEADING) is not None or any(
            p == path or p.startswith(f"{path}/") for p in self.prices
        )


def _summarizes(summary: str, block: _Block, title: set[str]) -> bool:
    """Whether `summary` can summarize the block: it is shorter, and most of its words other than the title's are the
    block's."""
    own = set(words(summary)) - title
    return len(block.form) > len(summary) and 2 * len(own & set(words(block.form))) > len(own)


def _extending(blocks: _Blocks, stated: Sequence[tuple[str, str]]) -> _Block | None:
    """The outermost prose block that begins with a stated value (or its ellipsis-cut form) and goes on or equals it.
    A block that equals a value other than a summary (the Open Graph description, and any value stating the same text)
    is that value in full, and nothing beyond it. White space is not compared: a meta description joins the paragraphs
    a page's blocks separate."""
    solids = _full(stated)
    cuts = [(cut, _solid(form) != cut) for _, form in stated if (cut := _uncut(_solid(form)))]
    matching = {b.node.mem_id: b for b in blocks.blocks.values() if any(_begins(b.form, *cut) for cut in cuts)}
    equal = [b for b in matching.values() if _solid(b.form) in solids]
    outer = [b for b in matching.values() if not any(a.mem_id in matching for a in _ancestors(b.node, blocks.region))]
    return _only(equal) or _only(outer)


def _full(stated: Sequence[tuple[str, str]]) -> list[str]:
    """The stated values, white space aside, that are no summary: neither Open Graph's nor one stating its text."""
    summaries = {_solid(form) for kind, form in stated if kind == _OPEN_GRAPH}
    return [solid for _, form in stated if (solid := _solid(form)) not in summaries]


def _uncut(solid: str) -> str:
    """A text without the ellipsis that ends it."""
    return solid.removesuffix(_ELLIPSES[0]) if solid.endswith(_ELLIPSES[0]) else solid.removesuffix(_ELLIPSES[1])


def _begins(form: str, cut: str, ellipsis: bool) -> bool:
    """Whether the collapsed `form` begins with `cut`, white space aside, without splitting a word (UAX #29
    approximated by letters and digits) unless an ellipsis marked the cut."""
    if not _solid(form).startswith(cut):
        return False
    left, end = len(cut), 0
    while left:
        left -= not form[end].isspace()
        end += 1
    return ellipsis or not (end < len(form) and cut[-1].isalnum() and form[end].isalnum())


def _solid(text: str) -> str:
    return "".join(text.split())


def _only(found: Sequence[_Block]) -> _Block | None:
    """The one block of `found`, where the others are prefixes of it; none when the blocks differ."""
    longest = max(found, key=lambda b: len(b.form), default=None)
    if longest is None or any(not longest.form.startswith(b.form) for b in found):
        return None
    return longest


def _labelled(blocks: _Blocks, labels: dict[tuple[str, ...], list[str]], name: str) -> _Block | None:
    region = blocks.region
    named = [form for form, fields in labels.items() if name in fields]
    found: list[_Block] = []
    for heading in region.css(_HEADING):
        if words(" ".join(heading.text(deep=True, separator=" ").split())) in named:
            found.extend(_section(blocks, heading))
    for element in region.css("[aria-label],[aria-labelledby]"):
        found.extend(_labelled_by(blocks, element, named))
    return _only(found)


def _section(blocks: _Blocks, heading: LexborNode) -> list[_Block]:
    """The prose that follows a heading up to the next heading, as one block."""
    parts = _section_parts(blocks, heading)
    return [_Block(parts[0].node, "\n".join(p.raw for p in parts), " ".join(p.form for p in parts))] if parts else []


def _section_parts(blocks: _Blocks, heading: LexborNode) -> list[_Block]:
    """The prose blocks that follow a heading up to the next heading; climbs only out of a wrapper that holds nothing
    after the heading."""
    node: LexborNode | None = None if heading.mem_id in blocks.apart else heading
    while node is not None and node != blocks.region:
        parts = _following(blocks, node)
        if parts:
            return parts
        if any(sibling.is_element_node for sibling in _after(node)):
            return []
        node = node.parent
    return []


def _after(node: LexborNode) -> Iterator[LexborNode]:
    sibling = node.next
    while sibling is not None:
        yield sibling
        sibling = sibling.next


def _following(blocks: _Blocks, node: LexborNode) -> list[_Block]:
    """The prose elements after `node` among its siblings, up to the next heading."""
    parts: list[_Block] = []
    for sibling in _after(node):
        if sibling.is_element_node and _stops(sibling):
            break
        block = blocks.prose(sibling) if sibling.is_element_node else None
        if block is not None:
            parts.append(block)
    return parts


def _stops(node: LexborNode) -> bool:
    return _heading(node) or bool(node.css_first(_HEADING))


def _labelled_by(blocks: _Blocks, element: LexborNode, named: list[tuple[str, ...]]) -> list[_Block]:
    label = _label(blocks, element)
    block = blocks.prose(element)
    if block is None or label is None or words(label) not in named:
        return []
    lead = " ".join(label.split())
    form = block.form[len(lead) :].strip() if block.form.startswith(lead) else block.form
    if not form:
        return []
    return [block if form == block.form else _Block(block.node, form, form)]


def _label(blocks: _Blocks, element: LexborNode) -> str | None:
    """The element's accessible name from `aria-label`, else the text of the elements `aria-labelledby` names (WAI-ARIA
    1.2 §4.3)."""
    label = element.attributes.get("aria-label")
    if label is not None:
        return label
    targets = [
        blocks.region.css_first(f'[id="{ident}"]')
        for ident in (element.attributes.get("aria-labelledby") or "").split()
        if '"' not in ident
    ]
    texts = [" ".join(t.text(deep=True, separator=" ").split()) for t in targets if t is not None]
    return " ".join(texts) or None


def _largest(blocks: _Blocks) -> _Block | None:
    """The longest of the region's maximal prose blocks (those whose parent is no prose block): the main text. A block
    of mostly links is no text; a heading that opens a block names it, it is not its text."""
    maximal = [b for b in blocks.blocks.values() if b.node.parent is None or blocks.prose(b.node.parent) is None]
    ranked = sorted((b for b in maximal if not _linked(b)), key=lambda b: len(b.form), reverse=True)[:2]
    if not ranked or (len(ranked) == 2 and len(ranked[0].form) == len(ranked[1].form)):
        return None
    return ranked[0]


def _linked(block: _Block) -> bool:
    """Whether most of the block's text is link text: a list of links is navigation or related items, not prose."""
    links = sum(len(" ".join(a.text(deep=True, separator=" ").split())) for a in block.node.css("a[href]"))
    return 2 * links > len(block.form)


def _untitled(block: _Block) -> _Block:
    heading = block.node.css_first(_HEADING)
    lines = block.raw.split("\n")
    if heading is None or " ".join(lines[0].split()) != " ".join(heading.text(deep=True, separator=" ").split()):
        return block
    raw = "\n".join(lines[1:]).strip()
    return _Block(block.node, raw, " ".join(raw.split()))
