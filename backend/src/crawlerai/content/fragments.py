"""Eager HTML fragments a page declares (extraction spec, "Source documents"): Hotwire Turbo frames.

A `<turbo-frame id src>` loads `src` as soon as the tag appears, unless its `loading` is `lazy`, which loads it only
when the frame becomes visible (Turbo handbook, Frames). The HTTP rung fetches an eager frame's `src` as a companion
call (`acquire.rungs`); the answer's element with the frame's `id` then replaces the frame's children
(`include`), as Turbo renders it. A lazy frame is not fetched.
"""

import re
from collections.abc import Iterator, Mapping
from typing import Final, NamedTuple
from urllib.parse import urldefrag, urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

__all__ = ["FRAME_HEADER", "MAX_FRAMES", "Answers", "Frame", "declares_frames", "eager_frames", "include"]

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


def include(tree: LexborHTMLParser, page_url: str, answers: Answers) -> None:
    """Replace the children of each eager frame of `tree` with those of the element whose id is the frame's in the
    answer to its `src` (`answers`: the one requested for that frame, else one that named no frame); a frame without
    an answer, or whose answer holds no such element, keeps its own."""
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
