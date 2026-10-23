"""Eager HTML fragments a page declares: Hotwire Turbo frames.

A `<turbo-frame id src>` loads `src` as soon as the tag appears, unless its `loading` is `lazy`, which loads it only
when the frame becomes visible (Turbo handbook, Frames). The HTTP rung fetches an eager frame's `src` as a companion
call (`acquire.rungs`); the answer's element with the frame's `id` then replaces the frame's children
(`include`), as Turbo renders it. A lazy frame is not fetched.

The other HTML answers a capture holds are the partials the page fetched from its own site (htmx-style swaps, a
frame's answer the browser fetched). A partial (an answer that is no whole
document) whose text the page does not show, as after a swap the render no longer holds, is appended to the page's
body (`append`), so the page's readers read it as they read the page; a whole document (a Turbo Drive visit) is not.
"""

import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from typing import Final, NamedTuple
from urllib.parse import urldefrag, urljoin, urlsplit

from selectolax import lexbor
from selectolax.lexbor import LexborHTMLParser, LexborNode

from crawlerai.content.text import render
from crawlerai.normalize.strings import collapse

__all__ = [
    "FRAME_HEADER",
    "MAX_FRAMES",
    "Answers",
    "Frame",
    "append",
    "declares_frames",
    "eager_frames",
    "include",
    "is_partial",
]

# Turbo handbook (Frames): the request header naming the frame a request is for; a server may answer that frame alone.
FRAME_HEADER: Final = "Turbo-Frame"
# The captured answers by URL and the frame their request named (None for a request that named none).
Answers = Mapping[tuple[str, str | None], str]
# The most frames of one page that are fetched: each is one more request to the site.
MAX_FRAMES: Final = 8
_FRAME: Final = "turbo-frame[id][src]"
_LAZY: Final = "lazy"
# The custom element's tag (HTML Standard §4.13: tag names compare ASCII case-insensitively).
_MARKER: Final = re.compile(r"<turbo-frame\b", re.IGNORECASE)
_WEB_SCHEMES: Final = ("http", "https")  # RFC 9110 §4.2
# HTML Standard §13.1: a whole document starts, after a byte order mark, white space and comments, with its DOCTYPE or
# an `html`, `head` or `body` start tag; a partial starts with none of them (one inside a script or comment counts not).
_DOCUMENT: Final = re.compile(r"<(?:!doctype|html|head|body)[\s>]", re.IGNORECASE)
# The element an appended partial is held in, naming the URL it answered.
_PARTIAL: Final = "<div data-fragment-src></div>"


class Frame(NamedTuple):
    """An eager frame: its `id` and the absolute URL its `src` names (RFC 3986 §5, without the fragment)."""

    id: str
    src: str


def declares_frames(html: str) -> bool:
    """Whether the document has a frame element at all (no parse)."""
    return _MARKER.search(html) is not None


def eager_frames(html: str, page_url: str) -> tuple[Frame, ...]:
    """The eager frames of the document, in document order, each once and at most `MAX_FRAMES`: the requests the
    page's own frames would make. Empty for a document without a frame (no parse)."""
    if not declares_frames(html):
        return ()
    frames = dict.fromkeys(frame for _, frame in _frames(LexborHTMLParser(html), page_url))
    return tuple(frames)[:MAX_FRAMES]


def include(tree: LexborHTMLParser, page_url: str, answers: Answers) -> set[str]:
    """Replace the children of each eager frame of `tree` with those of the element whose id is the frame's in the
    answer to its `src` (`answers`: the one requested for that frame, else one that named no frame); a frame without
    an answer, or whose answer holds no such element, keeps its own. The URLs of the answers included are returned."""
    included: set[str] = set()
    for node, frame in _frames(tree, page_url):
        answer = answers.get((frame.src, frame.id)) or answers.get((frame.src, None))
        if answer is None:
            continue
        source = next((n for n in LexborHTMLParser(answer).css("[id]") if n.attributes.get("id") == frame.id), None)
        if source is None:
            continue
        while (child := node.child) is not None:
            child.decompose()
        for child in source.iter(include_text=True):
            node.insert_child(child)
        included.add(frame.src)
    return included


def _frames(tree: LexborHTMLParser, page_url: str) -> Iterator[tuple[LexborNode, Frame]]:
    for node in tree.css(_FRAME):
        attributes = node.attributes
        frame_id, src = attributes.get("id"), (attributes.get("src") or "").strip()
        if not frame_id or not src or (attributes.get("loading") or "").strip().lower() == _LAZY:
            continue
        try:
            url = urldefrag(urljoin(page_url, src)).url
        except ValueError:  # an authority no URL parser reads (RFC 3986 §3.2.2) names no request
            continue
        if urlsplit(url).scheme.lower() in _WEB_SCHEMES:
            yield node, Frame(frame_id, url)


def is_partial(markup: str) -> bool:
    """Whether `markup` is a partial: no whole document (`_DOCUMENT`), its leading comments skipped."""
    start = markup.lstrip("\ufeff").lstrip()
    while start.startswith("<!--"):
        end = start.find("-->", 4)
        if end < 0:
            return True
        start = start[end + 3 :].lstrip()
    return _DOCUMENT.match(start) is None


def append(tree: LexborHTMLParser, partials: Sequence[tuple[str, str]], included: Collection[str] = ()) -> None:
    """Append to the body of `tree` each of the `partials` (URL, markup) whose text the document does not already
    show (its visible text, `content.text.render`; a hidden copy shows nothing), in capture order, each in an element
    naming its URL (`data-fragment-src`); one with no visible text, or a frame's answer `included`, adds nothing."""
    body = tree.body
    if body is None:
        return
    shown = collapse(render(body)[0].text)
    for url, markup in partials:
        if url in included:  # a frame's answer, read in its frame (`include`)
            continue
        holder = LexborHTMLParser(_PARTIAL).css_first("div")
        if holder is None:
            return
        for node in lexbor.parse_fragment(markup):
            holder.insert_child(node)
        text = collapse(render(holder)[0].text)
        if not text or text in shown:
            continue
        holder.attrs["data-fragment-src"] = url
        body.insert_child(holder)
        shown = f"{shown} {text}"
