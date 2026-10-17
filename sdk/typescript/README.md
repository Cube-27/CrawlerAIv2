# @crawlerai/sdk (TypeScript)

A typed client for the CrawlerAI API over `fetch`, with no runtime dependencies. Its types are generated from the
API's OpenAPI document (`src/schema.d.ts` by `pnpm gen`; CI fails when it is stale). Node 20 or later, and any runtime
with `fetch` and Web Crypto.

```sh
cd sdk/typescript && pnpm install && pnpm build   # the package is not published yet
export CRAWLERAI_API_KEY=ck_...                   # from `crawlerai apikey create --label me`
```

## Usage

```ts
import { APIError, CrawlerAI } from "@crawlerai/sdk";

const client = new CrawlerAI(process.env.CRAWLERAI_API_KEY!, { baseUrl: "http://localhost:8000" });

// One page, fetched while you wait.
const page = await client.scrape({ url: "https://example.com/", formats: ["markdown", "links"] });

// The URLs of a site.
const { urls } = await client.map({ url: "https://example.com/", limit: 50 });

// Web search; with `scrape`, the results are scraped by a batch job.
try {
  const found = await client.search({ query: "python asyncio", limit: 5, scrape: { formats: ["markdown"] } });
  for (const hit of found.results) console.log(hit.position, hit.title, hit.url);
  if (found.job_id) await client.waitForJob(found.job_id, { timeoutS: 120 }); // polls until it ends
} catch (error) {
  if (!(error instanceof APIError) || error.type !== "search_unavailable") throw error; // no provider configured
}

// A crawl that fetches the pages matching a query first, then follows its events and pages its results.
const job = await client.crawl({
  url: "https://docs.example.com/guide/",
  formats: ["markdown"],
  strategy: "best_first",
  query: "rate limits retry",
  limit: 20,
});
for await (const event of client.events(job.job_id)) console.log(event.kind, event.data);
for await (const result of client.iterJobResults(job.job_id)) console.log(result.url, result.status);
```

Only the members you give are sent, so the server's defaults apply to the rest. A problem the API answers with is an
`APIError` (`status`, `type`, `problem`); `waitForJob` rejects with `JobTimeout`. `client.events(jobId, lastEventId)`
resumes a stream after the last id seen.

## Webhooks

A job with a `webhook_url` is POSTed its summary when it ends, signed with the webhook secret of the key that submitted
it (`X-CrawlerAI-Signature: sha256=<hex>`, the HMAC-SHA256 of the raw body). Verify the raw body before you parse it:

```ts
import { parseWebhook, SIGNATURE_HEADER } from "@crawlerai/sdk";

// In a request handler: `body` is the raw text or bytes, never a re-serialised object.
const summary = await parseWebhook(process.env.CRAWLERAI_WEBHOOK_SECRET!, body, request.headers.get(SIGNATURE_HEADER));
console.log(summary.id, summary.status); // parseWebhook throws for a body not signed with the secret
```

`verifyWebhook` returns the boolean and `signWebhook` builds a header for tests.

## Development

```sh
pnpm check && pnpm test      # type-check, then the tests (node:test)
pnpm gen                     # after `make api-client` changed frontend/openapi.json
node examples/quickstart.mjs # against a running API, after `pnpm build`
```
