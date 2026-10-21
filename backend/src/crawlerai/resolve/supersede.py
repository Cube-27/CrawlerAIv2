"""Candidates of one text, long_text or image list field that another candidate of the same field supersedes
(resolution spec, requirement "Source precedence for text, url and image").

Source precedence ranks by kind, so a kind that states a field as a fragment would win over one that states it whole.
Two structural properties of the values say a candidate is a fragment of another, whatever its kind:
- long_text: a text that is a prefix of a longer candidate, or an ellipsis-cut prefix of it (Unicode U+2026 or
  `...`), is a truncation of it; an Open Graph description (the protocol defines it as a one-to-two sentence summary)
  is a summary, and so is a candidate of another kind stating the same text as it, so a longer description of a kind
  other than Open Graph supersedes it. A text that is another's with fewer line breaks, white space aside, is that
  text with its block structure flattened (paragraphs and `br` line breaks, HTML Standard §4.4.1, §4.5.27, dropped),
  so the rendition keeping more of its lines supersedes it. A text whose first line stands alone before the start of a
  longer candidate is that text with the heading that names its block kept as text (HTML Standard §4.3.6: a heading
  names its section, it is not its content; microdata reads an element's whole text content), a cut of it all the
  same, white space aside.
- text: a value that is another kind's value plus a separator (a dash or a vertical bar, between spaces) and more
  text, at either end, is that value with decoration; the other kind's undecorated value supersedes it.
- a list of images: a list whose files are all among a longer list's of another kind (`images.same_file`: a file or a
  rendition of it, and the other list names more files) is that list's representative part, whatever its kind: a
  structured `image` stating the main image only while the page's gallery or another source lists every view. The
  longer list supersedes it; it must name every file the shorter one does, so a list of other images never supersedes
  it. An Open Graph list needs only its first file named: `og:image` is an image to represent the object, and of a
  repeated property the first is preferred (Open Graph protocol, "Basic Metadata" and "Arrays"), so its further images
  (a site's default image beside the object's) are no views the longer list must hold.
"""

import unicodedata
from collections.abc import Sequence

from crawlerai.collect.base import Candidate
from crawlerai.normalize.base import Ok
from crawlerai.normalize.images import representative_part
from crawlerai.normalize.strings import collapse, is_cut_of, solid
from crawlerai.schemas.types import FieldSpec, FieldType

_OPEN_GRAPH = "og"
_BAR = "|"  # U+007C


def superseded(spec: FieldSpec, kept: Sequence[Candidate]) -> list[Candidate]:
    """The kept candidates that publish nothing while a candidate that supersedes them is kept."""
    if spec.type is FieldType.LONG_TEXT:
        return _by_length(kept)
    if spec.type is FieldType.TEXT:
        return _decorated(kept)
    if spec.item is not None and spec.item.type is FieldType.IMAGE_URL:
        return _representative(kept)
    return []


def _representative(kept: Sequence[Candidate]) -> list[Candidate]:
    files = [(c, _files(c)) for c in kept]
    return [
        c
        for c, own in files
        if own
        and any(
            o.source_kind != c.source_kind and representative_part(own, other, first_only=c.source_kind == _OPEN_GRAPH)
            for o, other in files
        )
    ]


def _files(c: Candidate) -> list[str]:
    """The images a list names, each file once (the normalizer keeps one rendition of a file)."""
    value = c.normalized.value if isinstance(c.normalized, Ok) else None
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _forms(kept: Sequence[Candidate]) -> list[tuple[Candidate, str]]:
    return [
        (c, collapse(c.normalized.value))
        for c in kept
        if isinstance(c.normalized, Ok) and isinstance(c.normalized.value, str)
    ]


def _by_length(kept: Sequence[Candidate]) -> list[Candidate]:
    forms = _forms(kept)
    summaries = {form for c, form in forms if c.source_kind == _OPEN_GRAPH}
    lines = _most_lines(kept)
    return [
        c
        for c, form in forms
        if any(_longer(c, form, other, longer, summaries) for other, longer in forms) or _flattened(c, lines)
    ]


def _longer(c: Candidate, form: str, other: Candidate, longer: str, summaries: set[str]) -> bool:
    if len(longer) <= len(form) or other is c:
        return False
    truncation = is_cut_of(form, longer, word_boundary=False)
    summary = form in summaries and other.source_kind != _OPEN_GRAPH
    return truncation or summary or _headed(c, longer)


def _headed(c: Candidate, longer: str) -> bool:
    """Whether `c`'s text is a first line, then the start of `longer`, white space aside (text content joins the
    paragraphs a rendered text separates)."""
    value = c.normalized.value if isinstance(c.normalized, Ok) else None
    _, line_break, rest = value.strip().partition("\n") if isinstance(value, str) else ("", "", "")
    return bool(line_break) and is_cut_of(rest, longer, word_boundary=False)


def _most_lines(kept: Sequence[Candidate]) -> dict[str, int]:
    """Of each text the kept candidates state, white space aside (`solid`), the most lines a candidate states it on."""
    lines: dict[str, int] = {}
    for c in kept:
        if isinstance(c.normalized, Ok) and isinstance(value := c.normalized.value, str):
            whole = solid(value)
            lines[whole] = max(lines.get(whole, 0), value.count("\n"))
    return lines


def _flattened(c: Candidate, lines: dict[str, int]) -> bool:
    """Whether another kept candidate states `c`'s text, white space aside, on more lines (`_most_lines`)."""
    value = c.normalized.value if isinstance(c.normalized, Ok) else None
    return isinstance(value, str) and lines[solid(value)] > value.count("\n")


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
