"""The page content formats (rest-api spec): markdown, cleaned html, links and metadata, each
read from the shared `ParsedPage`."""

from crawlerai.content.markdown import markdown
from crawlerai.content.page import ParsedPage

FINAL_URL = "https://shop.example.test/catalog/chairs?page=2"
ARTICLE = (
    '<!doctype html><html lang="en"><head><title>Chairs</title></head><body>'
    '<nav><a href="/">Home</a> <a href="/shop">Shop</a></nav>'
    "<article><h1>Folding chairs for small rooms</h1>"
    '<p>A folding chair saves space when it is not in use. This guide compares <a href="/guide/frames">frame'
    " materials</a> and seat widths across common designs.</p>"
    "<p>Steel frames carry more weight, while beech frames are lighter and quieter on wooden floors. Both fold flat"
    " to under five centimetres.</p>"
    '<img src="/img/chair.png" alt="A folded chair">'
    "<p>Seat widths range from forty to fifty centimetres; wider seats need a larger storage gap.</p></article>"
    "<footer>Copyright notice and terms of use.</footer></body></html>"
)


def test_markdown_is_the_main_content_with_its_links_and_images() -> None:
    assert markdown(ParsedPage(ARTICLE), FINAL_URL) == (
        "# Folding chairs for small rooms\n\n"
        "A folding chair saves space when it is not in use. This guide compares"
        " [frame materials](https://shop.example.test/guide/frames) and seat widths across common designs.\n\n"
        "Steel frames carry more weight, while beech frames are lighter and quieter on wooden floors. Both fold flat"
        " to under five centimetres.\n\n"
        "![A folded chair](https://shop.example.test/img/chair.png)\n\n"
        "Seat widths range from forty to fifty centimetres; wider seats need a larger storage gap."
    )


def _tile(i: int) -> str:
    return (
        f'<li class="tile"><a href="/p/{i}"><img src="/i/{i}.jpg" alt="Chair {i} photo"></a>'
        f'<h3><a href="/p/{i}" title="Chair {i}">Chair {i}</a></h3><p class="price">{i}9.90 EUR</p>'
        "<button>Add to basket</button></li>"
    )


LISTING = (
    '<!doctype html><html lang="en"><head><title>Chairs</title></head><body>'
    "<header><nav><ul>"
    + "".join(f'<li><a href="/c/{i}">Section {i}</a></li>' for i in range(6))
    + "</ul></nav></header>"
    "<main><h1>Folding chairs</h1><p>Chairs that fold flat, for rooms where space is short and guests are many.</p>"
    '<ol class="grid">' + "".join(_tile(i) for i in range(1, 13)) + "</ol></main>"
    "<footer>Copyright notice and terms of use.</footer></body></html>"
)


def test_listing_markdown_keeps_every_item_with_its_link_image_and_text() -> None:
    made = markdown(ParsedPage(LISTING), FINAL_URL, page_kind="listing")

    assert made.startswith("# Folding chairs\n\nChairs that fold flat")
    items = [line for line in made.splitlines() if line.startswith("- ")]
    assert items[0] == (
        "- [![Chair 1 photo](https://shop.example.test/i/1.jpg)](https://shop.example.test/p/1)"
        " [Chair 1](https://shop.example.test/p/1) 19.90 EUR"
    )
    assert len(items) == 12
    assert all(f"[Chair {i}](https://shop.example.test/p/{i}) {i}9.90 EUR" in items[i - 1] for i in range(1, 13))
    # Buttons are controls, not content (HTML Standard §4.10.6); the site's navigation is not an item.
    assert "basket" not in made
    assert "Section" not in made


# Main content whose source carries layout whitespace (indented blocks, line breaks and blank-line runs, as templates
# write them), a nested list, a `pre` block whose whitespace is content, and a `<base href>`.
# An API answer whose string values hold markup with escaped quotes, as a JSON text writes them (RFC 8259 §7).
