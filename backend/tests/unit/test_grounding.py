"""Grounding edge cases (llm spec) that the properties don't pin to one literal outcome."""

from crawlerai.content.text import Mark
from crawlerai.llm.grounding import GroundedElement, GroundedSpan, SpanClaim, align, ground_element

_TEXT = "Price 12.50 EUR\nWas 12.50 EUR"


def test_wrong_offsets_are_corrected_to_the_nearest_occurrence() -> None:
    assert align(SpanClaim(value="12.50 EUR", start=17, end=26), _TEXT) == GroundedSpan("12.50 EUR", 20, 29)


def test_an_empty_value_is_dropped() -> None:
    assert align(SpanClaim(value="", start=0, end=0), _TEXT) is None


_ELEMENTS = {
    "L1": Mark("link", 0, 5, "/html[1]/body[1]/a[1]", "/apply", ""),
    "I1": Mark("image", 5, 5, "/html[1]/body[1]/img[1]", "/a.png", "Front"),
}


def test_a_claimed_element_is_grounded_in_the_element_its_id_marks() -> None:
    grounded = ground_element("L1", "link", _ELEMENTS)

    assert grounded == GroundedElement("/apply", "/html[1]/body[1]/a[1]")
    assert grounded.locator == "dom:/html[1]/body[1]/a[1]"


def test_a_money_claim_is_grounded_at_the_text_whatever_the_spacing_after_its_sign() -> None:
    text = "Was $45.00 $ 19.98\nAdd"

    assert align(SpanClaim(value="$19.98", start=0, end=0), text, money=True) == GroundedSpan("$ 19.98", 11, 18)
    assert align(SpanClaim(value="$19.98", start=0, end=0), text) is None
    assert align(SpanClaim(value="$9.98", start=0, end=0), text, money=True) is None
