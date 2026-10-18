"""Candidates of one text or long_text field that another candidate of the same field supersedes
(resolution spec, requirement "Source precedence for text, url and image").

Source precedence ranks by kind, so a kind that states a field as a fragment would win over one that states it whole.
Two structural properties of the values say a candidate is a fragment of another, whatever its kind:
- long_text: a text that is a prefix of a longer candidate, or an ellipsis-cut prefix of it (Unicode U+2026 or
  `...`), is a truncation of it; an Open Graph description (the protocol defines it as a one-to-two sentence summary)
  is a summary, so a longer description of another kind supersedes it.
- text: a value that is another kind's value plus a separator (a dash or a vertical bar, between spaces) and more
  text, at either end, is that value with decoration; the other kind's undecorated value supersedes it.
"""

import re
import unicodedata
from collections.abc import Sequence

from crawlerai.collect.base import Candidate
from crawlerai.normalize.base import Ok
from crawlerai.schemas.types import FieldType

_ELLIPSIS = re.compile(r"\s*(?:…|\.{3})$")
_OPEN_GRAPH = "og"
_BAR = "|"  # U+007C


def superseded(type_: FieldType, kept: Sequence[Candidate]) -> list[Candidate]:
    """The kept candidates that publish nothing while a candidate that supersedes them is kept."""
    if type_ is FieldType.LONG_TEXT:
        return _by_length(kept)
    if type_ is FieldType.TEXT:
        return _decorated(kept)
    return []


def _forms(kept: Sequence[Candidate]) -> list[tuple[Candidate, str]]:
    return [
        (c, _collapsed(c.normalized.value))
        for c in kept
        if isinstance(c.normalized, Ok) and isinstance(c.normalized.value, str)
    ]


def _collapsed(value: str) -> str:
    # A normalized value is already entity-decoded and composed; only whitespace differs between renditions.
    return " ".join(value.split())


def _by_length(kept: Sequence[Candidate]) -> list[Candidate]:
    forms = _forms(kept)
    return [c for c, form in forms if any(_longer(c, form, other, longer) for other, longer in forms)]


def _longer(c: Candidate, form: str, other: Candidate, longer: str) -> bool:
    if len(longer) <= len(form) or other is c:
        return False
    cut = _ELLIPSIS.sub("", form)
    truncation = bool(cut) and longer.startswith(cut)
    summary = c.source_kind == _OPEN_GRAPH and other.source_kind != _OPEN_GRAPH
    return truncation or summary


def _decorated(kept: Sequence[Candidate]) -> list[Candidate]:
    forms = _forms(kept)
    return [
        c for c, form in forms if any(o.source_kind != c.source_kind and _decorates(form, clean) for o, clean in forms)
    ]


def _decorates(form: str, clean: str) -> bool:
    """Whether `form` is `clean` and ` <separator> ` and more text, in either order."""
    if not clean or len(form) <= len(clean) + 3:
        return False
    if form.startswith(clean) and _spaced_separator(form[len(clean) :][:3]):
        return True
    return form.endswith(clean) and _spaced_separator(form[: -len(clean)][-3:])


def _spaced_separator(three: str) -> bool:
    return (
        len(three) == 3
        and three[0] == " "
        and three[2] == " "
        and (three[1] == _BAR or unicodedata.category(three[1]) == "Pd")
    )
