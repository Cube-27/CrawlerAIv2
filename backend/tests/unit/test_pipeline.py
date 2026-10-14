"""The extraction pipeline (SPEC-05 §4.1, §4.8, §4.13, §4.14): a capture and a schema in, every field's outcome out.

Pages are synthetic (`example.test`); the schema.org vocabulary is the synthetic fixture (C3, C9).
"""

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.registry import Registry
from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.og import OpenGraphCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import EvalRunId, PageKind, SchemaId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve import pipeline
from crawlerai.resolve.evidence import Bucket, Calibration
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
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult, LLMCallRecord
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

# The `parses` fixture (tests/unit/conftest.py): parser constructions by name, each with `calls` and `inputs`.
Parses = Mapping[str, Any]

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders={t: ORDER for t in PRECEDENCE_TYPES}, calibration=None)


def _schema(page_kind: PageKind = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        version=1,
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
    body: str, *, block_class: BlockClass = "ok", method: CaptureMethod = "http", url: str = PAGE_URL
) -> CaptureBundle:
    raw = body.encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=url,
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
        "sku": ({"scheme": "sku", "value": "W-1"}, "structured", "jsonld"),
    }
    # No calibration was fitted, so every field is uncalibrated and the record has no confidence (§4.9).
    assert not any(o.calibrated for o in result.entity.values())
    assert result.record_confidence is None


def test_a_page_missing_a_required_field_is_partial() -> None:
    result = _extract(_bundle(_html(_product(price=None))))
    assert result.outcome == "partial"
    assert _statuses(result)["price"] == ("missing", "no_candidates")


def test_without_a_fitted_order_text_fields_decline() -> None:
    # D-0444: no precedence file, so no source kind ranks; exact-match types still publish on agreement.
    data = EngineData(vocabulary=VOCABULARY, orders=UNRANKED, calibration=None)
    result = _extract(_bundle(_html(_product())), data=data)
    assert _statuses(result) == {
        "title": ("missing", "unranked"),
        "price": ("published", None),
        "sku": ("published", None),
    }
    assert result.outcome == "partial"


def test_two_products_the_urls_do_not_settle_conflict_on_every_field() -> None:
    page = _html(
        _product("Widget Two", "https://shop.example.test/p/2"),
        _product("Widget Three", "https://shop.example.test/p/3"),
    )
    result = _extract(_bundle(page))
    assert set(_statuses(result).values()) == {("conflict", "intent_ambiguous")}
    assert result.outcome == "partial"


def test_the_product_the_page_url_names_is_the_target() -> None:
    page = _html(_product("Widget Two", "https://shop.example.test/p/2"), _product("Widget One", PAGE_URL))
    result = _extract(_bundle(page))
    assert result.entity is not None
    assert result.entity["title"].value == "Widget One"


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
    or with `failure`; on a listing, gives `listing_reply`. `error` is raised instead of either."""

    def __init__(
        self,
        *,
        failure: str | None = None,
        listing_reply: ListingGapReply | None = None,
        error: Exception | None = None,
    ) -> None:
        self.requests: list[GapRequest] = []
        self.listing_requests: list[ListingGapRequest] = []
        self._failure = failure
        self._listing_reply = listing_reply or ListingGapReply(candidates=(), llm_calls=())
        self._error = error

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        self.listing_requests.append(request)
        if self._error is not None:
            raise self._error
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
    assert role_c.requests[0].target.kind == "Product"
    assert result.entity is not None
    assert (result.entity["price"].value, result.entity["price"].evidence) == (PRICE, "llm_grounded")
    assert result.llm_calls == (CALL,)
    assert result.outcome == "extracted"


def test_role_c_is_not_called_when_every_required_field_publishes() -> None:
    role_c = FakeRoleC()
    result = _extract(_bundle(_html(_product())), role_c=role_c)
    assert (role_c.requests, result.llm_calls) == ([], ())


@pytest.mark.parametrize(("sku", "asked"), [("W-1", []), (None, [("sku", "gtin")])])
def test_role_c_is_asked_for_a_required_group_only_while_no_member_fills_it(
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


def test_role_c_is_not_called_for_conflicts() -> None:
    # §4.13: a conflict is never sent to the LLM; with no single target every field is one.
    role_c = FakeRoleC()
    page = _html(
        _product("Widget Two", "https://shop.example.test/p/2"),
        _product("Widget Three", "https://shop.example.test/p/3"),
    )
    _extract(_bundle(page), role_c=role_c)
    assert role_c.requests == []


def test_missing_optional_fields_ride_along_with_a_required_gap() -> None:
    # SPEC-06 §4.4, D-0025: one call, in schema order.
    role_c = FakeRoleC()
    node = {key: value for key, value in _product(price=None).items() if key != "sku"}
    _extract(_bundle(_html(node)), role_c=role_c)
    assert [r.missing for r in role_c.requests] == [("price", "sku")]


def test_missing_optional_fields_alone_do_not_call_role_c() -> None:
    role_c = FakeRoleC()
    node = {key: value for key, value in _product().items() if key != "sku"}
    result = _extract(_bundle(_html(node)), role_c=role_c)
    assert (role_c.requests, result.llm_calls) == ([], ())


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
    """A platform whose page URLs are under `/jobs/` of the synthetic host and whose API holds a `title` member."""

    name = "synthetic"

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="t", page_kind="detail") if "/jobs/" in url else None

    async def fetch(self, url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("extraction fetches nothing")

    def map(self, schema_org: Mapping[str, str], page_kind: PageKind) -> dict[str, str]:
        return {name: "$['title']" for name, path in schema_org.items() if path == "JobPosting.title"}


JOB = _schema(title=FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="JobPosting.title"))
JOB_URL = "https://jobs.example.test/jobs/1"


def test_an_api_capture_is_read_by_the_adapter_that_detects_its_page_url() -> None:
    data = EngineData(VOCABULARY, DATA.orders, None, adapters=Registry([FakeAdapter()], active=["synthetic"]))
    result = _extract(_bundle('{"title": "Engineer"}', method="api", url=JOB_URL), JOB, data=data)
    assert result.entity is not None
    title = result.entity["title"]
    assert (title.value, title.source_kind, title.evidence, title.locator) == (
        "Engineer",
        "adapter",
        "adapter",
        "adapter:synthetic:$['title']",
    )


def test_an_api_capture_no_active_adapter_detects_has_no_adapter_values() -> None:
    data = EngineData(VOCABULARY, DATA.orders, None, adapters=Registry([FakeAdapter()], active=[]))
    result = _extract(_bundle('{"title": "Engineer"}', method="api", url=JOB_URL), JOB, data=data)
    assert not any(c.source_kind == "adapter" for c in result.candidates)
    assert any(d.startswith("adapter: no active adapter") for d in result.diagnostics)


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


def test_an_item_list_holding_the_items_directly_and_in_microdata_gives_rows() -> None:
    body = (
        '<ul itemscope itemtype="https://schema.org/ItemList">'
        '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/Product">'
        '<a itemprop="url" href="/p/3"><span itemprop="name">Widget 3</span></a></li></ul>'
    )
    result = _listing(_html({"@type": "ItemList", "itemListElement": [_row(1)]}, body=body))
    titles = [row["title"].value for row in result.rows]
    assert titles == ["Widget 1", "Widget 3"]


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
    result = _listing(_html(_item_list(_row(1)), head=head))
    assert result.next_pages == ("https://shop.example.test/c/widgets?page=3",)
    # No source states the next page as a field value, so the page field is not filled from the link (C7, D-0355).
    assert result.entity is not None
    assert result.entity["next_page_url"].status == "missing"


def test_role_c_is_not_asked_for_a_listing_whose_structured_data_gives_rows() -> None:
    # ARCHITECTURE §8.6: rows come from structured data or from role C; a row's own gaps stay missing (D-0516).
    role_c = FakeRoleC()
    _listing(_html(_item_list({"@type": "Product", "url": "https://shop.example.test/p/1"})), role_c=role_c)
    assert (role_c.requests, role_c.listing_requests) == ([], [])


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


def _llm_row(position: int) -> Entity:
    return Entity(id=f"llm:rows[{position}]", kind="page", urls=(), parent=None)


ROWS_REPLY = ListingGapReply(
    candidates=(
        _llm("title", "llm:rows[0]", "Widget 1", 0),
        _llm("url", "llm:rows[0]", "https://shop.example.test/p/1", 9),
        _llm("title", "llm:rows[1]", "Widget 2", 40),
        _llm("page_title", "page", "All widgets", 60),
    ),
    llm_calls=(LISTING_CALL,),
    diagnostics=("role C: rows[1].url ungrounded",),
    rows=(_llm_row(0), _llm_row(1)),
)


def test_a_listing_without_structured_rows_takes_its_rows_from_role_c() -> None:
    role_c = FakeRoleC(listing_reply=ROWS_REPLY)
    result = _listing(_html(body="<p>Widget 1</p>"), role_c=role_c)

    (request,) = role_c.listing_requests
    assert (request.row_fields, request.page_missing) == (("title", "url", "price"), ("page_title", "next_page_url"))
    assert _row_values(result) == [{"title": "Widget 1", "url": "https://shop.example.test/p/1"}, {"title": "Widget 2"}]
    assert [(row["title"].evidence, row["title"].locator) for row in result.rows] == [
        ("llm_grounded", "text:0-8"),
        ("llm_grounded", "text:40-48"),
    ]
    # A row owns only its own values, and the page field is the page's, not a row's.
    assert [(row["url"].status, row["url"].reason) for row in result.rows][1] == ("missing", "not_owned")
    assert result.entity is not None
    assert (result.entity["page_title"].value, result.entity["next_page_url"].status) == ("All widgets", "missing")
    assert (result.llm_calls, result.diagnostics[-1]) == ((LISTING_CALL,), "role C: rows[1].url ungrounded")
    assert result.candidates[-4:] == ROWS_REPLY.candidates
    # The second row lacks its required url, so the page is partial (§10 "Incomplete pages").
    assert result.outcome == "partial"


def test_a_page_field_the_page_states_is_not_asked_again() -> None:
    role_c = FakeRoleC()
    _listing(_html(head='<meta property="og:title" content="All widgets">'), role_c=role_c)
    assert [r.page_missing for r in role_c.listing_requests] == [("next_page_url",)]


def test_a_listing_role_c_failure_leaves_the_asked_page_fields_missing_with_its_reason() -> None:
    failed = ListingGapReply(candidates=(), llm_calls=(), failure="llm_unavailable", diagnostics=("role C: x",))
    result = _listing(_html(), role_c=FakeRoleC(listing_reply=failed))
    assert result.entity is not None
    assert {name: (o.status, o.reason) for name, o in result.entity.items()} == {
        "page_title": ("missing", "llm_unavailable"),
        "next_page_url": ("missing", "llm_unavailable"),
    }
    assert (result.rows, result.outcome, result.diagnostics) == ((), "partial", ("role C: x",))


def test_a_listing_schema_without_row_fields_does_not_call_role_c() -> None:
    role_c = FakeRoleC()
    schema = _schema("listing", page_title=LISTING.fields["page_title"])
    _listing(_html(), schema, role_c=role_c)
    assert role_c.listing_requests == []


def test_a_listing_role_c_error_propagates() -> None:
    html, role_c = _html(), FakeRoleC(error=LookupError("no recorded response"))
    with pytest.raises(LookupError, match="no recorded response"):
        _listing(html, role_c=role_c)


def test_a_listing_parses_the_capture_once_per_parser(parses: Parses) -> None:
    body = '<a href="/c/widgets?page=3">3</a>'
    result = _listing(_html(_item_list(_row(1)), head='<meta property="og:title" content="All widgets">', body=body))
    assert result.next_pages == ("https://shop.example.test/c/widgets?page=3",)
    assert parses["selectolax"].calls == 1
    assert parses["lxml"].calls <= 1


@pytest.mark.parametrize(("url_n", "expected"), [(40, 0.975), (29, None)])
def test_a_listings_confidence_is_its_least_confident_rows(url_n: int, expected: float | None) -> None:
    # §10 per record: a row's confidence is its least confident required field's; one uncalibrated row has none.
    buckets = {"text|structured": Bucket(n=40, precision=0.99), "url|structured": Bucket(n=url_n, precision=0.975)}
    calibration = Calibration(eval_run_id=EvalRunId(uuid7()), git_sha="a" * 40, buckets=buckets)
    data = EngineData(VOCABULARY, DATA.orders, calibration)
    result = _listing(_html(_item_list(_row(1), _row(2))), data=data)
    assert result.record_confidence == expected
