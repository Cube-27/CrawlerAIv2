"""The `markdown_fit` content format: the page's main content with what is not its content pruned, deterministically and
without a model, and, given a `query`, only the blocks relevant to it.

Pruning runs on the copy of the page's tree that `content.markdown` writes, after its furniture is gone
(`content.regions`). Each leaf text block (an element that holds no other text block) is scored on its own, by three
structural properties, and dropped when
- its text is mostly link text (link density above one half: a menu, a list of related links);
- little of its markup is text (text density, the share of its characters that are text rather than tag names, times
  one minus the link density, under 0.3: a block of controls and wrappers around a few words);
- its text occurs again on the page (a repeated "Add to cart" or "Read more" is page furniture, not content).

Code (`pre`) and table cells, with the blocks inside them, are data a reader wants as written: no block score touches
them. Headings are dropped only when their section ends up empty. A page whose pruning leaves nothing, or only
headings, is returned as `markdown` would.

With a `query`, the pruned markdown is split into blocks (`content.md_blocks`) and each block that is not a heading is
scored against it with BM25 (`content.bm25`); blocks with a score of zero are dropped, and with `max_blocks` only the
highest-scoring ones stay, in page order. A heading stays while a block of its section does.
"""

from lxml.html import HtmlElement
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from crawlerai.content import bm25
from crawlerai.content.markdown import markdown
from crawlerai.content.md_blocks import Block, parse, render
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.strings import collapse

_LEAF_BLOCKS = ("p", "li", "dd", "dt", "blockquote", "figcaption", "summary", "div", "pre", "td", "th")
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_LEAF_TAGS = (*_LEAF_BLOCKS, *_HEADINGS)
# Blocks of data or code, read as written.
_AS_WRITTEN = frozenset({"pre", "td", "th"})
_MAX_LINK_DENSITY = 0.5
_MIN_TEXT_DENSITY = 0.3
# The characters of an element's tags, as a share of its markup: `<` + name + `>` and `</` + name + `>` are
# 2 * len(name) + 5.
_TAG_OVERHEAD = 5


class FitOptions(BaseModel):
    """`markdown_fit`'s options: the `query` the content is kept relevant to, and at most `max_blocks` blocks of it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str | None = Field(default=None, min_length=1)
    max_blocks: PositiveInt | None = None


def markdown_fit(page: ParsedPage, final_url: str, options: FitOptions | None = None) -> str:
    """The pruned main content as Markdown, kept to the blocks relevant to `options.query` when it is given; `""` when
    there is none."""
    options = options or FitOptions()
    blocks = _without_empty_sections(parse(markdown(page, final_url, prune=prune))) or parse(markdown(page, final_url))
    if options.query is not None:
        blocks = _relevant(blocks, options.query, options.max_blocks)
    return render(blocks)


def prune(tree: HtmlElement) -> None:
    """Take the page's low-content blocks out of `tree`."""
    blocks = [
        (element, collapse(element.text_content()))
        for element in tree.iter(*_LEAF_TAGS)
        if not any(True for _ in element.iterdescendants(*_LEAF_TAGS))
    ]
    counts: dict[str, int] = {}
    for _, text in blocks:
        counts[text.casefold()] = counts.get(text.casefold(), 0) + 1
    for element, text in blocks:
        if text and _drops(element, text, counts[text.casefold()]) and element.getparent() is not None:
            element.drop_tree()


def _drops(element: HtmlElement, text: str, occurrences: int) -> bool:
    tag = str(element.tag)
    if tag in _AS_WRITTEN or tag in _HEADINGS or _inside_as_written(element):
        return False
    if occurrences > 1:
        return True
    links = sum(len(collapse(link.text_content())) for link in element.iter("a"))
    link_density = links / len(text)
    markup = sum(2 * len(str(e.tag)) + _TAG_OVERHEAD for e in element.iter() if isinstance(e.tag, str))
    text_density = len(text) / (len(text) + markup)
    return link_density > _MAX_LINK_DENSITY or text_density * (1 - link_density) < _MIN_TEXT_DENSITY


def _inside_as_written(element: HtmlElement) -> bool:
    """Whether a block is part of a table cell or code (`_AS_WRITTEN`): a `p` in a `td` is the cell's data too."""
    return any(ancestor.tag in _AS_WRITTEN for ancestor in element.iterancestors())


def _without_empty_sections(blocks: list[Block]) -> list[Block]:
    """The blocks less each heading with no other block in its section (up to the next heading of its level or
    higher), subsections' content counting as its own."""
    kept: list[Block] = []
    for index, block in enumerate(blocks):
        if block.kind != "heading" or _has_content(blocks, index):
            kept.append(block)
    return kept


def _has_content(blocks: list[Block], heading: int) -> bool:
    for block in blocks[heading + 1 :]:
        if block.kind != "heading":
            return True
        if block.level <= blocks[heading].level:
            return False
    return False


def _relevant(blocks: list[Block], query: str, max_blocks: int | None) -> list[Block]:
    content = [index for index, block in enumerate(blocks) if block.kind != "heading"]
    scored = dict(zip(content, bm25.scores(query, [blocks[index].text for index in content]), strict=True))
    relevant = [index for index in content if scored[index] > 0]
    if max_blocks is not None:
        best = sorted(relevant, key=lambda index: (-scored[index], index))[:max_blocks]
        relevant = sorted(best)
    keep = {*relevant, *(index for index, block in enumerate(blocks) if block.kind == "heading")}
    return _without_empty_sections([block for index, block in enumerate(blocks) if index in keep])
