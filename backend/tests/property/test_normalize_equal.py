"""Type equality (SPEC-04 §4.5) through the dispatcher: each type's rule, lists as multisets of item equality,
objects field by field. The resolver's agreement rule (SPEC-05) and eval (SPEC-03) compare values this way."""

from decimal import Decimal
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize.dispatch import equal
from crawlerai.schemas.types import FieldSpec, FieldType

_PARAMETERS: dict[FieldType, dict[str, object]] = {
    FieldType.ENUM: {"vocab": "schema:ItemAvailability"},
    FieldType.IDENTIFIER: {"scheme": "gtin"},
    FieldType.LIST: {"item": {"type": "location"}},
    FieldType.OBJECT: {"fields": {"name": {"type": "text", "description": "A name."}}},
}


def _spec(type_: FieldType, **parameters: object) -> FieldSpec:
    return FieldSpec.model_validate({"type": type_, **_PARAMETERS.get(type_, {}), **parameters})


TEXT, LONG_TEXT, URL = _spec(FieldType.TEXT), _spec(FieldType.LONG_TEXT), _spec(FieldType.URL)
MONEY, RANGE, LOCATION = _spec(FieldType.MONEY), _spec(FieldType.RANGE), _spec(FieldType.LOCATION)
LOCATIONS = _spec(FieldType.LIST)

_json: st.SearchStrategy[JsonValue] = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=4), children, max_size=4),
    max_leaves=12,
)
_amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal(10**9), places=2)


def _place(locality: str | None, region: str | None, country: str | None, remote: bool = False) -> JsonValue:
    return {"locality": locality, "region": region, "country": country, "remote_flag": remote}


@given(st.sampled_from(list(FieldType)), _json, _json)
def test_every_type_is_reflexive_and_symmetric(type_: FieldType, a: JsonValue, b: JsonValue) -> None:
    spec = _spec(type_)

    assert equal(a, a, spec) is True
    assert equal(a, b, spec) is equal(b, a, spec)


@given(_amounts, st.integers(min_value=0, max_value=4))
def test_money_amounts_compare_as_decimals(amount: Decimal, zeros: int) -> None:
    written = format(amount, "f") + ("0" * zeros if "." in format(amount, "f") else "")

    assert equal({"amount": format(amount, "f"), "currency": "EUR"}, {"amount": written, "currency": "EUR"}, MONEY)
    assert not equal({"amount": written, "currency": "EUR"}, {"amount": written, "currency": "USD"}, MONEY)
    assert not equal({"amount": "1.00", "currency": "EUR"}, {"amount": "1.001", "currency": "EUR"}, MONEY)


def test_text_compares_after_the_text_normalization_case_sensitively() -> None:
    assert equal("a &amp;  b", "a & b", TEXT)
    assert equal("a\n\nb", "a b", TEXT)
    assert not equal("a\n\nb", "a b", LONG_TEXT)
    assert not equal("Blue", "blue", TEXT)


def test_url_compares_after_canonicalization() -> None:
    assert equal("HTTPS://Example.test:443/a/./b#top", "https://example.test/a/b", URL)
    assert equal("http://example.test/%7Ex", "http://example.test/~x", _spec(FieldType.IMAGE_URL))
    assert not equal("https://example.test/a", "https://example.test/A", URL)


@given(st.text(max_size=10), st.text(max_size=10))
def test_enum_and_date_compare_exactly(a: str, b: str) -> None:
    for spec in (_spec(FieldType.ENUM), _spec(FieldType.DATE), _spec(FieldType.DATETIME)):
        assert equal(a, b, spec) is (a == b)


@given(st.from_regex(r"[0-9]{7}|[0-9]{11}|[0-9]{12}", fullmatch=True))
def test_a_gtin_equals_its_zero_padded_form(digits: str) -> None:
    gtin = _spec(FieldType.IDENTIFIER)
    # GS1 General Specifications §3.3.2: a GTIN compares in its 14-digit form, left-padded with zeros.
    value = digits + _gs1_check_digit(digits)

    assert equal({"scheme": "gtin", "value": value}, {"scheme": "gtin", "value": value.zfill(14)}, gtin)
    other = value[:-1] + str((int(value[-1]) + 1) % 10)
    assert not equal({"scheme": "gtin", "value": value}, {"scheme": "gtin", "value": other.zfill(14)}, gtin)


def test_other_identifiers_compare_exactly() -> None:
    sku = _spec(FieldType.IDENTIFIER, scheme="sku")

    assert not equal({"scheme": "sku", "value": "0012"}, {"scheme": "sku", "value": "12"}, sku)
    assert not equal({"scheme": "sku", "value": "ab"}, {"scheme": "sku", "value": "AB"}, sku)
    assert not equal({"scheme": "sku", "value": "12"}, {"scheme": "mpn", "value": "12"}, sku)


def test_location_compares_country_and_casefolded_locality() -> None:
    assert equal(_place("Springfield", None, "DE"), _place("SPRINGFIELD", None, "DE"), LOCATION)
    assert not equal(_place("Springfield", None, "DE"), _place("Springfield", None, "FR"), LOCATION)
    assert not equal(_place("Springfield", None, "DE"), _place(None, None, "DE"), LOCATION)


def test_location_region_counts_only_when_both_have_one() -> None:
    assert equal(_place("Springfield", "BY", "DE"), _place("Springfield", None, "DE"), LOCATION)
    assert not equal(_place("Springfield", "BY", "DE"), _place("Springfield", "BE", "DE"), LOCATION)


def test_location_remote_flag_counts() -> None:
    assert not equal(_place(None, None, "DE", remote=True), _place(None, None, "DE"), LOCATION)


@given(st.lists(_amounts, min_size=2, max_size=2).map(sorted))
def test_range_compares_bounds_as_decimals_and_every_other_part(bounds: list[Decimal]) -> None:
    lo, hi = (format(b, "f") for b in bounds)
    value: dict[str, JsonValue] = {"min": lo, "max": hi, "currency": "EUR", "unit": None, "period": "YEAR"}

    assert equal(value, {**value, "min": lo + "0", "max": hi + "00"}, RANGE)
    assert not equal(value, {**value, "period": "MONTH"}, RANGE)
    assert not equal(value, {**value, "currency": "USD"}, RANGE)
    assert not equal(value, {**value, "currency": None, "unit": "EUR"}, RANGE)


@given(st.lists(st.text(max_size=3), max_size=6), st.randoms())
def test_lists_compare_as_multisets(items: list[JsonValue], rnd: Any) -> None:
    shuffled = list(items)
    rnd.shuffle(shuffled)
    texts = _spec(FieldType.LIST, item={"type": "text"})

    assert equal(items, shuffled, texts) is True
    if items:
        assert equal(items, [*items, items[0]], texts) is False
        assert equal(items, items[1:], texts) is False


def test_list_items_match_one_to_one_even_when_item_equality_is_not_transitive() -> None:
    # A place without a region equals both places with one; matching it to the first would leave the second unmatched.
    a = [_place("Springfield", None, "DE"), _place("Springfield", "BY", "DE")]
    b = [_place("Springfield", "BY", "DE"), _place("Springfield", "BE", "DE")]

    assert equal(a, b, LOCATIONS) is True
    assert equal(b, a, LOCATIONS) is True
    assert equal([a[1], a[1]], b, LOCATIONS) is False


def test_objects_compare_field_by_field() -> None:
    spec = _spec(FieldType.OBJECT, fields={"name": {"type": "text", "description": "A name."}, "place": LOCATION})
    a: dict[str, JsonValue] = {"name": "A  b", "place": _place("Springfield", None, "DE")}

    assert equal(a, {"place": _place("springfield", "BY", "DE"), "name": "A b"}, spec)
    assert not equal(a, {"name": "A b"}, spec)
    assert not equal({**a, "zip": "1"}, a, spec)


def test_container_types_refuse_other_json_kinds() -> None:
    assert equal("a", "a", LOCATIONS) is True  # reflexive, as every equality
    assert equal("a", ["a"], _spec(FieldType.LIST, item={"type": "text"})) is False
    assert equal(["a"], {"name": "a"}, _spec(FieldType.OBJECT)) is False


def _gs1_check_digit(digits: str) -> str:
    # GS1 General Specifications §7.9.1, for the digits before the check digit (weight 3 on the rightmost).
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return str(-total % 10)
