"""The engine executor (SPEC-08 §4.3): an IR's steps run in order over the `ParsedPage`, the first valid value is the
field's `config` candidate, multi-matches are invalid, and listings give one entity per row."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from lxml import html as lxml_html
from selectolax import lexbor

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.config import Executed
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.executor import ConfigMismatch, EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.resolve.evidence import assess_fields
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import PRECEDENCE_TYPES, PageFacts, Resolver
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
NO_BASE = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))

TEXT = FieldSpec(type=FieldType.TEXT, description="d")
URL = FieldSpec(type=FieldType.URL, description="d")
TEXTS = FieldSpec(type=FieldType.LIST, description="d", item=FieldSpec(type=FieldType.TEXT))
MONEY = FieldSpec(type=FieldType.MONEY, description="d")


def _schema(page_kind: str = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef.model_validate(
        {
            "id": SchemaId(uuid7()),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "page_kind": page_kind,
            "fields": fields,
        }
    )


def _ir(fields: dict[str, Any], *, page_kind: str = "detail", listing: dict[str, Any] | None = None) -> EngineExecutor:
    document = {
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
    return EngineExecutor(ExtractionConfigIR.model_validate(document), VOCABULARY)


def _run(executor: EngineExecutor, html: str, schema: SchemaDef, ctx: Context = CTX, **page: Any) -> Executed:
    return executor.execute(ParsedPage(html, **page), schema, ctx)


def _only(result: Executed) -> Candidate:
    (candidate,) = result.candidates
    return candidate


def _config(field: str, raw: Any, normalized: Any, locator: str, entity_id: str = "page") -> Candidate:
    return Candidate(
        field=field,
        entity_id=entity_id,
        source_kind="config",
        raw=raw,
        normalized=normalized,
        locator=locator,
        independent=False,
    )


def test_an_xpath_step_proposes_the_node_string_value_owned_by_the_page() -> None:
    executor = _ir({"title": [{"xpath": "//h1"}]})
    result = _run(executor, "<h1>Blue <b>mug</b></h1>", _schema(title=TEXT))
    assert result == Executed(
        rows=(), candidates=(_config("title", "Blue mug", Ok("Blue mug"), "config:title:0://h1"),)
    )
    # No match gives no candidate.
    assert _run(executor, "<p>x</p>", _schema(title=TEXT)) == Executed(rows=(), candidates=())


def test_the_first_step_with_a_valid_value_wins() -> None:
    steps = [{"xpath": "//h2"}, {"xpath": "//h1[@id='other']"}, {"xpath": "//h1[@id='t']"}, {"xpath": "//h1"}]
    candidate = _only(_run(_ir({"title": steps}), "<h1 id='t'>Mug</h1>", _schema(title=TEXT)))
    assert candidate.locator == "config:title:2://h1[@id='t']"
    assert candidate.normalized == Ok("Mug")


def test_a_multi_match_is_invalid_and_the_next_step_runs() -> None:
    html = "<p class='p'>1</p><p class='p'>2</p><span>Mug</span>"
    alone = _only(_run(_ir({"title": [{"xpath": "//p"}]}), html, _schema(title=TEXT)))
    assert (alone.raw, alone.normalized) == (["1", "2"], Invalid("multi_match"))
    fallback = _only(_run(_ir({"title": [{"xpath": "//p"}, {"xpath": "//span"}]}), html, _schema(title=TEXT)))
    assert (fallback.locator, fallback.normalized) == ("config:title:1://span", Ok("Mug"))


def test_without_a_valid_value_the_first_match_is_proposed_with_its_decline() -> None:
    steps = [{"xpath": "//h2"}, {"xpath": "//p"}, {"xpath": "//span"}]
    candidate = _only(_run(_ir({"price": steps}), "<p>soon</p><span>later</span>", _schema(price=MONEY)))
    assert candidate.locator == "config:price:1://p"
    assert (candidate.raw, candidate.normalized) == ("soon", Invalid("no_amount"))


def test_a_list_field_takes_every_match_in_document_order() -> None:
    html = "<ul><li>a</li><li>b</li><li>c</li></ul>"
    candidate = _only(_run(_ir({"tags": [{"xpath": "//li"}]}), html, _schema(tags=TEXTS)))
    assert candidate.normalized == Ok(["a", "b", "c"])


def test_string_and_attribute_results() -> None:
    html = "<h1 data-k=' v '>  Blue   mug </h1><a href='/next'>n</a>"
    schema = _schema(title=TEXT, url=URL)
    result = _run(_ir({"title": [{"xpath": "normalize-space(//h1)"}], "url": [{"xpath": "//a/@href"}]}), html, schema)
    assert [(c.field, c.raw) for c in result.candidates] == [("title", "Blue mug"), ("url", "/next")]


def test_a_css_step_runs_its_translation_and_is_located_by_its_css() -> None:
    candidate = _only(
        _run(_ir({"title": [{"css": "div.t > span"}]}), "<div class='t'><span>Mug</span></div>", _schema(title=TEXT))
    )
    assert (candidate.locator, candidate.normalized) == ("config:title:0:div.t > span", Ok("Mug"))


def test_a_regex_step_reads_the_body_and_takes_its_first_group() -> None:
    html = "<script>var s = 'sku: AB12';</script><p>x</p>"
    candidate = _only(_run(_ir({"sku": [{"regex": r"sku: (\w+)"}]}), html, _schema(sku=TEXT)))
    assert (candidate.raw, candidate.locator) == ("AB12", r"config:sku:0:sku: (\w+)")


def _ld(*blocks: Any) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)


def test_a_jsonld_step_reads_nodes_of_its_type_and_subtypes() -> None:
    html = _ld(
        {
            "@context": "https://schema.org",
            "@graph": [{"@type": "Organization", "name": "Org"}, {"@type": "Product", "name": "Mug"}],
        }
    )
    schema = _schema(title=TEXT)
    typed = _only(_run(_ir({"title": [{"jsonld": "$['name']", "when_type": "Product"}]}), html, schema))
    assert typed.raw == "Mug"
    untyped = _only(_run(_ir({"title": [{"jsonld": "$['name']"}]}), html, schema))
    assert untyped.normalized == Invalid("multi_match")
    # schema.org: an Organization is a Thing, so `Thing` selects both nodes.
    thing = _only(_run(_ir({"title": [{"jsonld": "$['name']", "when_type": "Thing"}]}), html, schema))
    assert thing.raw == ["Org", "Mug"]


def test_jsonpath_reads_the_documents_of_its_source() -> None:
    html = (
        _ld({"name": "from-ld"})
        + '<script type="application/json">{"p": {"name": "from-state"}}</script>'
        + '<script>window.s = {"q": "from-assignment"};</script>'
    )
    network = (b'{"r": "from-xhr"}', b"not json")
    schema = _schema(title=TEXT)

    def value(path: str, source: str) -> Any:
        return _only(_run(_ir({"title": [{"jsonpath": path, "source": source}]}), html, schema, network=network)).raw

    assert value("$['name']", "jsonld") == "from-ld"
    assert value("$['p']['name']", "js_state") == "from-state"
    assert value("$['q']", "js_state") == "from-assignment"
    assert value("$['r']", "xhr") == "from-xhr"


def test_steps_the_engine_cannot_run_are_diagnostics_and_the_next_step_runs() -> None:
    steps = [{"jsonpath": "$['r']", "source": "api"}, {"jsonpath": "$..name", "source": "jsonld"}, {"xpath": "//h1"}]
    result = _run(_ir({"title": steps}), _ld({"name": "x"}) + "<h1>Mug</h1>", _schema(title=TEXT))
    assert _only(result).locator == "config:title:2://h1"
    assert [d.split(":", 3)[2] for d in result.diagnostics] == ["0", "1"]
    assert "SPEC-09" in result.diagnostics[0]
    assert "unsupported_jsonpath" in result.diagnostics[1]


def test_post_ops_run_in_order_before_the_field_normalizer() -> None:
    step = {"xpath": "//p", "post": [{"regex_replace": {"pattern": r"^Ref:\s*", "repl": ""}}, {"trim": {}}]}
    candidate = _only(_run(_ir({"sku": [step]}), "<p>Ref:  AB-1  </p>", _schema(sku=TEXT)))
    assert (candidate.raw, candidate.normalized) == ("AB-1", Ok("AB-1"))


def test_absolutize_url_resolves_against_the_base_url_and_declines_without_one() -> None:
    step = {"xpath": "//a/@href", "post": [{"absolutize_url": {}}]}
    executor, schema = _ir({"url": [step]}), _schema(url=URL)
    resolved = _only(_run(executor, "<a href='/p/2'>x</a>", schema))
    assert resolved.raw == "https://shop.example.test/p/2"
    unresolved = _only(_run(executor, "<a href='/p/2'>x</a>", schema, NO_BASE))
    assert (unresolved.raw, unresolved.normalized) == ("/p/2", Invalid("no_base_url"))


def test_a_normalizer_op_checks_the_value_without_changing_it() -> None:
    steps = [{"xpath": "//p", "post": [{"money": {}}]}, {"xpath": "//span", "post": [{"money": {}}]}]
    html = "<p>none</p><span>12.50 EUR</span>"
    candidate = _only(_run(_ir({"title": steps}), html, _schema(title=TEXT)))
    assert (candidate.locator, candidate.raw) == ("config:title:1://span", "12.50 EUR")


def test_suspended_fields_do_not_run() -> None:
    fields = {"title": {"steps": [{"xpath": "//h1"}], "status": "suspended"}, "sku": [{"xpath": "//p"}]}
    executor = _ir(fields)
    assert dict(executor.field_status) == {"sku": "uncorroborated"}
    result = _run(executor, "<h1>Mug</h1><p>AB1</p>", _schema(title=TEXT, sku=TEXT))
    assert [c.field for c in result.candidates] == ["sku"]


def test_a_config_for_another_schema_does_not_run() -> None:
    executor = _ir({"title": [{"xpath": "//h1"}]})
    schema = _schema(title=TEXT).model_copy(update={"name": "another"})
    page = ParsedPage("<h1>x</h1>")
    with pytest.raises(ConfigMismatch):
        executor.execute(page, schema, CTX)


LISTING_HTML = """
<ul>
  <li class="r"><a href="/a">A</a><span>1.00 EUR</span></li>
  <li class="r"><a href="/b">B</a></li>
</ul>
<a rel="next" href="?page=2">next</a>
"""


def _listing_schema() -> SchemaDef:
    return _schema(
        page_kind="listing",
        title=TEXT,
        url=URL,
        price=MONEY,
        next_page_url=FieldSpec(type=FieldType.URL, description="d", scope="page"),
    )


def test_a_listing_gives_one_row_entity_per_row_with_fields_relative_to_it() -> None:
    listing = {
        "row": {"css": "li.r"},
        "fields": {
            "title": {"steps": [{"xpath": "a"}], "status": "uncorroborated"},
            "url": {"steps": [{"xpath": "a/@href", "post": [{"absolutize_url": {}}]}], "status": "uncorroborated"},
            "price": {"steps": [{"xpath": "span"}], "status": "uncorroborated"},
        },
        "next": {"xpath": "//a[@rel='next']/@href", "post": [{"absolutize_url": {}}]},
    }
    result = _run(_ir({}, page_kind="listing", listing=listing), LISTING_HTML, _listing_schema())
    assert result.rows == (
        Entity(id="config:row:0", types=("ListItem",), urls=(), parent=None),
        Entity(id="config:row:1", types=("ListItem",), urls=(), parent=None),
    )
    assert [(c.entity_id, c.field, c.raw) for c in result.candidates] == [
        ("config:row:0", "title", "A"),
        ("config:row:0", "url", "https://shop.example.test/a"),
        ("config:row:0", "price", "1.00 EUR"),
        ("config:row:1", "title", "B"),
        ("config:row:1", "url", "https://shop.example.test/b"),
        ("page", "next_page_url", "https://shop.example.test/p/1?page=2"),
    ]


def test_page_wide_steps_do_not_run_in_a_row() -> None:
    listing = {"row": {"css": "li.r"}, "fields": {"title": {"steps": [{"regex": "(A)"}], "status": "uncorroborated"}}}
    result = _run(_ir({}, page_kind="listing", listing=listing), LISTING_HTML, _listing_schema())
    assert result.candidates == ()
    # One per row.
    assert (
        result.diagnostics
        == ("config:title:0: not relative to a row: regex, jsonld and jsonpath steps read the whole page",) * 2
    )


def test_a_row_step_selects_elements() -> None:
    listing = {"row": {"jsonld": "$['itemListElement'][*]"}, "fields": {}}
    result = _run(_ir({}, page_kind="listing", listing=listing), LISTING_HTML, _listing_schema())
    assert result.rows == ()
    assert result.diagnostics == ("config:row: a row step selects elements, so it is an xpath or css step",)


def test_steps_read_the_parsed_page_and_never_parse_the_body_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-26: every step type on one page leaves one lxml and one selectolax parse."""
    calls = {"lxml": 0, "selectolax": 0}
    lxml_parse, selectolax_parse = lxml_html.document_fromstring, lexbor.LexborHTMLParser

    def count_lxml(*args: Any, **kwargs: Any) -> Any:
        calls["lxml"] += 1
        return lxml_parse(*args, **kwargs)

    def count_selectolax(*args: Any, **kwargs: Any) -> Any:
        calls["selectolax"] += 1
        return selectolax_parse(*args, **kwargs)

    monkeypatch.setattr(lxml_html, "document_fromstring", count_lxml)
    monkeypatch.setattr(lexbor, "LexborHTMLParser", count_selectolax)
    fields = {
        "a": [{"xpath": "//h1"}],
        "b": [{"css": "h1"}],
        "c": [{"regex": "(Mug)"}],
        "d": [{"jsonld": "$['name']"}],
        "e": [{"jsonpath": "$['name']", "source": "jsonld"}],
        "f": [{"jsonpath": "$['q']", "source": "js_state"}],
        "g": [{"attr": "lang"}],
    }
    html = (
        "<html lang='en'>"
        + _ld({"@context": "https://schema.org", "@type": "Product", "name": "Mug"})
        + "<h1>Mug</h1></html>"
    )
    schema = _schema("detail", **dict.fromkeys(fields, TEXT))
    result = _run(_ir(fields), html, schema)
    # Every step but the js_state one, which finds no state.
    assert [c.field for c in result.candidates] == ["a", "b", "c", "d", "e", "g"]
    assert calls == {"lxml": 1, "selectolax": 1}


def test_config_candidates_enter_resolution_with_their_field_status_bucket() -> None:
    """§8.4: config candidates resolve like any other; a corroborated field's value is `config_corroborated`, an
    uncorroborated one's `config_uncorroborated` (§10)."""
    html = (
        _ld({"@context": "https://schema.org", "@type": "Product", "name": "Mug"}) + "<h1>Blue mug</h1><p>12.50 EUR</p>"
    )
    page, schema = ParsedPage(html), _schema("detail", title=TEXT, price=MONEY)
    fields = {"title": {"steps": [{"xpath": "//h1"}], "status": "corroborated"}, "price": [{"xpath": "//p"}]}
    executor = _ir(fields)
    collected, executed = JsonLdCollector(VOCABULARY).collect(page, schema, CTX), executor.execute(page, schema, CTX)
    (product,) = collected.entities
    resolver = Resolver(
        graph=EntityGraph.of((*collected.entities, *executed.rows), VOCABULARY),
        target=product,
        page=PageFacts.of(PAGE_URL, lambda _: True),
        orders=dict.fromkeys(PRECEDENCE_TYPES, ("config", "jsonld")),
    )
    decisions = resolver.prefer(schema, (*collected.candidates, *executed.candidates))
    corroborated = frozenset(name for name, status in executor.field_status.items() if status == "corroborated")
    outcomes = assess_fields(schema, decisions, None, corroborated=corroborated)
    assert {name: (o.value, o.evidence, o.locator) for name, o in outcomes.items()} == {
        "title": ("Blue mug", "config_corroborated", "config:title:0://h1"),
        "price": ({"amount": "12.50", "currency": "EUR"}, "config_uncorroborated", "config:price:0://p"),
    }


@pytest.mark.parametrize(
    ("order", "evidence", "locator"),
    [
        (("config", "jsonld"), "config_corroborated", "config:title:0:$['name']"),
        (("jsonld", "config"), "structured", "jsonld:0:$['name']"),
    ],
)
def test_a_config_value_equal_to_its_source_never_counts_as_agreement(
    order: tuple[SourceKind, ...], evidence: str, locator: str
) -> None:
    """§8.1, §10: config candidates are not independent, so a `jsonld` step reading the node the JSON-LD collector
    reads is the same evidence once, not `agreed`."""
    page = ParsedPage(_ld({"@context": "https://schema.org", "@type": "Product", "name": "Mug"}))
    schema = _schema("detail", title=FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name"))
    executor = _ir({"title": {"steps": [{"jsonld": "$['name']", "when_type": "Product"}], "status": "corroborated"}})
    collected, executed = JsonLdCollector(VOCABULARY).collect(page, schema, CTX), executor.execute(page, schema, CTX)
    (product,) = collected.entities
    resolver = Resolver(
        graph=EntityGraph.of(collected.entities, VOCABULARY),
        target=product,
        page=PageFacts.of(PAGE_URL, lambda _: True),
        orders=dict.fromkeys(PRECEDENCE_TYPES, order),
    )
    decisions = resolver.prefer(schema, (*collected.candidates, *executed.candidates))
    outcome = assess_fields(schema, decisions, None, corroborated=frozenset({"title"}))["title"]
    assert (outcome.value, outcome.evidence, outcome.locator) == ("Mug", evidence, locator)
