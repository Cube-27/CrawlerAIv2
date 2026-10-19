"""Whether an HTTP page may need the browser, judged from cheap signals alone (master plan 2026-10-18 §3.1; owner #54;
owner plan 2026-10-19 P3): no extraction and no LLM call, so the fetch decides before role C runs once, on the capture
it keeps.

A detail page shows its offer over HTTP (`offer_shown`) when its structured data states a product's offer (a schema.org
Product with offers, an OGP product price, a microdata Product with offers: `classify.describes_product`), when it
carries a state document large enough to be the page's data rather than a script's settings (`holds_state`: a hydration
blob, a platform's analytics object, whatever its name), or when it shows a heading (`h1` to `h6`, HTML Standard §4.3.6;
a product's name is not always an `h1`) and a price: a digit beside a currency sign (Unicode general category Sc).
Without any of these its offer is filled in by script, and the browser renders it.

A listing is rendered when its document shows fewer than `MIN_ITEMS` repeated item blocks that show more than their
link (the item layer's first group, `ParsedPage.item_groups`, counted by `content.segment.shown_blocks`: its grid is
filled by script, and what repeats is chrome such as related links),
when the text it keeps from rendering (the `hidden` attribute, an inline `display: none`; `content.text.concealed`)
outweighs the text it renders (a streamed document whose script moves its segments into place), or when its
structured data lists fewer items than its document shows (the structured list is a subset of a grid the render may
complete). Text is counted in non-whitespace characters: rendering collapses whitespace, and counting only
non-whitespace makes the count independent of how text nodes are joined.
"""

import re
import sys
import unicodedata

from pydantic import JsonValue
from selectolax.lexbor import LexborNode

from crawlerai.acquire.classify import describes_product, structured_entries
from crawlerai.acquire.items import MIN_ITEMS, item_groups
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import shown_blocks
from crawlerai.content.state import script_state
from crawlerai.content.text import NOT_RENDERED, concealed

# The fewest scalar values (RFC 8259 strings, numbers, literals) a state document holds to be the page's data, not a
# script's settings: an unmeasured starting point, to be confirmed on dev.
STATE_MIN_VALUES = 50
_HEADINGS = "h1, h2, h3, h4, h5, h6"
# Unicode general category Sc (Symbol, currency): every currency sign, whatever its currency.
_SIGNS = re.escape("".join(c for c in map(chr, range(sys.maxunicode + 1)) if unicodedata.category(c) == "Sc"))
# A price as shown: a currency sign beside a digit, with at most one space between them, in either order.
_SHOWN_PRICE = re.compile(rf"[{_SIGNS}]\s?\d|\d\s?[{_SIGNS}]")


def offer_shown(page: ParsedPage) -> bool:
    """Whether a detail page's HTTP document carries its offer, by the module docstring's signals; the cheapest
    first."""
    return describes_product(page.tree) or holds_state(page) or _heading_and_price(page)


def holds_state(page: ParsedPage) -> bool:
    """Whether the page carries a state document of at least `STATE_MIN_VALUES` scalar values (`content.state`): its
    data came with the HTML, for its script to render."""
    return any(_values(document) >= STATE_MIN_VALUES for s in page.scripts for document in script_state(s, []))


def _values(document: JsonValue) -> int:
    """The scalar values of a JSON document, counted up to `STATE_MIN_VALUES` (walked with a stack, not recursion)."""
    count, stack = 0, [document]
    while stack and count < STATE_MIN_VALUES:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        else:
            count += 1
    return count


def _heading_and_price(page: ParsedPage) -> bool:
    if not any(heading.text(strip=True) for heading in page.tree.css(_HEADINGS)):
        return False
    return _SHOWN_PRICE.search(page.cleaned_text.text) is not None


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
    """How many items the page lists: the blocks of its richest repeated item group that show more than their link,
    a hidden segment's included (a streamed document's items wait there for its script, so they are the page's), or
    the items its structured data lists (`structured_entries`), whichever is more."""
    held = max((shown_blocks(group) for group in item_groups(page.lxml_tree)), default=0)
    return max(held, structured_entries(page.tree))


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
            text_shown, text_kept = _visit(child, hidden, stack)
            shown, kept = shown + text_shown, kept + text_kept
            child = child.next
    return shown, kept


def _visit(child: LexborNode, hidden: bool, stack: list[tuple[LexborNode, bool]]) -> tuple[int, int]:
    """A child's text weights, shown and kept; an element that renders is pushed onto `stack` to be read next."""
    if child.is_text_node:
        weight = len("".join((child.text_content or "").split()))
        return (0, weight) if hidden else (weight, 0)
    if child.is_element_node and (child.tag or "") not in NOT_RENDERED:
        stack.append((child, hidden or concealed(child.attributes)))
    return 0, 0
