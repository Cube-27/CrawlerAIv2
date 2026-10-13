"""Grounding by alignment (SPEC-06 §4.3, INV-12, ARCHITECTURE §11): a role C value is kept only as a verbatim span of
the cleaned text, with offsets that hold it.

The model's offsets are a hint, not a fact (D-0024). A claim whose offsets hold its value is accepted as stated;
otherwise the value is searched for exactly, and the occurrence nearest the claimed `start` wins. A value the text
does not contain is dropped. There is no fuzzy, case- or whitespace-insensitive matching: the cleaned text's own
normalization (SPEC-05 §4.4) is the only one. Offsets count code points of the cleaned text, as Python `str` indices
do.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from crawlerai.collect.locator import format_locator


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


def align(claim: SpanClaim, cleaned_text: str) -> GroundedSpan | None:
    """The claim as a span of `cleaned_text`, or None when the text does not contain its value (ungrounded)."""
    value = claim.value
    if not value:
        return None  # an empty span holds no value
    if claim.start >= 0 and claim.end <= len(cleaned_text) and cleaned_text[claim.start : claim.end] == value:
        return GroundedSpan(value, claim.start, claim.end)
    occurrences = _occurrences(value, cleaned_text)
    if not occurrences:
        return None
    # Nearest to the claimed start; of two equally near, the earlier, so the choice is deterministic (INV-10).
    start = min(occurrences, key=lambda i: (abs(i - claim.start), i))
    return GroundedSpan(value, start, start + len(value))


def _occurrences(value: str, text: str) -> list[int]:
    """Every index where `value` starts in `text`, overlapping occurrences included."""
    found: list[int] = []
    index = text.find(value)
    while index != -1:
        found.append(index)
        index = text.find(value, index + 1)
    return found
