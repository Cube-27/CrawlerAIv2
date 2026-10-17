# crawlerai-sdk (Python)

A typed client for the CrawlerAI API over `httpx`, with pydantic models generated from the API's OpenAPI document
(`src/crawlerai_sdk/models.py`; `./generate.sh` regenerates it and CI fails when it is stale). Python 3.12 or later.

```sh
pip install ./sdk/python        # from a checkout; the package is not published yet
export CRAWLERAI_API_KEY=ck_...   # from `crawlerai apikey create --label me`
```

## Usage

```python
import os
from crawlerai_sdk import APIError, CrawlerAI

with CrawlerAI(os.environ["CRAWLERAI_API_KEY"], "http://localhost:8000") as client:
    # One page, fetched while you wait.
    page = client.scrape(url="https://example.com/", formats=["markdown", "links"])
    print(page.markdown)

    # The URLs of a site.
    print(client.map(url="https://example.com/", limit=50).urls)

    # Web search; with `scrape`, the results are scraped by a batch job.
    try:
        found = client.search(query="python asyncio", limit=5, scrape={"formats": ["markdown"]})
    except APIError as error:
        if error.type == "search_unavailable":  # the operator configured no search provider
            ...
        raise
    for hit in found.results:
        print(hit.position, hit.title, hit.url)
    summary = client.wait_for_job(found.job_id, timeout=120)   # polls until completed, failed or cancelled

    # A crawl that fetches the pages matching a query first, then follows its events and pages its results.
    job = client.crawl(
        url="https://docs.example.com/guide/",
        formats=["markdown"],
        strategy="best_first",
        query="rate limits retry",
        limit=20,
    )
    for event in client.events(job.job_id):      # server-sent events until the job ends
        print(event.kind, event.data)
    for result in client.iter_job_results(job.job_id):
        print(result["url"], result["status"])
```

A request is the endpoint's model (`models.CrawlRequest`) or its members as keyword arguments. Members are validated
before anything is sent, and only the ones you give are sent, so the server's defaults apply to the rest. Every
failure answered by the API is an `APIError` with `status`, `type` (`validation`, `ssrf_rejected`,
`search_unavailable`, ...), `detail` and, for a 422, `errors`. `AsyncCrawlerAI` has the same methods, awaited
(`async for event in client.events(job_id)`).

## Webhooks

A job with a `webhook_url` is POSTed its summary when it ends, signed with the webhook secret of the key that
submitted it (`X-CrawlerAI-Signature: sha256=<hex>`, the HMAC-SHA256 of the raw body). Verify before you parse:

```python
from crawlerai_sdk import InvalidSignature, parse_webhook

def handle(body: bytes, signature_header: str | None) -> None:
    try:
        summary = parse_webhook(os.environ["CRAWLERAI_WEBHOOK_SECRET"], body, signature_header)
    except InvalidSignature:
        return  # not from the API
    print(summary.id, summary.status)
```

`verify_signature(secret, body, header)` returns the boolean, and `sign(secret, body)` builds a header for tests.

## Development

```sh
uv venv && uv pip install -e ".[dev]"
.venv/bin/ruff check src tests && .venv/bin/mypy src tests && .venv/bin/pytest
./generate.sh          # after `make api-client` changed frontend/openapi.json
python examples/quickstart.py   # against a running API
```
