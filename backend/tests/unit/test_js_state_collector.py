"""The embedded JSON state collector (extraction spec): JSON in inline scripts, admitted only by
equality to another source kind's candidate (not independent, owned by that candidate's entity) or, for a field with no
such candidate whose type has a checkable syntax, by visibility in the page text (independent, owned by the page, or by
the array row holding it)."""

import json
from datetime import UTC, datetime
from html import escape

import pytest
from pydantic import JsonValue

from crawlerai.collect.admission import Admitted
from crawlerai.collect.base import ARRAY_ROW, PAGE, Candidate, Entity
from crawlerai.collect.currencies import declared_currencies
from crawlerai.collect.js_state import JsStateCollector, state_documents
from crawlerai.content.page import ParsedPage
from crawlerai.content.state_decoders import revive_astro_props
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Context, NormalizeResult, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    },
)
SCRIPT = "/html[1]/head[1]/script[1]"


def _page(script: str, body: str = "", script_type: str | None = None) -> ParsedPage:
    type_attribute = "" if script_type is None else f' type="{script_type}"'
    return ParsedPage(f"<html><head><script{type_attribute}>{script}</script></head><body>{escape(body)}</body></html>")


def _state(document: JsonValue, body: str = "") -> ParsedPage:
    return _page(f"window.__STATE__ = {json.dumps(document)};", body)


def _candidate(
    field: str,
    raw: JsonValue,
    normalized: NormalizeResult,
    *,
    source_kind: SourceKind = "js_state",
    entity_id: str = "page",
    locator: str,
    independent: bool,
) -> Candidate:
    return Candidate(
        field=field,
        entity_id=entity_id,
        source_kind=source_kind,
        raw=raw,
        normalized=normalized,
        locator=locator,
        independent=independent,
    )


EUR_19_99 = Ok({"amount": "19.99", "currency": "EUR"})
JSONLD_PRICE = _candidate(
    "price",
    {"price": "19.99", "priceCurrency": "EUR"},
    EUR_19_99,
    source_kind="jsonld",
    entity_id="jsonld:0:$['offers']",
    locator="jsonld:0:$['offers']",
    independent=True,
)


def _collect(page: ParsedPage, *others: Candidate) -> Admitted:
    return JsStateCollector().collect(page, SCHEMA, CTX, others)


def test_a_value_equal_to_another_kinds_candidate_is_owned_by_its_entity_and_not_independent() -> None:
    # Not visible: equality alone admits it. Equality is the field type's (schemas spec), not the raw string's.
    result = _collect(_state({"p": {"cost": "€19.99"}}), JSONLD_PRICE)

    assert result == Admitted(
        candidates=(
            _candidate(
                "price",
                "€19.99",
                EUR_19_99,
                entity_id="jsonld:0:$['offers']",
                locator=f"js_state:{SCRIPT}:$['p']['cost']",
                independent=False,
            ),
        )
    )


# The script-reading tests probe with a visible price: a price is admitted by visibility alone (§8.1).
@pytest.mark.parametrize(
    "script",
    [
        'window.__S = {"cost": "€5.00"};',
        'var s={"cost": "€5.00"}',
        'let s = {"cost": "€5.00"}; init(s);',
        'if (x) { go(); }\nconst s =\n {"cost": "€5.00"}\n;',
    ],
)
def test_the_json_after_an_assignment_is_the_state(script: str) -> None:
    result = _collect(_page(script, body="€5.00"))

    assert [(c.field, c.locator) for c in result.candidates] == [("price", f"js_state:{SCRIPT}:$['cost']")]


# Array rows (Appendix A #55): an object item of an array of two or more objects is one of a set of items.
ROWS = "js_state:0:$['items']"


def test_a_visible_value_in_an_array_row_is_owned_by_its_row() -> None:
    document: JsonValue = {
        "items": [{"url": "/p/1", "cost": "€19.99"}, {"url": "https://other.example.test/p/2", "cost": "€5"}]
    }

    result = _collect(_state(document, body="Now €19.99, also €5.00"))

    assert [(c.entity_id, c.independent) for c in result.candidates if c.field == "price"] == [
        (f"{ROWS}[0]", True),
        (f"{ROWS}[1]", True),
    ]
    assert result.entities == (
        Entity(id=f"{ROWS}[0]", types=(ARRAY_ROW,), urls=(PAGE_URL,), parent=PAGE),
        Entity(id=f"{ROWS}[1]", types=(ARRAY_ROW,), urls=("https://other.example.test/p/2",), parent=PAGE),
    )


def _documents(page: ParsedPage) -> list[JsonValue]:
    return [document.data for document in state_documents(page, [])]


LAMP = {"name": "Desk lamp", "price": 19.99, "currency": "EUR"}


def test_a_devalue_iife_reads_with_its_parameters_substituted() -> None:
    # devalue `uneval` output as Nuxt 2 writes it after `window.__NUXT__=`: repeated values hoisted into parameters.
    script = (
        'window.__NUXT__=(function(a,b,c){return {layout:"default",data:[{product:{name:"Desk lamp",price:a,'
        'currency:b,tags:[c,c]}}],state:{cart:{currency:b}},serverRendered:true,routePath:"\\u002Fp\\u002Flamp"}}'
        '(19.99,"EUR",void 0));'
    )

    assert _documents(_page(script)) == [
        {
            "layout": "default",
            "data": [{"product": {**LAMP, "tags": [None, None]}}],
            "state": {"cart": {"currency": "EUR"}},
            "serverRendered": True,
            "routePath": "/p/lamp",
        }
    ]


def test_a_devalue_flat_array_reads_as_the_tree_it_references() -> None:
    # devalue `stringify` as Nuxt 3 writes `__NUXT_DATA__`: indices into the array, Nuxt's reviver tuples, a Date.
    payload = [
        ["ShallowReactive", 1],
        {"data": 2, "state": 8, "serverRendered": 11},
        ["ShallowReactive", 3],
        {"product-1": 4},
        {"name": 5, "price": 6, "offers": 7, "updated": 12},
        "Desk lamp",
        19.99,
        [13, 13],
        ["Reactive", 9],
        {"$scurrency": 10},
        ["Ref", 14],
        True,
        ["Date", "2026-10-01T00:00:00.000Z"],
        {"price": 6},
        "EUR",
    ]

    documents = _documents(_page(json.dumps(payload), script_type="application/json"))

    assert documents == [
        {
            "data": {
                "product-1": {
                    "name": "Desk lamp",
                    "price": 19.99,
                    "offers": [{"price": 19.99}, {"price": 19.99}],
                    "updated": "2026-10-01T00:00:00.000Z",
                }
            },
            "state": {"$scurrency": "EUR"},
            "serverRendered": True,
        }
    ]


def test_a_normalized_cache_reads_with_its_references_replaced_root_query_first() -> None:
    # Apollo SSR: `JSON.stringify(cache.extract())` with `<` escaped, `__ref` members naming cache IDs.
    script = (
        'window.__APOLLO_STATE__={"Product:1":{"__typename":"Product","name":"Desk lamp \\u003c 40 W",'
        '"offer":{"__ref":"Offer:9"}},"Offer:9":{"__typename":"Offer","price":"19.99","currency":"EUR"},'
        '"ROOT_QUERY":{"__typename":"Query","product({\\"id\\":\\"1\\"})":{"__ref":"Product:1"}}};'
    )
    offer = {"__typename": "Offer", "price": "19.99", "currency": "EUR"}
    product = {"__typename": "Product", "name": "Desk lamp < 40 W", "offer": offer}

    [document] = _documents(_page(script))

    assert document == {
        "ROOT_QUERY": {"__typename": "Query", 'product({"id":"1"})': product},
        "Product:1": product,
        "Offer:9": offer,
    }
    assert isinstance(document, dict)
    assert next(iter(document)) == "ROOT_QUERY"


@pytest.mark.parametrize(
    "script",
    [
        # Redux SSR: `JSON.stringify(preloadedState).replace(/</g, '\\u003c')`.
        'window.__PRELOADED_STATE__ = {"product":{"name":"\\u003cb\\u003eDesk lamp","price":19.99}}',
        # Pinia SSR: devalue's JS literal, `<` escaped as `\\u003C`.
        "window.__pinia = {product:{name:'\\u003Cb\\u003EDesk lamp',price:19.99,},}",
    ],
)
def test_serialized_state_reads_with_its_escapes(script: str) -> None:
    assert _documents(_page(script)) == [{"product": {"name": "<b>Desk lamp", "price": 19.99}}]


ANALYTICS = """
window.dataLayer = window.dataLayer || [];
dataLayer.push({ ecommerce: null });
dataLayer.push({
  event: "view_item",
  ecommerce: {currency: "USD", value: 30.03, items: [{item_id: "SKU_1", price: 10.01, quantity: 3,},],},
});
fbq('track', 'ViewContent', {value: 30.03, currency: 'USD', content_ids: ['SKU_1'], content_type: 'product'});
"""


def test_analytics_call_arguments_are_documents_and_declare_their_currency() -> None:
    page = _page(ANALYTICS)

    assert _documents(page) == [
        {"ecommerce": None},
        {
            "event": "view_item",
            "ecommerce": {
                "currency": "USD",
                "value": 30.03,
                "items": [{"item_id": "SKU_1", "price": 10.01, "quantity": 3}],
            },
        },
        {"value": 30.03, "currency": "USD", "content_ids": ["SKU_1"], "content_type": "product"},
    ]
    assert declared_currencies(page) == ("USD",)


def test_the_object_argument_of_a_start_call_is_a_document() -> None:
    # SvelteKit's hydration script: a bare assignment whose value holds calls (not state), then `kit.start` with
    # `devalue.uneval` data among reference arguments.
    script = """{
      __sveltekit_x1 = {base: new URL(".", location).pathname.slice(0, -1), env: {}};
      const element = document.currentScript.parentElement;
      Promise.all([import("./start.js"), import("./app.js")]).then(([kit, app]) => {
        kit.start(app, element, {
          node_ids: [0, 2],
          data: [null,{type:"data",data:{product:{name:"Desk lamp",price:19.99,currency:"EUR"}},uses:{params:["id"]}}],
          form: null,
          error: null
        });
      });
    }"""

    assert _documents(_page(script)) == [
        {
            "node_ids": [0, 2],
            "data": [None, {"type": "data", "data": {"product": LAMP}, "uses": {"params": ["id"]}}],
            "form": None,
            "error": None,
        }
    ]


@pytest.mark.parametrize(
    "script",
    [
        'window.__S = {cost: "€5.00", f: function () { return 1; }};',
        'window.__S = {cost: "€5.00", at: stamp()};',
        'var s = {cost: "€5.00", n: compute({x: 1}.x)}',
        'window.__NUXT__=(function(a){a.self=a;return {cost:a}}("€5.00"));',
        'dataLayer.push({cost: "€5.00", done: () => go()});',
        'var s = {cost: "€5.00"}.cost;',
        # Commented out, or written inside a string: not a statement.
        '// dataLayer.push({cost: "€5.00"});',
        '/* window.__S = {cost: "€5.00"}; */',
        'log("dataLayer.push({cost: 1})");',
        # Bounds: nesting past the reader's depth, and parameters used past its size.
        "window.__S = " + "[" * 100_000,
        "window.__S = (function(a){return [" + "a," * 2_000 + "]}([" + "0," * 1_000 + "]))",
    ],
)
def test_code_inside_a_value_ends_the_read_with_no_document(script: str) -> None:
    assert _documents(_page(script, body="€5.00")) == []


def test_an_array_whose_root_references_itself_is_no_flat_array() -> None:
    # devalue numbers values in first-visit order: the root's members name elements after it.
    document: JsonValue = [{"id": 0}]

    assert _documents(_page(json.dumps(document), script_type="application/json")) == [document]


def test_a_flat_array_whose_references_expand_past_the_bound_stays_as_written() -> None:
    # Each element references the next twice: the tree it stands for has 2**40 leaves.
    links: list[JsonValue] = [[i + 2, i + 2] for i in range(40)]
    payload: list[JsonValue] = [{"a": 1}, *links, "leaf"]

    assert _documents(_page(json.dumps(payload), script_type="application/json")) == [payload]


def test_astro_island_props_revive_from_their_type_tuples() -> None:
    # Astro `serializeObject`: every value a `[type, value]` tuple; `undefined` is `[0]`.
    props: JsonValue = {
        "product": [
            0,
            {
                "name": [0, "Desk lamp"],
                "price": [0, 19.99],
                "sizes": [1, [[0, "S"], [0, "M"]]],
                "added": [3, "2026-10-01T00:00:00.000Z"],
                "gone": [0],
            },
        ]
    }

    assert revive_astro_props(props) == {
        "product": {
            "name": "Desk lamp",
            "price": 19.99,
            "sizes": ["S", "M"],
            "added": "2026-10-01T00:00:00.000Z",
            "gone": None,
        }
    }
    assert revive_astro_props({"name": "Desk lamp"}) is None
