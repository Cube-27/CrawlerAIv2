"""Identifier normalizer (SPEC-04 §4.4, ARCHITECTURE §9): the identifier as a string. The scheme is the field's declared
one, so the value does not repeat it.

Accepts a string, or a non-negative JSON integer read as its decimal digits (JSON-LD publishers write schema.org Text
values such as `gtin13` unquoted). Any other JSON value is `Invalid("not_a_string")`.

- `gtin`: ASCII digits only, GTIN-8/12/13/14, with a passing GS1 check digit. The value is the digits as given.
- `isbn`: ISBN-10 or ISBN-13 with a passing checksum; ISO 2108 hyphens and spaces and the "ISBN " prefix are dropped.
- `mpn`, `sku`, `custom`: opaque; trimmed, non-empty, at most 64 characters.
"""

import re
from collections.abc import Hashable

from pydantic import JsonValue

from crawlerai.normalize.base import Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType

# GS1 General Specifications §3.3.2: the GTIN formats are GTIN-8, GTIN-12, GTIN-13 and GTIN-14.
_GTIN_LENGTHS = frozenset({8, 12, 13, 14})
# ISO 2108: a printed ISBN is preceded by "ISBN", and its parts are separated by hyphens or spaces. A separator
# stands between two characters; `X`, the ISBN-10 check character for 10, comes only last. Digits are ASCII.
_ISBN_PREFIX = re.compile(r"\AISBN\s+")
_ISBN_BODY = re.compile(r"\d(?:[- ]?\d)*(?:[- ]?[Xx])?", re.ASCII)
# ISO 2108: an ISBN-13 is an EAN-13 (a GTIN-13) under the GS1 prefixes 978 and 979.
_ISBN13_PREFIXES = ("978", "979")
# SPEC-04 §4.4: the length bound of an opaque identifier, in characters.
_MAX_OPAQUE_LEN = 64


def normalize(raw: Raw, spec: FieldSpec, _ctx: Context) -> NormalizeResult:
    """Normalize an identifier field (SPEC-04 §4.4). Identifiers need no page evidence, so the context is unused."""
    if spec.type is not FieldType.IDENTIFIER or spec.scheme is None:
        raise TypeError(f"the identifier normalizer does not handle type {spec.type} without a scheme")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        raw = str(raw)
    if not isinstance(raw, str):
        return Invalid("not_a_string")
    if has_surrogate(raw):
        return Invalid("surrogate")
    # Surrounding white space is layout, not part of an identifier (Unicode White_Space, as `str.strip` reads it).
    trimmed = raw.strip()
    if not trimmed:
        return Invalid("empty")
    match spec.scheme:
        case "gtin":
            result = _gtin(trimmed)
        case "isbn":
            result = _isbn(trimmed)
        case _:
            result = _opaque(trimmed)
    if isinstance(result, str):
        return Ok(result)
    return result


def has_check_digit(spec: FieldSpec) -> bool:
    """Whether the field's scheme validates a value by its check digit (GS1 for gtin, ISO 2108 for isbn), so that an
    arbitrary string declines; an opaque scheme accepts any short string."""
    return spec.scheme in ("gtin", "isbn")


def _gtin(s: str) -> str | Invalid:
    # GS1 General Specifications §7.9: a GTIN is numeric, its digits 0 to 9 (ASCII; `str.isdigit` admits other Nd).
    if not (s.isascii() and s.isdigit()):
        return Invalid("not_digits")
    if len(s) not in _GTIN_LENGTHS:
        return Invalid("length")
    if not _gs1_check_digit_passes(s):
        return Invalid("check_digit")
    return s


def _isbn(s: str) -> str | Invalid:
    body = _ISBN_PREFIX.sub("", s, count=1)
    if not _ISBN_BODY.fullmatch(body):
        return Invalid("not_digits")
    value = body.replace("-", "").replace(" ", "").upper()
    if value.endswith("X") and len(value) != 10:
        return Invalid("not_digits")
    if len(value) == 13:
        if not value.startswith(_ISBN13_PREFIXES):
            return Invalid("prefix")
        return value if _gs1_check_digit_passes(value) else Invalid("check_digit")
    if len(value) == 10:
        return value if _isbn10_check_passes(value) else Invalid("check_digit")
    return Invalid("length")


def _opaque(s: str) -> str | Invalid:
    # SPEC-04 §4.4: an mpn, sku or custom identifier is the publisher's own string; only its length is bounded.
    if len(s) > _MAX_OPAQUE_LEN:
        return Invalid("too_long")
    return s


def _gs1_check_digit_passes(digits: str) -> bool:
    # GS1 General Specifications §7.9.1: from the right, the check digit has weight 1, then weights alternate 3, 1;
    # the weighted sum is a multiple of 10.
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(reversed(digits)))
    return total % 10 == 0


def _isbn10_check_passes(value: str) -> bool:
    # ISO 2108 (ISBN-10): weights 10 down to 1, `X` standing for 10; the weighted sum is a multiple of 11.
    total = sum((10 if c == "X" else int(c)) * w for c, w in zip(value, range(10, 0, -1), strict=True))
    return total % 11 == 0


def key(value: JsonValue, spec: FieldSpec) -> Hashable:
    """Equality as a key (SPEC-04 §4.5): exact, except that GTINs compare in the GS1 14-digit form (D-0287)."""
    gtin = _gtin14(value) if spec.scheme == "gtin" else None
    return raw_key(value) if gtin is None else ("gtin", gtin)


def _gtin14(digits: JsonValue) -> str | None:
    # GS1 General Specifications §3.3.2: GTIN-8, -12 and -13 are compared as GTIN-14 by padding with leading zeros.
    if not (isinstance(digits, str) and digits.isascii() and digits.isdigit() and len(digits) in _GTIN_LENGTHS):
        return None
    return digits.zfill(14)
