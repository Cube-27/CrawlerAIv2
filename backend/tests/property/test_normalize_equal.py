"""Type equality through the dispatcher: each type's rule, lists as multisets of item equality,
objects field by field. The resolver's agreement rule and eval compare values this
way."""

from hypothesis import strategies as st
from pydantic import JsonValue

from snowcrawl.normalize.dispatch import equal, equality_key
from snowcrawl.schemas.types import FieldSpec, FieldType

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


def _place(locality: str | None, region: str | None, country: str | None, remote: bool = False) -> JsonValue:
    return {"text": None, "locality": locality, "region": region, "country": country, "remote_flag": remote}


def test_an_equality_key_is_equal_exactly_when_the_values_are() -> None:
    near = ["a &amp;  b", "a & b", "Blue", "blue", "https://example.test/a", "HTTPS://Example.test:443/a", None, 3]

    for spec in (TEXT, LONG_TEXT, URL):
        for a in near:
            for b in near:
                assert (equality_key(a, spec) == equality_key(b, spec)) is equal(a, b, spec), (a, b)


def test_scalar_types_compare_by_their_own_rule() -> None:
    assert equal("a &amp;  b", "a & b", TEXT)
    assert not equal("a\n\nb", "a b", LONG_TEXT)
    assert not equal("Blue", "blue", TEXT)
    assert equal("HTTPS://Example.test:443/a/./b#top", "https://example.test/a/b", URL)
    assert not equal("https://example.test/a", "https://example.test/A", URL)
    assert equal({"amount": "1.5", "currency": "EUR"}, {"amount": "1.50", "currency": "EUR"}, MONEY)
    assert not equal({"amount": "1.5", "currency": "EUR"}, {"amount": "1.5", "currency": "USD"}, MONEY)
    # GS1: a GTIN compares in its 14-digit form, left-padded with zeros.
    assert equal("4006381333931", "04006381333931", _spec(FieldType.IDENTIFIER))
    assert not equal("0012", "12", _spec(FieldType.IDENTIFIER, scheme="sku"))


def test_range_compares_bounds_as_decimals_and_every_other_part() -> None:
    value: dict[str, JsonValue] = {"min": "1", "max": "2", "currency": "EUR", "unit": None, "period": "YEAR"}

    assert equal(value, {**value, "min": "1.0", "max": "2.00"}, RANGE)
    assert not equal(value, {**value, "period": "MONTH"}, RANGE)
    assert not equal(value, {**value, "currency": "USD"}, RANGE)


def test_location_compares_country_casefolded_locality_and_region_when_both_have_one() -> None:
    assert equal(_place("Springfield", None, "DE"), _place("SPRINGFIELD", None, "DE"), LOCATION)
    assert not equal(_place("Springfield", None, "DE"), _place("Springfield", None, "FR"), LOCATION)
    assert equal(_place("Springfield", "BY", "DE"), _place("Springfield", None, "DE"), LOCATION)
    assert not equal(_place("Springfield", "BY", "DE"), _place("Springfield", "BE", "DE"), LOCATION)
    assert not equal(_place(None, None, "DE", remote=True), _place(None, None, "DE"), LOCATION)


def test_list_items_match_one_to_one_even_when_item_equality_is_not_transitive() -> None:
    # A place without a region equals both places with one; matching it to the first would leave the second unmatched.
    a = [_place("Springfield", None, "DE"), _place("Springfield", "BY", "DE")]
    b = [_place("Springfield", "BY", "DE"), _place("Springfield", "BE", "DE")]

    assert equal(a, b, LOCATIONS) is True
    assert equal(b, a, LOCATIONS) is True
    assert equal([a[1], a[1]], b, LOCATIONS) is False


def test_objects_compare_field_by_field_and_a_non_transitive_type_has_no_key() -> None:
    spec = _spec(FieldType.OBJECT, fields={"name": {"type": "text", "description": "A name."}, "place": LOCATION})
    a: dict[str, JsonValue] = {"name": "A  b", "place": _place("Springfield", None, "DE")}

    assert equal(a, {"place": _place("springfield", "BY", "DE"), "name": "A b"}, spec)
    assert not equal(a, {"name": "A b"}, spec)
    assert not equal({**a, "zip": "1"}, a, spec)
    assert equality_key(a["place"], LOCATION) is None
    assert equality_key(a, spec) is None
