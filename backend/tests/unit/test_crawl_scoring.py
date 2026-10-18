"""How a crawl orders its frontier (`crawlerai.crawl.scoring`, D-1440): best first ranks the links that match the
query above the rest, shallower and sitemap-preferred first among equals; depth first leases the deepest."""

from crawlerai.crawl.scoring import best_first_scores, page_relevance, query_terms

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


def test_a_link_whose_url_or_anchor_matches_the_query_outranks_one_that_does_not() -> None:
    by_path, by_anchor, none = f"{BASE}/guides/rate-limits", f"{BASE}/a/1", f"{BASE}/blog/holiday"
    scores = _scores([by_path, by_anchor, none], "rate limits", anchors={by_anchor: "Understanding rate limits"})

    assert min(scores[by_path], scores[by_anchor]) > scores[none]


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


def test_without_a_query_the_sitemap_priority_orders_the_links() -> None:
    high, low = f"{BASE}/a", f"{BASE}/b"

    scores = best_first_scores([high, low], depth=1, wanted=(), anchors={}, priorities={high: 0.9, low: 0.1})

    assert scores[high] > scores[low]
