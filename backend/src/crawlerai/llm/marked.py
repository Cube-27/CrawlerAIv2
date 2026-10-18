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
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final
from urllib.parse import urldefrag

from crawlerai.content.text import CleanedText, Mark, MarkKind
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
