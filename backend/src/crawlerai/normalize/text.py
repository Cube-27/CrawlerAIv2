"""Text and long_text normalizer (normalization spec): a decoded, composed, whitespace-collapsed string.

Accepts a string, from the DOM, an LLM or a structured source (schema.org Text values are JSON strings). Any other
JSON value is `Invalid("not_a_string")`. A long_text value arrives already extracted as main content (trafilatura,
in the content layer); here it keeps its line breaks, with at most one blank line between paragraphs.
"""

import html
import re
from collections import Counter
from collections.abc import Hashable

from pydantic import JsonValue

from crawlerai.normalize.base import (
    Context,
    Invalid,
    NormalizeResult,
    Ok,
    Raw,
    decoded_references,
    has_surrogate,
    raw_key,
)
from crawlerai.normalize.strings import collapse, compose, fold_words
from crawlerai.schemas.types import FieldSpec, FieldType

# normalization spec and D-0017: length bounds after normalization, in characters.
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
    """Normalize a text or long_text field (normalization spec). Text needs no page evidence, so the context is
    unused."""
    if spec.type not in _MAX_LEN:
        raise TypeError(f"the text normalizer does not handle type {spec.type}")
    return _text(raw, spec.type)


def key(value: JsonValue, spec: FieldSpec) -> Hashable:
    """Equality as a key (normalization spec): equal after the text normalization, case-sensitive."""
    text = _text(value, spec.type)
    return ("text", text.value, text.reasons) if isinstance(text, Ok) else raw_key(value)


def word_overlap(a: JsonValue, b: JsonValue) -> float | None:
    """The Sørensen-Dice coefficient of two texts' word multisets (`strings.fold_words`: letters, marks and numbers;
    case, form and punctuation aside): 1 for the same words in any order, 0 for none in common; `None` unless both are
    strings with a word. Linear in the texts' length, so a 100k-character long_text is cheap to compare."""
    if not (isinstance(a, str) and isinstance(b, str)):
        return None
    words_a, words_b = Counter(fold_words(a)), Counter(fold_words(b))
    if not words_a or not words_b:
        return None
    return 2 * (words_a & words_b).total() / (words_a.total() + words_b.total())


def text_form(s: str) -> str:
    """The text normalization without its declines: entity-decoded, composed, whitespace-collapsed. The form in which
    page text and values are compared (the content layer's visibility index)."""
    return collapse(compose(html.unescape(s)))


def _text(raw: Raw, type_: FieldType) -> NormalizeResult:
    if not isinstance(raw, str):
        return Invalid("not_a_string")
    if has_surrogate(raw):
        return Invalid("surrogate")
    # HTML Standard, named and numeric character references, those escaped twice too; then the composed form.
    decoded = compose(decoded_references(html.unescape(raw)))
    value = _collapse_lines(decoded) if type_ is FieldType.LONG_TEXT else collapse(decoded)
    if not value:
        return Invalid("empty")
    if len(value) > _MAX_LEN[type_]:
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


def _collapse_lines(s: str) -> str:
    # Each line collapses as text does; a run of blank lines is one paragraph break (Unicode line boundaries, as
    # `str.splitlines` reads them).
    lines = [collapse(line) for line in s.splitlines()]
    paragraphs = "\n".join(lines)
    return _BLANK_LINE_RUN.sub("\n\n", paragraphs).strip("\n")
