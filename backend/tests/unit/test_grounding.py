"""Grounding edge cases (SPEC-06 §4.3) that the properties don't pin to one literal outcome."""

import pytest

from crawlerai.llm.grounding import GroundedSpan, SpanClaim, align

_TEXT = "Price 12.50 EUR\nWas 12.50 EUR"


def test_stated_offsets_that_hold_the_value_win_over_an_earlier_occurrence() -> None:
    assert align(SpanClaim(value="12.50 EUR", start=20, end=29), _TEXT) == GroundedSpan("12.50 EUR", 20, 29)


def test_wrong_offsets_are_corrected_to_the_nearest_occurrence() -> None:
    assert align(SpanClaim(value="12.50 EUR", start=17, end=26), _TEXT) == GroundedSpan("12.50 EUR", 20, 29)


def test_an_occurrence_equally_near_on_both_sides_resolves_to_the_earlier_one() -> None:
    assert align(SpanClaim(value="ab", start=3, end=5), "ab-xx-ab") == GroundedSpan("ab", 0, 2)


def test_negative_offsets_are_not_read_as_counting_from_the_end() -> None:
    # `text[-3:29]` holds the second "EUR", but -3 is no offset into the text: the value is searched for, and the
    # first occurrence is the nearer one.
    assert align(SpanClaim(value="EUR", start=-3, end=29), _TEXT) == GroundedSpan("EUR", 12, 15)


def test_a_negative_end_is_not_read_as_counting_from_the_end() -> None:
    # `text[0:-2]` is the value, but -2 is no offset into the text: the value is searched for.
    assert align(SpanClaim(value="12.50", start=0, end=-2), "12.50 x") == GroundedSpan("12.50", 0, 5)


def test_an_end_past_the_text_is_not_clamped_to_it() -> None:
    # `text[16:99]` is "Was 12.50 EUR" by slice clamping; the stated end is no offset into the text.
    assert align(SpanClaim(value="Was 12.50 EUR", start=16, end=99), _TEXT) == GroundedSpan("Was 12.50 EUR", 16, 29)


def test_matching_is_exact_not_case_or_whitespace_insensitive() -> None:
    assert align(SpanClaim(value="price 12.50  eur", start=0, end=15), _TEXT) is None


def test_an_empty_value_is_dropped() -> None:
    assert align(SpanClaim(value="", start=0, end=0), _TEXT) is None


def test_the_locator_is_the_text_span() -> None:
    assert GroundedSpan("12.50 EUR", 6, 15).locator == "text:6-15"


def test_a_claim_is_read_from_the_model_reply_shape() -> None:
    claim = SpanClaim.model_validate({"value": "EUR", "start": 12, "end": 15})

    assert claim == SpanClaim(value="EUR", start=12, end=15)


def test_a_claim_with_extra_keys_is_refused() -> None:
    reply = {"value": "EUR", "start": 12, "end": 15, "note": "x"}
    with pytest.raises(ValueError, match="note"):
        SpanClaim.model_validate(reply)
