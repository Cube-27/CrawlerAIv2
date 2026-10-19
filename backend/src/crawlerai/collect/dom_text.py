"""The DOM description collector (extraction spec, requirement "DOM description block"): the prose block of a detail
page that states a long_text field in full, for pages whose structured data and Open Graph metadata hold only a
summary or a cut of it.

Two structures name such a block, both read from the page's main content (`collect.dom`: the `main` element, else the
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

Prose is a block that holds no table, form control, button, image, media, frame or other element that is not running
text (HTML Standard §3.2.5: flow and phrasing content). A block's text is the cleaned text of its element
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
from crawlerai.collect.locator import format_locator
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
)
# WAI-ARIA 1.2 §5.4: roles of content set apart from the main content.
_APART_ROLES = ("dialog", "alertdialog", "form", "navigation", "complementary", "banner", "contentinfo")
_HEADING = 'h1,h2,h3,h4,h5,h6,[role~="heading"]'
_OPEN_GRAPH = "og"  # the protocol defines og:description as a one-to-two sentence summary
_DESCRIPTION = "description"  # schema.org `Thing.description`
_ELLIPSES = ("…", "...")  # Unicode U+2026, and its NFKC form: how a cut text ends


class _Block(NamedTuple):
    node: LexborNode
    raw: str  # the cleaned text, one block box per line
    form: str  # the same, white space collapsed


class _Blocks:
    """The prose elements of a region with their cleaned text, in document order."""

    def __init__(self, page: ParsedPage, region: LexborNode, outside: frozenset[int]) -> None:
        self.page, self.region = page, region
        spans, text = page.text_spans, page.cleaned_text.text
        selector = ",".join(
            (
                *_TANGENTIAL,
                *_NOT_PROSE,
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
        blocks = _Blocks(page, region, self.outside)
        labels = field_labels(schema)
        found: list[tuple[str, _Block, JsonValue]] = [
            (name, block, None) for name in fields if (block := _described(blocks, labels, schema, name, others))
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
    blocks: _Blocks, labels: dict[tuple[str, ...], list[str]], schema: SchemaDef, name: str, others: Sequence[Candidate]
) -> _Block | None:
    """A long_text field's block: the one extending a stated value, else its labelled section, else the main text."""
    stated = [(c.source_kind, form) for c in others if c.field == name and (form := _stated(c))]
    return _extending(blocks, stated) or _labelled(blocks, labels, name) or _main_text(blocks, schema, name, stated)


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


def _main_text(blocks: _Blocks, schema: SchemaDef, name: str, stated: Sequence[tuple[str, str]]) -> _Block | None:
    """The main text, for a description that only an Open Graph summary (or nothing) states."""
    if _DESCRIPTION not in properties(schema.fields[name]) or any(kind != _OPEN_GRAPH for kind, _ in stated):
        return None
    return _largest(blocks)


def _extending(blocks: _Blocks, stated: Sequence[tuple[str, str]]) -> _Block | None:
    """The outermost prose block that begins with a stated value (or its ellipsis-cut form) and goes on or equals it.
    A block that equals a value other than the Open Graph summary is that value in full, and nothing beyond it. White
    space is not compared: a meta description joins the paragraphs a page's blocks separate."""
    solids = [_solid(form) for kind, form in stated if kind != _OPEN_GRAPH]
    cuts = [(cut, _solid(form) != cut) for _, form in stated if (cut := _uncut(_solid(form)))]
    matching = {b.node.mem_id: b for b in blocks.blocks.values() if any(_begins(b.form, *cut) for cut in cuts)}
    equal = [b for b in matching.values() if _solid(b.form) in solids]
    outer = [b for b in matching.values() if not any(a.mem_id in matching for a in _ancestors(b.node, blocks.region))]
    return _only(equal) or _only(outer)


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
