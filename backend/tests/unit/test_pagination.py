"""Pagination (extraction spec): `rel=next` first, then the structural numbered-link rule.

Pages are synthetic (`example.test`); parameter and segment names are generated, since the rule reads none (C4, C9).
"""

import string

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.content.page import ParsedPage
from crawlerai.resolve.pagination import next_page_candidates

BASE = "https://shop.example.test"


def _next(body: str, url: str, head: str = "") -> tuple[str, ...]:
    return next_page_candidates(ParsedPage(f"<html><head>{head}</head><body>{body}</body></html>"), url)


def _links(*hrefs: str) -> str:
    return "".join(f'<a href="{href}">{i}</a>' for i, href in enumerate(hrefs))


# --- rel=next (HTML standard) ---


def test_link_and_anchor_rel_next_are_candidates_resolved_against_the_page() -> None:
    head = '<link rel="next" href="/c/shoes?page=2">'
    body = '<a rel="nofollow NEXT" href="https://shop.example.test/c/shoes?page=2&amp;view=all">more</a>'
    assert _next(body, f"{BASE}/c/shoes", head) == (
        f"{BASE}/c/shoes?page=2",
        f"{BASE}/c/shoes?page=2&view=all",
    )


# --- structural numbered links ---


def test_the_link_one_integer_query_parameter_higher_is_a_candidate() -> None:
    body = _links("/c/shoes?p=1&sort=asc", "/c/shoes?p=3&sort=asc", "/c/shoes?p=4&sort=asc")
    assert _next(body, f"{BASE}/c/shoes?sort=asc&p=3") == (f"{BASE}/c/shoes?p=4&sort=asc",)


def test_links_differing_in_more_than_one_place_are_not_numbered_pages() -> None:
    body = _links(
        "/c?page=3&sort=desc",  # a second parameter differs
        "/d?page=3",  # the path differs too
        "/c?page=3&extra=1",  # a parameter is added
        "https://other.example.test/c?page=3",  # another host
        "http://shop.example.test/c?page=3",  # another scheme
        "/c?page=three",  # not an integer
        "/c?page=4",  # not current + 1
        "/c?page=3&sort=asc",  # the one numbered page
    )
    assert _next(body, f"{BASE}/c?page=2&sort=asc") == (f"{BASE}/c?page=3&sort=asc",)


_NAMES = st.text(string.ascii_lowercase, min_size=1, max_size=8)


@given(prefix=_NAMES, suffix=st.sampled_from(["", ".html", "-all", "_x.htm"]), current=st.integers(0, 10**6))
def test_an_integer_inside_a_path_segment_numbers_pages(prefix: str, suffix: str, current: int) -> None:
    def link(n: int) -> str:
        return f"/list/{prefix}-{n}{suffix}"

    body = _links(link(current + 2), f"/list/other-{current + 1}{suffix}", link(current + 1), link(current))
    assert _next(body, f"{BASE}{link(current)}") == (f"{BASE}{link(current + 1)}",)
