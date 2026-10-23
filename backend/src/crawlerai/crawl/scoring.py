"""How a crawl orders its frontier (`strategy`): breadth first, depth first, or best first by a score.

Best first scores each candidate URL a page contributes, from 0 to 1, as the page's depth decays a mix of how well the
link matches the caller's `query` and `keywords`, how relevant the page that holds the link is (inherited, as in
shark-search: Hersovici et al., "The Shark-Search Algorithm", WWW7 1998), and the URL's prior. The match is Okapi BM25
(Robertson and Zaragoza, "The Probabilistic Relevance Framework", 2009): the candidate's *document* is its anchor text
and the tokens of its URL path, a term's weight is its inverse document frequency among the candidates the same page
contributes (a term every link of a navigation bar carries weighs nothing), and the sum is divided by the best sum a
document could reach, so it is comparable between pages. Terms are the Unicode word characters (UAX #29) of the case-
folded text; there are no stopword or synonym lists (C4). A page's relevance is, for each query term, the BM25
saturation tf / (tf + k1) of its count in the page's visible text, averaged. The prior is the URL's sitemap `priority`
(sitemaps.org: 0.0 to 1.0, 0.5 when a sitemap lists the URL without one, and for a URL no sitemap lists), halved for a
URL outside the start URL's directory (the hierarchy of RFC 3986 §3.3: a link into the section the crawl started in is
likelier to be what it is after). Depth first scores the depth alone, deeper first. A task's score orders the queue
(`crawlerai.db.queue`); a crawl without a score is breadth first.
"""

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final, Literal
from urllib.parse import unquote, urlsplit

Strategy = Literal["bfs", "dfs", "best_first"]

# BM25's usual constants (Robertson and Zaragoza 2009): term-frequency saturation and length normalisation.
BM25_K1: Final = 1.2
BM25_B: Final = 0.75
# sitemaps.org, <priority>: "The default priority of a page is 0.5".
DEFAULT_PRIORITY: Final = 0.5
# How much of a best-first score is the link's match against the query, the page's relevance it inherits, and the URL's
# prior; with no query the score is the prior alone, so the crawl goes shallow first and by sitemap priority.
MATCH_WEIGHT: Final = 0.5
INHERIT_WEIGHT: Final = 0.3
OUTSIDE_HOME: Final = 0.5
# Each level of depth keeps this share of a candidate's score: a link on the start page outranks, at equal match,
# one three clicks away.
DEPTH_DECAY: Final = 0.8
_TERM = re.compile(r"[^\W_]+")  # UAX #29 word characters: letters and digits, not the underscore


def terms(text: str) -> list[str]:
    """The case-folded word tokens of `text`, in order."""
    return _TERM.findall(text.casefold())


def query_terms(query: str | None, keywords: Sequence[str]) -> tuple[str, ...]:
    """The distinct terms of the query and the keywords, in order."""
    return tuple(dict.fromkeys(term for text in (query or "", *keywords) for term in terms(text)))


def page_relevance(text: str, wanted: Sequence[str]) -> float:
    """How relevant a page's visible `text` is to the `wanted` terms, in [0, 1): the mean BM25 term-frequency
    saturation of the terms."""
    if not wanted:
        return 0.0
    counts = Counter(terms(text))
    return sum(counts[term] / (counts[term] + BM25_K1) for term in wanted) / len(wanted)


def depth_score(depth: int) -> float:
    """The score of depth first: it grows with depth, so deeper tasks are leased first; always in [0.5, 1)."""
    return 1 - 1 / (depth + 2)


def _document(url: str, anchor: str) -> list[str]:
    """The tokens a candidate is matched by: its anchor text and its URL path (RFC 3986 §3.3), percent-decoded."""
    return terms(anchor) + terms(unquote(urlsplit(url).path))


def _bm25(documents: Sequence[list[str]], wanted: Sequence[str]) -> list[float]:
    """The BM25 of each document, over `wanted`, as a share of the best any document could reach, in [0, 1]."""
    vocabulary = frozenset(wanted)
    count = len(documents)
    average = sum(map(len, documents)) / count or 1.0
    frequency = Counter(term for document in documents for term in set(document) if term in vocabulary)
    idf = {term: math.log(1 + (count - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in vocabulary}
    ceiling = sum(idf.values()) * (BM25_K1 + 1)
    scores: list[float] = []
    for document in documents:
        seen = Counter(term for term in document if term in idf)
        norm = BM25_K1 * (1 - BM25_B + BM25_B * len(document) / average)
        total = sum(idf[term] * seen[term] * (BM25_K1 + 1) / (seen[term] + norm) for term in seen)
        scores.append(total / ceiling if ceiling else 0.0)
    return scores


def best_first_scores(
    urls: Sequence[str],
    *,
    depth: int,
    wanted: Sequence[str],
    anchors: Mapping[str, str],
    priorities: Mapping[str, float],
    inherited: float = 0.0,
    home: str = "",
) -> dict[str, float]:
    """The best-first score of each of `urls`, canonical, which one page contributes at `depth`: `wanted` are the
    query terms, `anchors` the link texts (`content.links.anchor_texts`), `priorities` the sitemap priorities,
    `inherited` the contributing page's relevance (`page_relevance`) and `home` the start URL's directory."""
    if not urls:
        return {}
    matches = _bm25([_document(url, anchors.get(url, "")) for url in urls], wanted) if wanted else [0.0] * len(urls)
    decay = DEPTH_DECAY**depth
    weight = MATCH_WEIGHT if wanted else 0.0
    inherit = INHERIT_WEIGHT if wanted else 0.0
    prior_weight = 1 - weight - inherit

    def prior(url: str) -> float:
        return priorities.get(url, DEFAULT_PRIORITY) * (1.0 if url.startswith(home) else OUTSIDE_HOME)

    return {
        url: decay * (weight * match + inherit * inherited + prior_weight * prior(url))
        for url, match in zip(urls, matches, strict=True)
    }
