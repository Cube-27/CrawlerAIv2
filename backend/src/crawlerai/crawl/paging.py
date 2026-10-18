"""A listing's browser actions (owner #52): collect more of a listing's rows on one tab by turning its pages, scrolling,
or clicking the control that loads more, until the caller's row target, the list's end or a cap.

Every rule reads the document's structure (C2), never its words (C4):

- **The items.** The groups of repeated linked items (`acquire.items.item_groups`), ranked by the segment step with
  the rendered areas the tab measures (`content.segment.rank`): the listing is the group with the largest rendered
  area, not the most members, since a sidebar's link list may outnumber a product grid. An
  item's identity is its first hyperlink (HTML Standard §4.6.1) that no other item of the group links to, else its
  first one: items may share a link (a company's, a posting's several locations). A page that shows no linked items
  counts the rows of its calls instead: the rows of the first series of the page's latest data calls (`Tab.calls`;
  `network_match`: rows whose own strings the page shows), each named by its JSON text (RFC 8259, members
  sorted), so a scroll listing whose items hold no link keeps loading. Only one of the two is counted, so an item that
  a call loaded and the page links to counts once.
- **Next pages by link.** `resolve.pagination`: `rel=next` (HTML Standard §4.6.7), then the link whose URL is the
  page's with one integer one higher; the tab navigates there, robots.txt and the site's rate permitting (the gate).
- **A numbered pager.** The first element after the last item (document order) whose children hold at least three
  controls (`a` with `href`, `button`, the `button` role: HTML Standard §4.6.1, §4.10.6, WAI-ARIA 1.2), at least two
  of them labelled only by a page's ordinal in ASCII digits, outside the page's header and footer (`header`, `footer`,
  roles `banner`, `contentinfo`); a pager may sit in `nav`. The current page is the control marked `aria-current`
  (WAI-ARIA 1.2 §6.7), else the cluster's one integer that is no control, else the pages turned so far plus one.
  `pagination` clicks the integer one higher; `next` the control after the current one.
- **Scroll.** To the document's end (CSSOM View); content that loads on scroll may ignore the first one, so two
  rounds without growth rule it out.
- **The control after the items** (`load_more`, `show_more`): the visible, enabled controls after the last item, in
  the group's container or the elements after it (up to three ancestors out), outside the items, the site's chrome
  (`in_chrome` in `acquire/items.py`) and forms (a form's controls submit or edit it: HTML Standard §4.10.3); the
  first three are tried in order. A click that changes the URL left the listing, so it is undone. Growth with no
  data request since the click is `show_more`, else `load_more`; either hint uses this mechanism.

Without a hint the order is: next pages by link or pager, scroll, the control after the items. An action's effect is
waited for by polling until an item no earlier state showed appears, or for a page turn the first item changes, for
at most `Caps.wait_s`. A document state that an action may replace is kept before it when it shows an item no kept
state holds: before a page turn always; before a scroll or a click that grows the list too, and that state is
dropped again when the state after the action still shows every item of it, so a list that recycles its items while
growing (a virtualised list) keeps each batch, and one that only grows keeps one state. The last state is kept on the
same test.
"""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from lxml.html import HtmlElement

from crawlerai.acquire.browser_tab import Click, Ref, Tab
from crawlerai.acquire.items import element_path, in_chrome, is_hyperlink, item_groups
from crawlerai.acquire.types import ActionsReport, BrowserActions, PagingHint, StopReason
from crawlerai.collect import json_doc
from crawlerai.collect.network_match import data_calls, row_series
from crawlerai.content.dom import document_base_url, tokens
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import block_links, rank
from crawlerai.normalize.url import canonical_url
from crawlerai.resolve.pagination import NextLink, next_page_links

__all__ = ["Caps", "Gate", "collect"]

# Admits a browser action, waiting for the site's rate (acquisition spec): for a navigation, its URL, which robots.txt
# must allow; for a click or a scroll, None: it acts on the document the tab shows. False when the action may not be
# taken.
Gate = Callable[[str | None], Awaitable[bool]]

# A page's ordinal as a pager labels it: ASCII digits only (not other scripts' digits, which `\d` would take).
_ORDINAL: Final = re.compile(r"[0-9]+")
# A page's header and footer (HTML Standard §4.3.8, §4.3.9; WAI-ARIA 1.2 landmark roles `banner`, `contentinfo`): a
# pager there pages the site, not the list.
_PAGE_ENDS_TAGS: Final = frozenset({"header", "footer"})
_PAGE_ENDS_ROLES: Final = frozenset({"banner", "contentinfo"})
# WAI-ARIA 1.2 §5.4 role `button`, and the elements that are controls by the HTML Standard (§4.6.1 hyperlinks, §4.10.6
# `button`).
_BUTTON_ROLE: Final = "button"
# WAI-ARIA 1.2 §6.7 `aria-current`: any value but `false` marks the current item of a set; `aria-disabled="true"` and
# the HTML `disabled` attribute (§4.10.18.5) mark a control that does nothing.
_NOT_CURRENT: Final = "false"
# A pager has at least this many controls, at least this many of them ordinals: fewer is a pair of links, not a pager.
_PAGER_CONTROLS: Final = 3
_PAGER_ORDINALS: Final = 2
# The control after the items is looked for up to this many ancestors out from the group's container.
_CONTROL_LEVELS: Final = 3

Effect = Literal["grow", "turn"]
# The no-hint order of mechanisms: page turns, scroll, then the control after the items.
_DETECT: Final[tuple[PagingHint, ...]] = ("next", "scroll", "load_more")


@dataclass(frozen=True)
class Caps:
    """The bounds of one run (owner #52; the probe's measurements, D-1221): actions, the wait for one action's
    effect, the poll interval of that wait, the scroll rounds and control clicks without growth before giving up."""

    actions: int = 40
    wait_s: float = 5.0
    poll_s: float = 0.25
    idle_rounds: int = 2
    controls: int = 3


_CAPS: Final = Caps()


@dataclass(frozen=True)
class _View:
    """The document as the tab shows it at one moment: its parse, URL, the listing's items (elements in document
    order) and their identities (distinct, in order)."""

    root: HtmlElement
    url: str
    items: tuple[HtmlElement, ...]
    ids: tuple[str, ...]
    page: ParsedPage

    @property
    def first(self) -> str | None:
        return self.ids[0] if self.ids else None


# What one step of a mechanism came to: nothing to act on, an action without effect, an action whose effect showed
# (the new view), or a reason to stop the run.
_Nothing = Literal["nothing"]
_NOTHING: Final[_Nothing] = "nothing"


@dataclass(frozen=True)
class _Moved:
    view: _View
    kind: PagingHint


@dataclass(frozen=True)
class _Still:
    view: _View


_Step = _Nothing | _Moved | _Still | StopReason


@dataclass(frozen=True)
class _Held:
    """The run's record of kept states before a state was kept ahead of an action, to restore when it is dropped."""

    kept: frozenset[str]
    kept_any: bool
    keeps: int


async def collect(tab: Tab, request: BrowserActions, gate: Gate, deadline: float, caps: Caps = _CAPS) -> ActionsReport:
    """Collect the listing on `tab` until `request.records` distinct items were seen (module docstring), or
    `deadline` (`time.monotonic()`) passes; the document states to keep are kept on the tab."""
    return await _Run(tab, request, gate, deadline, caps).go()


@dataclass
class _Run:
    tab: Tab
    request: BrowserActions
    gate: Gate
    deadline: float
    caps: Caps
    seen: dict[str, None] = field(default_factory=dict)
    kept: set[str] = field(default_factory=set)
    kept_any: bool = False
    keeps: int = 0
    visited: set[str] = field(default_factory=set)
    actions: int = 0
    turned: int = 0
    mechanism: PagingHint | None = None
    stop: StopReason | None = None

    async def go(self) -> ActionsReport:
        view = await self._first_view()
        if view is None or not view.ids:
            self.stop = "no_items"
        else:
            self._see(view)
            self.visited.add(_page_url(view.url))
            view = await self._loop(view)
        if view is not None:
            await self._keep(view)
        elif not self.kept_any and await self.tab.keep():
            self.kept_any, self.keeps = True, self.keeps + 1
        return ActionsReport(
            mechanism=self.mechanism,
            stop=self.stop or "error",
            actions=self.actions,
            pages=self.keeps,
            items=len(self.seen),
        )

    async def _loop(self, view: _View) -> _View:
        idle = 0
        while self.stop is None:
            if (capped := self._capped()) is not None:
                self.stop = capped
                break
            step = await (self._detect(view) if self.mechanism is None else self._act(self.mechanism, view))
            view, idle = self._after(step, view, idle)
        return view

    def _after(self, step: _Step, view: _View, idle: int) -> tuple[_View, int]:
        """The view and the count of rounds without new items after `step`; sets the stop reason when it ends the
        run."""
        match step:
            case _Moved(view=moved, kind=kind):
                if self.mechanism is None:
                    self.mechanism = self.request.hint or kind
                idle = 0 if self._see(moved) else idle + 1
                if idle >= self.caps.idle_rounds:
                    self.stop = "end"
                return moved, idle
            case _Still(view=still):
                idle += 1
                if self.mechanism in ("next", "pagination") or idle >= self.caps.idle_rounds:
                    self.stop = "end"
                return still, idle
            case "nothing":
                self.stop = "end" if self.mechanism is not None else "no_mechanism"
                return view, idle
            case _:
                self.stop = step
                return view, idle

    def _capped(self) -> StopReason | None:
        if len(self.seen) >= self.request.records:
            return "records"
        if self.actions >= self.caps.actions:
            return "action_cap"
        if time.monotonic() >= self.deadline:
            return "time_cap"
        return None

    async def _detect(self, view: _View) -> _Step:
        """The no-hint order (module docstring): the first mechanism whose action shows an effect decides. The first
        reason to stop (an intercepted click, robots.txt) stops the run when nothing worked."""
        order = (self.request.hint,) if self.request.hint is not None else _DETECT
        stopped: StopReason | None = None
        for mechanism in order:
            step = await self._try(mechanism, view)
            if isinstance(step, _Moved) or step in ("records", "action_cap", "time_cap"):
                return step
            if isinstance(step, _Still):
                view = step.view
            elif step != _NOTHING:
                stopped = stopped or step
        return stopped or _NOTHING

    async def _try(self, mechanism: PagingHint, view: _View) -> _Step:
        """`mechanism`'s first action, or its first `idle_rounds` for scroll (content may ignore the first scroll)."""
        step: _Step = _NOTHING
        for _ in range(self.caps.idle_rounds if mechanism == "scroll" else 1):
            if (capped := self._capped()) is not None:
                return capped
            step = await self._act(mechanism, view)
            if not isinstance(step, _Still):
                return step
            view = step.view
        return step

    async def _act(self, mechanism: PagingHint, view: _View) -> _Step:
        if mechanism == "scroll":
            return await self._scroll(view)
        if mechanism in ("load_more", "show_more"):
            return await self._control(view)
        return await self._turn(view, by_ordinal=mechanism == "pagination")

    # --- page turns ---

    async def _turn(self, view: _View, *, by_ordinal: bool) -> _Step:
        """A next page by link, else a numbered pager's control (module docstring)."""
        link = next((link for link in _links(view) if _page_url(link.url) not in self.visited), None)
        if link is not None:
            return await self._follow(view, link)
        control = _pager_control(view, self.turned, by_ordinal=by_ordinal)
        if control is None or not await self._visible(control):
            return _NOTHING
        return await self._click_turn(view, control)

    async def _follow(self, view: _View, link: NextLink) -> _Step:
        if not await self._keep(view):
            return "error"
        if not await self.gate(link.url):
            return "not_admitted"
        self.actions += 1
        self.visited.add(_page_url(link.url))
        if not await self.tab.goto(link.url, max(0.0, self.deadline - time.monotonic())):
            return _Still(view)
        return self._turned(await self._effect(view, "turn"), "next" if link.rel_next else "pagination")

    async def _click_turn(self, view: _View, control: HtmlElement) -> _Step:
        if not await self._keep(view):
            return "error"
        target = _target(view, control)
        if not await self.gate(target):
            return "not_admitted"
        self.actions += 1
        clicked = await self.tab.click(_ref(control))
        if clicked != "clicked":
            return _click_stop(clicked)
        effect = await self._effect(view, "turn")
        if not await self._landed(view, target):
            return "not_admitted"
        self.visited.add(_page_url(self.tab.url))
        return self._turned(effect, "pagination")

    async def _landed(self, view: _View, target: str | None) -> bool:
        """Whether the document a click led to may be kept: the same one, the hyperlink's target the gate admitted, or
        a page a script navigated to that the gate admits now; a page it refuses is left (`back`)."""
        landed = _page_url(self.tab.url)
        if landed in (_page_url(view.url), target) or await self.gate(landed):
            return True
        await self.tab.back()
        return False

    def _turned(self, effect: tuple[_View, bool], kind: PagingHint) -> _Step:
        view, shown = effect
        if not shown:
            return _Still(view)
        self.turned += 1
        return _Moved(view, kind)

    # --- scroll ---

    async def _scroll(self, view: _View) -> _Step:
        if not await self.gate(None):
            return "not_admitted"
        held = await self._hold(view)
        if held is False:
            return "error"
        self.actions += 1
        await self.tab.scroll()
        moved, shown = await self._effect(view, "grow")
        self._release(held, view, moved)
        return _Moved(moved, "scroll") if shown else _Still(moved)

    # --- the control after the items ---

    async def _control(self, view: _View) -> _Step:
        """Click the first of the controls after the items whose click grows the list without leaving the URL."""
        candidates = [c for c in _controls_after(view) if await self._visible(c)][: self.caps.controls]
        if not candidates:
            return _NOTHING
        for control in candidates:
            if (capped := self._capped()) is not None:
                return capped
            step = await self._click_control(view, control)
            if not isinstance(step, _Still):
                return step
            view = step.view
        return _Still(view)

    async def _click_control(self, view: _View, control: HtmlElement) -> _Step:
        if not await self.gate(_target(view, control)):
            return _Still(view)  # a hyperlink to a page the gate refuses is no control of this listing
        held = await self._hold(view)
        if held is False:
            return "error"
        self.actions += 1
        url, requests = _page_url(self.tab.url), self.tab.data_requests()
        clicked = await self.tab.click(_ref(control))
        if clicked == "gone":
            self._release(held, view, view)
            return _Still(view)
        if clicked == "intercepted":
            self._release(held, view, view)
            return "click_intercepted"
        moved, shown = await self._effect(view, "grow")
        if _page_url(self.tab.url) != url:
            await self.tab.back()  # it left the listing: not a control that loads more of it
            if _page_url(self.tab.url) != url:
                return "error"  # the listing could not be got back
            return _Still(await self._read() or view)
        self._release(held, view, moved)
        if not shown:
            return _Still(moved)
        return _Moved(moved, "load_more" if self.tab.data_requests() > requests else "show_more")

    # --- reading the tab ---

    async def _first_view(self) -> _View | None:
        """The view once it shows items, waiting up to `wait_s` for a page that renders them late."""
        end = min(time.monotonic() + self.caps.wait_s, self.deadline)
        view = await self._read()
        while (view is None or not view.ids) and time.monotonic() < end:
            await asyncio.sleep(self.caps.poll_s)
            view = await self._read() or view
        return view

    async def _read(self) -> _View | None:
        html = await self.tab.html()
        if html is None:
            return None
        calls = await self.tab.calls()
        page = ParsedPage(html, tuple(body for _, body in calls), tuple(entry for entry, _ in calls))
        url = self.tab.url
        root = page.lxml_tree
        items = await self._largest(item_groups(root))
        ids = _identities(items, document_base_url(page, url)) if items else _call_rows(page)
        return _View(root, url, items, ids, page)

    async def _largest(self, groups: Sequence[tuple[HtmlElement, ...]]) -> tuple[HtmlElement, ...]:
        """The rendered items of the group the segment step ranks first by rendered area (`content.segment.rank`);
        none when no group is rendered at all. An item not rendered (hidden until a control shows it) is not on the
        page yet."""
        refs = [_ref(item) for group in groups for item in group]
        areas = await self.tab.areas(refs) if refs else []
        ranked = rank(groups, {path: area for (path, _), area in zip(refs, areas, strict=True)})
        return ranked[0] if ranked else ()

    async def _visible(self, element: HtmlElement) -> bool:
        return (await self.tab.areas([_ref(element)]))[0] > 0

    async def _effect(self, before: _View, effect: Effect) -> tuple[_View, bool]:
        """The view once the action's effect shows (an item not seen before; for a turn, a new first item too), and
        whether it showed within `wait_s`. The document is read again only when it changed."""
        end = min(time.monotonic() + self.caps.wait_s, self.deadline)
        view, last = before, None
        while True:
            await asyncio.sleep(self.caps.poll_s)
            mark = (self.tab.url, await self.tab.mutations())
            done = time.monotonic() >= end
            if mark[1] is not None and (mark != last or done):
                last = mark
                view = await self._read() or view
                if self._shows(before, view, effect):
                    return view, True
            if done:
                return view, False

    def _shows(self, before: _View, view: _View, effect: Effect) -> bool:
        new = any(identity not in self.seen for identity in view.ids)
        if effect == "grow":
            return new
        return view.first is not None and view.first != before.first

    def _see(self, view: _View) -> bool:
        """Count the view's items; whether any was new."""
        size = len(self.seen)
        self.seen.update(dict.fromkeys(view.ids))
        return len(self.seen) > size

    async def _hold(self, view: _View) -> _Held | bool:
        """Keep the state ahead of an action that may replace it (module docstring): what to restore when it is
        dropped, True when no state needed keeping, False when it could not be kept."""
        if self._held(view):
            return True
        held = _Held(frozenset(self.kept), self.kept_any, self.keeps)
        return held if await self._keep(view) else False

    def _release(self, held: _Held | bool, before: _View, after: _View) -> None:
        """Drop the state kept ahead of an action when the state after it still shows each of its items."""
        if isinstance(held, _Held) and set(before.ids) <= set(after.ids):
            self.tab.discard()
            self.kept, self.kept_any, self.keeps = set(held.kept), held.kept_any, held.keeps

    def _held(self, view: _View) -> bool:
        """Whether the kept states already hold every item of the view."""
        return self.kept_any and set(view.ids) <= self.kept

    async def _keep(self, view: _View) -> bool:
        """Keep the document state when it shows an item no kept state holds (or none is kept yet)."""
        if self._held(view):
            return True
        if not await self.tab.keep():
            return False
        self.kept_any, self.keeps = True, self.keeps + 1
        self.kept.update(view.ids)
        return True


def _click_stop(clicked: Click) -> _Step:
    # An element gone from the document between reading and clicking is an action without effect.
    return "click_intercepted" if clicked == "intercepted" else _NOTHING


def _page_url(url: str) -> str:
    """`url` without its fragment, canonical (RFC 3986 §3.5: the fragment names a part of one document)."""
    return canonical_url(url, None) or url


def _target(view: _View, control: HtmlElement) -> str | None:
    """The document a hyperlink control navigates to (HTML Standard §4.6.4), for the gate to admit before the click;
    None for a control that is no hyperlink or stays on the page (a fragment; a `javascript:` URL, no URL)."""
    if not is_hyperlink(control):
        return None
    url = canonical_url(control.get("href") or "", document_base_url(view.page, view.url))
    return None if url is None or url == _page_url(view.url) else url


def _identities(items: Sequence[HtmlElement], base: str) -> tuple[str, ...]:
    """Each item's identity (module docstring), distinct, in order; an item without a hyperlink has none."""
    urls = [list(dict.fromkeys(block_links(item, base))) for item in items]
    counts: dict[str, int] = {}
    for own in urls:
        for url in own:
            counts[url] = counts.get(url, 0) + 1
    identities = (next((url for url in own if counts[url] == 1), own[0]) for own in urls if own)
    return tuple(dict.fromkeys(identities))


def _call_rows(page: ParsedPage) -> tuple[str, ...]:
    """The rows of the first series of the page's data calls (module docstring), each named by a digest of its JSON
    text, distinct, in order."""
    series = next(iter(row_series(data_calls(page))), ())
    names: dict[str, None] = {}
    for data in series:
        for _, row in json_doc.select(data.rows or "", data.call.document):
            if isinstance(row, dict):
                text = json.dumps(row, sort_keys=True, ensure_ascii=False)
                names[hashlib.sha256(text.encode()).hexdigest()] = None
    return tuple(names)


def _links(view: _View) -> tuple[NextLink, ...]:
    return next_page_links(view.page, view.url)


def _ref(element: HtmlElement) -> Ref:
    """The element's element-index XPath path from the document root (`acquire.items.element_path`), and its tag."""
    return element_path(element), str(element.tag)


def _is_control(element: HtmlElement) -> bool:
    if not isinstance(element.tag, str):
        return False
    return is_hyperlink(element) or element.tag == "button" or _BUTTON_ROLE in tokens(element.get("role"))


def _enabled(element: HtmlElement) -> bool:
    return element.get("disabled") is None and element.get("aria-disabled") != "true"


def _after_items(view: _View) -> Iterator[HtmlElement]:
    """The controls after the last item in document order, outside every item; none without linked items."""
    if not view.items:
        return
    last = view.items[-1]
    inside = {element for item in view.items for element in item.iter()}
    started = False
    for element in view.root.iter():
        if element is last:
            started = True
        elif started and element not in inside and _is_control(element):
            yield element


def _within(element: HtmlElement, tags: frozenset[str], roles: frozenset[str]) -> bool:
    node: HtmlElement | None = element
    while node is not None:
        if node.tag in tags or not roles.isdisjoint(tokens(node.get("role"))):
            return True
        node = node.getparent()
    return False


def _ordinal(element: HtmlElement) -> int | None:
    text = element.text_content().strip()
    return int(text) if _ORDINAL.fullmatch(text) else None


def _pager_control(view: _View, turned: int, *, by_ordinal: bool) -> HtmlElement | None:
    """The numbered pager's control for the next page (module docstring); None without a pager or a next page."""
    pager = _pager(view)
    if pager is None:
        return None
    slots, controls = pager
    current = _current(slots, controls, turned)
    numbered = {_ordinal(control): control for control in controls}
    if by_ordinal:
        return numbered.get(current + 1)
    marked = next((c for c in controls if _ordinal(c) == current), None)
    if marked is None:
        return numbered.get(current + 1)
    following = controls[controls.index(marked) + 1 :]
    return next((c for c in following if _enabled(c)), None)


def _pager(view: _View) -> tuple[list[HtmlElement], list[HtmlElement]] | None:
    """The first pager after the items: its children and its controls, in order."""
    clusters: dict[HtmlElement, None] = {}
    for control in _after_items(view):
        if not _within(control, _PAGE_ENDS_TAGS, _PAGE_ENDS_ROLES):
            parent = _slot(control).getparent()
            clusters.setdefault(control if parent is None else parent, None)
    return next((pager for cluster in clusters if (pager := _cluster(cluster)) is not None), None)


def _cluster(element: HtmlElement) -> tuple[list[HtmlElement], list[HtmlElement]] | None:
    """`element`'s children and their controls when they make a pager: enough controls, enough of them ordinals."""
    slots = _children(element)
    controls = [control for slot in slots if (control := _slot_control(slot)) is not None]
    ordinals = [ordinal for ordinal in map(_ordinal, controls) if ordinal is not None]
    if len(controls) >= _PAGER_CONTROLS and len(ordinals) >= _PAGER_ORDINALS:
        return slots, controls
    return None


def _slot(control: HtmlElement) -> HtmlElement:
    """The pager child holding `control`: the control, or its parent when the control is that parent's one element
    (a list item around each link)."""
    parent = control.getparent()
    if (
        parent is not None
        and parent.getparent() is not None
        and len([c for c in parent if isinstance(c.tag, str)]) == 1
    ):
        return parent
    return control


def _children(element: HtmlElement) -> list[HtmlElement]:
    """The element's element children (lxml also iterates comments and processing instructions)."""
    return [child for child in element if isinstance(child.tag, str)]


def _slot_control(slot: HtmlElement) -> HtmlElement | None:
    if _is_control(slot):
        return slot
    return next((element for element in slot.iter() if element is not slot and _is_control(element)), None)


def _current(slots: list[HtmlElement], controls: list[HtmlElement], turned: int) -> int:
    """The current page's ordinal (module docstring)."""
    for control in controls:
        marked = control.get("aria-current")
        if marked is not None and marked != _NOT_CURRENT and (ordinal := _ordinal(control)) is not None:
            return ordinal
    plain = [o for slot in slots if _slot_control(slot) is None and (o := _ordinal(slot)) is not None]
    if len(plain) == 1:
        return plain[0]
    return turned + 1


def _controls_after(view: _View) -> list[HtmlElement]:
    """The candidates for the control after the items, nearest level first (module docstring)."""
    after = [c for c in _after_items(view) if _enabled(c) and not in_chrome(c) and not _in_form(c)]
    if not after:
        return []
    node: HtmlElement | None = view.items[-1].getparent()
    for _ in range(_CONTROL_LEVELS + 1):
        if node is None or node.tag == "body":
            break
        roots = {node, *node.itersiblings()}
        found = [c for c in after if _under(c, roots)]
        if found:
            return found
        node = node.getparent()
    return []


def _under(element: HtmlElement, roots: set[HtmlElement]) -> bool:
    """Whether `element` is one of `roots` or inside one."""
    return element in roots or any(ancestor in roots for ancestor in element.iterancestors())


def _in_form(element: HtmlElement) -> bool:
    return _within(element, frozenset({"form"}), frozenset())
