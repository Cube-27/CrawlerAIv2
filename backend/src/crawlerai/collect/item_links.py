"""Item URLs of a listing's role C rows from the page's repeated item blocks (ARCHITECTURE §8.6; D-1024 option (a),
admitted by the owner 2026-10-16).

Role C reads a listing's rows from the cleaned text, which holds no link targets, so its rows carry no item URL. The
page's repeated item blocks (`acquire.items.item_blocks`: sibling elements of one shape that each are or hold a
hyperlink) hold each item's own link. A row whose grounded text values all lie in the text of exactly one block, a
block no other row is in, takes that block's link for each row field that is the item's own schema.org `url`, when the
block's hyperlinks (HTML Standard §4.6.1) lead to exactly one document other than the page. A row in no block or in
several, a block two rows are in, or a block with links to several documents gives no candidate: the rule declines
rather than guesses (C7).
"""

from collections.abc import Iterator, Sequence

from lxml.html import HtmlElement

from crawlerai.acquire.items import is_hyperlink, item_blocks
from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, parse_paths
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import xpath_step
from crawlerai.normalize.base import Context
from crawlerai.normalize.url import canonical_url
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# schema.org Thing.url, "URL of the item": a path straight to it from the row's type names the item's own URL.
_ITEM_URL = ("url",)


def row_links(
    page: ParsedPage, schema: SchemaDef, ctx: Context, rows: Sequence[Entity], candidates: Sequence[Candidate]
) -> tuple[Candidate, ...]:
    """`dom` candidates of the item URL fields for the `rows` role C read, from their blocks (module docstring).
    `candidates` are role C's, which ground each row's text values."""
    fields = {name: spec for name, spec in schema.fields.items() if _item_url(spec)}
    if not fields or not rows:
        return ()
    blocks = item_blocks(page.lxml_tree)
    here = canonical_url(ctx.page_url, None) if ctx.page_url is not None else None
    links: list[Candidate] = []
    diagnostics: list[str] = []  # a URL the candidate model refuses is not a link of the block's own
    for row, block in _blocks_of(rows, blocks, schema, candidates).items():
        if (link := _one_link(block, ctx.base_url, here)) is None:
            continue
        href, xpath = link
        for name, spec in fields.items():
            found = candidate(name, spec, row.id, "dom", href, format_locator("dom", xpath), ctx, diagnostics)
            links.extend(() if found is None else (found,))
    return tuple(links)


def _blocks_of(
    rows: Sequence[Entity], blocks: Sequence[HtmlElement], schema: SchemaDef, candidates: Sequence[Candidate]
) -> dict[Entity, HtmlElement]:
    """Each row's block: the one block whose text holds all its text values, and no other row's."""
    texts = [_squeezed(block.text_content()) for block in blocks]
    rows_in: dict[int, list[Entity]] = {}
    for row in rows:
        values = _text_values(row, schema, candidates)
        found = [i for i, text in enumerate(texts) if values and all(value in text for value in values)]
        if len(found) == 1:
            rows_in.setdefault(found[0], []).append(row)
    return {owners[0]: blocks[i] for i, owners in rows_in.items() if len(owners) == 1}


def _item_url(spec: FieldSpec) -> bool:
    return (
        spec.scope == "row"
        and spec.type is FieldType.URL
        and spec.schema_org is not None
        and any(path.steps == _ITEM_URL and path.joined is None for path in parse_paths(spec.schema_org))
    )


def _text_values(row: Entity, schema: SchemaDef, candidates: Sequence[Candidate]) -> list[str]:
    """The row's grounded text values (role C's spans of text fields), white space dropped."""
    return [
        squeezed
        for c in candidates
        if c.entity_id == row.id
        and c.source_kind == "llm"
        and schema.fields[c.field].type is FieldType.TEXT
        and isinstance(c.raw, str)
        and (squeezed := _squeezed(c.raw))
    ]


def _squeezed(text: str) -> str:
    """`text` without white space: the cleaned text and the DOM's text place it differently between elements."""
    return "".join(text.split())


def _one_link(block: HtmlElement, base: str | None, here: str | None) -> tuple[str, str] | None:
    """The `href` and XPath of the block's first hyperlink to the one document its hyperlinks lead to, other than this
    page (`canonical_url`: http(s), without the fragment); None when they lead to none or to several."""
    targets: dict[str, tuple[str, HtmlElement]] = {}
    for anchor in _hyperlinks(block):
        href = anchor.get("href") or ""
        target = canonical_url(href, base)
        if target is not None and target != here:
            targets.setdefault(target, (href, anchor))
    if len(targets) != 1:
        return None
    ((href, anchor),) = targets.values()
    return href, _xpath(anchor)


def _hyperlinks(block: HtmlElement) -> Iterator[HtmlElement]:
    return (element for element in block.iter("a", "area") if is_hyperlink(element))


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
