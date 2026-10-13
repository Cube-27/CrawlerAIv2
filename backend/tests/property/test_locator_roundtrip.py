"""Every locator `format_locator` writes parses back to the same parts (SPEC-05 §4.3): induction (SPEC-08) reads
what collectors write."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.locator import Locator, format_locator, parse_locator

_index = st.integers(min_value=0, max_value=10**6).map(str)
_jsonpath = st.text(max_size=30).map(lambda tail: "$" + tail)
_xpath = st.text(min_size=1, max_size=30).map(lambda tail: "/" + tail)
# A script's path as `ParsedPage` writes it: element steps ending in `script[n]`.
_script_xpath = st.lists(st.from_regex(r"[a-z][a-z0-9]{0,8}\[[1-9][0-9]{0,2}\]", fullmatch=True), max_size=5).map(
    lambda steps: "".join(f"/{step}" for step in steps) + "/script[1]"
)
_token = st.from_regex(r"[A-Za-z0-9_.\-]{1,20}", fullmatch=True)
_name = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True)

_locators = st.one_of(
    st.tuples(st.just("jsonld"), _index, _jsonpath),
    st.tuples(st.just("microdata"), _xpath),
    st.tuples(st.just("meta"), st.from_regex(r"[^\s]{1,20}", fullmatch=True)),
    st.tuples(st.just("js_state"), _script_xpath, _jsonpath),
    st.tuples(st.just("xhr"), _index, _jsonpath),
    st.tuples(st.just("adapter"), _token, _jsonpath),
    st.tuples(st.just("api"), _token, _jsonpath),
    st.tuples(st.just("config"), _name, _index, st.text(min_size=1, max_size=30)),
    st.tuples(st.integers(0, 10**6), st.integers(1, 10**6)).map(lambda p: ("text", str(p[0]), str(p[0] + p[1]))),
)


@given(_locators)
def test_formatted_locators_parse_back(locator: tuple[str, ...]) -> None:
    scheme, *parts = locator
    text = format_locator(scheme, *parts)  # type: ignore[arg-type]
    assert parse_locator(text) == Locator(scheme, tuple(parts))  # type: ignore[arg-type]
