"""What role A reads of a sample page (SPEC-08 §4.6): reduced HTML, a cut that keeps the published values, and JSON
documents as key paths without values. Pages are synthetic."""

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


def test_a_cut_is_centred_on_the_published_values() -> None:
    text = "a" * 100 + "<p>Item</p>" + "b" * 100
    # "Item" is at 103 to 107; the 20 characters left over go 10 before and 10 after it.
    assert cut_around(text, ["Item"], 24) == Cut("aaaaaaa<p>Item</p>bbbbbb", "characters 93 to 117 of 211")


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
