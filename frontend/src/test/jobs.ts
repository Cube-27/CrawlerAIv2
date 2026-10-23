import type { JobSummary, StoredJobRequest, StoredRequestOf } from "../api/jobs";

/** A running batch job's summary: three tasks, two done and extracted, one queued. */
export function jobSummary(overrides: Partial<JobSummary> & Pick<JobSummary, "id">): JobSummary {
  return {
    kind: "batch_scrape",
    status: "running",
    counts: { queued: 1, claimed: 0, done: 2, failed: 0, cancelled: 0 },
    outcomes: {
      extracted: 2,
      partial: 0,
      links_only: 0,
      blocked: 0,
      shell: 0,
      not_found: 0,
      no_match: 0,
      auth_wall: 0,
      soft_404: 0,
      geo_redirect: 0,
      redirected_to_listing: 0,
      unsupported_media: 0,
      geo_blocked: 0,
      timeout: 0,
      failed: 0,
    },
    usage: { pages_fetched: 2 },
    llm_cost_usd: 0.0123,
    created_at: "2026-10-14T09:00:00Z",
    started_at: "2026-10-14T09:00:01Z",
    finished_at: null,
    engine_version: "0.0.0",
    webhook_url: null,
    schedule_id: null,
    cancel_requested: false,
    start_url: null,
    url_count: 3,
    ...overrides,
  };
}

type Stored<K extends StoredJobRequest["kind"]> = StoredRequestOf<K>;

/** A stored request's `fetch`: the server's defaults, with `overrides`. */
function storedFetch(
  overrides: Partial<Stored<"batch_scrape">["fetch"]>,
): Stored<"batch_scrape">["fetch"] {
  return {
    method_hint: "auto",
    max_rows: null,
    headers: {},
    cookies: {},
    proxy_pool: null,
    wait_for: null,
    actions: [],
    cache: "default",
    respect_robots: false,
    screenshot: "viewport",
    ...overrides,
  };
}

// The members a queued job's request shares, at the server's defaults.
const QUEUED = {
  locale: null,
  min_confidence: null,
  budget: null,
  webhook_url: null,
  webhook_events: ["job_completed", "job_failed", "job_cancelled"],
  webhook_batch: null,
} satisfies Partial<Stored<"extract">>;

// The members of a request with page formats, at the server's defaults.
const PAGES = {
  ...QUEUED,
  formats: ["markdown"],
  schema: null,
  render: { mode: "off", fields: [] },
  fit: null,
  chunking: null,
} satisfies Partial<Stored<"batch_scrape">>;

/** A batch job's stored request (`GET /v1/jobs/{id}/request`): the server's defaults, with `overrides`. */
export function storedBatch(
  overrides: Partial<Stored<"batch_scrape">> & Pick<Stored<"batch_scrape">, "urls">,
  fetch: Partial<Stored<"batch_scrape">["fetch"]> = {},
): StoredJobRequest {
  return {
    kind: "batch_scrape",
    request: { ...PAGES, page_kind: null, ...overrides, fetch: storedFetch(fetch) },
  };
}

/** A crawl job's stored request: the server's defaults, with `overrides`. */
export function storedCrawl(
  overrides: Partial<Stored<"crawl">> & Pick<Stored<"crawl">, "url">,
): StoredJobRequest {
  return {
    kind: "crawl",
    request: {
      ...PAGES,
      include: [],
      exclude: [],
      page_kind_rules: [],
      max_depth: 3,
      limit: 500,
      strategy: "bfs",
      query: null,
      keywords: [],
      allow_subdomains: false,
      allow_external: false,
      fetch: storedFetch({}),
      ...overrides,
    },
  };
}

/** An extract job's stored request: a stored schema's, with `overrides`. */
export function storedExtract(overrides: Partial<Stored<"extract">> = {}): StoredJobRequest {
  return {
    kind: "extract",
    request: {
      ...QUEUED,
      urls: ["https://shop.test/items/1"],
      schema: { id: "0192a000-0000-7000-8000-0000000000s1" },
      page_kind: "detail",
      limit: 1000,
      fetch: storedFetch({}),
      ...overrides,
    },
  };
}
