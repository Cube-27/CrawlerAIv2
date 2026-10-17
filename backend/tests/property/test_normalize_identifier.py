"""The identifier normalizer (SPEC-04 §4.4, ARCHITECTURE §9): GS1 check digits for GTIN-8/12/13/14, ISO 2108
checksums for ISBN-10/13, opaque `mpn`/`sku`/`custom` values, and declines on failed checksums and empty input
(INV-06)."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import identifier
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, IdentifierScheme

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
SCHEMES: tuple[IdentifierScheme, ...] = ("gtin", "isbn", "mpn", "sku", "custom")
OPAQUE: tuple[IdentifierScheme, ...] = ("mpn", "sku", "custom")
GTIN_LENGTHS = (8, 12, 13, 14)

_whitespace = st.text(alphabet=st.characters(categories=["Zs", "Cc"]).filter(str.isspace), max_size=8)


def _spec(scheme: IdentifierScheme) -> FieldSpec:
    return FieldSpec(type=FieldType.IDENTIFIER, scheme=scheme)


def _gs1_check_digit(body: str) -> str:
    # GS1 General Specifications §7.9.1, written independently of the module: weights 3, 1, 3, ... from the right.
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str(-total % 10)


def _isbn10_check_digit(body: str) -> str:
    # ISO 2108: weights 10 down to 2 over the nine body digits; the sum with the check is divisible by 11.
    check = -sum(int(d) * w for d, w in zip(body, range(10, 1, -1), strict=True)) % 11
    return "X" if check == 10 else str(check)


def _digits(n: int) -> st.SearchStrategy[str]:
    return st.text(alphabet="0123456789", min_size=n, max_size=n)


_gtins = st.sampled_from(GTIN_LENGTHS).flatmap(lambda n: _digits(n - 1)).map(lambda b: b + _gs1_check_digit(b))
_isbn13s = st.tuples(st.sampled_from(["978", "979"]), _digits(9)).map("".join).map(lambda b: b + _gs1_check_digit(b))
_isbn10s = _digits(9).map(lambda b: b + _isbn10_check_digit(b))


def _perturb(value: str, at: int, delta: int) -> str:
    # One character replaced by another: the GS1 mod-10 check (weights 1 and 3, both coprime with 10) and the
    # ISBN-10 mod-11 check (11 is prime) both detect every single-character error.
    at %= len(value)
    old = value[at]
    new = str(delta) if old == "X" else str((int(old) + delta) % 10)
    return value[:at] + new + value[at + 1 :]


@given(st.sampled_from(SCHEMES), _whitespace)
def test_empty_or_whitespace_input_is_invalid(scheme: IdentifierScheme, raw: str) -> None:
    assert identifier.normalize(raw, _spec(scheme), CTX) == Invalid("empty")


@given(_gtins, st.integers(min_value=0), st.integers(min_value=1, max_value=9))
def test_a_gtin_is_ok_with_a_correct_check_digit_and_invalid_with_one_digit_changed(
    value: str, at: int, delta: int
) -> None:
    assert identifier.normalize(value, _spec("gtin"), CTX) == Ok(value)
    assert identifier.normalize(_perturb(value, at, delta), _spec("gtin"), CTX) == Invalid("check_digit")


@pytest.mark.parametrize("raw", ["4006381333931", "96385074", "036000291452", "10012345678902"])
def test_known_valid_gtins_of_each_length_are_ok(raw: str) -> None:
    # Check digits computed by hand from GS1 General Specifications §7.9.1.
    assert identifier.normalize(raw, _spec("gtin"), CTX) == Ok(raw)


@given(st.integers(min_value=1, max_value=20).filter(lambda n: n not in GTIN_LENGTHS).flatmap(_digits))
def test_a_gtin_of_another_length_is_invalid(raw: str) -> None:
    assert identifier.normalize(raw, _spec("gtin"), CTX) == Invalid("length")


@pytest.mark.parametrize(
    "raw",
    # Unicode digits that are not ASCII (Nd: U+0663 ARABIC-INDIC THREE, U+FF14 FULLWIDTH FOUR) are not GS1 digits.
    ["4006381 333931", "4006-381333931", f"40063813339{chr(0x663)}1", f"{chr(0xFF14)}006381333931", "+4006381333931"],
)
def test_a_gtin_with_anything_but_ascii_digits_is_invalid(raw: str) -> None:
    assert identifier.normalize(raw, _spec("gtin"), CTX) == Invalid("not_digits")


@given(st.one_of(_isbn13s, _isbn10s), st.integers(min_value=0), st.integers(min_value=1, max_value=9))
def test_an_isbn_is_ok_with_a_correct_checksum_and_invalid_with_one_digit_changed(
    value: str, at: int, delta: int
) -> None:
    changed = _perturb(value, at, delta)
    # A change inside an ISBN-13's 978/979 prefix leaves the ISBN range before it breaks the checksum.
    reason = "prefix" if len(changed) == 13 and not changed.startswith(("978", "979")) else "check_digit"

    assert identifier.normalize(value, _spec("isbn"), CTX) == Ok(value)
    assert identifier.normalize(changed, _spec("isbn"), CTX) == Invalid(reason)


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("978-3-16-148410-0", "9783161484100"),
        ("ISBN 978 3 16 148410 0", "9783161484100"),
        ("ISBN 0-306-40615-2", "0306406152"),
        ("0-8044-2957-x", "080442957X"),
    ],
)
def test_isbn_hyphens_spaces_and_prefix_are_dropped(raw: str, value: str) -> None:
    # ISO 2108: the parts of an ISBN are separated by hyphens or spaces, and a printed ISBN is preceded by "ISBN".
    assert identifier.normalize(raw, _spec("isbn"), CTX) == Ok(value)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("4006381333931", "prefix"),  # an EAN-13 outside the 978/979 ISBN prefixes
        ("97831614841", "length"),
        ("978-3-16-148410-", "not_digits"),  # a separator stands between two characters
        ("12345678X0", "not_digits"),  # X only as the ISBN-10 check character
        ("ISBN", "not_digits"),
        ("978--3-16-148410-0", "not_digits"),
    ],
)
def test_malformed_isbns_are_invalid(raw: str, reason: str) -> None:
    assert identifier.normalize(raw, _spec("isbn"), CTX) == Invalid(reason)


_opaque_values = st.text(alphabet=st.characters(exclude_categories=["Cs"]), min_size=1, max_size=64).filter(
    lambda s: s == s.strip() and s != ""
)


@given(st.sampled_from(OPAQUE), _opaque_values, _whitespace)
def test_an_opaque_identifier_is_kept_as_given_but_trimmed(scheme: IdentifierScheme, value: str, pad: str) -> None:
    assert identifier.normalize(f"{pad}{value}{pad}", _spec(scheme), CTX) == Ok(value)


@pytest.mark.parametrize("scheme", OPAQUE)
def test_an_opaque_identifier_is_at_most_64_characters(scheme: IdentifierScheme) -> None:
    assert identifier.normalize("a" * 64, _spec(scheme), CTX) == Ok("a" * 64)
    assert identifier.normalize("a" * 65, _spec(scheme), CTX) == Invalid("too_long")


@given(st.sampled_from(SCHEMES), st.characters(categories=["Cs"]))
def test_input_with_a_lone_surrogate_is_invalid(scheme: IdentifierScheme, surrogate: str) -> None:
    assert identifier.normalize(f"97{surrogate}8", _spec(scheme), CTX) == Invalid("surrogate")


@pytest.mark.parametrize(("scheme", "raw", "value"), [("gtin", 4006381333931, "4006381333931"), ("sku", 1234, "1234")])
def test_a_json_integer_is_read_as_its_decimal_digits(scheme: IdentifierScheme, raw: int, value: str) -> None:
    # JSON-LD carries schema.org Text values such as `gtin13` as numbers when the publisher wrote them unquoted.
    assert identifier.normalize(raw, _spec(scheme), CTX) == Ok(value)


@pytest.mark.parametrize("raw", [None, True, 1.5, -5, ["4006381333931"], {"@value": "4006381333931"}])
def test_other_json_values_are_invalid(raw: JsonValue) -> None:
    assert identifier.normalize(raw, _spec("sku"), CTX) == Invalid("not_a_string")


def test_a_spec_of_another_type_is_a_programming_error() -> None:
    spec = FieldSpec(type=FieldType.TEXT)

    with pytest.raises(TypeError):
        identifier.normalize("4006381333931", spec, CTX)


def test_the_dispatcher_sends_identifiers_to_the_identifier_module() -> None:
    assert normalize("4006381333931", _spec("gtin"), CTX) == Ok("4006381333931")
