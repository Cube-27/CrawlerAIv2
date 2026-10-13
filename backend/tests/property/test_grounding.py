"""Grounding by alignment (SPEC-06 §4.3, INV-12): on generated texts and spans, `align` returns the exact span; a
value absent from the text is dropped; a repeated value takes the occurrence nearest the model's `start`; whatever it
accepts is a verbatim slice of the text at its stated offsets."""

from hypothesis import assume, given
from hypothesis import strategies as st

from crawlerai.collect.locator import parse_locator
from crawlerai.llm.grounding import SpanClaim, align

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

    grounded = align(SpanClaim(value=text[start:end], start=start, end=end), text)

    assert grounded is not None
    assert (grounded.value, grounded.start, grounded.end) == (text[start:end], start, end)


@given(_text_and_span(), _offset, _offset)
def test_a_value_found_once_gets_its_true_offsets_whatever_the_claimed_ones(
    case: tuple[str, int, int], claimed_start: int, claimed_end: int
) -> None:
    text, start, end = case
    value = text[start:end]
    assume(_occurrences(value, text) == [start])

    grounded = align(SpanClaim(value=value, start=claimed_start, end=claimed_end), text)

    assert grounded is not None
    assert (grounded.start, grounded.end) == (start, end)


@given(_text, st.text(min_size=1, max_size=20), _offset, _offset)
def test_a_value_absent_from_the_text_is_dropped(text: str, value: str, start: int, end: int) -> None:
    assume(value not in text)

    assert align(SpanClaim(value=value, start=start, end=end), text) is None


@given(_text, _text, _offset, _offset)
def test_whatever_is_accepted_is_the_text_at_its_offsets_and_its_locator_says_so(
    text: str, value: str, start: int, end: int
) -> None:
    grounded = align(SpanClaim(value=value, start=start, end=end), text)

    if grounded is not None:
        assert 0 <= grounded.start < grounded.end <= len(text)
        assert text[grounded.start : grounded.end] == grounded.value == value
        locator = parse_locator(grounded.locator)
        assert locator.scheme == "text"
        assert locator.parts == (str(grounded.start), str(grounded.end))


@given(
    st.text(st.sampled_from("ab"), min_size=1, max_size=4),
    st.lists(st.text(st.sampled_from("xyz"), min_size=1, max_size=6), min_size=3, max_size=6),
    _offset,
)
def test_a_repeated_value_takes_the_occurrence_nearest_the_claimed_start(
    value: str, gaps: list[str], hint: int
) -> None:
    text = value.join(gaps)  # `value` occurs len(gaps) - 1 times, separated by letters it doesn't contain
    grounded = align(SpanClaim(value=value, start=hint, end=hint + len(value)), text)

    assert grounded is not None
    nearest = min(_occurrences(value, text), key=lambda i: (abs(i - hint), i))
    assert (grounded.start, grounded.end) == (nearest, nearest + len(value))
