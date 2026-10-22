"""The item layer's segment step (listings spec, "Item groups"; owner #67): which groups of repeated item blocks
(`acquire.items`) a page shows its items in, best first. `ParsedPage.item_groups` holds the answer once per page;
every reader of a listing's items (the item layer's alignment, the render-need check, `xhr`, the browser's
paging driver) takes it from there or from `rank`, so one ranker decides.

A block the page does not render is not one of its items: with the browser's geometry, a block with no rendered area
(CSSOM View `getBoundingClientRect`), else a block the HTML Standard's rendering rules or the page's inline styles
hide (`content.text.hidden`, on the block or an ancestor), unless a script reveals that element (`revealed`: the
paths of the elements `content.text.script_revealed` names, as the cleaned text shows them). Groups are then ranked:
- with geometry (a browser capture), by the rendered area of their blocks: a listing's items fill the page's content
  (DEPTA, Zhai and Liu 2005: visual cues separate data records from navigation and adverts);
- else by structural evidence: each block counts one for an image and one for text in two or more runs (a label and
  something besides it), so a bare tag cloud or pager cannot outrank a grid of items showing more; then by size.
"""

from collections.abc import Iterator, Mapping, Sequence

from lxml.html import HtmlElement

from crawlerai.acquire.items import (
    Group,
    content_root,
    element_path,
    holds_image,
    holds_several_texts,
    hyperlinks,
    in_chrome,
)
from crawlerai.content.text import hidden, xpath_step
from crawlerai.normalize.url import canonical_url

# The rendered area of item blocks in CSS pixels, by element path (`acquire.items.element_path`).
Areas = Mapping[str, float]


def rank(
    groups: Sequence[Group], areas: Areas | None = None, revealed: frozenset[str] = frozenset()
) -> tuple[Group, ...]:
    """`groups` with their unrendered blocks left out, best first (module docstring); a group left with no block is
    dropped. Ties keep the order of `groups`."""
    shown = [kept for group in groups if (kept := _rendered(group, areas, revealed))]
    if areas is not None:
        scored = [(sum(areas.get(element_path(block), 0.0) for block in group), group) for group in shown]
    else:
        scored = [(float(evidence(group)), group) for group in shown]
    order = sorted(range(len(scored)), key=lambda i: (-scored[i][0], -len(scored[i][1]), i))
    return tuple(scored[i][1] for i in order)


def _rendered(group: Group, areas: Areas | None, revealed: frozenset[str]) -> Group:
    """The group's blocks the page renders: with geometry, those not measured with no area (a block past the browser
    rung's measuring cap has no entry and stays); else those the rendering rules do not hide."""
    if areas is not None:
        return tuple(block for block in group if areas.get(element_path(block), 1.0) > 0)
    return tuple(block for block in group if not _hidden(block, revealed))


def _hidden(element: HtmlElement, revealed: frozenset[str]) -> bool:
    node: HtmlElement | None = element
    while node is not None:
        if isinstance(node.tag, str) and hidden(node.tag, dict(node.attrib)) and text_path(node) not in revealed:
            return True
        node = node.getparent()
    return False


def evidence(group: Group) -> int:
    """How much the blocks show beyond their link (module docstring)."""
    return sum(holds_image(block) + holds_several_texts(block) for block in group)


def block_links(block: HtmlElement, base: str | None) -> Iterator[str]:
    """The canonical URLs the block's hyperlinks lead to, in document order, repeats kept."""
    for anchor in hyperlinks(block):
        if (url := canonical_url(anchor.get("href") or "", base)) is not None:
            yield url


def content_links(root: HtmlElement, base: str | None, revealed: frozenset[str] = frozenset()) -> frozenset[str]:
    """The canonical URLs the rendered hyperlinks of the page's content lead to (HTML Standard §4.6.1): in its main
    landmark, else its body, outside the site's chrome (`in_chrome` of `acquire.items`: navigation, header, footer,
    aside, menus), hidden ones left out, as `rank` leaves out unrendered blocks."""
    return frozenset(
        url
        for anchor in hyperlinks(content_root(root))
        if not _hidden(anchor, revealed)
        and not in_chrome(anchor)
        and (url := canonical_url(anchor.get("href") or "", base)) is not None
    )


def chrome_links(root: HtmlElement, base: str | None) -> list[tuple[HtmlElement, str]]:
    """The hyperlinks of the site's chrome (`in_chrome` of `acquire.items`: navigation, header, footer, aside, search,
    menus), each with the canonical URL it leads to, in document order."""
    return [
        (anchor, url)
        for anchor in hyperlinks(root)
        if in_chrome(anchor) and (url := canonical_url(anchor.get("href") or "", base)) is not None
    ]


def group_links(groups: Sequence[Group], base: str | None) -> list[frozenset[str]]:
    """The documents each group's blocks link to, by group."""
    return [frozenset(url for block in group for url in block_links(block, base)) for group in groups]


def text_path(element: HtmlElement) -> str:
    """The element's location path in the form the cleaned text's runs carry (`content.text.TextRun`): one positional
    step per ancestor, counting element siblings of the same tag (comments and processing instructions are no
    elements)."""
    steps: list[str] = []
    current: HtmlElement | None = element
    while current is not None:
        index = 1 + sum(1 for sibling in current.itersiblings(preceding=True) if sibling.tag == current.tag)
        steps.append(xpath_step(str(current.tag), index))
        current = current.getparent()
    return "/" + "/".join(reversed(steps))
