"""Pagination (SPEC-05 §4.12, ARCHITECTURE §8.6): `rel=next` first, then the structural numbered-link rule.

Pages are synthetic (`example.test`); parameter and segment names are generated, since the rule reads none (C4, C9).
"""

import string

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.content.page import ParsedPage
from crawlerai.resolve.pagination import NextLink, next_page_candidates, next_page_links

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


def test_a_base_element_sets_the_reference_base() -> None:
    head = f'<base href="{BASE}/archive/"><link rel="next" href="2">'
    assert _next("", f"{BASE}/c/shoes", head) == (f"{BASE}/archive/2",)


def test_rel_prev_and_non_http_references_are_not_candidates() -> None:
    head = (
        '<link rel="prev" href="/c?page=1"><link rel="next" href="mailto:a@example.test">'
        '<link rel="next" href="/c?page=3">'
    )
    assert _next("", f"{BASE}/c?page=2", head) == (f"{BASE}/c?page=3",)


# --- structural numbered links ---


def test_the_link_one_integer_query_parameter_higher_is_a_candidate() -> None:
    body = _links("/c/shoes?p=1&sort=asc", "/c/shoes?p=3&sort=asc", "/c/shoes?p=4&sort=asc")
    assert _next(body, f"{BASE}/c/shoes?sort=asc&p=3") == (f"{BASE}/c/shoes?p=4&sort=asc",)


def test_the_link_one_integer_path_segment_higher_is_a_candidate() -> None:
    body = _links("/c/shoes/page/1", "/c/shoes/page/2", "/c/shoes/page/3", "/c/boots/page/3")
    assert _next(body, f"{BASE}/c/shoes/page/2") == (f"{BASE}/c/shoes/page/3",)


def test_rel_next_comes_first_and_a_url_is_listed_once() -> None:
    head = '<link rel="next" href="/c?page=3">'
    body = _links("/c?page=3", "/c?page=3", "/c?page=1")
    assert _next(body, f"{BASE}/c?page=2", head) == (f"{BASE}/c?page=3",)


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


def test_a_page_url_without_the_integer_has_no_structural_candidate() -> None:
    # Which number the first page would carry is not stated, so it is not guessed (C7).
    links = _links("/c?page=1", "/c?page=2")
    assert _next(links, f"{BASE}/c") == ()
    assert _next(links, f"{BASE}/c?page=1") == (f"{BASE}/c?page=2",)


_NAMES = st.text(string.ascii_lowercase, min_size=1, max_size=8)


@given(name=_NAMES, current=st.integers(min_value=0, max_value=10**6))
def test_any_parameter_name_numbers_pages(name: str, current: int) -> None:
    body = _links(*(f"/list?{name}={n}" for n in (current - 1, current + 2, current + 1, current)))
    assert _next(body, f"{BASE}/list?{name}={current}") == (f"{BASE}/list?{name}={current + 1}",)


@given(segment=_NAMES, current=st.integers(min_value=0, max_value=10**6))
def test_any_path_segment_numbers_pages(segment: str, current: int) -> None:
    body = _links(*(f"/{segment}/{n}/all" for n in (current + 2, current + 1)))
    assert _next(body, f"{BASE}/{segment}/{current}/all") == (f"{BASE}/{segment}/{current + 1}/all",)


def test_next_page_links_name_their_element_and_whether_rel_next_found_them() -> None:
    page = ParsedPage(
        '<html><head><link rel="next" href="?page=2"></head>'
        '<body><a href="/c/shoes?page=2">2</a><a href="/c/shoes/3">x</a></body></html>'
    )

    assert next_page_links(page, f"{BASE}/c/shoes?page=1") == (
        NextLink(f"{BASE}/c/shoes?page=2", "?page=2", "/html[1]/head[1]/link[1]", rel_next=True),
    )
