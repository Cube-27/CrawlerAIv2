"""Crawl canonicalization (SPEC-10 §4.1, §6): the url type's canonical form with the query sorted by name, as the
frontier and `map` dedup by it. Properties: idempotence, no parameter dropped (D-0036), and pair order not mattering
except between pairs of one name."""

from collections import Counter
from random import Random

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.crawl.canonical import canonicalize

_name = st.text(alphabet="abcxyzé%2B+_-.~", min_size=1, max_size=4)
_value = st.text(alphabet="0123456789abc=/%20+", max_size=4)
_pairs = st.lists(st.tuples(_name, _value).map(lambda pair: f"{pair[0]}={pair[1]}"), max_size=6)
_paths = st.sampled_from(["", "/", "/a/./b/../c", "/%7Euser/Item", "/p%2fq"])
_fragments = st.sampled_from(["", "#", "#top", "#a?b"])


def _url(path: str, pairs: list[str], fragment: str = "") -> str:
    query = f"?{'&'.join(pairs)}" if pairs else ""
    return f"HTTPS://Shop.Example.TEST:443{path}{query}{fragment}"


@given(_paths, _pairs, _fragments)
def test_a_canonical_url_canonicalizes_to_itself(path: str, pairs: list[str], fragment: str) -> None:
    once = canonicalize(_url(path, pairs, fragment))

    assert once is not None
    assert canonicalize(once) == once


@given(_paths, _pairs)
def test_no_query_parameter_is_dropped(path: str, pairs: list[str]) -> None:
    canonical = canonicalize(_url(path, pairs))

    assert canonical is not None
    _, _, query = canonical.partition("?")
    expected = canonicalize(_url(path, sorted(pairs)))
    assert expected is not None
    # The same pairs, as the url type percent-normalizes them, in another order.
    assert Counter(query.split("&")) == Counter(expected.partition("?")[2].split("&"))
    assert len([pair for pair in query.split("&") if pair]) == len(pairs)


# Names without `%`: triplets that differ only in case are one name once the url type normalizes them.
@given(_paths, st.lists(_name.filter(lambda name: "%" not in name), unique=True, max_size=5), st.randoms())
def test_pairs_of_distinct_names_in_any_order_are_one_url(path: str, names: list[str], random: Random) -> None:
    pairs = [f"{name}=1" for name in names]
    shuffled = list(pairs)
    random.shuffle(shuffled)

    assert canonicalize(_url(path, shuffled)) == canonicalize(_url(path, pairs))


def test_pairs_are_sorted_by_name_and_pairs_of_one_name_keep_their_order() -> None:
    assert canonicalize("https://example.test/s?q=b&page=2&q=a&a") == "https://example.test/s?a&page=2&q=b&q=a"


def test_names_compare_form_decoded() -> None:
    # `+` decodes to a space (application/x-www-form-urlencoded), which sorts before `*`; the pairs keep their bytes.
    assert canonicalize("https://example.test/?a*=1&a+b=2") == "https://example.test/?a+b=2&a*=1"


def test_empty_pairs_are_skipped_and_an_empty_query_keeps_its_mark() -> None:
    assert canonicalize("https://example.test/s?b=1&&a=2&") == "https://example.test/s?a=2&b=1"
    assert canonicalize("https://example.test/s?&") == "https://example.test/s?"
    assert canonicalize("https://example.test/s?") == "https://example.test/s?"


def test_the_fragment_is_removed_and_a_relative_reference_resolves_against_its_base() -> None:
    assert canonicalize("../b?y=1&x=2#top", "https://example.test/a/c/") == "https://example.test/a/b?x=2&y=1"


def test_what_is_not_an_http_url_declines() -> None:
    assert canonicalize("mailto:someone@example.test") is None
    assert canonicalize("/relative") is None
