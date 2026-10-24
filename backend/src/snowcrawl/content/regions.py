"""The regions of a page: its furniture and its main region, one definition
for the content formats (`content.markdown`, `content.fit`) and the DOM collectors (`collect.dom`, `collect.dom_text`,
`collect.dom_images`).

Furniture is what a page shows around its content on every page of its site, or not at all:
- **Not rendered.** The elements the user-agent style sheet never renders (`content.text.NOT_RENDERED`: `script`,
  `style`, `template`, `noscript` unless scripting is off, ...), and those the page hides itself (`content.text.hidden`:
  the `hidden` attribute, an inline `display: none`, `aria-hidden="true"`, a closed `dialog`), but for one of a set of
  like siblings one of which is shown: a carousel's slides, a tab list's panels (WAI-ARIA Authoring Practices), each
  the page's content in its turn.
- **Landmarks.** `nav` and `aside` (HTML Standard §4.3.4, §4.3.5: navigation, content tangential to its
  surroundings), a page-level `header` or `footer` (§4.3.9: one whose scope is the body is the page's, one in an
  `article` or `section` that section's, HTML-AAM §4.1: one in `main` the main content's, unless it is a child of `main`
  that holds the site's navigation, as on a page that wraps its whole layout in `main`), an open `dialog`
  (§4.11.4: a window apart from the page), and the WAI-ARIA 1.2 roles of the same meaning (§5.3.4 landmarks
  `navigation`, `banner`, `contentinfo`, `complementary`, `search`; §5.4 windows `dialog`, `alertdialog`).
- **Named furniture.** An element whose `class` or `id` names one of the furniture words below, as Firecrawl's
  `onlyMainContent` (`excludeNonMainTags`) and Mozilla Readability (`unlikelyCandidates`) read class and id names: a
  word that is a whole token or one of its parts (split at `-`, `_` and camelCase boundaries), or, for the words that
  name a layout slot rather than furniture alone (`ad`, `widget`), only a whole token. A word after a part that makes
  it something the element has or lacks (`has-no-sidebar`, `page-with-sidebar-sidebar`) names a slot of a layout, not
  furniture, and so does the word in the names of what a wrapper so named as having it holds (`page-with-sidebar`
  holds its body column and the blocks placed there, `sidebar-text`), which the text and landmark signs judge; the
  root's and body's classes switch the style sheet for the whole document and name no region. A
  header or footer class counts only where the element would be the page's (page-level, as for the elements); an
  `id` is unique in the document (HTML Standard §3.2.6), so one naming a header or footer names the page's whatever
  its scope.

No furniture rule drops the page's content: an element that holds the page's first `h1` (HTML Standard §4.3.6: its
title), a `main` element or `role="main"` landmark or an `article` is kept, and so is an `aside`
that holds the page's longest leaf text block: content tangential to the page holds none of its main text (a faceted
listing's category text in its sidebar column). A name, the page's own hiding, or a `header` that is the page's only
by its scope and holds no navigation (HTML Standard §4.3.8: introductory content, which may wrap what it introduces)
is a weaker sign than a landmark the markup states, and an element so marked is kept when it is the page's content by
its text, as Mozilla Readability finds it: when it holds the page's longest leaf text block, or more than two fifths
of the page's text outside hyperlinks (HTML Standard §4.5.1: a hyperlink's content labels the link; a block that is
mostly links is a menu). That keeps a wrapper named after a sidebar or a modal it also holds, a body a consent script
reveals and a `header` that wraps an article. A class that an element so kept for its text bears, or a block holding
the longest leaf text block, names the page's blocks (a page builder's `widget` panels, a table style), not its
furniture, and the others of that class are kept too. When the names together would still drop more than two fifths
of that text, they name the page's layout rather than its furniture, and the page is read without them
(Readability's retry without its `unlikelyCandidates`, which keeps its visibility check). The elements never rendered
whatever a script does are dropped regardless.

The signs are read strongest first, the page's text measured anew after each: the stated landmarks; then the
tangential, scope-inferred and hidden elements; then the names. A cookie dialog's text is no measure of the page's
content, so the longest block and the two fifths are those of what the stronger signs leave.

A leaf text block is a block element (paragraph, list item, description, quote, caption, summary, `div`, `pre`, table
cell or heading) that holds no other; its text is the text outside hyperlinks.

The main region is the `main` element, else the one `role="main"` landmark, else the document's one `article`;
none when the page has several. The DOM collectors read the main region, else the body.
"""

from collections.abc import Iterator
from itertools import pairwise
from typing import Literal

from lxml.html import HtmlElement
from selectolax.lexbor import LexborNode

from snowcrawl.content.dom import name_parts, tokens
from snowcrawl.content.page import ParsedPage
from snowcrawl.content.text import NOT_RENDERED, hidden
from snowcrawl.normalize.strings import collapse

# HTML Standard §4.3: sectioning content of a page that is not its main content.
TANGENTIAL = ("nav", "header", "footer", "aside")
# HTML Standard §4.11.4 (`dialog`) and WAI-ARIA 1.2 §5.4 (roles `dialog`, `alertdialog`): a window apart from the
# page's content, such as a drawer or a modal. A closed `dialog` is not rendered at all (`content.text`).
DIALOG = "dialog"
DIALOG_ROLES = ("dialog", "alertdialog")
# WAI-ARIA 1.2 §5.3.4: the landmark roles that name page furniture; `main`, `region` and `form` hold content.
LANDMARK_ROLES = ("navigation", "banner", "contentinfo", "complementary", "search")
# HTML Standard §4.3.8, §4.3.9: a `header` or `footer` whose nearest ancestor that is sectioning content or a sectioning
# root is `body` is the page's; one inside an `article` or `section` belongs to that section. HTML-AAM §4.1 (`header`,
# `footer`): one inside `main` is no `banner` or `contentinfo` landmark either, but the main content's own.
_PAGE_LEVEL = frozenset({"header", "footer"})
# HTML Standard §4.3.8: a `header` is introductory content or navigational aids; one the page's by its scope alone that
# holds no navigation may wrap the content it introduces, an article whose title sits outside it. A `footer`
# holds what is about its section, never the section.
_HEADER = "header"
_SCOPES = frozenset(
    {*("article", "aside", "nav", "section", "blockquote", "details", "dialog", "fieldset", "figure", "td")}
    | {"body", "main"}
)
# WAI-ARIA 1.2 §5.3.4: the `navigation` landmark; HTML Standard §4.3.4: `nav`.
_NAVIGATION = "nav, [role~=navigation]"
_FURNITURE_ROLES = frozenset({*LANDMARK_ROLES, *DIALOG_ROLES})
_FURNITURE_TAGS = frozenset({"nav", DIALOG})
# HTML Standard §4.3.5 (`aside`), WAI-ARIA 1.2 §5.3.4 (`complementary`): content tangential to the page's, which holds
# none of its main text.
_ASIDE = "aside"
_COMPLEMENTARY = "complementary"
# Firecrawl `excludeNonMainTags` and Readability `unlikelyCandidates`: class and id words that name furniture.
_FURNITURE_WORDS = frozenset(
    {*("header", "footer", "nav", "navbar", "navigation", "menu", "breadcrumb", "breadcrumbs", "sidebar", "skip")}
    | {*("cookie", "cookies", "consent", "gdpr", "social", "share", "sharing", "newsletter", "modal", "popup")}
    | {"dialog"}
)
# Firecrawl `excludeNonMainTags`: words that name furniture only as a whole token (`.ad`, `.widget`); as a part they
# name page-builder blocks of any content (`page-widget`, `ad-free`).
_FURNITURE_TOKENS = frozenset({"ad", "ads", "advert", "widget", "overlay"})
# A part that makes the word after it something the element has or lacks rather than what it is: `has-no-sidebar`,
# `page-with-sidebar`, `without-header` name a layout with or without that furniture, not the furniture.
_QUALIFIERS = frozenset({"has", "with", "without", "no", "non", "not"})
# The qualifiers that make the word a slot a wrapper holds: `page-with-sidebar` wraps a sidebar column and a body.
_HOLDING = frozenset({"has", "with"})
# HTML Standard §4.1.1, §4.3.1: the document's root and its body, which wrap the whole page rather than a region.
_DOCUMENT = frozenset({"html", "body"})
# Above this share of the page's text outside hyperlinks an element is the page's content, whatever it is named; above
# it, the weak signs together name the page's layout.
_MAX_SHARE = 0.4
# The leaf text blocks (module docstring): HTML Standard §4.4 grouping content and table cells, and headings.
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
LEAF_TAGS = ("p", "li", "dd", "dt", "blockquote", "figcaption", "summary", "div", "pre", "td", "th", *_HEADINGS)
_MAIN = ("main", "article")
_NOSCRIPT = "noscript"
# The signs of furniture (`_furniture`): a landmark the markup states, a complementary one (`aside`), a header the
# page's by its scope alone, the page's own hiding, a name.
type Sign = Literal["stated", "tangential", "scoped", "hidden", "named"]
# The order the signs are read in (module docstring): what the markup states is out before the page's text is measured
# for the weaker signs, and the names last, measured on what the others leave.
_STAGES: tuple[frozenset[Sign], ...] = (
    frozenset({"stated"}),
    frozenset({"tangential", "scoped", "hidden"}),
    frozenset({"named"}),
)


# WAI-ARIA 1.2 windows and menus: a popup a control opens, never a disclosure's panel.
_WINDOWS = frozenset({"dialog", "alertdialog", "menu", "listbox", "tooltip"})


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
    root = body if body is not None else tree
    for signs in _STAGES:
        guard = _Guard(root)
        if "named" in signs:
            guard.read_layout(root)
        marked = _marked(tree, guard, shown, signs, _collapsed_panels(tree))
        if "named" in signs and sum(map(unlinked_length, marked)) > _MAX_SHARE * guard.size:
            marked = []
        for element in marked:
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


def _marked(
    tree: HtmlElement, guard: "_Guard", shown: frozenset[str], signs: frozenset[Sign], panels: frozenset[str]
) -> list[HtmlElement]:
    """The outermost elements furniture by one of `signs` that the guard does not keep."""
    marked: list[HtmlElement] = []
    stack = [tree]
    while stack:
        element = stack.pop()
        found = _furniture(element, panels) if element is not tree and element.tag not in shown else None
        if found not in signs or guard.keeps(element, found):
            stack.extend(reversed(element))
        else:
            marked.append(element)
    return marked


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
        self.layout: set[str] = set()

    def read_layout(self, root: HtmlElement) -> None:
        """Takes the classes the blocks holding the page's content bear (the longest leaf text block and its
        ancestors, and any element named furniture that holds more than two fifths of the text) for the names of
        the page's blocks, not its furniture."""
        named = (e for e in root.iter() if isinstance(e.tag, str) and _furniture_names(e))
        content = [*self.longest, *(e for e in named if unlinked_length(e) > _MAX_SHARE * self.size)]
        self.layout = {name for element in content for name in tokens(element.get("class"))}

    def keeps(self, element: HtmlElement, sign: Sign) -> bool:
        if self.title is not None and (element is self.title or self.title in element.iterdescendants("h1")):
            return True
        if _is_main(element) or any(_is_main(inside) for inside in element.iterdescendants()):
            return True
        if sign == "stated":
            return False
        if sign == "named" and _furniture_names(element) <= self.layout:
            return True
        return element in self.longest or (sign != "tangential" and unlinked_length(element) > _MAX_SHARE * self.size)


def _is_main(element: HtmlElement) -> bool:
    return element.tag in _MAIN or _role(element) == "main"


def _furniture(element: HtmlElement, panels: frozenset[str]) -> Sign | None:
    """Whether the element is furniture, and by what sign: one the markup states (a landmark element or role; content
    tangential to the page, `aside` or `complementary`, a sign of its own), or a weak one (a `header` the page's by
    its scope alone and holding no navigation, the page hides it, or its name calls it furniture)."""
    role = _role(element)
    if role == _COMPLEMENTARY or element.tag == _ASIDE:
        return "tangential"
    if role in _FURNITURE_ROLES or element.tag in _FURNITURE_TAGS:
        return "stated"
    if element.tag in _PAGE_LEVEL and _page_level(element):
        return "scoped" if element.tag == _HEADER and not element.cssselect(_NAVIGATION) else "stated"
    attributes: dict[str, str | None] = dict(element.attrib)
    if hidden(str(element.tag), attributes):
        if _disclosed(element, panels):
            return None
        if not _alternative(element):
            return "hidden"
    return "named" if _furniture_names(element) else None


def _role(element: HtmlElement) -> str:
    """WAI-ARIA 1.2 §7.1: `role` is a list of tokens, the first one a user agent recognizes taken; a furniture or main
    role is one of those, so the first token is read."""
    return next(iter(tokens((element.get("role") or "").lower())), "")


def _furniture_names(element: HtmlElement) -> set[str]:
    """The element's class and id names that call it furniture (module docstring), as written."""
    classes, ids = tokens(element.get("class")), tokens(element.get("id"))
    if not any(name.lower() in _FURNITURE_TOKENS or _words(name, frozenset()) for name in (*classes, *ids)):
        return set()
    slots = _slots(element)
    found = {
        name for name in (*classes, *ids) if name.lower() in _FURNITURE_TOKENS or _words(name, slots) - _PAGE_LEVEL
    }
    found.update(name for name in ids if _words(name, slots))
    page_level = [name for name in classes if _words(name, slots) & _PAGE_LEVEL]
    if page_level and _page_level(element):
        found.update(page_level)
    return found


def _words(name: str, slots: frozenset[str]) -> set[str]:
    """The furniture words among the name's parts, but for those that name a slot of a layout (`_slots`)."""
    return set(name_parts(name)) & _FURNITURE_WORDS - slots


def _slots(element: HtmlElement) -> frozenset[str]:
    """The furniture words that name a slot of a layout for the element's names: a word a qualifier precedes
    (`_QUALIFIERS`) in one of its own names (`page-with-sidebar-sidebar` names a column of a layout with a sidebar),
    and one a holding qualifier (`_HOLDING`) precedes in a name of a wrapper it sits in (`page-with-sidebar-body`
    holds the layout's columns and the blocks placed in them, `sidebar-text`). The root's and the body's classes
    are the document's switches for its style sheet (a page that has a sidebar somewhere), not a wrapper's name."""
    words = {word for name in _names(element) for before, word in _pairs(name) if before in _QUALIFIERS}
    for wrapper in element.iterancestors():
        if wrapper.tag not in _DOCUMENT:
            words.update(word for name in _names(wrapper) for before, word in _pairs(name) if before in _HOLDING)
    return frozenset(words & _FURNITURE_WORDS)


def _names(element: HtmlElement) -> list[str]:
    return [*tokens(element.get("class")), *tokens(element.get("id"))]


def _pairs(name: str) -> Iterator[tuple[str, str]]:
    return pairwise(name_parts(name))


def _page_level(element: HtmlElement) -> bool:
    """Whether the nearest ancestor that is sectioning content, a sectioning root or the main landmark is the body, or
    it is the main landmark, the element is its child and holds navigation: a page that wraps its whole layout in
    `main` puts its banner and footer there, beside its content, and they hold the site's navigation; the main
    content's own header or footer (its title, a citation, a link to the previous and next page) holds none, or sits
    inside the content's own wrapper."""
    scope = next((a for a in element.iterancestors() if a.tag in _SCOPES or _role(a) == "main"), None)
    if scope is None or scope.tag == "body":
        return True
    main = scope.tag == "main" or _role(scope) == "main"
    return main and element.getparent() is scope and bool(element.cssselect(_NAVIGATION))


def _collapsed_panels(tree: HtmlElement) -> frozenset[str]:
    """The ids of the panels a collapsed disclosure or tab control names (WAI-ARIA 1.2 `aria-controls` with
    `aria-expanded="false"` or `aria-selected="false"`; the Disclosure and Tabs patterns), read on the tree as the
    earlier stages left it: a control inside dropped furniture, or one the page hides itself, names nothing.
    A control that opens a popup (`aria-haspopup`: a menu, a dialog) is not a disclosure."""
    found: set[str] = set()
    for control in tree.iter():
        if not isinstance(control.tag, str) or not control.get("aria-controls"):
            continue
        state = control.get("aria-expanded") or control.get("aria-selected")
        popup = (control.get("aria-haspopup") or "false").lower() != "false"
        if (state or "").strip().lower() == "false" and not popup and not _concealed(control):
            found.update(tokens(control.get("aria-controls")))
    return frozenset(found)


def _concealed(element: HtmlElement) -> bool:
    return any(hidden(str(e.tag), dict(e.attrib)) for e in (element, *element.iterancestors()))


def _disclosed(element: HtmlElement, panels: frozenset[str]) -> bool:
    """Whether a hidden element is a collapsed disclosure's panel: `hidden="until-found"` (HTML Standard §6.1), or one
    a collapsed control names (`_collapsed_panels`) that is not itself a window (a `dialog`, `alertdialog` or `menu`
    role: WAI-ARIA 1.2 §5.4)."""
    if _role(element) in _WINDOWS:
        return False
    return (element.get("hidden") or "").strip().lower() == "until-found" or element.get("id") in panels


def _alternative(element: HtmlElement) -> bool:
    """Whether a hidden element is one of a set of like siblings (the same tag and role, a class in common) of which
    one is shown: a carousel's slides or a tab list's panels show one at a time and hide the others (WAI-ARIA Authoring
    Practices, Carousel and Tabs patterns: `aria-hidden` or `hidden` on the panels not shown), all of them the page's
    content."""
    parent = element.getparent()
    if parent is None:
        return False
    return any(
        _like(element, sibling) and not hidden(str(sibling.tag), dict(sibling.attrib))
        for sibling in parent.iterchildren(str(element.tag))
        if sibling is not element
    )


def _like(a: HtmlElement, b: HtmlElement) -> bool:
    return _role(a) == _role(b) and not set(tokens(a.get("class"))).isdisjoint(tokens(b.get("class")))
