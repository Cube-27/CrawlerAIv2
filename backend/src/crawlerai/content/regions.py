"""The regions of a page (extraction spec, "Page content formats"): its furniture and its main region, one definition
for the content formats (`content.markdown`, `content.fit`) and the DOM collectors (`collect.dom`, `collect.dom_text`,
`collect.dom_images`).

Furniture is what a page shows around its content on every page of its site, or not at all:
- **Not rendered.** The elements the user-agent style sheet never renders (`content.text.NOT_RENDERED`: `script`,
  `style`, `template`, `noscript` unless scripting is off, ...), and those the page hides itself (`content.text.hidden`:
  the `hidden` attribute, an inline `display: none`, `aria-hidden="true"`, a closed `dialog`).
- **Landmarks.** `nav` and `aside` (HTML Standard §4.3.4, §4.3.5: navigation, content tangential to its
  surroundings), a `header` or `footer` whose scope is the body (§4.3.8, §4.3.9: the page's header or footer; one in an
  `article` or `section` is that section's), an open `dialog` (§4.11.4: a window apart from the page), and the WAI-ARIA
  1.2 roles of the same meaning (§5.3.4 landmarks `navigation`, `banner`, `contentinfo`, `complementary`, `search`;
  §5.4 windows `dialog`, `alertdialog`).
- **Named furniture.** An element whose `class` or `id` names one of the furniture words below, as Firecrawl's
  `onlyMainContent` (`excludeNonMainTags`) and Mozilla Readability (`unlikelyCandidates`) read class and id names: a
  word that is a whole token or one of its parts (split at `-`, `_` and camelCase boundaries), or, for the words that
  name a layout slot rather than furniture alone (`ad`, `widget`), only a whole token. A header or footer class
  counts only where the element would be the page's (its scope is the body, as for the elements); an `id` is unique
  in the document (HTML Standard §3.2.6), so one naming a header or footer names the page's whatever its scope.

No furniture rule drops the page's content: an element that holds the page's first `h1` (HTML Standard §4.3.6: its
title), a `main` element or `role="main"` landmark (§4.4.14) or an `article` (§4.3.2) is kept. A name or the page's
own hiding is a weaker sign than a landmark the markup states, and an element so marked is kept when it is the
page's content by its text, as Mozilla Readability finds it: when it holds the page's longest leaf text block, or
more than two fifths of the page's text outside hyperlinks (HTML Standard §4.5.1: a hyperlink's content labels the
link; a block that is mostly links is a menu). That keeps a wrapper named after a sidebar or a modal it also holds
and a body a consent script reveals. When the names together would still drop more than two fifths of that text,
they name the page's layout rather than its furniture, and the page is read without them (Readability's retry
without its `unlikelyCandidates`, which keeps its visibility check). The elements never rendered whatever a script
does are dropped regardless.

A leaf text block is a block element (paragraph, list item, description, quote, caption, summary, `div`, `pre`, table
cell or heading) that holds no other; its text is the text outside hyperlinks.

The main region is the `main` element, else the one `role="main"` landmark, else the document's one `article`;
none when the page has several. The DOM collectors read the main region, else the body.
"""

import re
from collections.abc import Iterator
from typing import Literal

from lxml.html import HtmlElement
from selectolax.lexbor import LexborNode

from crawlerai.content.dom import tokens
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import NOT_RENDERED, hidden
from crawlerai.normalize.strings import collapse

# HTML Standard §4.3: sectioning content of a page that is not its main content.
TANGENTIAL = ("nav", "header", "footer", "aside")
# HTML Standard §4.11.4 (`dialog`) and WAI-ARIA 1.2 §5.4 (roles `dialog`, `alertdialog`): a window apart from the
# page's content, such as a drawer or a modal. A closed `dialog` is not rendered at all (`content.text`).
DIALOG = "dialog"
DIALOG_ROLES = ("dialog", "alertdialog")
# WAI-ARIA 1.2 §5.3.4: the landmark roles that name page furniture; `main`, `region` and `form` hold content.
LANDMARK_ROLES = ("navigation", "banner", "contentinfo", "complementary", "search")
# HTML Standard §4.3.8, §4.3.9: a `header` or `footer` whose nearest ancestor that is sectioning content or a sectioning
# root is `body` is the page's; one inside an `article` or `section` belongs to that section. `main` (§4.4.14) is
# neither, so a footer inside it is the page's.
_PAGE_LEVEL = frozenset({"header", "footer"})
_SCOPES = frozenset(
    {*("article", "aside", "nav", "section", "blockquote", "details", "dialog", "fieldset", "figure", "td", "body")}
)
_FURNITURE_ROLES = frozenset({*LANDMARK_ROLES, *DIALOG_ROLES})
_FURNITURE_TAGS = frozenset({"nav", "aside", DIALOG})
# Firecrawl `excludeNonMainTags` and Readability `unlikelyCandidates`: class and id words that name furniture.
_FURNITURE_WORDS = frozenset(
    {*("header", "footer", "nav", "navbar", "navigation", "menu", "breadcrumb", "breadcrumbs", "sidebar", "skip")}
    | {*("cookie", "cookies", "consent", "gdpr", "social", "share", "sharing", "newsletter", "modal", "popup")}
    | {"dialog"}
)
# Firecrawl `excludeNonMainTags`: words that name furniture only as a whole token (`.ad`, `.widget`); as a part they
# name page-builder blocks of any content (`page-widget`, `ad-free`).
_FURNITURE_TOKENS = frozenset({"ad", "ads", "advert", "widget", "overlay"})
# The parts of a class or id: split at `-`, `_` and camelCase boundaries (`apphub_HeaderTop`, `siteHeader`).
_PARTS = re.compile(r"[-_]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# Above this share of the page's text outside hyperlinks an element is the page's content, whatever it is named; above
# it, the weak signs together name the page's layout.
_MAX_SHARE = 0.4
# The leaf text blocks (module docstring): HTML Standard §4.4 grouping content and table cells, and headings (§4.3.6).
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
LEAF_TAGS = ("p", "li", "dd", "dt", "blockquote", "figcaption", "summary", "div", "pre", "td", "th", *_HEADINGS)
_MAIN = ("main", "article")
_NOSCRIPT = "noscript"


def main_region(page: ParsedPage) -> LexborNode | None:
    """The `main` element, else the `role="main"` landmark, else the one `article`; none when the page has several."""
    for selector in ("main", '[role="main"]', "article"):
        found = page.tree.css(selector)
        if found:
            return found[0] if len(found) == 1 else None
    return None


def content_region(page: ParsedPage) -> LexborNode | None:
    """The page's main content: its main region, else the document body."""
    return main_region(page) or page.tree.body


def drop_furniture(tree: HtmlElement, *, scripting: bool = True) -> None:
    """Takes the page's furniture (module docstring) out of `tree`, an lxml tree of the page, keeping each element's
    tail text. Without `scripting`, the page is read as a user agent with scripting disabled renders it: its `noscript`
    content is shown (HTML Standard §4.12.2)."""
    shown = frozenset() if scripting else frozenset({_NOSCRIPT})
    unrendered = NOT_RENDERED - shown
    for element in [e for e in tree.iter() if not isinstance(e.tag, str) or e.tag in unrendered]:
        _drop(element)
    body = tree.find("body")
    guard = _Guard(body if body is not None else tree)
    stated, named = _marked(tree, guard, shown)
    if sum(map(unlinked_length, named)) > _MAX_SHARE * guard.size:
        named = []
    for element in (*stated, *named):
        _drop(element)


def leaf_blocks(tree: HtmlElement) -> Iterator[HtmlElement]:
    """The tree's leaf text blocks (module docstring), in document order."""
    for element in tree.iter(*LEAF_TAGS):
        if next(element.iterdescendants(*LEAF_TAGS), None) is None:
            yield element


def unlinked_length(element: HtmlElement) -> int:
    """The length of the element's text outside hyperlinks, whitespace collapsed."""
    links = sum(len(collapse(link.text_content())) for link in element.iter("a"))
    return max(len(collapse(element.text_content())) - links, 0)


def _marked(tree: HtmlElement, guard: "_Guard", shown: frozenset[str]) -> tuple[list[HtmlElement], list[HtmlElement]]:
    """The outermost furniture elements the guard does not keep: those the markup states or the page hides, and those
    only named furniture."""
    stated: list[HtmlElement] = []
    named: list[HtmlElement] = []
    stack = [tree]
    while stack:
        element = stack.pop()
        found = _furniture(element) if element is not tree and element.tag not in shown else None
        if found is None or guard.keeps(element, weak=found != "stated"):
            stack.extend(reversed(element))
        else:
            (named if found == "named" else stated).append(element)
    return stated, named


def _drop(element: HtmlElement) -> None:
    if element.getparent() is not None:
        element.drop_tree()


class _Guard:
    """What no furniture rule drops: an element holding the page's title or its main content, and, for a weak sign of
    furniture, one holding the page's longest leaf text block or much of its text outside hyperlinks."""

    def __init__(self, root: HtmlElement) -> None:
        self.title = next(root.iter("h1"), None)
        self.size = unlinked_length(root)
        longest = max(leaf_blocks(root), key=unlinked_length, default=None)
        self.longest = frozenset() if longest is None else frozenset({longest, *longest.iterancestors()})

    def keeps(self, element: HtmlElement, *, weak: bool) -> bool:
        if self.title is not None and (element is self.title or self.title in element.iterdescendants("h1")):
            return True
        if _is_main(element) or any(_is_main(inside) for inside in element.iterdescendants()):
            return True
        return weak and (element in self.longest or unlinked_length(element) > _MAX_SHARE * self.size)


def _is_main(element: HtmlElement) -> bool:
    return element.tag in _MAIN or _role(element) == "main"


def _furniture(element: HtmlElement) -> Literal["stated", "hidden", "named"] | None:
    """Whether the element is furniture, and by what sign: one the markup states (a landmark element or role), or a
    weak one (the page hides it, or its name calls it furniture)."""
    if _role(element) in _FURNITURE_ROLES or element.tag in _FURNITURE_TAGS:
        return "stated"
    if element.tag in _PAGE_LEVEL and _page_level(element):
        return "stated"
    attributes: dict[str, str | None] = dict(element.attrib)
    if hidden(str(element.tag), attributes):
        return "hidden"
    return "named" if _named_furniture(element) else None


def _role(element: HtmlElement) -> str:
    """WAI-ARIA 1.2 §7.1: `role` is a list of tokens, the first one a user agent recognizes taken; a furniture or main
    role is one of those, so the first token is read."""
    return next(iter(tokens((element.get("role") or "").lower())), "")


def _named_furniture(element: HtmlElement) -> bool:
    classes, ids = tokens(element.get("class")), tokens(element.get("id"))
    if _FURNITURE_TOKENS.intersection(name.lower() for name in (*classes, *ids)):
        return True
    named, unique = _words(classes), _words(ids)
    return bool((named | unique) - _PAGE_LEVEL) or bool(unique) or (bool(named) and _page_level(element))


def _words(names: list[str]) -> set[str]:
    """The furniture words among the names' parts."""
    return {part.lower() for name in names for part in _PARTS.split(name)} & _FURNITURE_WORDS


def _page_level(element: HtmlElement) -> bool:
    """Whether the nearest ancestor that is sectioning content or a sectioning root is the body."""
    scope = next((str(a.tag) for a in element.iterancestors() if a.tag in _SCOPES), "body")
    return scope == "body"
