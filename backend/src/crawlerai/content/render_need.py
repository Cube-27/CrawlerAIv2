"""Whether an HTTP listing may show more of its items once rendered, judged from its structure alone (master plan
2026-10-18 §3.1; owner #54): no extraction and no LLM call, so the fetch decides before role C runs once, on the
capture it keeps.

A listing is rendered when its document shows fewer than `MIN_ITEMS` repeated item blocks that show more than their
link (the item layer's first group, `ParsedPage.item_groups`, counted by `content.segment.shown_blocks`: its grid is
filled by script, and what repeats is chrome such as related links),
when the text it keeps from rendering (the `hidden` attribute, an inline `display: none`; `content.text.concealed`)
outweighs the text it renders (a streamed document whose script moves its segments into place), or when its
structured data lists fewer items than its document shows (the structured list is a subset of a grid the render may
complete). Text is counted in non-whitespace characters: rendering collapses whitespace, and counting only
non-whitespace makes the count independent of how text nodes are joined.
"""

from selectolax.lexbor import LexborNode

from crawlerai.acquire.classify import structured_entries
from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import shown_blocks
from crawlerai.content.text import NOT_RENDERED, concealed


def listing_needs_render(page: ParsedPage, over: ParsedPage | None = None) -> bool:
    """Whether the listing `page` may show more of its items in the browser (module docstring). A render `over` the
    HTTP page it would replace no longer needs one when it lists more items than that page (owner #54: the capture
    with more rows is kept)."""
    if over is not None and listed(page) > listed(over):
        return False
    blocks = _shown(page)
    if blocks < MIN_ITEMS:
        return True
    shown, kept = _text_weights(page.tree.body)
    if kept > shown:
        return True
    return 0 < structured_entries(page.tree) < blocks


def lost_items(render: ParsedPage, over: ParsedPage) -> bool:
    """Whether a `render` lists fewer items than the HTTP page it would replace (`over`): what the render did not load
    (its images, fonts and media, `FetchPolicy.block_resources`) may be what shows them."""
    return listed(render) < listed(over)


def listed(page: ParsedPage) -> int:
    """How many items the page lists: the item blocks it shows (`_shown`), or the items its structured data lists
    (`structured_entries`), whichever is more."""
    return max(_shown(page), structured_entries(page.tree))


def _shown(page: ParsedPage) -> int:
    """How many blocks of the page's first item group show more than their link."""
    return shown_blocks(page.item_groups[0]) if page.item_groups else 0


def _text_weights(body: LexborNode | None) -> tuple[int, int]:
    """The non-whitespace characters of text the document renders, and of text it keeps from rendering (`concealed`).
    Elements that are never rendered (script data, style sheets, templates; `NOT_RENDERED`) count in neither."""
    shown = kept = 0
    # Explicit stack, not recursion: document depth is not bounded by the interpreter's recursion limit.
    stack: list[tuple[LexborNode, bool]] = [] if body is None else [(body, False)]
    while stack:
        node, hidden = stack.pop()
        child = node.child
        while child is not None:
            if child.is_text_node:
                weight = len("".join((child.text_content or "").split()))
                kept, shown = (kept + weight, shown) if hidden else (kept, shown + weight)
            elif child.is_element_node and (child.tag or "") not in NOT_RENDERED:
                stack.append((child, hidden or concealed(child.attributes)))
            child = child.next
    return shown, kept
