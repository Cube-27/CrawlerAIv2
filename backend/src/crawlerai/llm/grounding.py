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

A claim of a link or an image names the id the text gave it (`llm.marked`): it is kept only when that id marks an
element of the kind the field takes on the page, and its value is the element's `href` or `src` as the DOM states it,
never text of the model's.
"""

import re
from collections.abc import Mapping
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


def align(claim: SpanClaim, cleaned_text: str, *, money: bool = False) -> GroundedSpan | None:
    """The claim as a span of `cleaned_text`, or None when the text does not contain its value (ungrounded). A `money`
    claim is a whole number of the text, and one the text does not contain verbatim is found with any spacing between
    its currency sign and its digits."""
    value = claim.value
    if not value:
        return None  # an empty span holds no value

    def holds(start: int, end: int) -> bool:
        return not money or _whole(cleaned_text, start, end)

    # Both ends must be offsets into the text: a negative end would slice counting from the end.
    if (
        0 <= claim.start < claim.end <= len(cleaned_text)
        and cleaned_text[claim.start : claim.end] == value
        and holds(claim.start, claim.end)
    ):
        return GroundedSpan(value, claim.start, claim.end)
    spans = [(i, i + len(value)) for i in _occurrences(value, cleaned_text) if holds(i, i + len(value))]
    if not spans and money:
        spans = _sign_spaced(value, cleaned_text)
    if not spans:
        return None
    # Nearest to the claimed start; of two equally near, the earlier, so the choice is deterministic (INV-10).
    start, end = min(spans, key=lambda span: (abs(span[0] - claim.start), span[0]))
    return GroundedSpan(cleaned_text[start:end], start, end)


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
