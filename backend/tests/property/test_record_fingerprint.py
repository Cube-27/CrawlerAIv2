"""Record fingerprints and changed fields (SPEC-11 §4.4): the fingerprint is a pure function of the required
fields' and required groups' published values, and `changed_fields` names exactly the fields whose published value
differs, a field that became published or stopped publishing included."""

import json
import string

from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.recurring.record_fp import changed_fields, record_fingerprint
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDocument

_TEXT = FieldSpec(type=FieldType.TEXT, description="d")
_REQUIRED = FieldSpec(type=FieldType.TEXT, description="d", required=True)
SCHEMA = SchemaDocument(
    name="synthetic_product",
    version=1,
    page_kind="detail",
    required_groups=[["sku", "gtin"]],
    fields={"title": _REQUIRED, "price": _REQUIRED, "sku": _TEXT, "gtin": _TEXT, "colour": _TEXT, "notes": _TEXT},
)
FINGERPRINTED = ("title", "price", "sku", "gtin")
OPTIONAL = ("colour", "notes")

_scalars = st.none() | st.booleans() | st.integers() | st.text(alphabet=string.printable, max_size=8)
_values: st.SearchStrategy[JsonValue] = st.recursive(
    _scalars,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=4), inner, max_size=3),
    max_leaves=5,
)
# A record's `data`: the published fields only (ARCHITECTURE §6), each with its value.
_data = st.dictionaries(st.sampled_from(sorted(SCHEMA.fields)), _values)


def _canonical(value: JsonValue) -> str:
    # Values are compared as JSON: `true` and `1` are different values, though Python finds them equal.
    return json.dumps(value, sort_keys=True)


@given(_data)
def test_the_fingerprint_is_a_sha256_hex_digest_independent_of_key_order(data: dict[str, JsonValue]) -> None:
    reordered = dict(reversed(list(data.items())))

    fingerprint = record_fingerprint(data, SCHEMA)

    assert fingerprint == record_fingerprint(reordered, SCHEMA)
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set(string.hexdigits.lower())


@given(_data, st.sampled_from(OPTIONAL), _values)
def test_an_optional_field_outside_every_required_group_leaves_the_fingerprint_unchanged(
    data: dict[str, JsonValue], name: str, value: JsonValue
) -> None:
    without = {key: item for key, item in data.items() if key != name}

    assert record_fingerprint({**data, name: value}, SCHEMA) == record_fingerprint(without, SCHEMA)


@given(_data, st.sampled_from(FINGERPRINTED), _values, _values)
def test_a_required_or_group_field_with_another_value_changes_the_fingerprint(
    data: dict[str, JsonValue], name: str, before: JsonValue, after: JsonValue
) -> None:
    assume(_canonical(before) != _canonical(after))

    assert record_fingerprint({**data, name: before}, SCHEMA) != record_fingerprint({**data, name: after}, SCHEMA)


@given(_data, st.sampled_from(FINGERPRINTED))
def test_a_published_null_differs_from_a_field_that_did_not_publish(data: dict[str, JsonValue], name: str) -> None:
    without = {key: item for key, item in data.items() if key != name}

    assert record_fingerprint({**without, name: None}, SCHEMA) != record_fingerprint(without, SCHEMA)


def test_list_order_is_part_of_the_fingerprint() -> None:
    first = record_fingerprint({"title": ["a", "b"]}, SCHEMA)

    assert first != record_fingerprint({"title": ["b", "a"]}, SCHEMA)


@given(_data)
def test_a_record_compared_with_itself_has_no_changed_fields(data: dict[str, JsonValue]) -> None:
    assert changed_fields(data, dict(data), SCHEMA) == []


@given(_data, _data)
def test_changed_fields_are_the_fields_whose_published_json_value_differs_in_schema_order(
    previous: dict[str, JsonValue], current: dict[str, JsonValue]
) -> None:
    def differs(name: str) -> bool:
        published = (name in previous) != (name in current)
        return published or _canonical(previous.get(name)) != _canonical(current.get(name))

    assert changed_fields(previous, current, SCHEMA) == [name for name in SCHEMA.fields if differs(name)]


def test_a_changed_price_is_the_one_changed_field() -> None:
    previous: dict[str, JsonValue] = {"title": "Synthetic kettle", "price": {"amount": "19.90", "currency": "EUR"}}
    current: dict[str, JsonValue] = {"title": "Synthetic kettle", "price": {"amount": "17.50", "currency": "EUR"}}

    assert changed_fields(previous, current, SCHEMA) == ["price"]


def test_a_field_that_stops_publishing_or_starts_publishing_is_changed() -> None:
    previous: dict[str, JsonValue] = {"title": "Synthetic kettle", "sku": "A-1"}
    current: dict[str, JsonValue] = {"title": "Synthetic kettle", "colour": "red"}

    assert changed_fields(previous, current, SCHEMA) == ["sku", "colour"]
