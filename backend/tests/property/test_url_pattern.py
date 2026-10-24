"""URL patterns: a URL made from a pattern matches it with the values it was made with; the shape forgets only the
parameter names; the most specific matching pattern has no matching rival with more literal segments; the patterns
`generalize` makes match their samples."""

import re
from dataclasses import dataclass
from urllib.parse import quote

from hypothesis import given
from hypothesis import strategies as st

from snowcrawl.config_ir.url_pattern import generalize, match, most_specific, parse, shape

_HOST = "shop.example.test"
# Literal segments are lower-case words and values hold upper case, so a value never equals a literal; values hold
# characters that need percent-encoding (space, `%`, `/`, `?`, `&`, `=`, `+`, non-ASCII).
_literal = st.sampled_from(["p", "c", "item", "en"])
_value = st.text(alphabet="ABXZ09-._~ %/?&=+é", min_size=1, max_size=8)


@dataclass(frozen=True)
class _Made:
    """A pattern, a URL made from it, and the values it was made with."""

    pattern: str
    url: str
    values: dict[str, str]


@st.composite
def _made(draw: st.DrawFn) -> _Made:
    kinds = draw(st.lists(st.sampled_from(["literal", "name", "wildcard"]), max_size=5))
    template: list[str] = []
    path: list[str] = []
    values: dict[str, str] = {}
    for index, kind in enumerate(kinds):
        value = draw(_value)
        if kind == "literal":
            literal = draw(_literal)
            template.append(literal)
            path.append(literal)
            continue
        template.append("*" if kind == "wildcard" else f"{{s{index}}}")
        path.append(quote(value, safe=""))
        if kind == "name":
            values[f"s{index}"] = value
    if draw(st.booleans()):
        template.append("**")
        path += [quote(v, safe="") for v in draw(st.lists(_value, max_size=2))]
    keys = draw(st.lists(st.sampled_from(["q", "v", "page"]), unique=True, max_size=2))
    query = []
    for key in keys:
        values[f"k_{key}"] = value = draw(_value)
        query.append(f"{key}={quote(value, safe='')}")
    pattern = (
        _HOST + "".join(f"/{t}" for t in template) + ("?" + "&".join(f"{k}={{k_{k}}}" for k in keys) if keys else "")
    )
    url = f"https://{_HOST}/" + "/".join(path) + ("?" + "&".join([*query, "other=1"]) if query else "")
    return _Made(pattern, url, values)


@given(_made())
def test_a_url_made_from_a_pattern_matches_it_with_its_values(made: _Made) -> None:
    assert match(made.pattern, made.url) == made.values


@given(_made(), _value)
def test_a_url_with_another_literal_or_host_does_not_match(made: _Made, value: str) -> None:
    pattern = parse(made.pattern)
    literals = [i for i, segment in enumerate(pattern.path) if segment.isalpha()]
    other_host = made.url.replace(_HOST, f"other.{_HOST}", 1)
    assert match(made.pattern, other_host) is None
    if literals:
        segments = made.url.split("?")[0].split("/")
        segments[3 + literals[0]] = quote(value, safe="")
        assert match(made.pattern, "/".join(segments)) is None


@given(_made())
def test_renaming_or_wildcarding_the_parameters_keeps_the_shape_and_renaming_the_matches(made: _Made) -> None:
    renamed = made.pattern.replace("{s", "{r").replace("{k_", "{kk_")
    wildcarded = re.sub(r"\{s\d+\}", "*", made.pattern)

    assert shape(renamed) == shape(made.pattern) == shape(wildcarded)
    assert (match(renamed, made.url) is None) == (match(made.pattern, made.url) is None)


@given(st.lists(_made(), min_size=1, max_size=4), st.integers(min_value=0, max_value=3))
def test_the_most_specific_pattern_matches_and_none_matching_has_more_literals(made: list[_Made], pick: int) -> None:
    url = made[pick % len(made)].url
    patterns = [m.pattern for m in made]

    chosen = most_specific(patterns, url)

    assert chosen is not None
    assert match(chosen, url) is not None
    matching = [p for p in patterns if match(p, url) is not None]
    assert all(parse(p).literals <= parse(chosen).literals for p in matching)
    assert most_specific(reversed(patterns), url) == chosen


@given(st.lists(st.lists(_value, min_size=0, max_size=4), min_size=1, max_size=5))
def test_the_generalized_patterns_match_their_samples(paths: list[list[str]]) -> None:
    urls = [f"https://{_HOST}/" + "/".join(quote(v, safe="") for v in path) for path in paths]

    patterns = generalize(urls)

    assert all(any(match(pattern, url) is not None for pattern in patterns) for url in urls)
