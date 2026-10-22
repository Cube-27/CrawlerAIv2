"""The normalize dispatcher (normalization spec): each field type goes to its one module, lists and objects recurse
into their items and sub-fields, range resolves currencies by the registered money rules, no type returns `Ok`
for empty input (INV-06), and records serve money, ranges and numbers as JSON numbers ("Served form")."""

import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize.base import Ambiguous, Context, Invalid, Ok
from crawlerai.normalize.dispatch import normalize, served
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
    # A list reads a string as a list of one item, and an object needs an object.
    expected = {FieldType.LIST: Invalid("no_item"), FieldType.OBJECT: Invalid("not_an_object")}

    assert normalize(raw, _spec(type_), PAGE_CTX) == expected.get(type_, Invalid("empty"))


def test_each_field_type_goes_to_its_module() -> None:
    ctx = Context(captured_at=AT, page_url="https://example.test/p")

    assert normalize("a &amp;\n\nb", _spec(FieldType.TEXT), CTX) == Ok("a & b")
    assert normalize("a &amp;\n\nb", _spec(FieldType.LONG_TEXT), CTX) == Ok("a &\n\nb")
    assert normalize("HTTPS://example.test/p#x", _spec(FieldType.URL), ctx) == Ok(
        "https://example.test/p",
        stated="HTTPS://example.test/p#x",  # it publishes as the page writes it
    )
    assert normalize("HTTPS://example.test/p#x", _spec(FieldType.IMAGE_URL), ctx) == Invalid("page_url")
    assert normalize("2026-03-04T23:30:00-02:00", _spec(FieldType.DATE), CTX) == Ok("2026-03-04")
    assert normalize("2026-03-04T23:30:00-02:00", _spec(FieldType.DATETIME), CTX) == Ok("2026-03-05T01:30:00Z")
    unit_range: JsonValue = {"@type": "QuantitativeValue", "minValue": 1, "maxValue": 2.5, "unitCode": "KGM"}
    expected: JsonValue = {"min": "1", "max": "2.5", "currency": None, "unit": "KGM", "period": None}
    assert normalize(unit_range, _spec(FieldType.RANGE), CTX) == Ok(expected)


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


def test_an_object_normalizes_its_sub_fields_and_ignores_other_keys() -> None:
    raw: JsonValue = {"@type": "Person", "name": " A &amp; B ", "home": "HTTPS://example.test/a#x"}

    assert normalize(raw, PERSON, CTX) == Ok(
        {"name": "A & B", "home": "https://example.test/a"},
        stated={"name": "A & B", "home": "HTTPS://example.test/a#x"},
    )


_bounds = st.tuples(*[st.decimals(min_value=1, max_value=999, places=2)] * 2).map(sorted)


def _range(lo: Decimal, hi: Decimal, code: str | None, period: str | None) -> JsonValue:
    return {"min": format(lo, "f"), "max": format(hi, "f"), "currency": code, "unit": None, "period": period}


@settings(deadline=None)
@given(_bounds)
def test_a_dollar_sign_is_ambiguous_without_evidence_and_settled_by_a_page_currency(bounds: list[Decimal]) -> None:
    lo, hi = bounds
    raw = f"${lo} - ${hi} per year"

    # C7: never USD by default; a range states one currency or none (the money rules leave `$` unknown).
    assert normalize(raw, _spec(FieldType.RANGE), CTX) == Ambiguous("currency_unknown", ())
    settled = Context(captured_at=AT, page_currencies=("CAD",))
    assert normalize(raw, _spec(FieldType.RANGE), settled) == Ok(_range(lo, hi, "CAD", "YEAR"))


def test_a_list_is_as_checked_as_its_least_checked_item_and_as_settled_as_its_weakest() -> None:
    prices = FieldSpec(type=FieldType.LIST, item=FieldSpec(type=FieldType.MONEY))
    page = CTX.model_copy(update={"page_currencies": ("EUR",)})
    assert normalize(["EUR 5", "$7"], prices, page) == Ok(
        [{"amount": "5", "currency": "EUR"}, {"amount": "7", "currency": None}],
        basis="unknown",
        checked=True,
    )
    signless = normalize(["EUR 5", "7"], prices, page)
    assert isinstance(signless, Ok)
    assert (signless.checked, signless.basis) == (False, "page")


def test_a_range_bound_past_any_amount_is_not_a_number() -> None:
    raw: JsonValue = {"currency": "EUR", "value": {"minValue": "1e1000000000", "maxValue": 5}}
    assert normalize(raw, _spec(FieldType.RANGE), CTX) == Invalid("bound_not_a_number")


# Money's storage bounds (`numbers.storable`: under 10^12, six fraction digits) within binary64's 15 exact digits.
_written = st.decimals(min_value=0, max_value=Decimal("999999999.999999"), places=6).map(
    lambda d: format(d.normalize() if d else d, "f")
)


@given(_written, _written)
def test_records_serve_money_and_range_amounts_as_the_json_numbers_they_state_and_numbers_to_two_places(
    a: str, b: str
) -> None:
    lo, hi = sorted([a, b], key=Decimal)
    fields = {
        "price": _spec(FieldType.MONEY),
        "salary": _spec(FieldType.RANGE),
        "rating": _spec(FieldType.NUMBER),
        "variants": FieldSpec.model_validate(
            {"type": "list", "item": {"type": "object", "fields": {"price": {"type": "money", "description": "d"}}}}
        ),
    }
    money: JsonValue = {"amount": a, "currency": "EUR"}
    salary: JsonValue = {"min": lo, "max": hi, "currency": "EUR", "unit": None, "period": "YEAR"}
    data: dict[str, JsonValue] = {"price": money, "salary": salary, "rating": a, "variants": [{"price": money}], "x": a}

    # As a JSON document carries them: the text a JSON number is written in reads back as the stated decimal.
    out = json.loads(json.dumps(served(data, fields)), parse_float=Decimal, parse_int=Decimal)

    assert out["price"] == out["variants"][0]["price"] == {"amount": Decimal(a), "currency": "EUR"}
    assert out["salary"] == {**salary, "min": Decimal(lo), "max": Decimal(hi)}
    assert out["rating"] == Decimal(a).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    assert out["x"] == a  # a key the schema lacks is served as it is
