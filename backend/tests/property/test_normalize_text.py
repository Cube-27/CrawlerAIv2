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


@given(st.sampled_from([TEXT, LONG]), st.text(max_size=200))
def test_an_ok_value_is_nfc_without_control_characters_and_normalizes_to_itself_as_html(
    spec: FieldSpec, raw: str
) -> None:
    result = text.normalize(raw, spec, CTX)

    if isinstance(result, Ok):
        value = result.value
        assert isinstance(value, str)
        assert value == unicodedata.normalize("NFC", value)
        assert all(unicodedata.category(c) != "Cc" or c == "\n" for c in value)
        # A text value is trimmed and on one line with single spaces.
        assert spec is LONG or value == " ".join(value.split())
        assert text.normalize(html.escape(value, quote=False), spec, CTX) == result


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


# --- word overlap (`text.word_overlap`, D-1462) ---

# Words are runs of letters, marks and numbers; punctuation separates them.
_sentences = st.lists(st.from_regex(r"[A-Za-z]{1,12}", fullmatch=True), min_size=1, max_size=30)


@given(_sentences, _sentences)
def test_word_overlap_is_symmetric_and_between_zero_and_one(a: list[str], b: list[str]) -> None:
    score = text.word_overlap(" ".join(a), " ".join(b))
    assert score is not None
    assert 0 <= score <= 1
    assert score == text.word_overlap(" ".join(b), " ".join(a))


@given(st.permutations(["alpha", "beta", "gamma", "delta"]))
def test_the_same_words_in_any_order_case_or_punctuation_overlap_fully(words: list[str]) -> None:
    assert text.word_overlap("Alpha, beta. Gamma\n\ndelta!", " ".join(w.upper() for w in words)) == 1.0


def test_word_overlap_counts_repeated_words() -> None:
    # Dice over multisets: {a, a, b} and {a, b} share 2 of 5 words, twice over.
    assert text.word_overlap("a a b", "a b") == pytest.approx(0.8)
    assert text.word_overlap("one two", "three four") == 0.0


@pytest.mark.parametrize(("a", "b"), [("words", None), (3, "words"), ("...", "words"), ("words", "")])
def test_word_overlap_needs_two_texts_with_words(a: JsonValue, b: JsonValue) -> None:
    assert text.word_overlap(a, b) is None


def test_word_overlap_tells_texts_that_differ_only_in_a_figure_apart() -> None:
    # D-1583: "10" and "20" are words, so one of five words differs.
    assert text.word_overlap("The battery lasts 10 hours", "The battery lasts 20 hours") == pytest.approx(0.8)
    assert text.word_overlap("Model X1 ships", "model x1, ships!") == 1.0
    assert text.word_overlap("Model X1", "Model X2") == pytest.approx(0.5)
