"""Listing induction: a
listing's row selector and row-field steps generalized from the item layer's aligned blocks across the learning
sample, without an LLM.

On each sample page the item layer's align step (`collect.items.align`) locates the group of repeated item blocks; the
group whose item URLs the published rows name most is the page's. Then:
- **row selector**: for each block, each anchored path to it (`induction`: stable attributes only, no positions),
  then its tag path from the document with the ancestors' positions; one is kept when, on every page, it
  selects every block that leads to an item and nothing outside the group (DEPTA's partial alignment, Zhai and Liu
  2005: a block the page does not repeat is no row);
- **row fields**: each published row is paired with the block whose item URL it publishes (RFC 3986 §6: compared
  canonical). Within the block, every element whose normalized text (XPath 1.0 `normalize-space`) or one attribute
  normalizes to the row's published value proposes relative paths to itself: through each stable anchor on it or an
  ancestor inside the block, then its tag path, then its tag path with positions. A path is kept when the most rows
  propose it among those every page verifies: run by the engine executor under the row selector, it gives a valid value
  on every row, and the published value on every row paired with a block, rows aligned in document order as held-out
  validation aligns them (`row_alignment`).

What the engine published is the oracle: its own values and role C's grounded ones, which the published rows hold
alike. Site strings exist only in the steps produced, which are IR data (C3).
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from lxml import etree
from lxml.html import HtmlElement
from pydantic import JsonValue, ValidationError

from crawlerai.collect.induce import induced
from crawlerai.collect.items.align import Items, align
from crawlerai.collect.schema_org_map import item_url_fields
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.executor import EngineExecutor, row_id
from crawlerai.config_ir.induction import Published, SamplePage, anchored_paths, anchors, reading
from crawlerai.config_ir.model import (
    NEXT_PAGE_FIELD,
    ExtractionConfigIR,
    Fetch,
    FieldSteps,
    ListingSpec,
    Provenance,
    SchemaRef,
    Step,
    XPathStep,
)
from crawlerai.config_ir.row_alignment import align as align_rows
from crawlerai.content.text import name_test, xpath_step
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import FieldStatus
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.normalize.strings import collapse
from crawlerai.normalize.url import canonical_url
from crawlerai.schemas.types import FieldSpec, SchemaDef, document_digest

_STATUS: Final[FieldStatus] = "uncorroborated"  # until validation records corroboration
# HTML Standard §4.12.1, §4.2.6: a script's and a style's contents are not rendered text, so no value is read there.
# An ordinary `template` left after the pre-passes (`content.page.prepassed`) holds inert content, never rendered.
_UNREAD: Final = frozenset({"script", "style", "template", "noscript"})
# The reasons a row field is left to synthesis.
NO_ITEM_BLOCKS: Final = "no_item_blocks"
NO_ROW_SELECTOR: Final = "no_row_selector"
NO_PAIRED_ROWS: Final = "no_paired_rows"
NOT_IN_BLOCK: Final = "not_in_block"
NO_VERIFIED_SELECTOR: Final = "no_verified_selector"
LIST_FIELD: Final = "list_field"


@dataclass(frozen=True, slots=True)
class ListingInduction:
    """The induced row selector and row-field steps (None without a row selector or any field), and each row field
    left without steps with the reason."""

    listing: ListingSpec | None = None
    to_synthesize: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Page:
    """A sample page, its item blocks (the elements leading to an item and the group's other elements), and its
    published rows each paired with its block."""

    sample: SamplePage
    blocks: tuple[HtmlElement, ...]
    group: frozenset[HtmlElement]
    pairs: tuple[tuple[HtmlElement, Mapping[str, Published]], ...]


def induce_listing(schema: SchemaDef, sample: Sequence[SamplePage], vocabulary: Vocabulary) -> ListingInduction:
    """The listing's rows induced from `sample` (module docstring) for the row fields of `schema`, a listing schema
    without row-mapped fields."""
    names = row_fields(schema)
    pages = [page for s in sample if (page := _page(schema, s)) is not None]
    if not names:
        return ListingInduction()
    if not sample or len(pages) < len(sample):
        return ListingInduction(to_synthesize=dict.fromkeys(names, NO_ITEM_BLOCKS))
    row = _row_selector(pages)
    if row is None:
        return ListingInduction(to_synthesize=dict.fromkeys(names, NO_ROW_SELECTOR))
    trial = _Trial(schema, pages, vocabulary, row)
    fields: dict[str, FieldSteps] = {}
    left: dict[str, str] = {}
    for name in names:
        found = trial.field(name)
        if isinstance(found, str):
            left[name] = found
        else:
            fields[name] = FieldSteps(steps=[found], status=_STATUS)
    return ListingInduction(ListingSpec(row=row, fields=fields) if fields else None, left)


def row_fields(schema: SchemaDef) -> list[str]:
    """The fields a listing's rows hold: row-scoped, other than the next page's URL, which runs on the whole page."""
    return [name for name, spec in schema.fields.items() if spec.scope == "row" and name != NEXT_PAGE_FIELD]


def _page(schema: SchemaDef, sample: SamplePage) -> _Page | None:
    """The page's item blocks, of the aligned group whose item URLs the published rows name most; None without one."""
    found = align(sample.page, schema, sample.ctx)
    if not found:
        return None
    urls = [_row_url(schema, row, sample.ctx) for row in sample.rows]
    best = max(found, key=lambda items: sum(block.link in urls for block in items.blocks))
    return _Page(sample, tuple(b.element for b in best.blocks), frozenset(best.group), _pairs(best, urls, sample))


def _row_url(schema: SchemaDef, row: Mapping[str, Published], ctx: Context) -> str | None:
    for name in item_url_fields(schema):
        published = row.get(name)
        if published is not None and isinstance(published.value, str):
            return canonical_url(published.value, ctx.base_url)
    return None


def _pairs(
    items: Items, urls: Sequence[str | None], sample: SamplePage
) -> tuple[tuple[HtmlElement, Mapping[str, Published]], ...]:
    by_link = {block.link: block.element for block in items.blocks}
    return tuple((by_link[url], row) for url, row in zip(urls, sample.rows, strict=True) if url in by_link)


# --- the row selector -------------------------------------------------------------------------------------------------


def _row_selector(pages: Sequence[_Page]) -> Step | None:
    """The row selector every page proposes that selects each page's blocks and nothing outside its group."""
    proposals = [[xpath for block in page.blocks for xpath in _block_paths(block)] for page in pages]
    xpath = induced(proposals, len(pages), lambda candidate: _selects_all(candidate, pages))
    return None if xpath is None else XPathStep(xpath=xpath)


def _selects_all(xpath: str, pages: Sequence[_Page]) -> bool:
    """Whether `xpath` is a step the IR accepts and selects each page's blocks and nothing outside its group."""
    try:
        XPathStep(xpath=xpath)
    except ValidationError:  # outside XPath 1.0 as the IR accepts it
        return False
    return all(_selects_blocks(xpath, page) for page in pages)


def _block_paths(block: HtmlElement) -> Iterator[str]:
    """The block's anchored paths, nearest anchor first, then its tag path with its ancestors' positions."""
    yield from anchored_paths(block)
    steps = [name_test(str(block.tag))]
    node = block.getparent()
    while node is not None and isinstance(node.tag, str):
        steps.append(xpath_step(str(node.tag), _position(node)))
        node = node.getparent()
    yield "/" + "/".join(reversed(steps))


def _position(node: HtmlElement) -> int:
    """XPath 1.0 §2.4: the node's position among its parent's children of its name."""
    parent = node.getparent()
    if parent is None:
        return 1
    return [child for child in parent if child.tag == node.tag].index(node) + 1


def _selects_blocks(xpath: str, page: _Page) -> bool:
    try:
        found = page.sample.page.lxml_tree.xpath(xpath)
    except etree.XPathError:  # an attribute name lxml's HTML parser accepts and XPath does not (`data-a:b`)
        return False
    if not isinstance(found, list) or not found:
        return False
    selected = set(found)
    return selected <= page.group and all(block in selected for block in page.blocks)


# --- row fields -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Trial:
    """The row fields' induction under one row selector."""

    schema: SchemaDef
    pages: Sequence[_Page]
    vocabulary: Vocabulary
    row: Step

    def field(self, name: str) -> Step | str:
        """The field's induced step, or why it has none."""
        spec = self.schema.fields[name]
        if spec.item is not None:
            return LIST_FIELD
        proposals = [
            [step.model_dump_json() for step in _proposals(block, row[name], spec, page.sample.ctx)]
            for page in self.pages
            for block, row in page.pairs
            if name in row
        ]
        if not proposals:
            return NO_PAIRED_ROWS
        if not any(proposals):
            return NOT_IN_BLOCK
        steps = {key: XPathStep.model_validate_json(key) for found in proposals for key in found}
        key = induced(proposals, len(self.pages), lambda k: self._verified(name, steps[k]))
        return NO_VERIFIED_SELECTOR if key is None else steps[key]

    def _verified(self, name: str, step: Step) -> bool:
        listing = ListingSpec(row=self.row, fields={name: FieldSteps(steps=[step], status=_STATUS)})
        executor = EngineExecutor(_config(self.schema, listing), self.vocabulary)
        return all(self._reproduces(executor, page, name) for page in self.pages)

    def _reproduces(self, executor: EngineExecutor, page: _Page, name: str) -> bool:
        """Whether the step gives a valid value on every row, and the published one on each row paired with a block,
        rows aligned as held-out validation aligns them. A published row no block holds (a source that lists more
        items than the page shows) is left to validation, which counts it against the field's yield."""
        sample = page.sample
        executed = executor.execute(sample.page, self.schema, sample.ctx)
        found = {c.entity_id: c.normalized for c in executed.candidates if c.field == name}
        if not all(isinstance(result, Ok) for result in found.values()):
            return False
        values = [found.get(row_id(n)) for n in range(len(executed.rows))]
        config = [{name: value.value} if isinstance(value, Ok) else {} for value in values]
        engine = [{name: row[name].value} if name in row else {} for _, row in page.pairs]
        spec = self.schema.fields[name]
        aligned = align_rows(engine, config, lambda _, value, published: equal(value, published, spec))
        return all(n is not None and name in config[n] for n, row in zip(aligned, engine, strict=True) if name in row)


def _config(schema: SchemaDef, listing: ListingSpec) -> ExtractionConfigIR:
    """A config holding `listing` only, for the engine executor to run while induction verifies a step."""
    return ExtractionConfigIR(
        ir_version="1",
        site="induction",
        schema_=SchemaRef(name=schema.name, digest=document_digest(schema)),
        page_kind=schema.page_kind,
        fetch=Fetch(method="http"),
        fields={},
        listing=listing,
        provenance=Provenance(
            origin="induced", validated_on=[], learned_at=datetime.now(UTC), engine_version=ENGINE_VERSION
        ),
    )


def _proposals(block: HtmlElement, published: Published, spec: FieldSpec, ctx: Context) -> Iterator[Step]:
    """The relative steps of every element in `block` whose text or one attribute is the published value."""
    for element, attribute in _holding(block, published.value, spec, ctx):
        for nodes in _relative_paths(block, element):
            yield from reading(nodes, attribute, spec)


def _holding(
    block: HtmlElement, value: JsonValue, spec: FieldSpec, ctx: Context
) -> Iterator[tuple[HtmlElement, str | None]]:
    """Each element of the block, in document order, with the reading that gives `value`: its text (None) or the
    name of an attribute."""
    for element in block.iter():
        if not isinstance(element.tag, str) or element.tag in _UNREAD:
            continue
        if _gives(collapse(element.text_content()), value, spec, ctx):
            yield element, None
        for attribute, raw in element.attrib.items():
            if _gives(raw, value, spec, ctx) or _gives(_absolute(raw, ctx), value, spec, ctx):
                yield element, attribute


def _absolute(raw: str, ctx: Context) -> str:
    # RFC 3986 §5: a reference resolves against the document base URL; without one it stays as written (C7).
    return raw if ctx.base_url is None else canonical_url(raw, ctx.base_url) or raw


def _gives(raw: str, value: JsonValue, spec: FieldSpec, ctx: Context) -> bool:
    if not raw:
        return False
    result = normalize(raw, spec, ctx)
    return isinstance(result, Ok) and equal(result.value, value, spec)


def _relative_paths(block: HtmlElement, element: HtmlElement) -> Iterator[str]:
    """Paths from `block` to `element`: through each stable anchor on it or an ancestor inside the block (nearest
    first), then its tag path, then its tag path with positions (XPath 1.0 §2.5 abbreviated syntax)."""
    if element is block:
        yield "."
        return
    chain = []
    node: HtmlElement | None = element
    while node is not None and node is not block:
        chain.append(node)
        node = node.getparent()
    below = ""
    for node in chain:
        test = name_test(str(node.tag))
        for anchor in anchors(node):
            yield f".//{test}[{anchor}]{below}"
        below = f"/{test}{below}"
    yield "." + below
    yield "./" + "/".join(xpath_step(str(n.tag), _position(n)) for n in reversed(chain))
