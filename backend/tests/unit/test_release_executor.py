"""The release executor (SPEC-08 §4.12): it parses the body itself, runs each field's steps in order, and gives the
first value that passes the post ops and the field's rule; it needs nothing of the engine but the IR model."""

import json
from typing import Any

import pytest

from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.release_executor import FieldRule, Released, ReleasePage, Value, release_run

PAGE_URL = "https://shop.example.test/p/1"


def _text(value: Value, type_: str | None) -> bool:
    """A stand-in for the text normalizer: a non-empty string."""
    return isinstance(value, str) and value != ""


TEXT = FieldRule(many=False, accepts=_text)
TEXTS = FieldRule(many=True, accepts=lambda value, type_: type_ is not None or isinstance(value, list))


def _ir(fields: dict[str, Any], listing: dict[str, Any] | None = None) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
            "page_kind": "detail" if listing is None else "listing",
            "fetch": {"method": "http"},
            "fields": {
                name: {"steps": steps, "status": "uncorroborated"} if isinstance(steps, list) else steps
                for name, steps in fields.items()
            },
            "listing": listing,
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )


def _run(fields: dict[str, Any], html: str, rules: dict[str, FieldRule] | None = None, **page: Any) -> Released:
    return release_run(_ir(fields), ReleasePage(html, **page), rules or {"title": TEXT})


def test_the_first_step_with_a_valid_value_wins() -> None:
    html = "<html><body><h1></h1><p>a</p><p>b</p><h2>Second</h2><h3>Third</h3></body></html>"
    steps = [{"xpath": "//h4"}, {"xpath": "//h1"}, {"xpath": "//p"}, {"xpath": "//h2"}, {"xpath": "//h3"}]
    # no match, an invalid value, a multi-match, then the value
    assert _run({"title": steps}, html).fields == {"title": "Second"}


def test_a_list_field_takes_every_match_in_document_order() -> None:
    html = "<html><body><li> b </li><li>a</li></body></html>"
    result = _run({"tags": [{"xpath": "//li", "post": [{"trim": {}}]}]}, html, {"tags": TEXTS})
    assert result.fields == {"tags": ["b", "a"]}


def test_xpath_results_are_string_values_numbers_and_attribute_values() -> None:
    html = "<html><body><h1>A <b>b</b></h1><a href='/x'>l</a></body></html>"
    rules = {"t": TEXT, "n": FieldRule(many=False, accepts=lambda value, type_: True), "h": TEXT}
    fields = {"t": [{"css": "h1"}], "n": [{"xpath": "count(//h1)"}], "h": [{"xpath": "//a/@href"}]}
    assert _run(fields, html, rules).fields == {"t": "A b", "n": 1.0, "h": "/x"}


def test_post_ops_run_in_order_and_a_normalizer_op_is_the_rule_s_check() -> None:
    html = "<html><body><h1> Price 12 </h1></body></html>"
    checked: list[tuple[Value, str | None]] = []

    def accepts(value: Value, type_: str | None) -> bool:
        checked.append((value, type_))
        return True

    rule = FieldRule(many=False, accepts=accepts)
    post = [{"trim": {}}, {"money": {}}, {"regex_replace": {"pattern": "[0-9]+", "repl": "N"}}]
    assert _run({"title": [{"xpath": "//h1", "post": post}]}, html, {"title": rule}).fields == {"title": "Price N"}
    assert checked == [("Price 12", "money"), ("Price N", None)]


def test_absolutize_url_resolves_against_the_base_url_and_declines_without_one() -> None:
    html = "<html><body><a href='../q'>l</a></body></html>"
    fields = {"title": [{"xpath": "//a/@href", "post": [{"absolutize_url": {}}]}]}
    assert _run(fields, html, base_url=PAGE_URL).fields == {"title": "https://shop.example.test/q"}
    assert _run(fields, html).fields == {}


def test_a_regex_step_reads_the_body_and_takes_its_first_group() -> None:
    html = '<html><body><div data-sku="AB-1"></div></body></html>'
    assert _run({"title": [{"regex": 'data-sku="([^"]+)"'}]}, html).fields == {"title": "AB-1"}
    assert _run({"title": [{"regex": "AB-[0-9]"}]}, html).fields == {"title": "AB-1"}


def test_a_jsonld_step_reads_typed_nodes_by_type_name_without_subtypes() -> None:
    graph = [
        {"@type": "IndividualProduct", "name": "sub"},
        {"@type": ["http://schema.org/Product"], "name": "by-iri"},
        {"name": "untyped"},
    ]
    block = {"@context": "https://schema.org", "@graph": graph}
    html = f'<html><head><script type="application/ld+json">{json.dumps(block)}</script></head></html>'
    multi = {"title": FieldRule(many=True, accepts=lambda value, type_: True)}
    typed = _run({"title": [{"jsonld": "$['name']", "when_type": "Product"}]}, html, multi)
    assert typed.fields == {"title": ["by-iri"]}
    any_type = _run({"title": [{"jsonld": "$['name']"}]}, html, multi)
    assert any_type.fields == {"title": ["sub", "by-iri"]}


def test_a_jsonld_block_with_a_raw_newline_in_a_string_is_read_as_the_collector_reads_it() -> None:
    block = '{"@context": "https://schema.org", "@type": "Product", "name": "Two\nlines"}'  # a raw newline
    html = f'<html><head><script type="application/ld+json">{block}</script></head></html>'
    multi = {"title": FieldRule(many=True, accepts=lambda value, type_: True)}
    assert _run({"title": [{"jsonld": "$['name']"}]}, html, multi).fields == {"title": ["Two\nlines"]}


@pytest.mark.parametrize(
    ("context", "names"),
    [
        (None, ["by-iri"]),  # no vocabulary in scope: a term is no schema.org type
        ("https://vocab.example.test/", ["by-iri"]),
        ("http://schema.org/", ["term", "by-iri"]),
        ({"@vocab": "https://schema.org/"}, ["term", "by-iri"]),
        (["https://schema.org", {"name": "https://vocab.example.test/name"}], ["term", "by-iri"]),
        (["https://schema.org", None], ["by-iri"]),  # JSON-LD 1.1 §4.1: `null` resets the context
    ],
)
def test_a_jsonld_type_term_is_schema_org_only_where_its_context_says_so(context: Value, names: list[str]) -> None:
    graph = [{"@type": "Product", "name": "term"}, {"@type": "https://schema.org/Product", "name": "by-iri"}]
    block = {"@graph": graph} if context is None else {"@context": context, "@graph": graph}
    html = f'<html><head><script type="application/ld+json">{json.dumps(block)}</script></head></html>'
    multi = {"title": FieldRule(many=True, accepts=lambda value, type_: True)}

    result = _run({"title": [{"jsonld": "$['name']", "when_type": "Product"}]}, html, multi)

    assert result.fields == {"title": names}


def test_jsonpath_reads_the_documents_of_its_source() -> None:
    html = (
        '<html><head><script type="application/ld+json">{"name": "from-ld"}</script>'
        '<script type="application/json">{"p": {"name": "from-state"}}</script>'
        '<script>var n = 1; window.__S = {"q": "from-assignment"};</script>'
        '<script src="/x.js">window.__T = {"q": "external"};</script></head></html>'
    )
    network = (b'{"r": "from-xhr"}', b"not json", b"\xff")

    def value(path: str, source: str) -> Value:
        return _run({"title": [{"jsonpath": path, "source": source}]}, html, network=network).fields.get("title")

    assert value("$['name']", "jsonld") == "from-ld"
    assert value("$['p']['name']", "js_state") == "from-state"
    assert value("$['q']", "js_state") == "from-assignment"  # after a scalar one
    assert value("$['name']", "js_state") is None
    assert value("$['r']", "xhr") == "from-xhr"


def test_steps_it_cannot_run_are_diagnostics_and_the_next_step_runs() -> None:
    html = "<html><body><h1>T</h1></body></html>"
    steps = [{"jsonpath": "$['r']", "source": "api"}, {"xpath": "//h1"}]
    result = _run({"title": steps, "other": [{"xpath": "//h1"}]}, html)
    assert result.fields == {"title": "T"}
    assert result.diagnostics == (
        "title:0: an api source is read through SPEC-09's api recipe executor",
        "other: no rule",
    )


def test_a_structured_value_is_read_by_the_rule_and_an_xpath_value_is_not() -> None:
    # The caller defines how a field reads a structured-data value (`release_rules`: the engine's markup read).
    block = {"@context": "https://schema.org", "@type": "Product", "description": "<p>a</p><p>b</p>"}
    html = (
        f'<html><head><script type="application/ld+json">{json.dumps(block)}</script></head>'
        "<body><p>&lt;i&gt;c&lt;/i&gt;</p></body></html>"
    )
    rule = FieldRule(many=False, accepts=_text, structured=lambda value: f"read:{value}")
    fields = {"description": [{"jsonld": "$['description']"}], "note": [{"xpath": "//body/p"}]}
    result = _run(fields, html, {"description": rule, "note": rule})
    assert result.fields == {"description": "read:<p>a</p><p>b</p>", "note": "<i>c</i>"}


def test_suspended_fields_do_not_run() -> None:
    suspended = {"steps": [{"xpath": "//h1"}], "status": "suspended"}
    fields = {"title": suspended, "heading": [{"xpath": "//h1"}]}
    result = _run(fields, "<html><body><h1>T</h1></body></html>", {"title": TEXT, "heading": TEXT})
    assert result.fields == {"heading": "T"}


def test_a_listing_gives_one_mapping_per_row_and_the_next_page_url() -> None:
    html = (
        "<html><body><em>outside</em><ul>"
        "<li data-k='k1'><em>One</em></li><li><em>a</em><em>b</em></li><li data-k='k3'></li>"
        "</ul><a rel='next' href='?page=2'>n</a></body></html>"
    )
    listing = {
        "row": {"css": "ul > li"},
        "fields": {
            "title": {"steps": [{"xpath": "em"}], "status": "uncorroborated"},
            "key": {"steps": [{"regex": "k[0-9]"}, {"attr": "data-k"}], "status": "uncorroborated"},
        },
        "next": {"xpath": "//a[@rel='next']/@href", "post": [{"absolutize_url": {}}]},
    }
    rules = {"title": TEXT, "key": TEXT, "next_page_url": TEXT}
    result = release_run(_ir({}, listing), ReleasePage(html, base_url=PAGE_URL), rules)
    assert result.rows == ({"title": "One", "key": "k1"}, {}, {"key": "k3"})
    assert result.fields == {"next_page_url": "https://shop.example.test/p/1?page=2"}
    assert result.diagnostics[0] == "key:0: regex, jsonld and jsonpath steps read the whole page, not a row"


def test_a_row_step_selects_elements() -> None:
    listing = {"row": {"jsonld": "$['itemListElement'][*]"}, "fields": {}}
    result = release_run(_ir({}, listing), ReleasePage("<html></html>"), {})
    assert (result.rows, result.diagnostics) == ((), ("row: a row step is an xpath or css step",))
