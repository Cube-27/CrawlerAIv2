"""The extraction pipeline (SPEC-05 §4.1, §4.8, §4.13, §4.14): a capture and a schema in, every field's outcome out.

Pages are synthetic (`example.test`); the schema.org vocabulary is the synthetic fixture (C3, C9).
"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch, Shape
from crawlerai.adapters.registry import Registry
from crawlerai.collect.base import Candidate
from crawlerai.collect.og import OpenGraphCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve import pipeline
from crawlerai.resolve.evidence import MIN_CALIBRATED_N, Bucket, Calibration
from crawlerai.resolve.pipeline import (
    UNRANKED,
    EngineData,
    GapReply,
    GapRequest,
    ListingGapReply,
    ListingGapRequest,
    RoleC,
    extract_page,
)
from crawlerai.resolve.preference import PRECEDENCE_FILE, PRECEDENCE_TYPES, load_precedence
from crawlerai.resolve.types import ExtractionResult, LLMCallRecord
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    Headers,
    NetworkBody,
    network_file,
    sha256_hex,
)

# The `parses` fixture (tests/unit/conftest.py): parser constructions by name, each with `calls` and `inputs`.
Parses = Mapping[str, Any]

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
# The order committed under `backend/data/` (SPEC-05 §4.7), as the engine loads it when no fit has replaced it.
COMMITTED_ORDERS = load_precedence(Path(__file__).parents[2] / "data" / PRECEDENCE_FILE)
COMMITTED = EngineData(vocabulary=VOCABULARY, orders=COMMITTED_ORDERS, calibration=None)


def _schema(page_kind: PageKind = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind=page_kind,
        fields=fields,
    )


PRODUCT = _schema(
    title=FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
    price=FieldSpec(type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"),
    sku=FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku"),
)
PRICE: JsonValue = {"amount": "19.90", "currency": "EUR"}


def _product(name: str = "Widget One", url: str = PAGE_URL, *, price: str | None = "19.90") -> dict[str, Any]:
    node: dict[str, Any] = {"@type": "Product", "name": name, "url": url, "sku": "W-1"}
    if price is not None:
        node["offers"] = {"@type": "Offer", "price": price, "priceCurrency": "EUR"}
    return node


def _html(*nodes: Mapping[str, Any], head: str = "", body: str = "") -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", **n})}</script>'
        for n in nodes
    )
    return f'<html lang="en"><head>{blocks}{head}</head><body><h1>Widget One</h1>{body}</body></html>'


def _bundle(
    body: str,
    *,
    block_class: BlockClass = "ok",
    method: CaptureMethod = "http",
    url: str = PAGE_URL,
    final_url: str | None = None,
) -> CaptureBundle:
    raw = body.encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=final_url or url,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method=method,
        status_code=200,
        block_class=block_class,
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=raw, network=())


def _extract(
    bundle: CaptureBundle,
    schema: SchemaDef = PRODUCT,
    *,
    role_c: RoleC | None = None,
    data: EngineData = DATA,
) -> ExtractionResult:
    return asyncio.run(extract_page(bundle, schema, None, role_c, data=data))


def _statuses(result: ExtractionResult) -> dict[str, tuple[str, str | None]]:
    assert result.entity is not None
    return {name: (outcome.status, outcome.reason) for name, outcome in result.entity.items()}


# --- a served page ---


def test_a_product_page_publishes_its_structured_values() -> None:
    result = _extract(_bundle(_html(_product())))
    assert result.outcome == "extracted"
    assert result.entity is not None
    published = {name: (o.value, o.evidence, o.source_kind) for name, o in result.entity.items()}
    assert published == {
        "title": ("Widget One", "structured", "jsonld"),
        "price": (PRICE, "structured", "jsonld"),
        "sku": ("W-1", "structured", "jsonld"),
    }
    # No calibration was fitted, so every field is uncalibrated and the record has no confidence (§4.9).
    assert not any(o.calibrated for o in result.entity.values())
    assert result.record_confidence is None


def test_a_calibrated_page_publishes_with_its_confidence_unless_the_request_sets_a_minimum() -> None:
    buckets = {f"{t}|structured": Bucket(n=MIN_CALIBRATED_N, precision=0.6) for t in ("text", "money", "identifier")}
    calibrated = EngineData(VOCABULARY, DATA.orders, Calibration(git_sha="a" * 40, buckets=buckets))
    bundle = _bundle(_html(_product()))

    open_ = _extract(bundle, data=calibrated)
    gated = _extract(bundle, data=calibrated.with_min_confidence(0.9))

    assert open_.outcome == "extracted"
    assert open_.entity is not None
    assert {(o.status, o.confidence, o.calibrated) for o in open_.entity.values()} == {("published", 0.6, True)}
    assert open_.record_confidence == 0.6
    assert gated.outcome == "partial"
    assert gated.entity is not None
    assert {(o.status, o.reason) for o in gated.entity.values()} == {("abstained", "below_min_confidence")}


def test_a_page_missing_a_required_field_is_partial() -> None:
    result = _extract(_bundle(_html(_product(price=None))))
    assert result.outcome == "partial"
    assert _statuses(result)["price"] == ("missing", "no_candidates")


def test_without_a_fitted_order_text_fields_decline() -> None:
    # D-0486: with no precedence file no source kind ranks; exact-match types still publish on agreement. The repo
    # commits SPEC-05 §4.7's order (D-0444), which ranks them: see the role C test below.
    data = EngineData(vocabulary=VOCABULARY, orders=UNRANKED, calibration=None)
    result = _extract(_bundle(_html(_product())), data=data)
    assert _statuses(result) == {
        "title": ("missing", "unranked"),
        "price": ("published", None),
        "sku": ("published", None),
    }
    assert result.outcome == "partial"


def test_the_product_the_page_url_names_is_the_target() -> None:
    page = _html(_product("Widget Two", "https://shop.example.test/p/2"), _product("Widget One", PAGE_URL))
    result = _extract(_bundle(page))
    assert result.entity is not None
    assert result.entity["title"].value == "Widget One"


def _group(*prices: str) -> dict[str, Any]:
    # A ProductGroup whose offers sit only under its variants, each variant repeating the group's URL.
    variants = [
        {
            "@type": "Product",
            "url": PAGE_URL,
            "sku": f"W-1-{i}",
            "offers": {"@type": "Offer", "price": price, "priceCurrency": "EUR"},
        }
        for i, price in enumerate(prices)
    ]
    return {"@type": "ProductGroup", "name": "Widget One", "url": PAGE_URL, "hasVariant": variants}


def test_a_product_group_whose_variant_offers_agree_publishes_their_price() -> None:
    result = _extract(_bundle(_html(_group("19.90", "19.90", "19.90"))))
    assert result.entity is not None
    assert (result.entity["title"].value, result.entity["price"].value) == ("Widget One", PRICE)
    # Each variant's sku is the variant's, not the group's (§4.6): the group states none.
    assert _statuses(result)["sku"] == ("missing", "not_owned")


def test_a_product_group_whose_variant_offers_disagree_declines_the_price() -> None:
    result = _extract(_bundle(_html(_group("19.90", "24.90"))))
    assert _statuses(result)["price"] == ("conflict", "offers_disagree")
    assert _statuses(result)["title"] == ("published", None)


def test_page_level_and_embedded_state_values_join_the_candidates() -> None:
    head = '<meta property="og:title" content="Widget One">'
    body = '<script>window.state = {"item": {"code": "W-1"}}</script>'
    result = _extract(_bundle(_html(_product(), head=head, body=body)))
    kinds = {(c.field, c.source_kind) for c in result.candidates}
    assert {("title", "og"), ("sku", "js_state")} <= kinds
    assert result.entity is not None
    # The og title agrees with the JSON-LD one: two independent kinds (§10).
    assert result.entity["title"].evidence == "agreed"


# --- pages that were not served (INV-11) ---


@pytest.mark.parametrize("block_class", ["blocked", "shell", "not_found", "error"])
def test_a_page_that_was_not_served_yields_its_block_class_and_nothing_else(block_class: BlockClass) -> None:
    result = _extract(_bundle(_html(_product()), block_class=block_class))
    assert (result.outcome, result.entity, result.rows, result.candidates) == (block_class, None, (), ())


# --- one parse per parser (INV-26) ---


def test_extract_page_parses_the_capture_once_per_parser(parses: Parses) -> None:
    head = (
        f'<link rel="canonical" href="{PAGE_URL}"><link rel="alternate" hreflang="de" href="{PAGE_URL}?l=de">'
        '<meta property="og:title" content="Widget One"><meta property="og:locale" content="en_GB">'
    )
    body = (
        '<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Widget One</span></div>'
        '<script type="application/json">{"sku": "W-1"}</script><script>var s = {"price": "19.90"}</script>'
    )
    result = _extract(_bundle(_html(_product(), head=head, body=body)))
    assert result.outcome == "extracted"
    assert parses["selectolax"].calls == 1
    assert parses["lxml"].calls <= 1


# --- failures (§4.14) ---


def test_a_collector_that_raises_leaves_a_diagnostic_and_the_others_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: object) -> None:
        raise RuntimeError("collector bug")

    monkeypatch.setattr(OpenGraphCollector, "collect", broken)
    result = _extract(_bundle(_html(_product(), head='<meta property="og:title" content="Widget One">')))
    assert "OpenGraphCollector: RuntimeError: collector bug" in result.diagnostics
    assert result.entity is not None
    assert (result.entity["title"].value, result.entity["title"].evidence) == ("Widget One", "structured")


def test_resolution_that_raises_fails_the_page_without_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("resolution bug")

    monkeypatch.setattr(pipeline, "assess_fields", broken)
    result = _extract(_bundle(_html(_product())))
    assert (result.outcome, result.entity, result.record_confidence) == ("error", None, None)


# --- the LLM hook (§4.13) ---

CALL = LLMCallRecord(
    prompt_kind="c_extract_detail",
    provider="provider-a",
    model="model-a",
    request_hash="0" * 64,
    tokens_in=9,
    tokens_out=3,
)


class FakeRoleC:
    """On a detail page, answers each missing field with the money value the page text shows, grounded on the target,
    or with `failure`; on a listing, gives `listing_reply`, or with `fill_blocks` fills each asked field of each block
    with the block's first line, grounded there. `error` is raised instead of either."""

    def __init__(
        self,
        *,
        failure: str | None = None,
        listing_reply: ListingGapReply | None = None,
        fill_blocks: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.requests: list[GapRequest] = []
        self.listing_requests: list[ListingGapRequest] = []
        self._failure = failure
        self._listing_reply = listing_reply or ListingGapReply(candidates=(), llm_calls=())
        self._fill_blocks = fill_blocks
        self._error = error

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        self.listing_requests.append(request)
        if self._error is not None:
            raise self._error
        if self._fill_blocks:
            filled = tuple(
                _llm(name, block.row, block.text.split("\n")[0], block.start)
                for block in request.blocks
                for name in block.fields
            )
            return ListingGapReply(candidates=filled, llm_calls=(LISTING_CALL,))
        return self._listing_reply

    async def detail(self, request: GapRequest) -> GapReply:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._failure is not None:
            return GapReply((), (), failure=self._failure, diagnostics=(f"role C: {self._failure}",))
        candidates = tuple(
            Candidate(
                field=name,
                entity_id=request.target.id,
                source_kind="llm",
                raw="19.90 EUR",
                normalized=Ok(PRICE),
                locator="text:0-9",
                independent=True,
            )
            for name in request.missing
        )
        return GapReply(candidates=candidates, llm_calls=(CALL,))


def test_required_fields_left_missing_go_to_role_c_once() -> None:
    role_c = FakeRoleC()
    result = _extract(_bundle(_html(_product(price=None))), role_c=role_c)
    assert [r.missing for r in role_c.requests] == [("price",)]
    assert role_c.requests[0].target.types == ("Product",)
    assert result.entity is not None
    assert (result.entity["price"].value, result.entity["price"].evidence) == (PRICE, "llm_grounded")
    assert result.llm_calls == (CALL,)
    assert result.outcome == "extracted"


def test_with_the_committed_order_a_json_ld_complete_page_publishes_without_role_c() -> None:
    # Text fields rank by the committed order, so JSON-LD carrying every required field leaves no gap for role C.
    role_c = FakeRoleC()
    result = _extract(_bundle(_html(_product())), role_c=role_c, data=COMMITTED)
    assert _statuses(result) == {
        "title": ("published", None),
        "price": ("published", None),
        "sku": ("published", None),
    }
    assert result.outcome == "extracted"
    assert (role_c.requests, result.llm_calls) == ([], ())


@pytest.mark.parametrize(("sku", "asked"), [("W-1", [("gtin",)]), (None, [("sku", "gtin")])])
def test_role_c_is_asked_for_each_missing_member_of_a_required_group(
    sku: str | None, asked: list[tuple[str, ...]]
) -> None:
    schema = _schema(
        title=PRODUCT.fields["title"],
        sku=FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku"),
        gtin=FieldSpec(type=FieldType.IDENTIFIER, scheme="gtin", description="d", schema_org="Product.gtin"),
    ).model_copy(update={"required_groups": [["sku", "gtin"]]})
    node = {key: value for key, value in _product().items() if key != "sku"} | ({"sku": sku} if sku else {})
    role_c = FakeRoleC()
    _extract(_bundle(_html(node)), schema, role_c=role_c)
    assert [r.missing for r in role_c.requests] == asked


def test_role_c_reads_the_page_with_the_currencies_its_structured_data_states() -> None:
    # SPEC-04 §4.4: a microdata Offer that writes its price as text (`$12.50`) and its currency as USD; the price is
    # left to role C, which normalizes the `$` it reads with the page's stated currency.
    body = (
        '<div itemscope itemtype="https://schema.org/Offer"><span itemprop="price">$12.50</span>'
        '<meta itemprop="priceCurrency" content="USD"></div>'
    )
    role_c = FakeRoleC()
    _extract(_bundle(_html(_product(price=None), body=body)), role_c=role_c)
    assert [r.ctx.page_currencies for r in role_c.requests] == [("USD",)]


def test_role_c_is_not_called_for_conflicts() -> None:
    # §4.13: a conflict is never sent to the LLM; with no single target every field is one.
    role_c = FakeRoleC()
    page = _html(
        _product("Widget Two", "https://shop.example.test/p/2"),
        _product("Widget Three", "https://shop.example.test/p/3"),
    )
    result = _extract(_bundle(page), role_c=role_c)
    assert _statuses(result) == dict.fromkeys(("title", "price", "sku"), ("conflict", "intent_ambiguous"))
    assert (result.outcome, role_c.requests, result.llm_calls) == ("partial", [], ())


def test_missing_optional_fields_ride_along_with_a_required_gap() -> None:
    # Llm spec, "When role C is asked": one call, in schema order.
    role_c = FakeRoleC()
    node = {key: value for key, value in _product(price=None).items() if key != "sku"}
    _extract(_bundle(_html(node)), role_c=role_c)
    assert [r.missing for r in role_c.requests] == [("price", "sku")]


def test_a_missing_optional_field_alone_calls_role_c() -> None:
    # Llm spec, "When role C is asked": on a detail page every missing field is asked, optional ones included.
    role_c = FakeRoleC()
    node = {key: value for key, value in _product().items() if key != "sku"}
    result = _extract(_bundle(_html(node)), role_c=role_c)
    assert [r.missing for r in role_c.requests] == [("sku",)]
    assert result.llm_calls == (CALL,)


def test_a_role_c_call_without_a_reply_leaves_the_asked_fields_missing_with_its_reason() -> None:
    # SPEC-06 §4.7: never a published guess; the page is partial and says why.
    result = _extract(_bundle(_html(_product(price=None))), role_c=FakeRoleC(failure="llm_budget"))
    assert _statuses(result) == {
        "title": ("published", None),
        "price": ("missing", "llm_budget"),
        "sku": ("published", None),
    }
    assert (result.outcome, result.diagnostics) == ("partial", ("role C: llm_budget",))


def test_a_role_c_failure_is_not_a_resolution_error() -> None:
    # A replay's missing recording must reach the harness, which drops the page (SPEC-03 §4.5).
    role_c = FakeRoleC(error=LookupError("no recorded response"))
    bundle = _bundle(_html(_product(price=None)))
    with pytest.raises(LookupError, match="no recorded response"):
        _extract(bundle, role_c=role_c)


# --- api captures (D-0445) ---


class FakeAdapter:
    """A platform whose page URLs are under `/jobs/` of the synthetic host, whose API is under `/api/`, and whose
    answer is a JobPosting with a `title` member."""

    name = "synthetic"

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="t", page_kind="detail") if "/jobs/" in url else None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return "/api/" in endpoint

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        raise AssertionError("extraction fetches nothing")

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return (Shape(type="JobPosting", properties={"title": ("title",)}),)


JOB = _schema(title=FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="JobPosting.title"))
JOB_URL = "https://jobs.example.test/jobs/1"
JOB_API = "https://jobs.example.test/api/jobs/1"


def test_an_api_capture_is_read_by_the_adapter_that_detects_its_page_url_and_serves_its_endpoint() -> None:
    data = EngineData(VOCABULARY, DATA.orders, None, adapters=Registry([FakeAdapter()]))
    bundle = _bundle('{"title": "Engineer"}', method="api", url=JOB_URL, final_url=JOB_API)
    result = _extract(bundle, JOB, data=data)
    assert result.entity is not None
    title = result.entity["title"]
    assert (title.value, title.source_kind, title.evidence, title.locator) == (
        "Engineer",
        "adapter",
        "adapter",
        "adapter:synthetic:$['title']",
    )


def test_an_api_capture_no_active_adapter_detects_has_no_adapter_values() -> None:
    data = EngineData(VOCABULARY, DATA.orders, None, adapters=Registry(()))
    bundle = _bundle('{"title": "Engineer"}', method="api", url=JOB_URL, final_url=JOB_API)
    result = _extract(bundle, JOB, data=data)
    assert (result.candidates, _statuses(result)) == ((), {"title": ("missing", "no_candidates")})
    assert result.diagnostics == ("adapter: no active adapter reads this api capture",)


def test_an_api_capture_from_another_endpoint_of_a_detected_page_is_not_the_adapters() -> None:
    # INV-39: an API recipe's capture of a page URL the adapter detects is the recipe's, not the adapter's.
    data = EngineData(VOCABULARY, DATA.orders, None, adapters=Registry([FakeAdapter()]))
    bundle = _bundle('{"title": "Engineer"}', method="api", url=JOB_URL, final_url="https://data.example.test/1")
    result = _extract(bundle, JOB, data=data)
    assert (result.candidates, _statuses(result)) == ((), {"title": ("missing", "no_candidates")})
    assert result.diagnostics == ("adapter: no active adapter reads this api capture",)


class BoardAdapter(FakeAdapter):
    """A board whose API keeps each posting's primary place apart from its further ones."""

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="t", page_kind="listing") if "/jobs/" in url else None

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        posting = Shape(
            type="JobPosting",
            at=("jobs", "*"),
            properties={"title": ("title",), "url": ("url",), "jobLocation": ("place",)},
            also={"jobLocation": (("more", "*"),)},
        )
        return (Shape(type="ItemList", nodes={"itemListElement": (posting,)}),)


def test_a_job_listing_row_publishes_every_place_its_posting_states() -> None:
    # D-1477: `job_listing.locations` is a list, so a posting's primary and further places publish together.
    data = EngineData(VOCABULARY, DATA.orders, None, adapters=Registry([BoardAdapter()]))
    jobs = [
        {"title": "Engineer", "url": f"{JOB_URL}/a", "place": "Northtown", "more": ["Eastport", "Southville"]},
        {"title": "Analyst", "url": f"{JOB_URL}/b", "place": "Eastport", "more": []},
    ]
    bundle = _bundle(json.dumps({"jobs": jobs}), method="api", url=JOB_URL, final_url=JOB_API)
    preset = next(p for p in load_presets() if p.name == "job_listing")
    schema = SchemaDef(**preset.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")

    result = _extract(bundle, schema, data=data)

    places = [[place["text"] for place in cast(list[dict[str, str]], row["locations"].value)] for row in result.rows]
    assert [row["locations"].status for row in result.rows] == ["published", "published"]
    assert places == [["Northtown", "Eastport", "Southville"], ["Eastport"]]


# --- cold listings (§4.7 "Listings", §8.6) ---

LISTING_URL = "https://shop.example.test/c/widgets?page=2"
LISTING = _schema(
    "listing",
    title=PRODUCT.fields["title"],
    url=FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url"),
    price=FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    # og:title fills text fields whose path ends in `.name` (the OGP table, §4.5); on the page, only the page owns it.
    page_title=FieldSpec(type=FieldType.TEXT, description="d", scope="page", schema_org="Product.name"),
    next_page_url=FieldSpec(type=FieldType.URL, description="d", scope="page"),
)


def _row(n: int, **extra: Any) -> dict[str, Any]:
    return {**_product(f"Widget {n}", f"https://shop.example.test/p/{n}", price=f"{n}.50"), **extra}


def _item_list(*items: Mapping[str, Any]) -> dict[str, Any]:
    elements = [{"@type": "ListItem", "position": i + 1, "item": item} for i, item in enumerate(items)]
    return {"@type": "ItemList", "itemListElement": elements}


def _listing(page: str, schema: SchemaDef = LISTING, **kwargs: Any) -> ExtractionResult:
    return _extract(_bundle(page, url=LISTING_URL), schema, **kwargs)


def _row_values(result: ExtractionResult) -> list[dict[str, JsonValue]]:
    return [{name: o.value for name, o in row.items() if o.status == "published"} for row in result.rows]


def test_the_items_of_an_item_list_are_the_rows() -> None:
    result = _listing(_html(_item_list(_row(1), _row(2))))
    assert _row_values(result) == [
        {"title": "Widget 1", "url": "https://shop.example.test/p/1", "price": {"amount": "1.50", "currency": "EUR"}},
        {"title": "Widget 2", "url": "https://shop.example.test/p/2", "price": {"amount": "2.50", "currency": "EUR"}},
    ]
    # Each row holds its row-scoped fields; the page-scoped ones resolve once, against the page.
    assert {frozenset(row) for row in result.rows} == {frozenset({"title", "url", "price"})}
    assert result.entity is not None
    assert set(result.entity) == {"page_title", "next_page_url"}
    assert result.outcome == "extracted"


def test_row_urls_drop_the_session_parameters_every_row_shares_and_keep_identity_and_page_ones() -> None:
    # `sid` names the visit (one value on every row, not on the page); `v` is identity; `page` is the page's own.
    rows = [
        _product(f"Widget {n}", f"https://shop.example.test/p/{n}?page=2&sid=abc&v={n}", price=f"{n}.50")
        for n in (1, 2)
    ]
    result = _listing(_html(_item_list(*rows)))

    assert [row["url"].value for row in result.rows] == [
        "https://shop.example.test/p/1?page=2&v=1",
        "https://shop.example.test/p/2?page=2&v=2",
    ]
    assert result.session_params == {"url": ("sid",)}


def test_an_item_list_holding_the_items_directly_and_in_microdata_gives_rows() -> None:
    body = (
        '<ul itemscope itemtype="https://schema.org/ItemList">'
        '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/Product">'
        '<a itemprop="url" href="/p/3"><span itemprop="name">Widget 3</span></a></li></ul>'
    )
    result = _listing(_html({"@type": "ItemList", "itemListElement": [_row(1)]}, body=body))
    titles = [row["title"].value for row in result.rows]
    assert titles == ["Widget 1", "Widget 3"]


def _microdata_items(*ns: int) -> str:
    items = "".join(
        '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/Product">'
        f'<link itemprop="mainEntityOfPage" href="{LISTING_URL}">'
        f'<a itemprop="url" href="/p/{n}"><span itemprop="name">Widget {n}</span></a></li>'
        for n in ns
    )
    return f'<ul itemscope itemtype="https://schema.org/ItemList">{items}</ul>'


def test_items_both_syntaxes_state_are_one_row_each() -> None:
    # A row is an item, not a statement of it: microdata repeating the JSON-LD items adds only the item JSON-LD lacks.
    # Every row names the listing page too, which names no item.
    rows = [_row(n, mainEntityOfPage=LISTING_URL) for n in (1, 2)]
    result = _listing(_html(_item_list(*rows), body=_microdata_items(1, 2, 3)))

    assert [(row["title"].value, row["title"].source_kind) for row in result.rows] == [
        ("Widget 1", "jsonld"),
        ("Widget 2", "jsonld"),
        ("Widget 3", "microdata"),
    ]


def test_three_top_level_items_no_page_url_names_are_the_rows() -> None:
    result = _listing(_html(_row(1), _row(2), _row(3)))
    assert [row["title"].value for row in result.rows] == ["Widget 1", "Widget 2", "Widget 3"]


@pytest.mark.parametrize(
    "nodes",
    [
        pytest.param((_row(1), _row(2)), id="fewer-than-three"),
        pytest.param((_row(1), _row(2), _product("Widget 9", LISTING_URL)), id="the-page-url-names-one"),
    ],
)
def test_top_level_items_are_not_rows_on_a_detail_like_page(nodes: tuple[dict[str, Any], ...]) -> None:
    result = _listing(_html(*nodes))
    assert result.rows == ()
    # No rows: nothing on the page is complete (§10 "Incomplete pages").
    assert result.outcome == "partial"


def test_an_item_related_to_a_row_is_not_a_row() -> None:
    result = _listing(_html(_item_list(_row(1), _row(2, isRelatedTo=_row(7)))))
    assert [row["title"].value for row in result.rows] == ["Widget 1", "Widget 2"]


def test_a_row_takes_no_page_level_value() -> None:
    # og:title describes the page, not one of its rows, so it fills the page's field and no row's (§4.6).
    head = '<meta property="og:title" content="All widgets">'
    nameless = {key: value for key, value in _row(2).items() if key != "name"}
    result = _listing(_html(_item_list(_row(1), nameless), head=head))
    assert [(row["title"].status, row["title"].reason) for row in result.rows] == [
        ("published", None),
        ("missing", "not_owned"),
    ]
    assert result.entity is not None
    assert result.entity["page_title"].value == "All widgets"
    assert result.outcome == "partial"


def test_the_next_pages_come_with_the_listing() -> None:
    head = '<link rel="next" href="/c/widgets?page=3">'
    result = _listing(_html(_item_list(_row(1)), head=head), data=COMMITTED)
    assert result.next_pages == ("https://shop.example.test/c/widgets?page=3",)
    # HTML's `rel=next` states the next document, so it fills the page field, read from the link element (D-1226).
    assert result.entity is not None
    found = result.entity["next_page_url"]
    assert (found.status, found.value, found.source_kind, found.locator) == (
        "published",
        "https://shop.example.test/c/widgets?page=3",
        "dom",
        "dom:/html[1]/head[1]/link[1]",
    )


def test_a_numbered_link_is_a_next_page_but_fills_no_field() -> None:
    # A link one integer higher is only inferred to be the next page: the value is not stated, so it is not filled (C7).
    body = '<a href="/c/widgets?page=3">3</a>'
    result = _listing(_html(_item_list(_row(1)), body=body), data=COMMITTED)
    assert result.next_pages == ("https://shop.example.test/c/widgets?page=3",)
    assert result.entity is not None
    assert result.entity["next_page_url"].status == "missing"


def test_role_c_is_not_asked_when_the_rows_publish_every_row_field() -> None:
    role_c = FakeRoleC()
    result = _listing(_html(_item_list(_row(1), _row(2))), role_c=role_c)
    assert len(result.rows) == 2
    assert (role_c.requests, role_c.listing_requests) == ([], [])


def _branded(n: int) -> str:
    return f'<li class="card"><h3><a href="/p/{n}">Widget {n}</a></h3><span>{n}.50 EUR</span><p>Acme {n}</p></li>'


BRANDED = _schema(
    "listing",
    title=LISTING.fields["title"],
    url=LISTING.fields["url"],
    brand=FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name"),
)


def test_role_c_fills_the_block_rows_when_a_row_field_publishes_on_no_row() -> None:
    # Listings spec, "Role C rows": no block publishes `brand`, so each block's row is asked for it, and only for it.
    role_c = FakeRoleC(fill_blocks=True)
    page = _html(body=f"<ul>{''.join(_branded(n) for n in (1, 2, 3))}</ul>")

    result = _listing(page, BRANDED, role_c=role_c, data=COMMITTED)

    (request,) = role_c.listing_requests
    assert [(block.index, block.url, block.fields) for block in request.blocks] == [
        (n - 1, f"https://shop.example.test/p/{n}", ("brand",)) for n in (1, 2, 3)
    ]
    assert [block.text for block in request.blocks] == [f"Widget {n}\n{n}.50 EUR\nAcme {n}" for n in (1, 2, 3)]
    assert [block.row for block in request.blocks] == [f"item_block:0:{i}" for i in range(3)]
    # The fake fills `brand` with the first line: the claim fills the block's row, the block's own values stand.
    assert [(row["title"].value, row["brand"].value, row["brand"].evidence) for row in result.rows] == [
        (f"Widget {n}", f"Widget {n}", "llm_grounded") for n in (1, 2, 3)
    ]


def test_only_block_rows_lacking_a_required_row_field_are_asked() -> None:
    # One card's heading is an image without a name: its row lacks the required title; the others are not asked.
    cards = [_branded(n) for n in range(1, 6)]
    cards[1] = '<li class="card"><h3><a href="/p/2"><img src="/i/2.png" alt=""></a></h3><span>2.50 EUR</span></li>'
    schema = _schema("listing", title=LISTING.fields["title"], url=LISTING.fields["url"], price=LISTING.fields["price"])
    role_c = FakeRoleC()

    _listing(_html(body=f"<ul>{''.join(cards)}</ul>"), schema, role_c=role_c, data=COMMITTED)

    (request,) = role_c.listing_requests
    assert [(block.index, block.fields) for block in request.blocks] == [(1, ("title",))]


def test_an_object_row_field_no_row_publishes_is_never_asked() -> None:
    # A claim is one verbatim span, which cannot hold an object's sub-fields: the blocks are not asked for it.
    dims = FieldSpec.model_validate(
        {"type": "object", "description": "d", "fields": {"w": {"type": "text", "description": "d"}}}
    )
    schema = _schema("listing", title=LISTING.fields["title"], url=LISTING.fields["url"], dims=dims)
    role_c = FakeRoleC()

    _listing(_html(body=f"<ul>{''.join(_branded(n) for n in (1, 2, 3))}</ul>"), schema, role_c=role_c, data=COMMITTED)

    assert role_c.listing_requests == []


def test_the_page_members_of_an_unmet_required_group_are_asked() -> None:
    # As on a detail page: no member of a required group publishes, so its optional members are asked.
    optional = LISTING.fields["page_title"]
    schema = _schema(
        "listing", title=LISTING.fields["title"], url=LISTING.fields["url"], heading=optional, subtitle=optional
    ).model_copy(update={"required_groups": [["heading", "subtitle"]]})
    role_c = FakeRoleC()

    _listing(_html(body=f"<ul>{''.join(_branded(n) for n in (1, 2, 3))}</ul>"), schema, role_c=role_c, data=COMMITTED)

    (request,) = role_c.listing_requests
    assert (request.blocks, request.page_missing) == ((), ("heading", "subtitle"))


def test_a_listing_without_rows_does_not_ask_role_c_for_rows() -> None:
    # Role C fills the rows of blocks: with none, and no required page field missing, it is not asked.
    role_c = FakeRoleC()

    result = _listing(_html(body="<p>Widget 1</p>"), role_c=role_c)

    assert (role_c.listing_requests, result.rows, result.reason) == ([], (), "no_rows: not_asked")


LISTING_CALL = CALL.model_copy(update={"prompt_kind": "c_extract_listing"})


def _llm(field: str, owner: str, raw: str, start: int) -> Candidate:
    return Candidate(
        field=field,
        entity_id=owner,
        source_kind="llm",
        raw=raw,
        normalized=Ok(raw),
        locator=f"text:{start}-{start + len(raw)}",
        independent=True,
    )


# A listing schema whose page title is required: role C is asked for the page fields when it is missing.
TITLED = _schema(
    "listing",
    **{**LISTING.fields, "page_title": LISTING.fields["page_title"].model_copy(update={"required": True})},
)


def test_the_page_fields_are_asked_when_a_required_one_is_missing() -> None:
    role_c = FakeRoleC(listing_reply=ListingGapReply((_llm("page_title", "page", "All widgets", 0),), (LISTING_CALL,)))

    result = _listing(_html(body="<h1>All widgets</h1>"), TITLED, role_c=role_c)

    (request,) = role_c.listing_requests
    assert (request.blocks, request.page_missing) == ((), ("page_title", "next_page_url"))
    assert result.entity is not None
    assert (result.entity["page_title"].value, result.entity["page_title"].evidence) == ("All widgets", "llm_grounded")
    assert result.llm_calls == (LISTING_CALL,)


def test_a_page_field_the_page_states_is_not_asked_again() -> None:
    role_c = FakeRoleC()
    _listing(_html(head='<meta property="og:title" content="All widgets">'), TITLED, role_c=role_c)
    assert role_c.listing_requests == []


def test_optional_page_fields_alone_are_not_asked() -> None:
    role_c = FakeRoleC()
    _listing(_html(), role_c=role_c)
    assert role_c.listing_requests == []


def test_a_listing_role_c_failure_leaves_the_asked_page_fields_missing_with_its_reason() -> None:
    failed = ListingGapReply(candidates=(), llm_calls=(), failure="llm_unavailable", diagnostics=("role C: x",))
    result = _listing(_html(), TITLED, role_c=FakeRoleC(listing_reply=failed))
    assert result.entity is not None
    assert {name: (o.status, o.reason) for name, o in result.entity.items()} == {
        "page_title": ("missing", "llm_unavailable"),
        "next_page_url": ("missing", "llm_unavailable"),
    }
    assert (result.rows, result.outcome, result.diagnostics) == ((), "partial", ("role C: x",))


@pytest.mark.parametrize("role_c", [None, FakeRoleC()])
def test_a_listing_without_rows_says_why_and_keeps_its_page_fields(role_c: FakeRoleC | None) -> None:
    # The next page the page states still resolves; role C, which fills the rows of blocks, was not asked.
    result = _listing(_html(head='<link rel="next" href="/c/widgets?page=3">'), role_c=role_c, data=COMMITTED)

    assert (result.rows, result.reason) == ((), "no_rows: not_asked")
    assert result.entity is not None
    assert result.entity["next_page_url"].value == "https://shop.example.test/c/widgets?page=3"


def test_a_listing_with_rows_or_a_detail_page_has_no_reason() -> None:
    assert _listing(_html(_item_list(_row(1))), data=COMMITTED).reason is None
    assert _extract(_bundle(_html(_product()))).reason is None


def test_a_listing_schema_without_row_fields_does_not_call_role_c() -> None:
    role_c = FakeRoleC()
    schema = _schema("listing", page_title=LISTING.fields["page_title"])
    result = _listing(_html(), schema, role_c=role_c)
    assert result.entity is not None
    assert {name: (o.status, o.reason) for name, o in result.entity.items()} == {
        "page_title": ("missing", "no_candidates")
    }
    assert role_c.listing_requests == []


def test_a_listing_role_c_error_propagates() -> None:
    html, role_c = _html(), FakeRoleC(error=LookupError("no recorded response"))
    with pytest.raises(LookupError, match="no recorded response"):
        _listing(html, TITLED, role_c=role_c)


def test_a_listing_parses_the_capture_once_per_parser(parses: Parses) -> None:
    body = '<a href="/c/widgets?page=3">3</a>'
    result = _listing(_html(_item_list(_row(1)), head='<meta property="og:title" content="All widgets">', body=body))
    assert result.next_pages == ("https://shop.example.test/c/widgets?page=3",)
    assert parses["selectolax"].calls == 1
    assert parses["lxml"].calls <= 1


@pytest.mark.parametrize(("url_n", "expected"), [(40, 0.975), (MIN_CALIBRATED_N - 1, None)])
def test_a_listings_confidence_is_its_least_confident_rows(url_n: int, expected: float | None) -> None:
    # §10 per record: a row's confidence is its least confident required field's; one uncalibrated row has none.
    buckets = {"text|structured": Bucket(n=40, precision=0.99), "url|structured": Bucket(n=url_n, precision=0.975)}
    calibration = Calibration(git_sha="a" * 40, buckets=buckets)
    data = EngineData(VOCABULARY, DATA.orders, calibration)
    result = _listing(_html(_item_list(_row(1), _row(2))), data=data)
    assert result.record_confidence == expected


def _card(n: int, *links: str) -> str:
    anchors = "".join(f'<a href="{href}">Widget {n}</a>' for href in links)
    return f'<li class="card"><h3>{anchors or f"Widget {n}"}</h3><span>{n}.50 EUR</span></li>'


def test_a_grid_of_cards_gives_its_rows_before_role_c_is_asked() -> None:
    # Listings spec, "Rows from blocks": each card's heading link and price; its `#reviews` link is the same document.
    cards = "".join(_card(n, f"/p/{n}", f"/p/{n}#reviews") for n in (1, 2, 3))
    role_c = FakeRoleC()

    result = _listing(_html(body=f"<ul>{cards}</ul>"), role_c=role_c, data=COMMITTED)

    assert _row_values(result) == [
        {
            "title": f"Widget {n}",
            "url": f"https://shop.example.test/p/{n}",
            "price": {"amount": f"{n}.50", "currency": "EUR"},
        }
        for n in (1, 2, 3)
    ]
    assert [(row["url"].source_kind, row["url"].locator) for row in result.rows] == [
        ("dom", f"dom:/html[1]/body[1]/ul[1]/li[{n}]/h3[1]/a[1]") for n in (1, 2, 3)
    ]
    assert (role_c.listing_requests, result.outcome) == ([], "extracted")


# --- listing rows from captured calls (Appendix A #58) ---


def _network_listing(*items: Mapping[str, Any], shown: Sequence[Mapping[str, Any]] | None = None) -> CaptureBundle:
    """A rendered listing showing each item's link and price (`shown`'s, else the call's), and the call it loaded
    `items` with."""
    cards = "".join(f'<li><a href="{i["href"]}">{i["href"]}</a> <span>{i["price"]}</span></li>' for i in shown or items)
    raw = f'<html lang="en"><body><h1>All widgets</h1><ul>{cards}</ul></body></html>'.encode()
    data = json.dumps({"results": list(items)}).encode()
    entry = NetworkBody(
        url="https://api.example.test/widgets?page=1",
        status=200,
        content_type="application/json",
        sha256=sha256_hex(data),
        file=network_file(0),
        method="GET",
    )
    bundle = _bundle(raw.decode(), method="browser", url=LISTING_URL)
    manifest = bundle.manifest.model_copy(update={"network_bodies": (entry,)})
    return CaptureBundle(manifest=manifest, body=bundle.body, network=(data,))


NETWORK_ITEMS = [
    {"name": f"Widget {n}", "href": f"https://shop.example.test/p/{n}", "price": f"€{n}.50"} for n in (1, 2, 3)
]


def test_a_listing_without_structured_rows_takes_the_rows_of_its_captured_call() -> None:
    result = _extract(_network_listing(*NETWORK_ITEMS), LISTING, data=COMMITTED)

    assert _row_values(result) == [
        {"url": f"https://shop.example.test/p/{n}", "price": {"amount": f"{n}.50", "currency": "EUR"}}
        for n in (1, 2, 3)
    ]
    # The cards show each item's link and price: the price agrees with the call's, the link is the page's spelling.
    assert {(row["price"].evidence, row["price"].source_kind) for row in result.rows} == {("agreed", "xhr")}
    assert [row["url"].locator for row in result.rows] == [
        f"dom:/html[1]/body[1]/ul[1]/li[{n}]/a[1]" for n in (1, 2, 3)
    ]
    # The titles are text, admitted by equality only: every row lacks its required title.
    assert result.outcome == "partial"


def test_rows_of_a_call_that_lack_a_required_field_are_filled_through_their_blocks() -> None:
    # Listings spec, "Rows from captured calls" and "Role C rows": each call row bound to a card is asked for the title
    # it lacks, and role C's claim fills that call row; the call's own values stand.
    role_c = FakeRoleC(fill_blocks=True)

    result = _extract(_network_listing(*NETWORK_ITEMS), LISTING, role_c=role_c, data=COMMITTED)

    (request,) = role_c.listing_requests
    assert [block.fields for block in request.blocks] == [("title",)] * 3
    # The rows filled are the call's, the cards bound to them.
    assert all(block.row.startswith("xhr:") for block in request.blocks)
    assert [(row["title"].evidence, row["url"].value) for row in result.rows] == [
        ("llm_grounded", f"https://shop.example.test/p/{n}") for n in (1, 2, 3)
    ]


def test_the_blocks_beside_rows_of_a_call_stand_when_role_c_fills_nothing() -> None:
    # Listings spec, "Stated rows and blocks": a fourth card no call row names is a row beside them.
    fourth = {"name": "Widget 4", "href": "https://shop.example.test/p/4", "price": "€4.50"}
    bundle = _network_listing(*NETWORK_ITEMS, shown=[*NETWORK_ITEMS, fourth])

    result = _extract(bundle, LISTING, role_c=FakeRoleC(), data=COMMITTED)

    assert [row["url"].value for row in result.rows] == [f"https://shop.example.test/p/{n}" for n in (1, 2, 3, 4)]


def test_rows_of_a_call_stand_when_role_c_fills_nothing() -> None:
    result = _extract(_network_listing(*NETWORK_ITEMS), LISTING, role_c=FakeRoleC(), data=COMMITTED)

    assert [row["url"].value for row in result.rows] == [f"https://shop.example.test/p/{n}" for n in (1, 2, 3)]


def test_role_c_asked_beside_complete_call_rows_asks_only_the_field_no_row_publishes() -> None:
    # Listings spec, "Role C rows": an optional row field the call lacks asks role C for it; the call rows stand.
    brand = FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name")
    schema = _schema("listing", url=LISTING.fields["url"], price=LISTING.fields["price"], brand=brand)
    role_c = FakeRoleC()

    result = _extract(_network_listing(*NETWORK_ITEMS), schema, role_c=role_c, data=COMMITTED)

    (request,) = role_c.listing_requests
    assert [block.fields for block in request.blocks] == [("brand",)] * 3
    assert [row["url"].value for row in result.rows] == [f"https://shop.example.test/p/{n}" for n in (1, 2, 3)]
    assert result.outcome == "extracted"


def test_complete_rows_of_a_call_do_not_call_role_c() -> None:
    role_c = FakeRoleC()
    schema = _schema("listing", url=LISTING.fields["url"], price=LISTING.fields["price"])
    result = _extract(_network_listing(*NETWORK_ITEMS), schema, role_c=role_c, data=COMMITTED)

    assert (role_c.listing_requests, result.outcome, len(result.rows)) == ([], "extracted", 3)
