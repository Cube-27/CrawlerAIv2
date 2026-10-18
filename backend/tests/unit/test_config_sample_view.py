"""What role A reads of a sample page (SPEC-08 §4.6): reduced HTML, a cut that keeps the published values, and JSON
documents as key paths without values. Pages are synthetic."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.config_ir.sample_view import KEYS_MAX_CHARS, Cut, cut_around, json_keys, reduced_html
from crawlerai.content.page import ParsedPage


def test_reduced_html_drops_scripts_styles_comments_and_other_attributes() -> None:
    page = ParsedPage(
        "<html><head><style>h1{color:red}</style><script>var a = 1;</script></head><body>"
        "<!-- note --><h1 id='t' class='title' style='x' onclick='y' data-sku='S-1' aria-label='z'>Item</h1>"
        "<a href='/p/2' rel='next' title='t'>next</a><meta property='og:title' content='Item'></body></html>"
    )
    assert reduced_html(page) == (
        "<html><head></head><body>"
        '<h1 id="t" class="title" data-sku="S-1">Item</h1>'
        '<a href="/p/2">next</a><meta property="og:title" content="Item"></body></html>'
    )


def test_reduced_html_leaves_the_parsed_page_unchanged() -> None:
    page = ParsedPage("<html><body><h1 style='x'>Item</h1></body></html>")
    reduced_html(page)
    assert page.lxml_tree.xpath("//h1/@style") == ["x"]


def test_a_text_within_the_limit_is_not_cut() -> None:
    assert cut_around("<p>Item</p>", ["Item"], 100) == Cut("<p>Item</p>")


def test_a_cut_is_centred_on_the_published_values() -> None:
    text = "a" * 100 + "<p>Item</p>" + "b" * 100
    # "Item" is at 103 to 107; the 20 characters left over go 10 before and 10 after it.
    assert cut_around(text, ["Item"], 24) == Cut("aaaaaaa<p>Item</p>bbbbbb", "characters 93 to 117 of 211")


def test_values_are_found_as_escaped_html_text() -> None:
    text = "a" * 100 + "<p>A &amp; B</p>" + "b" * 100
    assert "A &amp; B" in cut_around(text, ["A & B"], 20).text


def test_without_a_found_value_the_cut_keeps_the_start() -> None:
    assert cut_around("abcdef", ["zzz"], 3) == Cut("abc", "characters 0 to 3 of 6")


@given(st.text(min_size=1), st.text(min_size=1, max_size=20), st.text(), st.integers(min_value=20, max_value=200))
def test_a_cut_holds_a_value_no_longer_than_the_limit(before: str, value: str, after: str, limit: int) -> None:
    # A value made of `&`, `<` or `>` escapes to more characters than the limit allows, so escaping is left out here.
    value = value.replace("&", "").replace("<", "").replace(">", "") or "v"
    text = before + value + after
    cut = cut_around(text, [value], limit)
    assert len(cut.text) <= limit
    assert value in cut.text


def test_json_documents_are_shown_as_key_paths_with_types_and_no_other_value() -> None:
    page = ParsedPage(
        '<html><head><script type="application/ld+json">'
        '{"@type": "Product", "name": "Secret name", "offers": [{"price": 5}, {"price": 6}]}'
        '</script><script type="application/json">{"state": {"id": 7}}</script></head></html>'
    )
    keys = json_keys(page, KEYS_MAX_CHARS)
    assert keys.note is None
    assert keys.text.splitlines()[0] == "jsonld block 0: $['@type']=Product $['name'] $['offers'][*]['price']"
    assert keys.text.splitlines()[1].endswith(": $['state']['id']")
    assert "Secret name" not in keys.text


def test_json_keys_are_cut_to_their_limit() -> None:
    members = ", ".join(f'"key{n}": 1' for n in range(5_000))
    page = ParsedPage(f'<html><head><script type="application/json">{{{members}}}</script></head></html>')
    keys = json_keys(page, KEYS_MAX_CHARS)
    assert len(keys.text) == KEYS_MAX_CHARS
    assert keys.note is not None
    assert keys.note.startswith(f"the first {KEYS_MAX_CHARS} of ")


def test_json_keys_are_cut_to_a_smaller_limit_and_never_past_the_maximum() -> None:
    members = ", ".join(f'"key{n}": 1' for n in range(5_000))
    page = ParsedPage(f'<html><head><script type="application/json">{{{members}}}</script></head></html>')
    assert len(json_keys(page, 100).text) == 100
    assert len(json_keys(page, KEYS_MAX_CHARS * 2).text) == KEYS_MAX_CHARS
