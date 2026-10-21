"""Grounding by alignment (llm spec, INV-12): on generated texts and spans, `align` returns the exact span when it is
whole words; a value absent from the text is dropped; a repeated value takes the occurrence nearest the model's
`start`; an occurrence inside a longer word is never grounded; an accepted claim's locator names its offsets. An
empty value is dropped, and a claimed element is grounded in the element its id marks."""

from hypothesis import assume, given
from hypothesis import strategies as st

from crawlerai.collect.locator import Locator, parse_locator
from crawlerai.content.text import Mark
from crawlerai.llm.grounding import GroundedElement, SpanClaim, align, bounded, ground_element

_text = st.text(st.characters(codec="utf-8", exclude_categories=["Cs"]), max_size=200)
_offset = st.integers(min_value=-1_000, max_value=1_000)


def _occurrences(value: str, text: str) -> list[int]:
    """Every index where `value` starts in `text`, overlapping ones included."""
    return [i for i in range(len(text)) if text.startswith(value, i)]


@st.composite
def _text_and_span(draw: st.DrawFn) -> tuple[str, int, int]:
    text = draw(_text.filter(bool))
    start = draw(st.integers(min_value=0, max_value=len(text) - 1))
    end = draw(st.integers(min_value=start + 1, max_value=len(text)))
    return text, start, end


@given(_text_and_span())
def test_a_claim_whose_offsets_hold_the_value_is_accepted_as_stated(case: tuple[str, int, int]) -> None:
    text, start, end = case
    assume(bounded(text, start, end))

    grounded = align(SpanClaim(value=text[start:end], start=start, end=end), text)

    assert grounded is not None
    assert (grounded.value, grounded.start, grounded.end) == (text[start:end], start, end)
    assert parse_locator(grounded.locator) == Locator("text", (str(start), str(end)))


@given(_text, st.text(min_size=1, max_size=20), _offset, _offset)
def test_a_value_absent_from_the_text_is_dropped(text: str, value: str, start: int, end: int) -> None:
    assume(value not in text)

    assert align(SpanClaim(value=value, start=start, end=end), text) is None


@given(
    st.text(st.sampled_from("ab"), min_size=1, max_size=4),
    st.lists(st.text(st.sampled_from("xyz"), min_size=1, max_size=6), min_size=3, max_size=6),
    _offset,
)
def test_a_repeated_value_takes_the_occurrence_nearest_the_claimed_start(
    value: str, gaps: list[str], hint: int
) -> None:
    # `value` occurs len(gaps) - 1 times, a word of its own between words of letters it doesn't contain
    text = f" {value} ".join(gaps)
    grounded = align(SpanClaim(value=value, start=hint, end=hint + len(value)), text)

    assert grounded is not None
    nearest = min(_occurrences(value, text), key=lambda i: (abs(i - hint), i))
    assert (grounded.start, grounded.end) == (nearest, nearest + len(value))


@given(
    st.text(st.sampled_from("ab1"), min_size=1, max_size=4), st.text(st.sampled_from("xyz9_"), min_size=1, max_size=4)
)
def test_an_occurrence_inside_a_longer_word_is_not_grounded(value: str, extra: str) -> None:
    text = f"{value}{extra} {extra}{value}"  # `value` only as the head and the tail of a longer word

    assert align(SpanClaim(value=value, start=0, end=len(value)), text) is None


def test_an_empty_value_is_dropped() -> None:
    assert align(SpanClaim(value="", start=0, end=0), "Price 12.50 EUR\nWas 12.50 EUR") is None


_ELEMENTS = {
    "L1": Mark("link", 0, 5, "/html[1]/body[1]/a[1]", "/apply", ""),
    "I1": Mark("image", 5, 5, "/html[1]/body[1]/img[1]", "/a.png", "Front"),
}


def test_a_claimed_element_is_grounded_in_the_element_its_id_marks() -> None:
    grounded = ground_element("L1", "link", _ELEMENTS)

    assert grounded == GroundedElement("/apply", "/html[1]/body[1]/a[1]")
    assert grounded.locator == "dom:/html[1]/body[1]/a[1]"
