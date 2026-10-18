"""Per-page session parameters (`normalize.url_key.session_parameters`, owner #67): a parameter every row link carries
with one same value, absent from the page's own URLs, is dropped; one with a value per row is identity and is kept.
Synthetic `.test` URLs only (C9)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.normalize.url_key import session_parameters, without_parameters

PAGE = "https://shop.example.test/list"
names = st.from_regex(r"[a-z]{1,6}", fullmatch=True)
values = st.from_regex(r"[a-z0-9]{1,6}", fullmatch=True)


def _row(i: int, query: str) -> str:
    return f"https://shop.example.test/item/{i}?{query}" if query else f"https://shop.example.test/item/{i}"


@given(st.integers(min_value=2, max_value=8), names, values, names)
def test_a_shared_parameter_is_dropped_and_a_per_row_one_kept(rows: int, shared: str, value: str, own: str) -> None:
    if own == shared:
        own += "x"
    urls = [_row(i, f"{own}={i}&{shared}={value}") for i in range(rows)]

    found = session_parameters(urls, [PAGE])

    assert found == {shared}
    assert [without_parameters(url, found) for url in urls] == [_row(i, f"{own}={i}") for i in range(rows)]


@given(st.integers(min_value=2, max_value=8), names, values)
def test_a_parameter_the_page_url_carries_is_kept(rows: int, shared: str, value: str) -> None:
    urls = [_row(i, f"{shared}={value}") for i in range(rows)]

    assert session_parameters(urls, [f"{PAGE}?{shared}=other"]) == frozenset()


@given(names, values)
def test_one_row_shows_nothing_to_compare(shared: str, value: str) -> None:
    assert session_parameters([_row(1, f"{shared}={value}")], [PAGE]) == frozenset()


@pytest.mark.parametrize(
    "urls",
    [
        # Missing from one row, repeated within a row, or with two values: none names the visit.
        [_row(1, "sid=a"), _row(2, "")],
        [_row(1, "sid=a&sid=a"), _row(2, "sid=a&sid=a")],
        [_row(1, "sid=a"), _row(2, "sid=b")],
    ],
)
def test_a_parameter_not_carried_alike_by_every_row_is_kept(urls: list[str]) -> None:
    assert session_parameters(urls, [PAGE]) == frozenset()


def test_dropping_every_pair_drops_the_question_mark() -> None:
    assert without_parameters(_row(1, "sid=a&src=b"), {"sid", "src"}) == _row(1, "")
    assert without_parameters(_row(1, ""), {"sid"}) == _row(1, "")
