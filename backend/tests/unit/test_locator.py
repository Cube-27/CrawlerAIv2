"""The locator format (extraction spec): `<scheme>:<address>`, one address grammar per scheme."""

import pytest

from crawlerai.collect.locator import InvalidLocator, Locator, parse_locator


@pytest.mark.parametrize(
    ("text", "scheme", "parts"),
    [
        ("jsonld:0:$['@graph'][2]['offers']", "jsonld", ("0", "$['@graph'][2]['offers']")),
        ("jsonld:12:$", "jsonld", ("12", "$")),
        ("microdata:/html[1]/body[1]/div[3]/span[1]", "microdata", ("/html[1]/body[1]/div[3]/span[1]",)),
        ("microdata:/html[1]/body[1]/*[name()='o:p'][1]", "microdata", ("/html[1]/body[1]/*[name()='o:p'][1]",)),
        (
            "dom:/html[1]/body[1]/table[1]/tbody[1]/tr[1]/td[1]",
            "dom",
            ("/html[1]/body[1]/table[1]/tbody[1]/tr[1]/td[1]",),
        ),
        ("meta:og:title", "meta", ("og:title",)),
        ("meta:description", "meta", ("description",)),
        (
            "js_state:/html[1]/body[1]/script[2]:$['props']['price']",
            "js_state",
            ("/html[1]/body[1]/script[2]", "$['props']['price']"),
        ),
        ("xhr:3:$['data'][0]['name']", "xhr", ("3", "$['data'][0]['name']")),
        ("adapter:job_board:$['title']", "adapter", ("job_board", "$['title']")),
        ("api:0192a1b2-c3d4:$['items'][0]", "api", ("0192a1b2-c3d4", "$['items'][0]")),
        ("config:price:1:div.a > span:nth-child(2)", "config", ("price", "1", "div.a > span:nth-child(2)")),
        ("text:10-24", "text", ("10", "24")),
        ("derived:canonical_link", "derived", ("canonical_link",)),
        ("derived:final_url", "derived", ("final_url",)),
    ],
)
def test_parse_reads_scheme_and_address_parts(text: str, scheme: str, parts: tuple[str, ...]) -> None:
    assert parse_locator(text) == Locator(scheme, parts)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "jsonld",
        "css:div.price",  # unknown scheme
        "JSONLD:0:$",  # schemes are lower case
        "jsonld:0:",  # empty JSONPath
        "jsonld:x:$",  # block index is not a number
        "jsonld:01:$",  # leading zero: two spellings of one index
        "jsonld:٣:$",  # only ASCII digits
        "jsonld:0:@graph",  # a JSONPath query starts with `$`
        "microdata:html/body",  # an XPath here is absolute
        "microdata:",
        "meta:",
        "meta:og title",  # a meta property name holds no whitespace
        "js_state:/html[1]/body[1]/div[1]:$",  # the XPath must name a script element
        "js_state:/html[1]/body[1]/script[1]",  # no JSONPath
        "xhr:-1:$",
        "adapter::$",
        "api:id with space:$",
        "config:Price:0:span",  # a field name is lower case
        "config:price:x:span",
        "config:price:0:",
        "text:5-5",  # an empty span holds no value
        "text:9-3",
        "text:3",
        "text:-3-9",
        "derived:",
        "derived:absolutize",  # an absolutized value keeps its source candidate's locator
        "derived:final_url:x",
    ],
)
def test_parse_refuses_malformed_locators(text: str) -> None:
    with pytest.raises(InvalidLocator):
        parse_locator(text)
