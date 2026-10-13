"""The text and long_text normalizer (SPEC-04 §4.4, ARCHITECTURE §9): entity decoding, NFC, whitespace collapse,
and declines on empty, over-long and template-placeholder input (INV-06)."""

import html
import unicodedata
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import text
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
TEXT = FieldSpec(type=FieldType.TEXT)
LONG = FieldSpec(type=FieldType.LONG_TEXT)

# Python's `str.isspace` set: Unicode White_Space, including the C0 separators.
_whitespace = st.text(alphabet=st.characters(categories=["Zs", "Cc"]).filter(str.isspace), max_size=8)
_words = st.from_regex(r"[A-Za-z0-9]{1,12}", fullmatch=True)


@given(st.sampled_from([TEXT, LONG]), _whitespace)
def test_empty_or_whitespace_input_is_invalid(spec: FieldSpec, raw: str) -> None:
    assert text.normalize(raw, spec, CTX) == Invalid("empty")


@given(st.sampled_from([TEXT, LONG]), st.text(max_size=200))
def test_an_ok_value_rendered_as_html_normalizes_to_itself(spec: FieldSpec, raw: str) -> None:
    result = text.normalize(raw, spec, CTX)

    if isinstance(result, Ok):
        assert isinstance(result.value, str)
        assert text.normalize(html.escape(result.value, quote=False), spec, CTX) == result


@given(st.text(max_size=200))
def test_a_text_value_is_nfc_trimmed_and_on_one_line_with_single_spaces(raw: str) -> None:
    result = text.normalize(raw, TEXT, CTX)

    if isinstance(result, Ok):
        value = result.value
        assert isinstance(value, str)
        assert value == unicodedata.normalize("NFC", value)
        assert value == " ".join(value.split())


@given(st.sampled_from([TEXT, LONG]), st.text(max_size=200))
def test_an_ok_value_has_no_control_characters_but_line_breaks(spec: FieldSpec, raw: str) -> None:
    result = text.normalize(raw, spec, CTX)

    if isinstance(result, Ok):
        assert isinstance(result.value, str)
        assert all(unicodedata.category(c) != "Cc" or c == "\n" for c in result.value)


@pytest.mark.parametrize("raw", ["\x00", "\x01\x7f", " \x1b \x9f "])
def test_input_of_control_characters_only_is_empty(raw: str) -> None:
    assert text.normalize(raw, TEXT, CTX) == Invalid("empty")


def test_control_characters_are_removed_from_a_value() -> None:
    assert text.normalize("a\x00b\x07 c", TEXT, CTX) == Ok("ab c")


@given(st.sampled_from([TEXT, LONG]), st.text(max_size=40), st.integers(min_value=0), st.characters(categories=["Cs"]))
def test_input_with_a_lone_surrogate_is_invalid(spec: FieldSpec, raw: str, at: int, surrogate: str) -> None:
    # Unicode general category Cs: a lone surrogate is not a Unicode scalar value and has no UTF-8 encoding.
    at %= len(raw) + 1

    assert text.normalize(raw[:at] + surrogate + raw[at:], spec, CTX) == Invalid("surrogate")


@given(st.lists(_words, min_size=1, max_size=5), _whitespace)
def test_text_joins_words_with_one_space_whatever_whitespace_separates_them(words: list[str], gap: str) -> None:
    raw = (" " + gap).join(words)

    assert text.normalize(f" {gap}{raw}{gap} ", TEXT, CTX) == Ok(" ".join(words))


def test_long_text_keeps_line_breaks_and_one_blank_line_between_paragraphs() -> None:
    raw = "  First   line\t \nsecond line\n\n \n\n  Next&nbsp;paragraph  \n"

    assert text.normalize(raw, LONG, CTX) == Ok("First line\nsecond line\n\nNext paragraph")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fish &amp; chips", "Fish & chips"),
        ("caf&eacute; &#8212; &#x2603;", "café — ☃"),
        ("cafe\u0301", "caf\u00e9"),  # NFD to NFC
        ("a\u00a0\u2003b", "a b"),
    ],
)
def test_entities_are_decoded_and_unicode_composed(raw: str, expected: str) -> None:
    assert text.normalize(raw, TEXT, CTX) == Ok(expected)


@pytest.mark.parametrize(("spec", "limit"), [(TEXT, 512), (LONG, 100_000)])
def test_length_is_bounded_after_normalization(spec: FieldSpec, limit: int) -> None:
    assert text.normalize("x" * limit, spec, CTX) == Ok("x" * limit)
    assert text.normalize("x" * (limit + 1), spec, CTX) == Invalid("too_long")
    assert text.normalize(" " * limit + "x", spec, CTX) == Ok("x")


@given(
    st.sampled_from([TEXT, LONG]),
    st.text(max_size=20),
    st.sampled_from(["{{ item_name }}", "{{x}}", "${title}", "${ a.b }", "%s", "%d", "%(name)s", "%1$s"]),
    st.text(max_size=20),
)
def test_a_template_placeholder_anywhere_is_invalid(spec: FieldSpec, before: str, placeholder: str, after: str) -> None:
    raw = f"{before} {placeholder} {after}"

    assert text.normalize(raw, spec, CTX) == Invalid("template_placeholder")


@pytest.mark.parametrize("raw", ["100% sure", "50%sale", "{x}", "$ {x}", "{ {x} }", "% s"])
def test_percent_signs_and_single_braces_are_not_placeholders(raw: str) -> None:
    assert text.normalize(raw, TEXT, CTX) == Ok(raw)


@pytest.mark.parametrize("raw", [None, 3, 1.5, True, ["a"], {"@value": "a"}])
def test_a_non_string_is_invalid(raw: JsonValue) -> None:
    assert text.normalize(raw, TEXT, CTX) == Invalid("not_a_string")


@pytest.mark.parametrize("type_", [FieldType.URL, FieldType.DATE])
def test_a_spec_of_another_type_is_a_programming_error(type_: FieldType) -> None:
    spec = FieldSpec(type=type_)

    with pytest.raises(TypeError):
        text.normalize("a", spec, CTX)


@given(st.sampled_from([TEXT, LONG]), st.text(max_size=50))
def test_the_result_depends_only_on_the_arguments(spec: FieldSpec, raw: str) -> None:
    first = text.normalize(raw, spec, CTX)

    assert text.normalize(raw, spec, CTX) == first
