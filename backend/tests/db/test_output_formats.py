"""The output formats over HTTP (`POST /v1/scrape`, the artifacts of a capture, `GET /v1/jobs/{id}/results` and its
`llms.txt`): a screenshot and PDF stored beside the capture and served by the API, the files of a job's records,
and the `llms.txt` made from its captures.

The web is a stub of synthetic pages on RFC 2606 hosts; its browser rung answers with a screenshot and PDF as the real
one (`tests/unit/test_browser_fetch.py`) makes them, and its HTTP rung fails the test when a capture format asks it.
"""

import io
import json
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import httpx
import openpyxl
import pyarrow.parquet as pq
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.db.keys import create_key
from crawlerai.db.models import ApiKey, Capture
from crawlerai.resolve.pipeline import EngineData
from crawlerai.scheduler.retention import expire_captures
from crawlerai.services.fetching import Fetching
from crawlerai.storage.artifacts import artifact_key
from crawlerai.storage.fs import FsStore
from tests.db.conftest import LISTING_FIELDS, listing_page

pytestmark = pytest.mark.anyio

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic screenshot"
PDF = b"%PDF-1.4 synthetic print"
PAGE = b"""<!doctype html><html lang="en"><head><title>Blue kettle</title>
<meta name="description" content="A kettle that boils quickly."></head>
<body><main><h1>Blue kettle</h1>
<p>A kettle that boils water quickly and quietly, with a handle that stays cool to the touch while it pours.</p>
<p>It holds one and a half litres and switches itself off once the water boils, so it never boils dry.</p>
</main></body></html>"""
TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}


def _product_page(url: str, name: str) -> bytes:
    node = {"@context": "https://schema.org", "@type": "Product", "name": name, "url": url}
    return PAGE.replace(b"</head>", f'<script type="application/ld+json">{json.dumps(node)}</script></head>'.encode())


@pytest.fixture
async def database(
    database_url: str, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[AsyncEngine]:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    keys_engine = create_async_engine(database_url)
    async with keys_engine.connect() as conn:
        keys = set((await conn.execute(select(ApiKey.id))).scalars())
    yield engine
    async with keys_engine.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id.not_in(keys)))
    await keys_engine.dispose()


@pytest.fixture
def pages(own_origin: str) -> dict[str, tuple[int, bytes]]:
    return {f"{own_origin}/robots.txt": (200, b"User-agent: *\nAllow: /\n")}


@pytest.fixture
def policies() -> list[FetchPolicy]:
    """The policy of each page fetch, by the rung that made it: the browser's."""
    return []


@pytest.fixture
def fetching(
    fetch_result: Callable[..., FetchResult],
    pages: dict[str, tuple[int, bytes]],
    policies: list[FetchPolicy],
    tmp_path: Path,
) -> Fetching:
    async def http(url: str, policy: FetchPolicy) -> FetchResult:
        status, body = pages.get(url, (404, b""))
        assert url.endswith("/robots.txt") or not policy.captures_page, "a capture format was fetched over HTTP"
        return fetch_result(url, status, body, block_class="ok" if status == 200 else "not_found", policy=policy)

    async def browser(url: str, policy: FetchPolicy) -> FetchResult:
        policies.append(policy)
        status, body = pages.get(url, (404, b""))
        result = fetch_result(url, status, body, method="browser", policy=policy)
        files = {**({"screenshot.png": PNG} if policy.screenshot else {}), **({"page.pdf": PDF} if policy.pdf else {})}
        return result.model_copy(update={"artifacts": files})

    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("93.184.215.14")]

    return Fetching(
        Rungs(http=http, browser=browser), SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter()
    )


@pytest.fixture
async def client(
    database: AsyncEngine, fetching: Fetching, engine_data: EngineData
) -> AsyncIterator[httpx.AsyncClient]:
    async with database.begin() as conn:
        key = await create_key(conn, "output-formats-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        app.state.fetching = fetching
        app.state.engine_data = engine_data
        yield client


async def _scrape(client: httpx.AsyncClient, url: str, **body: Any) -> dict[str, Any]:
    response = await client.post("/v1/scrape", json={"url": url, **body})
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


async def test_a_screenshot_and_a_pdf_are_made_in_the_browser_stored_and_served_by_the_api(
    client: httpx.AsyncClient,
    pages: dict[str, tuple[int, bytes]],
    own_origin: str,
    policies: list[FetchPolicy],
    fetching: Fetching,
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)

    body = await _scrape(client, url, formats=["screenshot", "pdf"], fetch={"screenshot": "full_page"})

    capture_id = body["capture_id"]
    assert body["screenshot"] == {
        "url": f"/v1/captures/{capture_id}/artifacts/screenshot.png",
        "content_type": "image/png",
    }
    assert body["pdf"] == {"url": f"/v1/captures/{capture_id}/artifacts/page.pdf", "content_type": "application/pdf"}
    assert "markdown" not in body
    assert [(p.method_hint, p.screenshot, p.pdf) for p in policies] == [("browser", "full_page", True)]
    served = await client.get(body["screenshot"]["url"])
    assert (served.status_code, served.headers["content-type"], served.content) == (200, "image/png", PNG)
    assert served.headers["x-content-type-options"] == "nosniff"
    assert (await client.get(body["pdf"]["url"])).content == PDF
    stored = fetching.store.list("captures/")
    assert sorted(key.split(".", 1)[1] for key in stored) == ["bundle.zst", "page.pdf", "screenshot.png"]


async def test_a_viewport_screenshot_is_the_default_and_a_pdf_alone_makes_no_screenshot(
    client: httpx.AsyncClient,
    pages: dict[str, tuple[int, bytes]],
    own_origin: str,
    policies: list[FetchPolicy],
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)

    shot = await _scrape(client, url, formats=["screenshot"])
    pdf = await _scrape(client, url, formats=["pdf"])

    assert "pdf" not in shot
    assert "screenshot" not in pdf
    assert [(p.screenshot, p.pdf) for p in policies] == [("viewport", False), (None, True)]


async def test_a_screenshot_is_refused_over_http_before_any_job_is_made(
    client: httpx.AsyncClient, own_origin: str
) -> None:
    response = await client.post(
        "/v1/scrape",
        json={"url": f"{own_origin}/kettles/blue", "formats": ["screenshot"], "fetch": {"method_hint": "http"}},
    )

    assert response.status_code == 422
    assert "browser" in response.text


async def test_max_age_reuses_a_capture_only_when_it_holds_the_file_asked_for(
    client: httpx.AsyncClient,
    pages: dict[str, tuple[int, bytes]],
    own_origin: str,
    policies: list[FetchPolicy],
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)
    first = await _scrape(client, url, formats=["markdown"])

    again = await _scrape(client, url, formats=["screenshot"], max_age=3600)
    reused = await _scrape(client, url, formats=["screenshot"], max_age=3600)

    assert first["capture_id"] != again["capture_id"]
    assert reused["capture_id"] == again["capture_id"]
    assert len(policies) == 1
    assert reused["screenshot"] == again["screenshot"]


async def test_an_artifact_that_does_not_exist_is_a_404(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)
    body = await _scrape(client, url, formats=["screenshot"])
    capture_id = body["capture_id"]

    assert (await client.get(f"/v1/captures/{capture_id}/artifacts/page.pdf")).status_code == 404
    assert (await client.get(f"/v1/captures/{capture_id}/artifacts/body.html")).status_code == 404
    assert (
        await client.get(f"/v1/captures/{'0' * 8}-0000-7000-8000-{'0' * 12}/artifacts/screenshot.png")
    ).status_code == 404
    unauthenticated = httpx.AsyncClient(transport=client._transport, base_url="http://api.test")
    async with unauthenticated:
        assert (await unauthenticated.get(f"/v1/captures/{capture_id}/artifacts/screenshot.png")).status_code == 401


async def test_retention_deletes_the_artifacts_with_the_bundle(
    client: httpx.AsyncClient,
    pages: dict[str, tuple[int, bytes]],
    own_origin: str,
    fetching: Fetching,
    database: AsyncEngine,
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)
    body = await _scrape(client, url, formats=["screenshot", "pdf"])
    async with database.begin() as conn:
        await conn.execute(
            update(Capture).where(Capture.id == body["capture_id"]).values(expires_at=func.now() - timedelta(seconds=1))
        )
        deleted = await expire_captures(conn, fetching.store, batch=10)

    assert deleted >= 1
    assert not any(str(body["capture_id"]) in key for key in fetching.store.list("captures/"))


async def test_a_jobs_page_outputs_name_the_files_and_the_formats_with_their_options(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)
    formats = ["screenshot", "markdown_fit", "chunks"]
    body = await _scrape(
        client,
        url,
        formats=formats,
        fit={"query": "litres boils", "max_blocks": 1},
        chunking={"strategy": "sentence", "size": 12},
    )

    results = await client.get(f"/v1/jobs/{body['job_id']}/results")

    (item,) = results.json()["items"]
    assert item["screenshot"] == body["screenshot"]
    assert item["markdown_fit"] == body["markdown_fit"]
    assert item["chunks"] == body["chunks"]
    assert len(body["chunks"]) > 1
    assert "litres" in body["markdown_fit"]
    assert "quietly" not in body["markdown_fit"]


async def test_options_need_their_format(client: httpx.AsyncClient, own_origin: str) -> None:
    url = f"{own_origin}/kettles/blue"
    for options in ({"fit": {"query": "x"}}, {"chunking": {"size": 10}}):
        response = await client.post("/v1/scrape", json={"url": url, "formats": ["markdown"], **options})

        assert response.status_code == 422, options


async def test_llms_txt_and_llms_full_txt_of_a_jobs_pages(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)
    body = await _scrape(client, url, formats=["markdown"])

    short = await client.get(f"/v1/jobs/{body['job_id']}/llms.txt")
    full = await client.get(f"/v1/jobs/{body['job_id']}/llms-full.txt")

    assert short.headers["content-type"].startswith("text/plain")
    assert short.text == (
        "# Blue kettle\n\n> A kettle that boils quickly.\n\n## Pages\n\n"
        f"- [Blue kettle]({url}): A kettle that boils quickly.\n"
    )
    assert full.text.startswith("# Blue kettle\n\n> A kettle that boils quickly.\n\n## Blue kettle\n\n")
    assert f"Source: {url}" in full.text
    assert "switches itself off" in full.text


async def test_llms_txt_of_a_job_that_reached_nothing_is_a_conflict(client: httpx.AsyncClient, own_origin: str) -> None:
    missing = await _scrape(client, f"{own_origin}/nowhere", formats=["markdown"])

    response = await client.get(f"/v1/jobs/{missing['job_id']}/llms.txt")

    assert response.status_code == 409
    assert (await client.get(f"/v1/jobs/{'0' * 8}-0000-7000-8000-{'0' * 12}/llms.txt")).status_code == 404


async def _records_job(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], origin: str, schema_name: str, names: list[str]
) -> str:
    """A scrape of a listing with a row per name, as a job with records."""
    url = f"{origin}/kettles"
    pages[url] = (200, listing_page(origin, names))
    inline = {"name": schema_name, "page_kind": "listing", "fields": LISTING_FIELDS}
    body = await _scrape(client, url, formats=["records"], schema={"inline": inline}, page_kind="listing")
    return str(body["job_id"])


async def test_a_jobs_records_are_exported_as_jsonl_xlsx_and_parquet(
    client: httpx.AsyncClient,
    database: AsyncEngine,
    pages: dict[str, tuple[int, bytes]],
    own_origin: str,
    schema_name: str,
) -> None:
    job_id = await _records_job(client, pages, own_origin, schema_name, ["=Blue kettle", "Red kettle"])
    base = f"/v1/jobs/{job_id}/results"

    jsonl = (await client.get(base, params={"format": "jsonl"})).json()
    xlsx = await client.get(base, params={"format": "xlsx"})
    parquet = await client.get(base, params={"format": "parquet"})

    columns = ["title", "url", "_status_title", "_status_url"]
    # Newest first, as `/v1/records` pages them.
    expected = [
        ["Red kettle", f"{own_origin}/kettles/2", "published", "published"],
        ["=Blue kettle", f"{own_origin}/kettles/1", "published", "published"],
    ]
    assert jsonl["format"] == "jsonl"
    assert [list(json.loads(line).values()) for line in jsonl["content"].splitlines()] == expected
    assert xlsx.headers["content-type"].endswith("spreadsheetml.sheet")
    assert xlsx.headers["content-disposition"] == f'attachment; filename="job-{job_id}.xlsx"'
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx.content))["records"]
    assert [list(row) for row in sheet.iter_rows(values_only=True)] == [columns, *expected]
    assert sheet["A3"].data_type == "s"  # `=Blue kettle` is text, not a formula
    assert parquet.headers["content-type"] == "application/vnd.apache.parquet"
    table = pq.read_table(io.BytesIO(parquet.content))
    assert table.column_names == columns
    assert [list(row.values()) for row in table.to_pylist()] == expected


async def test_a_file_export_takes_no_page_and_a_job_without_records_has_none(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)
    body = await _scrape(client, url, formats=["markdown"])
    base = f"/v1/jobs/{body['job_id']}/results"

    assert (await client.get(base, params={"format": "xlsx", "limit": 5})).status_code == 422
    assert (await client.get(base, params={"format": "parquet", "cursor": body["job_id"]})).status_code == 422
    assert (await client.get(base, params={"format": "xlsx"})).status_code == 409
    assert (await client.get(base, params={"format": "jsonl"})).status_code == 409


async def test_parquet_without_pyarrow_is_a_503_problem(
    client: httpx.AsyncClient,
    database: AsyncEngine,
    pages: dict[str, tuple[int, bytes]],
    own_origin: str,
    schema_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = await _records_job(client, pages, own_origin, schema_name, ["Red kettle"])
    monkeypatch.setitem(__import__("sys").modules, "pyarrow", None)

    response = await client.get(f"/v1/jobs/{job_id}/results", params={"format": "parquet"})

    assert response.status_code == 503
    assert response.json()["type"] == "format_unavailable"


def test_the_artifact_key_sits_beside_the_bundles() -> None:
    assert artifact_key("captures/2026/10/abc.bundle.zst", "page.pdf") == "captures/2026/10/abc.page.pdf"
    with pytest.raises(ValueError, match="no artifact"):
        artifact_key("eval/dev/abc.bundle.zst", "page.pdf")
