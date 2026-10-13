"""Type equality for labels (SPEC-03 §4.6, SPEC-04 §4.5): scalars go to their type's normalizer `equal`, lists
compare as multisets of item equality, objects field by field."""

from typing import Any, get_args

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.eval.labels import ListShape, ObjectShape, ScalarShape, ScalarType, values_equal

_json: st.SearchStrategy[JsonValue] = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=4), children, max_size=4),
    max_leaves=12,
)

_LIST_OF_TEXT = ListShape(type="list", item=ScalarShape(type="text"))
_LOCATION = ObjectShape(
    type="object", fields={"locality": ScalarShape(type="text"), "country": ScalarShape(type="text")}
)


@given(st.sampled_from(get_args(ScalarType)), _json)
def test_every_scalar_type_is_reflexive(type_: ScalarType, value: JsonValue) -> None:
    assert values_equal(value, value, ScalarShape(type=type_)) is True


@given(st.sampled_from(get_args(ScalarType)), _json, _json)
def test_scalar_stubs_are_exact_until_spec_04(type_: ScalarType, a: JsonValue, b: JsonValue) -> None:
    assert values_equal(a, b, ScalarShape(type=type_)) is (a == b)


@given(st.lists(st.text(max_size=3), max_size=6), st.randoms())
def test_lists_compare_as_multisets(items: list[JsonValue], rnd: Any) -> None:
    shuffled = list(items)
    rnd.shuffle(shuffled)

    assert values_equal(items, shuffled, _LIST_OF_TEXT) is True


@given(st.lists(st.text(max_size=3), min_size=1, max_size=6))
def test_list_multiplicity_counts(items: list[JsonValue]) -> None:
    assert values_equal(items, [*items, items[0]], _LIST_OF_TEXT) is False
    assert values_equal(items, items[1:], _LIST_OF_TEXT) is False


def test_list_items_use_item_equality() -> None:
    shape = ListShape(type="list", item=_LOCATION)
    a: list[JsonValue] = [{"locality": "Springfield", "country": "DE"}, {"locality": "Shelbyville", "country": "FR"}]
    b: list[JsonValue] = [a[0], {"locality": "Shelbyville", "country": "DE"}]

    assert values_equal(a, list(reversed(a)), shape) is True
    assert values_equal(a, b, shape) is False


def test_objects_compare_field_by_field() -> None:
    a: dict[str, JsonValue] = {"locality": "Springfield", "country": "DE"}

    assert values_equal(a, dict(reversed(a.items())), _LOCATION) is True
    assert values_equal(a, {"locality": "Springfield", "country": "FR"}, _LOCATION) is False
    assert values_equal(a, {"locality": "Springfield"}, _LOCATION) is False
    assert values_equal({**a, "zip": "1"}, {**a, "zip": "1"}, _LOCATION) is False


def test_container_shapes_refuse_other_json_kinds() -> None:
    assert values_equal("a", "a", _LIST_OF_TEXT) is False
    assert values_equal(["a"], ["a"], _LOCATION) is False
