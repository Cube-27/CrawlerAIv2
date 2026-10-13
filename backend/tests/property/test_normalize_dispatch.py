"""The normalize dispatcher (SPEC-04 §4.3, §4.7): each field type goes to its one module, a type without a
normalizer declines as `unknown_type`, and no type returns `Ok` for empty input (INV-06)."""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize.base import Ambiguous, Context, Invalid, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
CTX = Context(captured_at=AT)
PAGE_CTX = Context(captured_at=AT, base_url="https://example.test/a", page_url="https://example.test/a")
_PARAMETERS: dict[FieldType, dict[str, object]] = {
    FieldType.ENUM: {"vocab": "schema:ItemAvailability"},
    FieldType.IDENTIFIER: {"scheme": "gtin"},
    FieldType.LIST: {"item": {"type": "text"}},
    FieldType.OBJECT: {"fields": {"name": {"type": "text", "description": "A name."}}},
}


def _spec(type_: FieldType) -> FieldSpec:
    return FieldSpec.model_validate({"type": type_, **_PARAMETERS.get(type_, {})})


@given(
    st.sampled_from(list(FieldType)),
    st.text(alphabet=st.characters(categories=["Zs", "Cc"]).filter(str.isspace), max_size=8),
)
def test_no_type_returns_ok_for_empty_input(type_: FieldType, raw: str) -> None:
    assert not isinstance(normalize(raw, _spec(type_), PAGE_CTX), Ok)


def test_text_and_long_text_go_to_the_text_module() -> None:
    raw = "a &amp;\n\nb"

    assert normalize(raw, _spec(FieldType.TEXT), CTX) == Ok("a & b")
    assert normalize(raw, _spec(FieldType.LONG_TEXT), CTX) == Ok("a &\n\nb")


def test_url_and_image_url_go_to_the_url_module() -> None:
    ctx = Context(captured_at=AT, page_url="https://example.test/p")

    assert normalize("HTTPS://example.test/p#x", _spec(FieldType.URL), ctx) == Ok("https://example.test/p")
    assert normalize("HTTPS://example.test/p#x", _spec(FieldType.IMAGE_URL), ctx) == Invalid("page_url")


def test_date_and_datetime_go_to_the_date_module() -> None:
    raw = "2026-03-04T23:30:00-02:00"

    assert normalize(raw, _spec(FieldType.DATE), CTX) == Ok("2026-03-04")
    assert normalize(raw, _spec(FieldType.DATETIME), CTX) == Ok("2026-03-05T01:30:00Z")


TEXTS = _spec(FieldType.LIST)
PERSON = FieldSpec.model_validate(
    {
        "type": "object",
        "fields": {
            "name": {"type": "text", "description": "A name.", "required": True},
            "home": {"type": "url", "description": "A home page."},
        },
    }
)


@given(st.lists(st.text(alphabet="ab &", min_size=1, max_size=6), min_size=1, max_size=5))
def test_a_list_normalizes_each_item(items: list[str]) -> None:
    expected: list[JsonValue] = [" ".join(item.split()) for item in items]

    result = normalize(list(items), TEXTS, CTX)

    if all(expected):
        assert result == Ok(expected)
    elif any(expected):
        assert isinstance(result, Ok)
        assert result.value == [e for e in expected if e]
        assert result.reasons == tuple(f"[{i}]: empty" for i, e in enumerate(expected) if not e)
    else:
        assert result == Invalid("no_item")


def test_a_single_value_is_a_list_of_one() -> None:
    assert normalize("a  b", TEXTS, CTX) == Ok(["a b"])


def test_an_empty_list_is_invalid() -> None:
    assert normalize([], TEXTS, CTX) == Invalid("empty")


def test_a_list_whose_items_are_only_ambiguous_is_ambiguous() -> None:
    dates = FieldSpec.model_validate({"type": "list", "item": {"type": "date"}})

    assert normalize(["03/04/2026", ""], dates, CTX) == Ambiguous("no_item", ())
    assert normalize(["03/04/2026", "2026-05-06"], dates, CTX) == Ok(["2026-05-06"], ("[0]: date_order",))


def test_an_object_normalizes_its_sub_fields_and_ignores_other_keys() -> None:
    raw: JsonValue = {"@type": "Person", "name": " A &amp; B ", "home": "HTTPS://example.test/a#x"}

    assert normalize(raw, PERSON, CTX) == Ok({"name": "A & B", "home": "https://example.test/a"})


def test_an_optional_sub_field_that_declines_is_dropped_and_reported() -> None:
    assert normalize({"name": "A", "home": "mailto:a@example.test"}, PERSON, CTX) == Ok(
        {"name": "A"}, ("home: not_http",)
    )
    assert normalize({"name": "A", "home": None}, PERSON, CTX) == Ok({"name": "A"})


def test_a_required_sub_field_that_declines_declines_the_object() -> None:
    assert normalize({"home": "https://example.test/"}, PERSON, CTX) == Invalid("name: missing")
    assert normalize({"name": None}, PERSON, CTX) == Invalid("name: missing")
    assert normalize({"name": " "}, PERSON, CTX) == Invalid("name: empty")
    assert normalize("A", PERSON, CTX) == Invalid("not_an_object")


def test_nested_reasons_carry_their_path() -> None:
    people = FieldSpec(type=FieldType.LIST, item=PERSON)

    result = normalize([{"name": "A", "home": "ftp://example.test/"}, {"home": "https://example.test/"}], people, CTX)

    assert result == Ok([{"name": "A"}], ("[0].home: not_http", "[1]: name: missing"))


def test_range_goes_to_the_range_module() -> None:
    unit_range: JsonValue = {"@type": "QuantitativeValue", "minValue": 1, "maxValue": 2.5, "unitCode": "KGM"}

    expected: JsonValue = {"min": "1", "max": "2.5", "currency": None, "unit": "KGM", "period": None}
    assert normalize(unit_range, _spec(FieldType.RANGE), CTX) == Ok(expected)


def test_range_resolves_its_currency_by_the_registered_money_rules() -> None:
    money_range: JsonValue = {"currency": "EUR", "minValue": 1, "maxValue": 2, "unitText": "YEAR"}
    money = normalize({"price": 1, "priceCurrency": "EUR"}, _spec(FieldType.MONEY), CTX)

    result = normalize(money_range, _spec(FieldType.RANGE), CTX)

    # Before SPEC-04 PR 3 registers money, its decline is the range's decline.
    if isinstance(money, Ok):
        assert isinstance(result, Ok)
        assert isinstance(result.value, dict)
        assert (result.value["currency"], result.value["period"]) == ("EUR", "YEAR")
    else:
        assert result == money
