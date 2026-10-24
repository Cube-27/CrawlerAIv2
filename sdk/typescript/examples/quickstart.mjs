// Search, crawl best-first, and follow the jobs: run `pnpm build` first, then
// SNOWCRAWL_API_KEY=... node examples/quickstart.mjs (and SNOWCRAWL_URL for another server).
import { APIError, Snowcrawl } from "../dist/index.js";

const client = new Snowcrawl(process.env.SNOWCRAWL_API_KEY, {
  baseUrl: process.env.SNOWCRAWL_URL ?? "http://localhost:8000",
});

// Search the web, and scrape the results in a batch job.
try {
  const found = await client.search({ query: "python asyncio event loop", limit: 3, scrape: { formats: ["markdown"] } });
  for (const hit of found.results) console.log(hit.position, hit.title, hit.url);
  if (found.job_id) {
    const done = await client.waitForJob(found.job_id, { pollIntervalS: 1, timeoutS: 120 });
    console.log("scrape", done.status, done.counts.done, "pages");
  }
} catch (error) {
  if (!(error instanceof APIError) || error.type !== "search_unavailable") throw error;
  console.log("no search provider is configured on this server");
}

// Crawl a docs section best-first: the pages about the query come first.
const job = await client.crawl({
  url: "https://docs.example.com/guide/",
  formats: ["markdown"],
  strategy: "best_first",
  query: "asyncio event loop",
  max_depth: 2,
  limit: 5,
});
for await (const event of client.events(job.job_id)) console.log("event", event.kind);
for await (const page of client.iterJobResults(job.job_id)) if (page.status === "done") console.log(page.url);
