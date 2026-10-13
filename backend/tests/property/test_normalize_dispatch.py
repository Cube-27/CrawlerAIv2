"""The normalize dispatcher (SPEC-04 §4.3, §4.7): each field type goes to its one module, a type without a
normalizer declines as `unknown_type`, and no type returns `Ok` for empty input (INV-06)."""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
CTX = Context(captured_at=AT)
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
    ctx = Context(captured_at=AT, base_url="https://example.test/a", page_url="https://example.test/a")

    assert not isinstance(normalize(raw, _spec(type_), ctx), Ok)


def test_text_and_long_text_go_to_the_text_module() -> None:
    raw = "a &amp;\n\nb"

    assert normalize(raw, _spec(FieldType.TEXT), CTX) == Ok("a & b")
    assert normalize(raw, _spec(FieldType.LONG_TEXT), CTX) == Ok("a &\n\nb")


def test_url_and_image_url_go_to_the_url_module() -> None:
    ctx = Context(captured_at=AT, page_url="https://example.test/p")

    assert normalize("HTTPS://example.test/p#x", _spec(FieldType.URL), ctx) == Ok("https://example.test/p")
    assert normalize("HTTPS://example.test/p#x", _spec(FieldType.IMAGE_URL), ctx) == Invalid("page_url")


def test_a_type_without_a_normalizer_yet_declines_as_unknown_type() -> None:
    # `list` and `object` recursion arrives with SPEC-04 PR 9, the last normalizer PR.
    assert normalize(["a"], _spec(FieldType.LIST), CTX) == Invalid("unknown_type")
