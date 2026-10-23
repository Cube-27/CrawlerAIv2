"""Role C value checks: whether a grounded span is the field's own fact.

Grounding (`llm.grounding`) finds where the page states a claimed value; these checks read what the page says that
text is, from the page's own structure, never from words listed in code (C4):
- An identifier starts at the identifier. A label the claim kept before it, ended by a colon and white space (the
  label-value pair, `Ref.: X`), and the number sign before a number (Unicode U+0023, read "number": `#123`) are not
  part of it: the span moves past them. What remains lies within one text run, the text of one node: an identifier is
  one token the page states (schema.org `identifier`), and two runs side by side (`<span>1234</span> <span>WHT</span>`)
  are two values the page states apart, not one it states.
- A span the page labels as another field is not this field's. Its label is the text right before it on its line, ended
  by a colon ("ISBN: 1400215528" for a product id); for a number, also the words right after it on its line, which
  name what it counts ("293 Reviews" for a rating). A label names the fields whose label vocabulary holds its words
  (`collect.labels`: a field's name, schema.org property, description and drafted synonyms); one that names fields,
  none of them this one, rejects the span. A label that names no field, or this one among others, decides nothing.
- A number or count written as a percentage (a CLDR percent sign next to it, `100% (4)` of a review histogram) is a
  ratio of two quantities, not a count and not a value on the field's own scale: the span is not taken.
"""

import re
from collections.abc import Mapping, Sequence

from crawlerai.collect.labels import Words, words
from crawlerai.llm.grounding import GroundedSpan
from crawlerai.normalize.numbers import percentage
from crawlerai.schemas.types import FieldSpec, FieldType

# The fields each label's words name (`collect.labels.field_labels`).
Labels = Mapping[Words, Sequence[str]]

# A label's end: a colon and white space after it, or the fullwidth colon of East Asian text (U+FF1A), which needs
# none.
_LABEL_END = re.compile(":\\s+|\N{FULLWIDTH COLON}\\s*")
_COLONS = (":", "\N{FULLWIDTH COLON}")
_NUMBER_SIGN = re.compile(r"#\s*(?=\d)")  # before a number only: `#SKU-7` is the identifier
_BREAK = "\n"  # the cleaned text's line break (`content.text`)
# A label is a short phrase: the longest one looked for, in words.
_MAX_LABEL_WORDS = 6
_COUNTED = frozenset({FieldType.NUMBER, FieldType.COUNT})
# How far beside a span a percent sign is looked for, in characters: a CLDR sign, the white space and the bidi marks
# (Unicode Cf) some locales write around it.
_SIGN_REACH = 8


def checked(
    span: GroundedSpan, text: str, name: str, spec: FieldSpec, labels: Labels, breaks: frozenset[int]
) -> GroundedSpan | None:
    """The span of `text` that holds the field's value, or None when the page labels it as another field's, or it
    is an identifier two text runs state (module docstring). `breaks` are the offsets where two text runs meet."""
    kind = value_type(spec)
    if kind is FieldType.IDENTIFIER:
        found = unlabelled(span, text)
        if found is None or any(found.start < at < found.end for at in breaks):
            return None
        span = found
    named = [_label_before(text, span.start, labels)]
    if kind in _COUNTED:
        if _percentage(text, span):
            return None
        named.append(_label_after(text, span.end, labels))
    return None if any(fields and name not in fields for fields in named) else span


def value_type(spec: FieldSpec) -> FieldType | None:
    """The type of one claimed value of the field: a list's item type (each member is claimed and checked alone)."""
    return spec.item.type if spec.type is FieldType.LIST and spec.item is not None else spec.type


def unlabelled(span: GroundedSpan, text: str) -> GroundedSpan | None:
    """The span past a label and a number sign before its value; None when nothing follows them."""
    cut = 0
    for label_end in _LABEL_END.finditer(span.value):
        cut = label_end.end()
    if (sign := _NUMBER_SIGN.match(span.value, cut)) is not None:
        cut = sign.end()
    if cut == 0:
        return span
    if cut == len(span.value):
        return None
    start = span.start + cut
    return GroundedSpan(text[start : span.end], start, span.end)


def _percentage(text: str, span: GroundedSpan) -> bool:
    """Whether the span's number is written as a percentage, with the sign in the span or beside it on its line."""
    line_start = text.rfind(_BREAK, 0, span.start) + 1
    line_end = text.find(_BREAK, span.end)
    before = text[max(line_start, span.start - _SIGN_REACH) : span.start]
    after = text[span.end : min(len(text) if line_end == -1 else line_end, span.end + _SIGN_REACH)]
    return percentage(before, span.value, after)


def _label_before(text: str, start: int, labels: Labels) -> Sequence[str]:
    """The fields the label before `start` on its line names, its words' longest named ending; none without a colon
    ending it."""
    head = text[text.rfind(_BREAK, 0, start) + 1 : start].rstrip()
    if not head.endswith(_COLONS):
        return ()
    said = words(head[:-1])[-_MAX_LABEL_WORDS:]
    return next((labels[said[i:]] for i in range(len(said)) if said[i:] in labels), ())


def _label_after(text: str, end: int, labels: Labels) -> Sequence[str]:
    """The fields the words after `end` on its line name, their longest named beginning."""
    stop = text.find(_BREAK, end)
    said = words(text[end : len(text) if stop == -1 else stop])[:_MAX_LABEL_WORDS]
    return next((labels[said[:i]] for i in range(len(said), 0, -1) if said[:i] in labels), ())
