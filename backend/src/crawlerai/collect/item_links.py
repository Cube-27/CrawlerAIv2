"""Item URLs of a listing's role C rows from the page's repeated item blocks (ARCHITECTURE §8.6; D-1024 option (a),
admitted by the owner 2026-10-16).

Role C reads a listing's rows from the cleaned text, which holds no link targets, so its rows carry no item URL. The
page's repeated item blocks (`acquire.items.item_groups`: sibling elements of one shape that each are or hold a
hyperlink) hold each item's own link. A row's block is the one block whose span of the cleaned text
(`content.item_text.block_spans`) holds every grounded value of the row at its offsets (INV-12): where the values
sit in the page, not what they say, so items that repeat a title and price (one product in several colours) each
keep their own block (D-1490). A block no other row has as its block gives the row's fields that are the item's own
schema.org `url` the one document its hyperlinks (HTML Standard §4.6.1) lead to other than the page, or else the one
document its hyperlinks labelled with a row value (their whole text is one) lead to (§4.5.1: an `a` element's content
labels its link; D-1243). The rows are looked for in every group of repeated items, and the group that places most
rows is theirs (D-1244). Block text, for the labels, is read as the cleaned text shows it (`content.text`: hidden and
non-rendered elements left out, NFC, an ellipsis cut completed by its `title`; D-1241). A row in no block, a block two
rows have, or a block whose links lead to several documents with none labelled by the row gives no candidate: the
rule declines rather than guesses (C7).
"""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from lxml.html import HtmlElement

from crawlerai.acquire.items import is_hyperlink, item_groups
from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.locator import format_locator, parse_locator
from crawlerai.collect.schema_org_map import candidate, parse_paths
from crawlerai.content.item_text import block_spans
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import completed, hidden, xpath_step
from crawlerai.normalize.base import Context
from crawlerai.normalize.text import compose
from crawlerai.normalize.url import canonical_url
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# A span of the cleaned text: its start and end offsets.
_Span = tuple[int, int]
# schema.org Thing.url, "URL of the item": a path straight to it from the row's type names the item's own URL.
_ITEM_URL = ("url",)


@dataclass(frozen=True, slots=True)
class _Block:
    """One repeated item block and each element's whole text in it as the cleaned text shows it, white space dropped
    (`_squeezed`)."""

    element: HtmlElement
    texts: dict[HtmlElement, str]

    @classmethod
    def read(cls, element: HtmlElement) -> "_Block":
        return cls(element, _shown_texts(element))


def row_links(
    page: ParsedPage, schema: SchemaDef, ctx: Context, rows: Sequence[Entity], candidates: Sequence[Candidate]
) -> tuple[Candidate, ...]:
    """`dom` candidates of the item URL fields for the `rows` role C read, from their blocks (module docstring).
    `candidates` are role C's, which ground each row's values at `text` locators."""
    fields = {name: schema.fields[name] for name in item_url_fields(schema)}
    if not fields or not rows:
        return ()
    grounded = {row.id: _grounded(row, candidates) for row in rows}
    here = canonical_url(ctx.page_url, None) if ctx.page_url is not None else None
    links: list[Candidate] = []
    diagnostics: list[str] = []  # a URL the candidate model refuses is not a link of the block's own
    for row, element in _rows_group(page, rows, grounded).items():
        if (link := _one_link(page, _Block.read(element), grounded[row.id], ctx.base_url, here)) is None:
            continue
        href, xpath = link
        for name, spec in fields.items():
            found = candidate(name, spec, row.id, "dom", href, format_locator("dom", xpath), ctx, diagnostics)
            links.extend(() if found is None else (found,))
    return tuple(links)


def _rows_group(
    page: ParsedPage, rows: Sequence[Entity], grounded: dict[str, list[tuple[str, _Span]]]
) -> dict[Entity, HtmlElement]:
    """The rows' blocks in the group that places most rows; on a tie, the larger group, then the first."""
    best: dict[Entity, HtmlElement] = {}
    best_size = 0
    for group in item_groups(page.lxml_tree):
        spans = block_spans(page, group)
        placed = _blocks_of(rows, grounded, spans)
        if (len(placed), len(group)) > (len(best), best_size):
            best, best_size = {row: group[i] for row, i in placed.items()}, len(group)
    return best


def _blocks_of(
    rows: Sequence[Entity], grounded: dict[str, list[tuple[str, _Span]]], spans: Sequence[_Span | None]
) -> dict[Entity, int]:
    """Each row's block (`_block_of`), when no other row has it as its block."""
    rows_in: dict[int, list[Entity]] = {}
    for row in rows:
        if (found := _block_of([span for _, span in grounded[row.id]], spans)) is not None:
            rows_in.setdefault(found, []).append(row)
    return {owners[0]: i for i, owners in rows_in.items() if len(owners) == 1}


def _block_of(values: Sequence[_Span], spans: Sequence[_Span | None]) -> int | None:
    """The block whose span holds every value's span; None when the row has no value or no one block holds them all
    (sibling blocks do not overlap, so at most one does)."""
    if not values:
        return None
    return next(
        (
            i
            for i, span in enumerate(spans)
            if span is not None and all(span[0] <= start and end <= span[1] for start, end in values)
        ),
        None,
    )


def item_url_fields(schema: SchemaDef) -> tuple[str, ...]:
    """The schema's row fields that `row_links` fills: the item's own URL (`_ITEM_URL`)."""
    return tuple(name for name, spec in schema.fields.items() if _item_url(spec))


def _item_url(spec: FieldSpec) -> bool:
    return (
        spec.scope == "row"
        and spec.type is FieldType.URL
        and spec.schema_org is not None
        and any(path.steps == _ITEM_URL and path.joined is None for path in parse_paths(spec.schema_org))
    )


def _grounded(row: Entity, candidates: Sequence[Candidate]) -> list[tuple[str, _Span]]:
    """The row's grounded values, white space dropped, with their spans of the cleaned text: role C's values of any of
    its fields, each a span of the cleaned text at its `text` locator (SPEC-06 §4.3, INV-12)."""
    found: list[tuple[str, _Span]] = []
    for c in candidates:
        if c.entity_id != row.id or c.source_kind != "llm" or not isinstance(c.raw, str):
            continue
        locator = parse_locator(c.locator)
        if locator.scheme == "text" and (squeezed := _squeezed(c.raw)):
            found.append((squeezed, (int(locator.parts[0]), int(locator.parts[1]))))
    return found


def _squeezed(text: str) -> str:
    """`text` without white space, in the cleaned text's Unicode form (`compose`, NFC): the cleaned text and the DOM's
    text place white space differently between elements."""
    return "".join(compose(text).split())


def _shown_texts(root: HtmlElement) -> dict[HtmlElement, str]:
    """Each element's text under `root` as the cleaned text shows it, white space dropped: elements the HTML Standard
    does not render or the page hides (`content.text.hidden`) are left out, and an element whose text is its `title`
    cut short reads as that title (`content.text.completed`, D-1154). Children are read before their parents, without
    recursion."""
    texts: dict[HtmlElement, str] = {}
    for element in reversed(list(root.iter())):
        tag = element.tag
        # A comment or processing instruction, or an element the cleaned text hides with its subtree.
        if not isinstance(tag, str) or hidden(tag, dict(element.attrib)):
            continue
        own = _squeezed(element.text or "") + "".join(
            texts.get(child, "") + _squeezed(child.tail or "") for child in element
        )
        title = element.get("title")
        full = completed(element.text_content(), title) if title else None
        texts[element] = own if full is None else _squeezed(full)
    return texts


def _one_link(
    page: ParsedPage, block: _Block, values: Sequence[tuple[str, _Span]], base: str | None, here: str | None
) -> tuple[str, str] | None:
    """The `href` and XPath of the block's first hyperlink to the one document its hyperlinks lead to, other than this
    page (`canonical_url`: http(s), without the fragment); when they lead to several, of the one document the
    hyperlinks a row value labels lead to (`_labelled`); None when there is no such one document."""
    targets = _targets(_hyperlinks(block.element), base, here)
    if len(targets) > 1:
        targets = _without_queries(targets) or _targets(_labelled(page, block, values), base, here)
    if len(targets) != 1:
        return None
    ((href, anchor),) = targets.values()
    return href, _xpath(anchor)


def _without_queries(targets: dict[str, tuple[str, HtmlElement]]) -> dict[str, tuple[str, HtmlElement]]:
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


def _labelled(page: ParsedPage, block: _Block, values: Sequence[tuple[str, _Span]]) -> list[HtmlElement]:
    """The block's hyperlinks a row value labels (HTML Standard §4.5.1: an `a` element's content labels its link):
    those whose content holds a grounded value at its offsets, or whose whole text is a row value (D-1243)."""
    anchors = list(_hyperlinks(block.element))
    texts = {text for text, _ in values}
    spans = block_spans(page, anchors)
    return [
        anchor
        for anchor, span in zip(anchors, spans, strict=True)
        if block.texts.get(anchor) in texts or (span is not None and _holds(span, [at for _, at in values]))
    ]


def _holds(span: _Span, values: Iterable[_Span]) -> bool:
    return any(span[0] <= start and end <= span[1] for start, end in values)


def _targets(anchors: Iterable[HtmlElement], base: str | None, here: str | None) -> dict[str, tuple[str, HtmlElement]]:
    """The documents `anchors` lead to other than this page, each with its first anchor and that anchor's `href`."""
    targets: dict[str, tuple[str, HtmlElement]] = {}
    for anchor in anchors:
        href = anchor.get("href") or ""
        target = canonical_url(href, base)
        if target is not None and target != here:
            targets.setdefault(target, (href, anchor))
    return targets


def _hyperlinks(block: HtmlElement) -> Iterator[HtmlElement]:
    return (element for element in block.iter("a", "area") if is_hyperlink(element))


def block_links(block: HtmlElement, base: str | None) -> Iterator[str]:
    """The canonical URLs the block's hyperlinks (HTML Standard §4.6.1) lead to, in document order, repeats kept."""
    for anchor in _hyperlinks(block):
        if (url := canonical_url(anchor.get("href") or "", base)) is not None:
            yield url


def group_links(page: ParsedPage, base: str | None) -> list[frozenset[str]]:
    """The documents each group of repeated item blocks (`item_groups`) links to, by group, in the groups' order."""
    return [
        frozenset(url for block in group for url in block_links(block, base)) for group in item_groups(page.lxml_tree)
    ]


def _xpath(element: HtmlElement) -> str:
    """The XPath 1.0 path of `element`, one positional step per ancestor (`content.page.node_xpath`'s form)."""
    steps: list[str] = []
    current: HtmlElement | None = element
    while current is not None:
        parent, tag = current.getparent(), str(current.tag)
        siblings = [] if parent is None else parent.findall(tag)
        index = 1 + next((i for i, sibling in enumerate(siblings) if sibling is current), 0)
        steps.append(xpath_step(tag, index))
        current = parent
    return "/" + "/".join(reversed(steps))
