"""How a crawl orders its frontier (`crawlerai.crawl.scoring`, D-1440): best first ranks the links that match the
query above the rest, shallower and sitemap-preferred first among equals; depth first leases the deepest."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.crawl.frontier import Frontier
from crawlerai.crawl.rules import Scope
from crawlerai.crawl.scoring import best_first_scores, depth_score, page_relevance, query_terms, terms

BASE = "https://docs.example.test"


def _scores(
    urls: list[str],
    query: str,
    *,
    depth: int = 1,
    anchors: dict[str, str] | None = None,
    priorities: dict[str, float] | None = None,
) -> dict[str, float]:
    return best_first_scores(
        urls, depth=depth, wanted=query_terms(query, ()), anchors=anchors or {}, priorities=priorities or {}
    )


def test_terms_are_case_folded_unicode_words() -> None:
    assert terms("Rate-Limits_v2 Über") == ["rate", "limits", "v2", "über"]
    assert query_terms("Rate limits", ["limits", "Retry"]) == ("rate", "limits", "retry")


def test_a_link_whose_url_or_anchor_matches_the_query_outranks_one_that_does_not() -> None:
    by_path, by_anchor, none = f"{BASE}/guides/rate-limits", f"{BASE}/a/1", f"{BASE}/blog/holiday"
    scores = _scores([by_path, by_anchor, none], "rate limits", anchors={by_anchor: "Understanding rate limits"})

    assert min(scores[by_path], scores[by_anchor]) > scores[none]


def test_a_term_every_candidate_carries_does_not_discriminate() -> None:
    urls = [f"{BASE}/docs/a", f"{BASE}/docs/b", f"{BASE}/docs/c"]

    scores = _scores(urls, "docs")

    assert len(set(scores.values())) == 1


def test_the_match_is_the_same_for_a_link_of_any_page_but_depth_decays_it() -> None:
    url = f"{BASE}/guides/rate-limits"
    shallow = _scores([url], "rate limits", depth=1)[url]
    deep = _scores([url], "rate limits", depth=3)[url]

    assert 0 < deep < shallow <= 1


def test_a_link_inherits_the_relevance_of_the_page_that_holds_it() -> None:
    url = f"{BASE}/a"

    holder_matches = best_first_scores([url], depth=1, wanted=("rate",), anchors={}, priorities={}, inherited=0.9)
    holder_does_not = best_first_scores([url], depth=1, wanted=("rate",), anchors={}, priorities={}, inherited=0.0)

    assert holder_matches[url] > holder_does_not[url]


def test_a_page_is_relevant_by_how_often_it_names_the_terms() -> None:
    wanted = ("rate", "limits")

    assert page_relevance("nothing here", wanted) == 0
    assert page_relevance("rate limits", wanted) < page_relevance("rate limits rate limits rate limits", wanted) < 1
    assert page_relevance("rate only", wanted) < page_relevance("rate limits", wanted)
    assert page_relevance("anything", ()) == 0


def test_a_link_into_the_start_urls_directory_outranks_one_outside_it() -> None:
    home = f"{BASE}/3/"
    inside, outside = f"{BASE}/3/library", f"{BASE}/3.11/"

    scores = best_first_scores([inside, outside], depth=1, wanted=(), anchors={}, priorities={}, home=home)

    assert scores[inside] > scores[outside]


def test_without_a_query_the_sitemap_priority_orders_the_links() -> None:
    high, low = f"{BASE}/a", f"{BASE}/b"

    scores = best_first_scores([high, low], depth=1, wanted=(), anchors={}, priorities={high: 0.9, low: 0.1})

    assert scores[high] > scores[low]


def test_a_url_no_sitemap_lists_has_the_default_priority() -> None:
    listed, unlisted = f"{BASE}/a", f"{BASE}/b"

    scores = best_first_scores([listed, unlisted], depth=0, wanted=(), anchors={}, priorities={listed: 0.5})

    assert scores[listed] == scores[unlisted]


@given(depth=st.integers(0, 50))
def test_depth_first_scores_grow_with_depth(depth: int) -> None:
    assert 0.5 <= depth_score(depth) < depth_score(depth + 1) < 1


@given(
    paths=st.lists(st.text("abcd-/", min_size=1, max_size=10), min_size=1, max_size=6, unique=True),
    query=st.text("abcd ", min_size=1, max_size=8),
    depth=st.integers(0, 6),
)
def test_best_first_scores_stay_in_the_unit_interval(paths: list[str], query: str, depth: int) -> None:
    urls = [f"{BASE}/{path}" for path in paths]

    scores = _scores(urls, query, depth=depth)

    assert set(scores) == set(urls)
    assert all(0 <= score <= 1 for score in scores.values())


@pytest.mark.parametrize(("strategy", "expected"), [("bfs", {}), ("dfs", {"u": depth_score(2)})])
def test_a_frontier_scores_by_its_strategy(strategy: str, expected: dict[str, float]) -> None:
    frontier = Frontier(Scope("docs.example.test"), (), 3, 10, strategy)  # type: ignore[arg-type]

    assert frontier.scores(["u"], 2, {}, {}, 0.0) == expected


def test_a_scope_takes_subdomains_or_every_host_only_when_asked() -> None:
    host = "docs.example.test"
    sub, other = f"https://api.{host}/x", "https://elsewhere.example.test/x"

    assert not Frontier(Scope(host), (), 1, 1).admits(sub)
    assert Frontier(Scope(host, subdomains=True), (), 1, 1).admits(sub)
    assert not Frontier(Scope(host, subdomains=True), (), 1, 1).admits(other)
    assert Frontier(Scope(host, external=True), (), 1, 1).admits(other)
    assert not Frontier(Scope(host, (), (f"{other}*",), external=True), (), 1, 1).admits(other)
