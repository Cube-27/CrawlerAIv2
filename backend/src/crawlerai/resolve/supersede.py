"""Candidates of one text, long_text or image list field that another candidate of the same field supersedes
(resolution spec, requirement "Source precedence for text, url and image").

Source precedence ranks by kind, so a kind that states a field as a fragment would win over one that states it whole.
Two structural properties of the values say a candidate is a fragment of another, whatever its kind:
- long_text: a text that is a prefix of a longer candidate, or an ellipsis-cut prefix of it (Unicode U+2026 or
  `...`), is a truncation of it; an Open Graph description (the protocol defines it as a one-to-two sentence summary)
  is a summary, and so is a candidate of another kind stating the same text as it, so a longer description of a kind
  other than Open Graph supersedes it. A text that is another's with fewer line breaks, white space aside, is that
  text with its block structure flattened (paragraphs and `br` line breaks, HTML Standard §4.4.1, §4.5.27, dropped),
  so the rendition keeping more of its lines supersedes it.
- text: a value that is another kind's value plus a separator (a dash or a vertical bar, between spaces) and more
  text, at either end, is that value with decoration; the other kind's undecorated value supersedes it.
- a list of images: an Open Graph list (the protocol's `og:image` is an image to represent the object, as its
  description is a summary) whose files are all among a longer list's of another kind (`resource_key`) is that list's
  representative part; the longer list supersedes it.
"""

import re
import unicodedata
from collections.abc import Hashable, Sequence

from crawlerai.collect.base import Candidate
from crawlerai.normalize.base import Ok
from crawlerai.normalize.dispatch import resource_key
from crawlerai.schemas.types import FieldSpec, FieldType

_ELLIPSIS = re.compile(r"\s*(?:…|\.{3})$")
_OPEN_GRAPH = "og"
_BAR = "|"  # U+007C


def superseded(spec: FieldSpec, kept: Sequence[Candidate]) -> list[Candidate]:
    """The kept candidates that publish nothing while a candidate that supersedes them is kept."""
    if spec.type is FieldType.LONG_TEXT:
        return _by_length(kept)
    if spec.type is FieldType.TEXT:
        return _decorated(kept)
    if spec.item is not None and spec.item.type is FieldType.IMAGE_URL:
        return _representative(spec.item, kept)
    return []


def _representative(item: FieldSpec, kept: Sequence[Candidate]) -> list[Candidate]:
    files = [(c, _files(c, item)) for c in kept]
    return [
        c
        for c, own in files
        if c.source_kind == _OPEN_GRAPH
        and own
        and any(o.source_kind != _OPEN_GRAPH and own < other for o, other in files)
    ]


def _files(c: Candidate, item: FieldSpec) -> frozenset[Hashable]:
    """The files a list of images names (`resource_key`)."""
    value = c.normalized.value if isinstance(c.normalized, Ok) else None
    keys = [resource_key(v, item) for v in value] if isinstance(value, list) else []
    return frozenset(k for k in keys if k is not None)


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
    summaries = {form for c, form in forms if c.source_kind == _OPEN_GRAPH}
    return [
        c
        for c, form in forms
        if any(_longer(c, form, other, longer, summaries) for other, longer in forms) or _flattened(c, kept)
    ]


def _longer(c: Candidate, form: str, other: Candidate, longer: str, summaries: set[str]) -> bool:
    if len(longer) <= len(form) or other is c:
        return False
    cut = _ELLIPSIS.sub("", form)
    truncation = bool(cut) and longer.startswith(cut)
    summary = form in summaries and other.source_kind != _OPEN_GRAPH
    return truncation or summary


def _flattened(c: Candidate, kept: Sequence[Candidate]) -> bool:
    """Whether another kept candidate states `c`'s text, white space aside, on more lines."""
    value = c.normalized.value if isinstance(c.normalized, Ok) else None
    if not isinstance(value, str):
        return False
    solid = "".join(value.split())
    return any(
        isinstance(other := o.normalized.value if isinstance(o.normalized, Ok) else None, str)
        and other.count("\n") > value.count("\n")
        and "".join(other.split()) == solid
        for o in kept
    )


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
