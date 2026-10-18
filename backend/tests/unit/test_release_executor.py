"""The release executor (learning-configs spec): it parses the body itself, runs each field's steps in order, and gives
the first value that passes the post ops and the field's rule; it needs nothing of the engine but the IR model."""

from typing import Any

from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.release_executor import FieldRule, Released, ReleasePage, Value, release_run

PAGE_URL = "https://shop.example.test/p/1"


def _text(value: Value, type_: str | None) -> bool:
    """A stand-in for the text normalizer: a non-empty string."""
    return isinstance(value, str) and value != ""


TEXT = FieldRule(many=False, accepts=_text)


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


def test_jsonpath_reads_the_documents_of_its_source() -> None:
    html = (
        '<html><head><script type="application/ld+json">{"name": "from-ld"}</script>'
        '<script type="application/json">{"p": {"name": "from-state"}}</script>'
        '<script>var n = 1; window.__S = {"q": "from-assignment"};</script>'
        '<script src="/x.js">window.__T = {"q": "external"};</script></head></html>'
    )
    network = (b"[" * 100_000 + b"]" * 100_000, b'{"r": "from-xhr"}', b"not json", b"\xff")

    def value(path: str, source: str) -> Value:
        return _run({"title": [{"jsonpath": path, "source": source}]}, html, network=network).fields.get("title")

    assert value("$['name']", "jsonld") == "from-ld"
    assert value("$['p']['name']", "js_state") == "from-state"
    assert value("$['q']", "js_state") == "from-assignment"  # after a scalar one
    assert value("$['name']", "js_state") is None
    assert value("$['r']", "xhr") == "from-xhr"


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
