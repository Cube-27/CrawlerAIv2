"""Which field types have a syntax their normalizer checks (ARCHITECTURE §8.1, SPEC-05 §4.5): a value of such a type
that normalizes is evidence of the type, so a visible one may be admitted from `js_state` or `xhr` with no other
source to equal. Any string normalizes as text, so text admits by equality only."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.normalize.dispatch import checkable
from crawlerai.schemas.types import FieldSpec, FieldType

ANY_RAW = st.one_of(st.text(), st.integers(), st.floats(allow_nan=False))


def _spec(type_: FieldType, **parameters: object) -> FieldSpec:
    return FieldSpec.model_validate({"type": type_, **parameters})


@given(ANY_RAW)
def test_text_long_text_and_objects_are_never_checkable(raw: str | int | float) -> None:
    opaque = (
        _spec(FieldType.TEXT),
        _spec(FieldType.LONG_TEXT),
        _spec(FieldType.OBJECT, fields={"amount": {"type": "money", "description": "An amount."}}),
    )

    assert [checkable(raw, spec) for spec in opaque] == [False, False, False]


@given(ANY_RAW)
def test_types_with_a_grammar_or_vocabulary_are_always_checkable(raw: str | int | float) -> None:
    specs = (
        _spec(FieldType.MONEY),
        _spec(FieldType.ENUM, vocab="schema:ItemAvailability"),
        _spec(FieldType.DATE),
        _spec(FieldType.DATETIME),
        _spec(FieldType.LOCATION),
        _spec(FieldType.RANGE),
    )

    assert all(checkable(raw, spec) for spec in specs)


def test_an_identifier_is_checkable_only_under_a_scheme_with_a_check_digit() -> None:
    schemes = ("gtin", "isbn", "mpn", "sku", "custom")

    assert {s: checkable("4006381333931", _spec(FieldType.IDENTIFIER, scheme=s)) for s in schemes} == {
        "gtin": True,
        "isbn": True,
        "mpn": False,
        "sku": False,
        "custom": False,
    }


def test_a_url_is_checkable_only_when_absolute() -> None:
    raws = ("https://shop.example.test/p/1", "HTTP://example.test", "/p/1", "p1", "mailto:a@example.test", 7)

    for type_ in (FieldType.URL, FieldType.IMAGE_URL):
        assert [checkable(raw, _spec(type_)) for raw in raws] == [True, True, False, False, False, False]


def test_a_list_is_checkable_as_its_item_is() -> None:
    prices = _spec(FieldType.LIST, item={"type": "money"})
    names = _spec(FieldType.LIST, item={"type": "text"})

    assert (checkable("€5.00", prices), checkable("€5.00", names)) == (True, False)
