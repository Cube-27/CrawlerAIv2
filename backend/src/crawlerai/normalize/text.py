"""Text and long_text normalizer (SPEC-04 §4.4, ARCHITECTURE §9): a decoded, composed, whitespace-collapsed string.

Accepts a string, from the DOM, an LLM or a structured source (schema.org Text values are JSON strings). Any other
JSON value is `Invalid("not_a_string")`. A long_text value arrives already extracted as main content (trafilatura,
in the content layer); here it keeps its line breaks, with at most one blank line between paragraphs.

`equal` is a stub until SPEC-04 PR 9 implements §4.5.
"""

import html
import re
import unicodedata

from pydantic import JsonValue

from crawlerai.normalize.base import Context, Invalid, NormalizeResult, Ok, Raw
from crawlerai.schemas.types import FieldSpec, FieldType

# SPEC-04 §4.4 and D-0017: length bounds after normalization, in characters.
_MAX_LEN = {FieldType.TEXT: 512, FieldType.LONG_TEXT: 100_000}
# Structural: an unrendered template placeholder means the page shows its template, not a value. Covered syntaxes:
# `{{ … }}` (Mustache, Handlebars, Jinja, Angular), `${ … }` (JavaScript template literals, shell parameter
# expansion), and printf conversions without flags (C `printf` `%s`/`%d`, POSIX positional `%1$s`, Python `%(name)s`).
# A printf conversion must end at a word boundary, so "50%sale" is text. The delimited syntaxes are found with
# `str.find`, which stays linear on a 100k-character long_text with many unclosed openers.
_DELIMITED_PLACEHOLDERS = (("{{", "}}"), ("${", "}"))
_PRINTF_PLACEHOLDER = re.compile(r"%(?:\(\w+\)|\d+\$)?[sd]\b")
_BLANK_LINE_RUN = re.compile(r"\n{3,}")


def normalize(raw: Raw, spec: FieldSpec, _ctx: Context) -> NormalizeResult:
    """Normalize a text or long_text field (SPEC-04 §4.4). Text needs no page evidence, so the context is unused."""
    if spec.type not in _MAX_LEN:
        raise TypeError(f"the text normalizer does not handle type {spec.type}")
    if not isinstance(raw, str):
        return Invalid("not_a_string")
    # HTML Standard, named and numeric character references; then Unicode NFC (UAX #15), so one text has one form.
    decoded = unicodedata.normalize("NFC", html.unescape(raw))
    value = _collapse_lines(decoded) if spec.type is FieldType.LONG_TEXT else _collapse(decoded)
    if not value:
        return Invalid("empty")
    if len(value) > _MAX_LEN[spec.type]:
        return Invalid("too_long")
    if _has_placeholder(value):
        return Invalid("template_placeholder")
    return Ok(value)


def _has_placeholder(value: str) -> bool:
    for opener, closer in _DELIMITED_PLACEHOLDERS:
        # If the first opener has no closer after it, no later opener has one either.
        start = value.find(opener)
        if start >= 0 and value.find(closer, start + len(opener)) >= 0:
            return True
    return _PRINTF_PLACEHOLDER.search(value) is not None


def _collapse(s: str) -> str:
    # Unicode White_Space (what `str.split` splits on) collapses to one space; the ends are trimmed.
    return " ".join(s.split())


def _collapse_lines(s: str) -> str:
    # Each line collapses as text does; a run of blank lines is one paragraph break (Unicode line boundaries, as
    # `str.splitlines` reads them).
    lines = [_collapse(line) for line in s.splitlines()]
    paragraphs = "\n".join(lines)
    return _BLANK_LINE_RUN.sub("\n\n", paragraphs).strip("\n")


def equal(a: JsonValue, b: JsonValue) -> bool:
    """Stub until SPEC-04 PR 9 implements §4.5 (equal after text normalization).

    Exact equality of two normalized values, which labels and engine output both hold (SPEC-03 §4.3).
    """
    return a == b
