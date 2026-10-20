"""Grounding by alignment (llm spec, INV-12): a role C value is kept only as a verbatim span of
the cleaned text, with offsets that hold it.

The model's offsets are a hint, not a fact (D-0024). A claim whose offsets hold its value is accepted as stated;
otherwise the value is searched for exactly, and the occurrence nearest the claimed `start` wins. A value the text
does not contain is dropped. There is no fuzzy, case- or whitespace-insensitive matching: the cleaned text's own
normalization (extraction spec) is the only one. Offsets count code points of the cleaned text, as Python `str` indices
do.

A money claim may differ from the text only in the spacing between its currency sign and its digits: CLDR's
`currencySpacing` makes that space the locale's presentation, so `$19.98` is grounded at the text's `$ 19.98`, and the
value is the text's span, never the model's spelling.

A span is whole words (Unicode UAX #29 word boundaries: letters, digits and connector punctuation such as `_` continue
a word; ideographic and South-East Asian scripts, written without spaces, break anywhere): an occurrence that continues
a word of the text, the `0` inside `9781400215522`, holds no value. Where two text runs of the page meet, a word ends
(`breaks`: the element boundary is a boundary the text does not show). An identifier claim grounds only outside an
address: an occurrence inside a URL or a media file's name (RFC 3986 URI or path reference, a name whose extension is
a registered image, audio or video media type) is a resource the page names, not an identifier it states.

A claim of a link or an image names the id the text gave it (`llm.marked`): it is kept only when that id marks an
element of the kind the field takes on the page, and its value is the element's `href` or `src` as the DOM states it,
never text of the model's.
"""

import mimetypes
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from crawlerai.collect.locator import format_locator
from crawlerai.content.text import Mark, MarkKind


class SpanClaim(BaseModel):
    """One value as the model reports it: `{"value": ..., "start": ..., "end": ...}` (§4.4 output schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    value: str
    start: int
    end: int


@dataclass(frozen=True)
class GroundedSpan:
    """A value that is `cleaned_text[start:end]`; `value` is the `raw` for the field's normalizer (§4.3 step 3)."""

    value: str
    start: int
    end: int

    @property
    def locator(self) -> str:
        return format_locator("text", str(self.start), str(self.end))


@dataclass(frozen=True)
class GroundedElement:
    """A link's `href` or an image's `src` as the page's DOM states it, at the element's path."""

    value: str
    path: str

    @property
    def locator(self) -> str:
        return format_locator("dom", self.path)


def ground_element(ref: str, kind: MarkKind, elements: Mapping[str, Mark]) -> GroundedElement | None:
    """The element `ref` names when it is one of `elements` and of `kind`, else None (ungrounded)."""
    mark = elements.get(ref)
    if mark is None or mark.kind != kind:
        return None
    return GroundedElement(mark.target, mark.path)


def align(
    claim: SpanClaim,
    cleaned_text: str,
    *,
    money: bool = False,
    identifier: bool = False,
    breaks: frozenset[int] = frozenset(),
) -> GroundedSpan | None:
    """The claim as a span of `cleaned_text`, or None when the text does not contain its value as whole words
    (ungrounded). A `money` claim is a whole number of the text, and one the text does not contain verbatim is found
    with any spacing between its currency sign and its digits. An `identifier` claim is not grounded in an address
    (module docstring). `breaks` are the offsets where two text runs meet."""
    value = claim.value
    if not value:
        return None  # an empty span holds no value
    holds = _holds(cleaned_text, money=money, identifier=identifier, breaks=breaks)
    # Both ends must be offsets into the text: a negative end would slice counting from the end.
    if (
        0 <= claim.start < claim.end <= len(cleaned_text)
        and cleaned_text[claim.start : claim.end] == value
        and holds(claim.start, claim.end)
    ):
        return GroundedSpan(value, claim.start, claim.end)
    spans = [(i, i + len(value)) for i in _occurrences(value, cleaned_text) if holds(i, i + len(value))]
    if not spans and money:
        spans = [span for span in _sign_spaced(value, cleaned_text) if holds(*span)]
    if not spans:
        return None
    # Nearest to the claimed start; of two equally near, the earlier, so the choice is deterministic (INV-10).
    start, end = min(spans, key=lambda span: (abs(span[0] - claim.start), span[0]))
    return GroundedSpan(cleaned_text[start:end], start, end)


def _holds(text: str, *, money: bool, identifier: bool, breaks: frozenset[int]) -> Callable[[int, int], bool]:
    """Whether the span `[start, end)` of `text` can hold the claim's value (module docstring)."""

    def holds(start: int, end: int) -> bool:
        if not bounded(text, start, end, breaks):
            return False
        if money and not _whole(text, start, end):
            return False
        return not (identifier and in_address(text, start, end))

    return holds


def bounded(text: str, start: int, end: int, breaks: frozenset[int] = frozenset()) -> bool:
    """Whether `text[start:end]` begins and ends at word boundaries (UAX #29), a meeting of two text runs being one."""
    return _boundary(text, start, breaks) and _boundary(text, end, breaks)


def _boundary(text: str, at: int, breaks: frozenset[int]) -> bool:
    if at <= 0 or at >= len(text) or at in breaks:
        return True
    return not (_word_char(text[at - 1]) and _word_char(text[at]))


# UAX #14 class SA (complex context: Thai, Lao, Myanmar, Khmer) writes words without spaces, as East Asian wide and
# fullwidth characters (UAX #11: ideographs, kana, Hangul syllables) do; UAX #29 finds no boundary between letters from
# the characters alone there, so none is required.
_SPACELESS = ((0x0E00, 0x0EFF), (0x1000, 0x109F), (0x1780, 0x17FF))


def _word_char(char: str) -> bool:
    """A character that continues a word (UAX #29 ALetter, Numeric, ExtendNumLet: letters, marks, digits and connector
    punctuation), outside the scripts written without spaces."""
    if unicodedata.category(char)[0] not in "LMN" and unicodedata.category(char) != "Pc":
        return False
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return False
    return not any(low <= ord(char) <= high for low, high in _SPACELESS)


# An address is never longer than this many characters (RFC 9110 §4.1 recommends supporting URIs of 8000 octets), so
# the token around a span is looked for no further.
_LONGEST = 8000
# RFC 3986 §3: a URI's scheme and authority (`https://`), or a network-path or absolute-path reference (§4.2).
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://|\A//|\A/[^/\s]")
# The media types Python ships (`mimetypes` defaults, from the IANA registry), never the host's own files, so the
# reading is the same on every machine (INV-10).
_MEDIA_TYPES = mimetypes.MimeTypes(filenames=())
_MEDIA = ("image/", "audio/", "video/")


def in_address(text: str, start: int, end: int) -> bool:
    """Whether the span lies inside a URL or a media file's name the text writes (module docstring)."""
    span = text[start:end]
    if any(char.isspace() for char in span):
        return False  # an address holds no white space
    word = text[_token_edge(text, start, -1) : _token_edge(text, end, 1)]
    if _URI.search(word):
        return True
    name = word.rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
    media, _ = _MEDIA_TYPES.guess_type(name, strict=True)
    return media is not None and media.startswith(_MEDIA)


def _token_edge(text: str, at: int, step: int) -> int:
    """Where the run of non-space characters through `at` ends, going back (`step` -1) or on (1)."""
    limit = max(0, at - _LONGEST) if step < 0 else min(len(text), at + _LONGEST)
    while at != limit and not text[at - 1 if step < 0 else at].isspace():
        at += step
    return at


# A spaced match is not one end of a displayed range (`$ 19.98 - $ 24.99`): no range dash right before or after it.
_DASHES = "\\-\u2013\u2014~"
_NOT_AFTER_DASH = rf"(?<![{_DASHES}])(?<![{_DASHES}]\s)"
_NOT_BEFORE_DASH = rf"(?!\s*[{_DASHES}])"
# One amount: digits, with the grouping and decimal marks between them.
_AMOUNT = re.compile(r"\d(?:[\d.,'\u00a0\u202f ]*\d)?")
# What continues a number past its digits, or leads into them: a digit, or a CLDR decimal or group symbol next to one
# (a space-separated group is three digits, CLDR grouping), so `$4` is not the head of `$4,000` nor `219.98` the tail
# of `1 219.98`.
_CONTINUES = re.compile(r"\d|[.,'\u2019]\d|\s\d{3}(?!\d)")
_LEADS = re.compile(r"(?:[\d.,]|\d[\s'\u2019])\Z")


def _whole(text: str, start: int, end: int) -> bool:
    """Whether `text[start:end]` writes whole numbers: not the head or tail of a longer, grouped or decimal one."""
    head = text[end - 1].isdigit() and _CONTINUES.match(text, end) is not None
    tail = text[start].isdigit() and _LEADS.search(text, max(0, start - 2), start) is not None
    return not (head or tail)


def _sign_spaced(value: str, text: str) -> list[tuple[int, int]]:
    """The spans of `text` that write `value`'s one amount with its sign before or after it, with any whitespace (or
    none) between sign and digits (CLDR `currencySpacing`); not part of a longer or grouped number (head or tail), nor
    one end of a range."""
    amounts = list(_AMOUNT.finditer(value))
    if len(amounts) != 1:
        return []
    amount = amounts[0]
    before, after = value[: amount.start()].rstrip(), value[amount.end() :].lstrip()
    if not (before or after):
        return []
    prefix = rf"(?<![\d.,]){re.escape(before)}\s*" if before else ""
    suffix = rf"\s*{re.escape(after)}" if after else ""
    pattern = rf"{_NOT_AFTER_DASH}{prefix}{re.escape(amount.group())}{suffix}{_NOT_BEFORE_DASH}"
    return [match.span() for match in re.finditer(pattern, text) if _whole(text, *match.span())]


def _occurrences(value: str, text: str) -> list[int]:
    """Every index where `value` starts in `text`, overlapping occurrences included."""
    found: list[int] = []
    index = text.find(value)
    while index != -1:
        found.append(index)
        index = text.find(value, index + 1)
    return found
