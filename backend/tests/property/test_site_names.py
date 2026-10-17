"""Site names (SPEC-05 §4.5): for any title and site name, stripping keeps a non-empty prefix of the title, keeps its
first segment, removes a trailing segment that is the stated site name, and is idempotent."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.site_names import SiteNames, fold

_WORD = st.text(st.characters(categories=("L", "N")), min_size=1, max_size=8)
_PHRASE = st.lists(_WORD, min_size=1, max_size=3).map(" ".join)
# ASCII separators, and the en dash, em dash, middle dot and bullet by code point.
_SEPARATORS = st.sampled_from(["|", "-", ":", "/", *map(chr, (0x2013, 0x2014, 0x00B7, 0x2022))])
_TITLE = st.tuples(_PHRASE, st.lists(st.tuples(_SEPARATORS, _PHRASE), max_size=3)).map(
    lambda t: t[0] + "".join(f" {sep} {phrase}" for sep, phrase in t[1])
)


@given(
    _TITLE, st.lists(_PHRASE, max_size=2), st.sampled_from([None, "https://shop.example.test/p", "http://10.0.0.1/"])
)
def test_stripping_keeps_a_prefix_with_the_first_segment_and_is_idempotent(
    title: str, site_names: list[str], page_url: str | None
) -> None:
    site = SiteNames.of(site_names, page_url)

    stripped = site.without_site(title)

    assert title.startswith(stripped)
    assert stripped.startswith(title.split(" ")[0])
    assert site.without_site(stripped) == stripped


@given(_PHRASE, _SEPARATORS, _PHRASE)
def test_a_trailing_stated_site_name_is_stripped(item: str, separator: str, site_name: str) -> None:
    site = SiteNames.of([site_name], None)

    assert site.without_site(f"{item} {separator} {site_name}") == item


@given(_PHRASE, _PHRASE)
def test_a_title_naming_the_site_is_one_of_its_writings(site_name: str, other: str) -> None:
    site = SiteNames.of([site_name], None)

    assert site.names(f" {site_name}! ")
    assert site.names(other) == (fold(other) == fold(site_name))


def test_a_site_name_of_many_parts_costs_a_bounded_number_of_runs() -> None:
    name = " | ".join(f"part{i}" for i in range(2000))

    site = SiteNames.of([name], None)

    assert len(site.stated) <= 8 * 9 // 2 + 1
    assert site.names("part0part1")
    assert site.names(name.replace(" | ", ""))
