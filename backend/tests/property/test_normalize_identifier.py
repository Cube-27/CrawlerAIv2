"""The identifier normalizer: GS1 check digits for GTIN-8/12/13/14, ISO 2108
checksums for ISBN-10/13, opaque `mpn`/`sku`/`custom` values, and declines on failed checksums and empty input."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from snowcrawl.normalize import identifier
from snowcrawl.normalize.base import Context, Invalid, Ok
from snowcrawl.schemas.types import FieldSpec, FieldType, IdentifierScheme

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
SCHEMES: tuple[IdentifierScheme, ...] = ("gtin", "isbn", "mpn", "sku", "custom")

_whitespace = st.text(alphabet=st.characters(categories=["Zs", "Cc"]).filter(str.isspace), max_size=8)


def _spec(scheme: IdentifierScheme) -> FieldSpec:
    return FieldSpec(type=FieldType.IDENTIFIER, scheme=scheme)


def _gs1_check_digit(body: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str(-total % 10)


def _digits(n: int) -> st.SearchStrategy[str]:
    return st.text(alphabet="0123456789", min_size=n, max_size=n)


_gtins = st.sampled_from([8, 12, 13, 14]).flatmap(lambda n: _digits(n - 1)).map(lambda b: b + _gs1_check_digit(b))


@given(st.sampled_from(SCHEMES), _whitespace)
def test_empty_or_whitespace_input_is_invalid(scheme: IdentifierScheme, raw: str) -> None:
    assert identifier.normalize(raw, _spec(scheme), CTX) == Invalid("empty")


@given(_gtins, st.integers(min_value=0), st.integers(min_value=1, max_value=9))
def test_a_gtin_is_ok_with_a_correct_check_digit_and_invalid_with_one_digit_changed(
    value: str, at: int, delta: int
) -> None:
    at %= len(value)
    changed = value[:at] + str((int(value[at]) + delta) % 10) + value[at + 1 :]

    assert identifier.normalize(value, _spec("gtin"), CTX) == Ok(value)
    assert identifier.normalize(changed, _spec("gtin"), CTX) == Invalid("check_digit")


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("12345", "length"),
        ("4006381 333931", "not_digits"),
        (f"{chr(0xFF14)}006381333931", "not_digits"),  # a fullwidth digit is no GS1 digit
    ],
)
def test_a_malformed_gtin_is_invalid(raw: str, reason: str) -> None:
    assert identifier.normalize(raw, _spec("gtin"), CTX) == Invalid(reason)


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("978-3-16-148410-0", "9783161484100"),
        ("ISBN 0-306-40615-2", "0306406152"),
        ("0-8044-2957-x", "080442957X"),
    ],
)
def test_isbn_separators_and_prefix_are_dropped_and_the_checksum_holds(raw: str, value: str) -> None:
    assert identifier.normalize(raw, _spec("isbn"), CTX) == Ok(value)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("4006381333931", "prefix"),  # an EAN-13 outside the 978/979 ISBN prefixes
        ("9783161484101", "check_digit"),
        ("0306406153", "check_digit"),
        ("97831614841", "length"),
        ("12345678X0", "not_digits"),
    ],
)
def test_malformed_isbns_are_invalid(raw: str, reason: str) -> None:
    assert identifier.normalize(raw, _spec("isbn"), CTX) == Invalid(reason)
