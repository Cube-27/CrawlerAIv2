"""The cleaned text as role C reads it on a detail page (llm spec, "Role C input, claims and candidates"): the text,
with an id after each shown link and at each shown image the fields asked can claim (`content.text.Mark`).

A link reads `[L<n>]` after its text, or `[L<n>: <name>]` when it announces a name its text does not show; an image
reads `[I<n>]`, or `[I<n>: <alt>]`. The ids are numbered in document order, so the same page gives the same text
(INV-10). Only a link to another resource is marked: a same-document reference (RFC 3986 §4.4: resolved, the base URL
up to its fragment) names the page itself, not a link it states. A target that is not an http(s) URL (a `data:` image,
a `javascript:` link) is not marked either, as no url or image_url value comes of it (`normalize.url`). The page is
its own URL when known: a `<base href>` elsewhere moves where relative targets resolve, not which page this is. The ids
take at most `budget` characters together, so the text stays near its cut; the marks past it are not shown.

The ids are not page text: a span the model claims is grounded in the cleaned text itself, its offsets moved back past
the ids before it (`cleaned_offset`), and a claimed id is grounded in the element it marks (`llm.grounding`, INV-12).

Role C's evidence is the product's own (`scoped`): the text runs and marks of the elements that hold other items'
content (`collect.dom.other_item_paths`: related and similar items, reviews, lists of other documents' cards, the cards
of other items whose prices the page shows) are left out, with the line breaks and spaces that follow them, so the
model neither reads nor grounds a value of another item. Offsets of the scoped text map back to the whole cleaned
text (`Scoped.cleaned_offset`), where locators point.
"""

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final
from urllib.parse import urldefrag

from crawlerai.content.text import CleanedText, Mark, MarkKind, TextRun
from crawlerai.normalize.url import canonical_url

_PREFIX: Final[Mapping[MarkKind, str]] = MappingProxyType({"link": "L", "image": "I"})


@dataclass(frozen=True, slots=True)
class MarkedText:
    """`text` is what the model reads: `cleaned`, the cleaned text it was made from (as cut), with an id inserted at
    each of `inserted`'s positions in `cleaned`, the ids' lengths in `lengths`; `elements` are the marks by id."""

    text: str
    cleaned: str
    elements: Mapping[str, Mark]
    inserted: tuple[int, ...] = ()
    lengths: tuple[int, ...] = ()

    def cleaned_offset(self, offset: int) -> int:
        """The offset in `cleaned` of the character at `offset` in `text`: past every id that ends at or before it, an
        offset inside an id moved to the id's position."""
        shift = 0
        for at, length in zip(self.inserted, self.lengths, strict=True):
            if at + shift >= offset:
                break
            if offset < at + shift + length:
                return at
            shift += length
        return offset - shift


def marked(
    cleaned: CleanedText,
    read: str,
    kinds: frozenset[MarkKind],
    base_url: str | None,
    page_url: str | None,
    budget: int,
) -> MarkedText:
    """`read` (the cleaned text's first characters, as cut) with the ids of the shown marks of `kinds` inside it, the
    ids within `budget` characters."""
    if not kinds:
        return MarkedText(read, read, MappingProxyType({}))
    elements: dict[str, Mark] = {}
    counts = dict.fromkeys(_PREFIX, 0)
    own = page_url or base_url
    page = None if own is None else urldefrag(canonical_url(own, None) or own).url
    pieces: list[str] = []
    inserted: list[int] = []
    lengths: list[int] = []
    position = 0
    for mark in cleaned.marks:
        if mark.kind not in kinds or mark.end > len(read) or not _other_resource(mark.target, base_url, page):
            continue
        ref = f"{_PREFIX[mark.kind]}{counts[mark.kind] + 1}"
        label = _label(ref, mark, read)
        if sum(lengths) + len(label) > budget:
            break
        counts[mark.kind] += 1
        elements[ref] = mark
        pieces.extend((read[position : mark.end], label))
        inserted.append(mark.end)
        lengths.append(len(label))
        position = mark.end
    pieces.append(read[position:])
    return MarkedText("".join(pieces), read, MappingProxyType(elements), tuple(inserted), tuple(lengths))


def _other_resource(target: str, base_url: str | None, page: str | None) -> bool:
    """Whether `target` resolves to an http(s) URL other than the page's own (RFC 3986 §4.4)."""
    resolved = canonical_url(target, base_url)
    return resolved is not None and urldefrag(resolved).url != page


def _label(ref: str, mark: Mark, read: str) -> str:
    """The id as the text shows it, with the mark's name when its own text does not already read so."""
    shown = read[mark.start : mark.end]
    named = mark.name and mark.name != shown
    return f"[{ref}: {mark.name}]" if named else f"[{ref}]"


@dataclass(frozen=True, slots=True)
class Scoped:
    """The cleaned text without other items' content: `text` keeps the runs and marks outside `elsewhere`, and
    `segments` are the kept `(start in text, start in the whole cleaned text)` pairs, in order."""

    text: CleanedText
    segments: tuple[tuple[int, int], ...] = ((0, 0),)

    def cleaned_offset(self, offset: int, *, end: bool = False) -> int:
        """The offset in the whole cleaned text of `offset` in the scoped text; an `end` offset at a segment's end
        stays in that segment (it closes a span there)."""
        starts = [at for at, _ in self.segments]
        index = max(0, bisect_right(starts, offset - (1 if end and offset else 0)) - 1)
        at, origin = self.segments[index]
        return origin + offset - at


def scoped(cleaned: CleanedText, elsewhere: frozenset[str]) -> Scoped:
    """`cleaned` without the text runs and marks of the elements at the node paths `elsewhere` and inside them, each
    left-out run taken with what separates it from the next run."""
    kept = _kept(cleaned, elsewhere) if elsewhere else None
    if kept is None:
        return Scoped(cleaned)
    runs, text = cleaned.offsets, cleaned.text
    pieces: list[str] = []
    segments: list[tuple[int, int]] = []
    length = 0
    for start, stop in kept:
        segments.append((length, start))
        pieces.append(text[start:stop])
        length += stop - start
    moved = _Mover(tuple(kept), tuple(segments))
    offsets = tuple(TextRun(*span, run.node_path) for run in runs if (span := moved.span(run.start, run.end)))
    marks = tuple(
        mark._replace(start=span[0], end=span[1])
        for mark in cleaned.marks
        if not _inside(mark.path, elsewhere) and (span := moved.span(mark.start, mark.end))
    )
    return Scoped(CleanedText("".join(pieces), offsets, marks), tuple(segments))


def _kept(cleaned: CleanedText, elsewhere: frozenset[str]) -> list[tuple[int, int]] | None:
    """The spans of `cleaned`'s text left once the runs inside `elsewhere` are cut, each with what follows it up to the
    next run; None when no run is."""
    runs, text = cleaned.offsets, cleaned.text
    cuts: list[tuple[int, int]] = []
    for index, run in enumerate(runs):
        if not _inside(run.node_path, elsewhere):
            continue
        stop = runs[index + 1].start if index + 1 < len(runs) else len(text)
        if cuts and cuts[-1][1] == run.start:
            cuts[-1] = (cuts[-1][0], stop)
        else:
            cuts.append((run.start, stop))
    if not cuts:
        return None
    kept: list[tuple[int, int]] = []
    position = 0
    for start, stop in cuts:
        if start > position:
            kept.append((position, start))
        position = stop
    if position < len(text) or not kept:
        kept.append((position, len(text)))
    return kept


def _inside(path: str, roots: frozenset[str]) -> bool:
    """Whether the element at `path` is one of `roots` or inside one (an XPath location path is its ancestors' plus
    one step)."""
    while path:
        if path in roots:
            return True
        path = path.rpartition("/")[0]
    return False


@dataclass(frozen=True, slots=True)
class _Mover:
    """Moves a span of the whole cleaned text into the scoped text, when it lies in one kept segment."""

    kept: tuple[tuple[int, int], ...]
    segments: tuple[tuple[int, int], ...]

    def span(self, start: int, end: int) -> tuple[int, int] | None:
        index = bisect_right([s for s, _ in self.kept], start) - 1
        if index < 0:
            return None
        low, high = self.kept[index]
        if not low <= start <= end <= high:
            return None
        at = self.segments[index][0]
        return at + start - low, at + end - low
