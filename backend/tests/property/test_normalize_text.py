"""The text and long_text normalizer: entity decoding, NFC, whitespace collapse,
and declines on empty, over-long and template-placeholder input."""

from datetime import UTC, datetime

import pytest
from pydantic import JsonValue

from snowcrawl.normalize import text
from snowcrawl.normalize.base import Context, Invalid, Ok
from snowcrawl.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
TEXT = FieldSpec(type=FieldType.TEXT)
LONG = FieldSpec(type=FieldType.LONG_TEXT)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fish &amp; chips", "Fish & chips"),
        ("Fish &amp;amp; chips &amp;#39;n&amp;#39; &amp;co", "Fish & chips 'n' &co"),  # escaped twice
        ("&amp;#0000065; &#38;lt;", "A <"),  # leading zeros; an `&` escaped as a number
        ("caf&eacute; &#8212; &#x2603;", "café — ☃"),
        ("cafe\u0301", "caf\u00e9"),  # NFD to NFC
        ("a\u00a0\u2003b", "a b"),
        ("a\x00b\x07 c", "ab c"),
    ],
)
def test_entities_are_decoded_unicode_composed_and_controls_removed(raw: str, expected: str) -> None:
    assert text.normalize(raw, TEXT, CTX) == Ok(expected)


@pytest.mark.parametrize(("raw", "reason"), [("\x00", "empty"), (" \x1b \x9f ", "empty"), ("a\ud800b", "surrogate")])
def test_input_with_no_content_or_a_lone_surrogate_is_invalid(raw: str, reason: str) -> None:
    assert text.normalize(raw, TEXT, CTX) == Invalid(reason)


@pytest.mark.parametrize(("spec", "limit"), [(TEXT, 512), (LONG, 100_000)])
def test_length_is_bounded_after_normalization(spec: FieldSpec, limit: int) -> None:
    assert text.normalize("x" * limit, spec, CTX) == Ok("x" * limit)
    assert text.normalize("x" * (limit + 1), spec, CTX) == Invalid("too_long")
    assert text.normalize(" " * limit + "x", spec, CTX) == Ok("x")


@pytest.mark.parametrize("placeholder", ["{{ item_name }}", "${title}", "%s", "%(name)s"])
def test_a_template_placeholder_anywhere_is_invalid(placeholder: str) -> None:
    assert text.normalize(f"Buy {placeholder} now", TEXT, CTX) == Invalid("template_placeholder")


@pytest.mark.parametrize("raw", ["100% sure", "50%sale", "{x}", "% s"])
def test_percent_signs_and_single_braces_are_not_placeholders(raw: str) -> None:
    assert text.normalize(raw, TEXT, CTX) == Ok(raw)


@pytest.mark.parametrize("raw", [None, 3, True, ["a"], {"@value": "a"}])
def test_a_non_string_is_invalid(raw: JsonValue) -> None:
    assert text.normalize(raw, TEXT, CTX) == Invalid("not_a_string")


def test_word_overlap_is_dice_over_word_multisets_and_tells_a_differing_figure_apart() -> None:
    assert text.word_overlap("a a b", "a b") == pytest.approx(0.8)
    assert text.word_overlap("one two", "three four") == 0.0
    # "10" and "20" are words, so one of five words differs.
    assert text.word_overlap("The battery lasts 10 hours", "The battery lasts 20 hours") == pytest.approx(0.8)


@pytest.mark.parametrize(("a", "b"), [("words", None), (3, "words"), ("...", "words"), ("words", "")])
def test_word_overlap_needs_two_texts_with_words(a: JsonValue, b: JsonValue) -> None:
    assert text.word_overlap(a, b) is None
