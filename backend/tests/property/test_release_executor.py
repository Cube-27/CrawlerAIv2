"""The release executor: it parses the body itself, runs each field's steps in order,
and gives the first value that passes the post ops and the field's rule; it needs nothing of the engine but the IR
model. The two executors agree: on generated pages and IRs, every field value the engine executor proposes as valid is
the value the release executor gives, and the release executor gives none where the engine has no valid value. Their
code is independent (`.importlinter`), so agreement is the evidence the release check uses."""

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from snowcrawl.collect.base import PAGE
from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.config_ir.executor import EngineExecutor, row_id
from snowcrawl.config_ir.model import ExtractionConfigIR
from snowcrawl.config_ir.release_executor import FieldRule, Released, ReleasePage, Value, release_run
from snowcrawl.config_ir.release_rules import release_rules
from snowcrawl.content.page import ParsedPage
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import SchemaId
from snowcrawl.normalize.base import Context, Ok
from snowcrawl.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"

TEXT = FieldSpec(type=FieldType.TEXT, description="d")
URL = FieldSpec(type=FieldType.URL, description="d")
TEXTS = FieldSpec(type=FieldType.LIST, description="d", item=FieldSpec(type=FieldType.TEXT))
DETAIL_FIELDS = {"title": TEXT, "link": URL, "tags": TEXTS}
LISTING_FIELDS = {"title": TEXT, "link": URL, "next_page_url": URL}


def _text(value: Value, type_: str | None) -> bool:
    """A stand-in for the text normalizer: a non-empty string."""
    return isinstance(value, str) and value != ""


TEXT_RULE = FieldRule(many=False, accepts=_text)

_value = st.from_regex(r"[A-Za-z0-9&<]([A-Za-z0-9&< ]{0,10}[A-Za-z0-9&<])?", fullmatch=True)
_padded = st.builds(lambda pad, v: f"{pad}{v}{pad}", st.sampled_from(["", " ", "\n "]), _value)
_href = st.sampled_from(["/p/2", "https://shop.example.test/q", "", "rel?x=1"])

# Steps over every selector kind and post op, for the page `_detail_page` builds.
_DETAIL_STEPS = [
    {"xpath": "normalize-space(//span[@class='v'])"},
    {"css": "span.v", "post": [{"trim": {}}]},
    {"xpath": "//span[@class='v']", "post": [{"text": {}}, {"regex_replace": {"pattern": "([a-z]+)", "repl": "\\1-"}}]},
    {"xpath": "//a/@href", "post": [{"absolutize_url": {}}]},
    {"regex": 'data-x="([^"]*)"'},
    {"jsonld": "$['name']", "when_type": "Product"},
    {"jsonld": "$['offers'][*]['sku']", "when_type": "Product"},
    {"jsonpath": "$['p']['name']", "source": "js_state"},
    {"jsonpath": "$['items'][*]", "source": "xhr"},
    {"jsonpath": "$['r']", "source": "api"},
]
_ROW_STEPS = [
    {"xpath": "em"},
    {"xpath": "normalize-space(em)"},
    {"attr": "data-k"},
    {"xpath": "a/@href", "post": [{"absolutize_url": {}}]},
    {"regex": "[a-z]+"},
]
_steps = st.lists(st.sampled_from(_DETAIL_STEPS), min_size=1, max_size=3)
_row_steps = st.lists(st.sampled_from(_ROW_STEPS), min_size=1, max_size=3)


def _schema(page_kind: str, fields: dict[str, FieldSpec]) -> SchemaDef:
    document = {"id": SchemaId(uuid7()), "origin": "user", "status": "active", "name": "synthetic"}
    return SchemaDef.model_validate({**document, "page_kind": page_kind, "fields": fields})


def _ir(page_kind: str, fields: dict[str, Any], listing: dict[str, Any] | None = None) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
            "page_kind": page_kind,
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


def _engine_values(
    executor: EngineExecutor, page: ParsedPage, schema: SchemaDef, ctx: Context
) -> dict[tuple[str, str], Any]:
    """The engine's valid values by owner and field."""
    result = executor.execute(page, schema, ctx)
    return {(c.entity_id, c.field): c.raw for c in result.candidates if isinstance(c.normalized, Ok)}


def _context(base: bool) -> Context:
    url = PAGE_URL if base else None
    return Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=url, page_url=url)


def _run(
    fields: dict[str, Any], html: str, rules: dict[str, FieldRule] | None = None, network: tuple[bytes, ...] = ()
) -> Released:
    return release_run(_ir("detail", fields), ReleasePage(ParsedPage(html, network)), rules or {"title": TEXT_RULE})


# Each example parses the page and runs both executors; its time depends on the machine, not on the property.
_RUNS_BOTH_EXECUTORS = settings(deadline=None)


@st.composite
def _detail_page(draw: st.DrawFn) -> tuple[str, tuple[bytes, ...]]:
    spans = "".join(f"<span class='v'>{escape(v)}</span>" for v in draw(st.lists(_padded, max_size=3)))
    links = "".join(f"<a href='{escape(h)}'>l</a>" for h in draw(st.lists(_href, max_size=2)))
    nodes = [
        {"@type": t, "name": n, "offers": [{"@type": "Offer", "sku": s} for s in skus]}
        for t, n, skus in draw(
            st.lists(st.tuples(st.sampled_from(["Product", "Offer"]), _value, st.lists(_value, max_size=2)), max_size=2)
        )
    ]
    jsonld = json.dumps({"@context": "https://schema.org", "@graph": nodes})
    state = json.dumps({"p": {"name": draw(_value)}}) if draw(st.booleans()) else "1"
    attr = escape(draw(_value), quote=True)
    html = (
        f"<html><head><script type='application/ld+json'>{jsonld}</script>"
        f"<script>window.__S = {state};</script></head>"
        f'<body><div data-x="{attr}">{spans}{links}</div></body></html>'
    )
    network = tuple(json.dumps({"items": items}).encode() for items in draw(st.lists(st.lists(_value), max_size=2)))
    return html, network


@_RUNS_BOTH_EXECUTORS
@given(
    _detail_page(),
    st.fixed_dictionaries({}, optional={"title": _steps, "link": _steps, "tags": _steps}),
    st.booleans(),
)
def test_the_executors_agree_on_page_fields(
    page: tuple[str, tuple[bytes, ...]], fields: dict[str, Any], base: bool
) -> None:
    html, network = page
    ir, schema, ctx = _ir("detail", fields), _schema("detail", DETAIL_FIELDS), _context(base)
    engine = _engine_values(EngineExecutor(ir, VOCABULARY), ParsedPage(html, network), schema, ctx)
    released = release_run(ir, ReleasePage(ParsedPage(html, network), ctx.base_url), release_rules(schema, ctx))
    assert released.fields == {name: value for (owner, name), value in engine.items() if owner == PAGE}


@st.composite
def _listing_page(draw: st.DrawFn) -> str:
    rows = draw(st.lists(st.tuples(st.lists(_padded, max_size=2), st.none() | _value, st.none() | _href), max_size=4))
    items = "".join(
        "<li"
        + ("" if key is None else f" data-k='{escape(key, quote=True)}'")
        + ">"
        + "".join(f"<em>{escape(v)}</em>" for v in ems)
        + ("" if href is None else f"<a href='{escape(href)}'>r</a>")
        + "</li>"
        for ems, key, href in rows
    )
    next_link = "".join(f"<a rel='next' href='{escape(h)}'>n</a>" for h in draw(st.lists(_href, max_size=2)))
    return f"<html><body><em>outside</em><ul>{items}</ul>{next_link}</body></html>"


@_RUNS_BOTH_EXECUTORS
@given(
    _listing_page(),
    st.fixed_dictionaries({}, optional={"title": _row_steps, "link": _row_steps}),
    st.booleans(),
)
def test_the_executors_agree_on_listing_rows_and_the_next_page(page: str, fields: dict[str, Any], base: bool) -> None:
    listing = {
        "row": {"css": "ul > li"},
        "fields": {name: {"steps": steps, "status": "uncorroborated"} for name, steps in fields.items()},
        "next": {"xpath": "//a[@rel='next']/@href", "post": [{"absolutize_url": {}}]},
    }
    ir, schema, ctx = _ir("listing", {}, listing), _schema("listing", LISTING_FIELDS), _context(base)
    engine = _engine_values(EngineExecutor(ir, VOCABULARY), ParsedPage(page), schema, ctx)
    released = release_run(ir, ReleasePage(ParsedPage(page), ctx.base_url), release_rules(schema, ctx))
    rows = [
        {name: value for (owner, name), value in engine.items() if owner == row_id(n)}
        for n in range(len(released.rows))
    ]
    assert list(released.rows) == rows
    assert released.fields == {name: value for (owner, name), value in engine.items() if owner == PAGE}
    assert len(released.rows) == page.count("<li")


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
    result = _run(fields, "<html><body><h1>T</h1></body></html>", {"title": TEXT_RULE, "heading": TEXT_RULE})
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
    rules = {"title": TEXT_RULE, "key": TEXT_RULE, "next_page_url": TEXT_RULE}
    result = release_run(_ir("listing", {}, listing), ReleasePage(ParsedPage(html), PAGE_URL), rules)
    assert result.rows == ({"title": "One", "key": "k1"}, {}, {"key": "k3"})
    assert result.fields == {"next_page_url": "https://shop.example.test/p/1?page=2"}
    assert result.diagnostics[0] == "key:0: regex, jsonld and jsonpath steps read the whole page, not a row"


def test_attribute_and_magento_init_json_are_read_as_the_engine_reads_them() -> None:
    html = (
        '<html><head><script type="text/x-magento-init">{"#form": {"name": "Init"}}</script></head><body>'
        '<div data-page="{&quot;props&quot;: {&quot;name&quot;: &quot;Page&quot;}}"></div>'
        '<div data-config="{&quot;props&quot;: {&quot;name&quot;: &quot;Other&quot;}}"></div>'
        '<astro-island props="{&quot;item&quot;: [0, {&quot;sizes&quot;: [1, [[0, &quot;S&quot;]]]}]}"></astro-island>'
        "</body></html>"
    )
    attr = [{"jsonpath": "$['props']['name']", "source": "attr"}]
    init = [{"jsonpath": "$['#form']['name']", "source": "js_state"}]
    astro = [{"jsonpath": "$['item']['sizes'][0]", "source": "attr"}]
    rules = {"title": TEXT_RULE, "init": TEXT_RULE, "astro": TEXT_RULE}
    assert _run({"title": attr, "init": init, "astro": astro}, html, rules).fields == {
        "title": "Page",
        "init": "Init",
        "astro": "S",
    }
