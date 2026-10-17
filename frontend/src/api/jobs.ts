/** The job endpoints (SPEC-10 §4.2–4.5), in the generated shapes. */
import type { ApiClient } from "./client";
import type { RecordPage, StoredRecord } from "./records";
import type { Opened } from "./events";
import { apiResult, type ApiResult } from "./result";
import type { components, operations } from "./schema";
import type { FetchMember, SchemaRef } from "./scrape";

type Schemas = components["schemas"];

/** A job's schema: by id, inline (a SchemaDef the server validates), or field names to draft one from (SPEC-14
 * §4.10). `BatchScrapeRequest` and `CrawlRequest` take no prompt. */
export type JobSchemaRef = Exclude<SchemaRef, { prompt: string }>;

export type JobSummary = Schemas["JobSummary"];
export type JobPage = Schemas["JobPage"];
export type JobKind = JobSummary["kind"];
export type JobStatus = JobSummary["status"];
export type TaskCounts = Schemas["TaskCounts"];
export type OutcomeCounts = Schemas["OutcomeCounts"];
/** A `url_task` outcome (ARCHITECTURE §6). */
export type TaskOutcome = keyof OutcomeCounts;
export type PageOutput = Schemas["PageOutput"];
export type TaskStatus = PageOutput["status"];
export type PageOutputPage = Schemas["PageOutputPage"];
export type ExportPage = Schemas["ExportPage"];
export type ExportFormat = ExportPage["format"];
export type JsonValuesPage = Schemas["JsonValuesPage"];
export type JsonValuesItem = Schemas["JsonValuesItem"];
export type PageKindRule = Schemas["PageKindRule"];
export type MapResult = Schemas["MapResult"];

/** The requests as the forms build them. The generated types mark every member with a default as required
 * (openapi-typescript), so a request that leaves a default to the server is sent as that type; the server validates
 * it. */
export type BatchRequest = Omit<Schemas["BatchScrapeRequest"], "fetch" | "schema"> & {
  fetch: FetchMember;
  schema: JobSchemaRef | null;
};
export type CrawlRequest = Omit<
  Schemas["CrawlRequest"],
  "fetch" | "schema" | "limit" | "max_depth" | "strategy" | "allow_subdomains" | "allow_external"
> & {
  fetch: FetchMember;
  schema: JobSchemaRef | null;
  limit?: number;
  max_depth?: number;
  strategy?: CrawlStrategy;
  allow_subdomains?: boolean;
  allow_external?: boolean;
};
export type CrawlStrategy = Schemas["CrawlRequest"]["strategy"];
export type ExtractRequest = Omit<
  Schemas["ExtractRequest"],
  "fetch" | "schema" | "budget" | "limit"
> & {
  fetch: FetchMember;
  schema: SchemaRef;
  budget?: Schemas["Budget"];
  limit?: number;
};
export type MapRequest = Pick<Schemas["MapRequest"], "url" | "include" | "exclude"> &
  Partial<Pick<Schemas["MapRequest"], "limit" | "use_sitemaps" | "use_links">>;

/** A job's results page in `format=json`: its records, or, for a job without a schema, its page outputs. */
export type ResultsPage =
  | { kind: "records"; page: RecordPage }
  | { kind: "pages"; page: PageOutputPage };

/** The page sizes `GET /v1/jobs/{id}/results` allows (SPEC-07 §4.6): an export reads the largest. */
const EXPORT_LIMIT = 200;

// The server's 200 answer is a union; its items tell which: a record has `fields`, a page output does not.
function isRecord(item: StoredRecord | PageOutput): item is StoredRecord {
  return "fields" in item;
}

function isPageOutput(item: StoredRecord | PageOutput): item is PageOutput {
  return !isRecord(item);
}

function resultsPage(page: RecordPage | ExportPage | PageOutputPage | JsonValuesPage): ResultsPage {
  if ("format" in page)
    throw new Error("GET /v1/jobs/{id}/results answered an export to format=json");
  const items: (StoredRecord | PageOutput)[] = page.items;
  const { next_cursor } = page;
  const outputs = items.filter(isPageOutput);
  // An empty page is a page of records: a job without a schema lists every task from its start (D-0630).
  return outputs.length === 0
    ? { kind: "records", page: { items: items.filter(isRecord), next_cursor } }
    : { kind: "pages", page: { items: outputs, next_cursor } };
}

type ResultsQuery = NonNullable<
  operations["job_results_v1_jobs__job_id__results_get"]["parameters"]["query"]
>;

function results(client: ApiClient, id: string, query: ResultsQuery) {
  return client.GET("/v1/jobs/{job_id}/results", { params: { path: { job_id: id }, query } });
}

// SPEC-10 §4.2: a completed or failed job can't be cancelled (409); a cancelled one is already.
const CANCELLABLE: ReadonlySet<JobStatus> = new Set<JobStatus>(["queued", "running"]);

/** Where a job is with cancelling: it can be cancelled, a cancel was asked for (it ends once its claimed tasks end),
 * or it has ended. */
export function cancelState(job: JobSummary): "cancellable" | "requested" | "ended" {
  if (!CANCELLABLE.has(job.status)) return "ended";
  return job.cancel_requested ? "requested" : "cancellable";
}

/** Which jobs a list shows: one kind and one status, or every one when null (SPEC-10 §4.2). */
export interface JobFilters {
  kind: JobKind | null;
  status: JobStatus | null;
}

/** One page of the jobs that pass `filters`, newest first: the first when `cursor` is null, `limit` jobs at most. */
export function listJobs(
  client: ApiClient,
  { filters, cursor, limit }: { filters: JobFilters; cursor: string | null; limit: number },
): Promise<ApiResult<JobPage>> {
  const query = {
    ...(filters.kind === null ? {} : { kind: filters.kind }),
    ...(filters.status === null ? {} : { status: filters.status }),
    ...(cursor === null ? {} : { cursor }),
    limit,
  };
  return apiResult(() => client.GET("/v1/jobs", { params: { query } }), "Listing the jobs");
}

export function getJob(client: ApiClient, id: string): Promise<ApiResult<JobSummary>> {
  return apiResult(
    () => client.GET("/v1/jobs/{job_id}", { params: { path: { job_id: id } } }),
    "Loading the job",
  );
}

/** The request the job was submitted with, as the server stored it (defaults filled in). */
export function getJobRequest(
  client: ApiClient,
  id: string,
): Promise<ApiResult<Readonly<Record<string, unknown>>>> {
  return apiResult(
    () => client.GET("/v1/jobs/{job_id}/request", { params: { path: { job_id: id } } }),
    "Loading the job's request",
  );
}

/** Cancels the job; the answer is its summary after the cancel. */
export function cancelJob(client: ApiClient, id: string): Promise<ApiResult<JobSummary>> {
  return apiResult(
    () => client.DELETE("/v1/jobs/{job_id}", { params: { path: { job_id: id } } }),
    "Cancelling the job",
  );
}

/** The job's results at `cursor` (the first page when null), `limit` at most. */
export async function listJobResults(
  client: ApiClient,
  id: string,
  { cursor, limit }: { cursor: string | null; limit: number },
): Promise<ApiResult<ResultsPage>> {
  const query: ResultsQuery = { ...(cursor === null ? {} : { cursor }), limit };
  const result = await apiResult(() => results(client, id, query), "Listing the job's results");
  return result.kind === "done" ? { kind: "done", value: resultsPage(result.value) } : result;
}

/** What a `json_values` read asks of each page beyond its records: its metadata (`include=metadata`) and how it was
 * fetched (`include=fetch`, D-1392). */
export interface ValuesPage {
  cursor: string | null;
  limit: number;
  withMetadata: boolean;
  withFetch: boolean;
}

/** One page of the job's tasks as `json_values` items (SPEC-14 §4.4) at `cursor` (the first page when null), `limit`
 * at most. */
export async function listJobValues(
  client: ApiClient,
  id: string,
  { cursor, limit, withMetadata, withFetch }: ValuesPage,
): Promise<ApiResult<JsonValuesPage>> {
  const include = [
    ...(withMetadata ? ["metadata" as const] : []),
    ...(withFetch ? ["fetch" as const] : []),
  ];
  const query: ResultsQuery = {
    format: "json_values",
    limit,
    ...(cursor === null ? {} : { cursor }),
    ...(include.length === 0 ? {} : { include }),
  };
  const result = await apiResult(() => results(client, id, query), "Listing the job's pages");
  if (result.kind === "failed") return result;
  const page = result.value;
  if (!("format" in page) || page.format !== "json_values")
    throw new Error("GET /v1/jobs/{id}/results answered format=json_values with another format");
  return { kind: "done", value: page };
}

/** Every item of the pages `read` gives, at the largest page size, read in turn by cursor. */
async function allItems<T>(
  read: (cursor: string | null) => Promise<ApiResult<{ items: T[]; next_cursor: string | null }>>,
): Promise<ApiResult<T[]>> {
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    // Sequential: each page's cursor comes from the page before it (SPEC-07 §4.6).
    const page = await read(cursor);
    if (page.kind === "failed") return page;
    items.push(...page.value.items);
    cursor = page.value.next_cursor;
  } while (cursor !== null);
  return { kind: "done", value: items };
}

/** Every page of the job's `json_values` items. */
export function exportJobValues(
  client: ApiClient,
  id: string,
  withMetadata: boolean,
): Promise<ApiResult<JsonValuesItem[]>> {
  return allItems((cursor) =>
    listJobValues(client, id, { cursor, limit: EXPORT_LIMIT, withMetadata, withFetch: false }),
  );
}

/** Every page output of a job without a schema (`format=json`, SPEC-10 §4.2): what its JSON export saves, as its
 * drawers show them. */
export function exportJobOutputs(client: ApiClient, id: string): Promise<ApiResult<PageOutput[]>> {
  return allItems(async (cursor) => {
    const page = await listJobResults(client, id, { cursor, limit: EXPORT_LIMIT });
    if (page.kind === "failed") return page;
    const { kind, page: results } = page.value;
    const items = kind === "pages" ? results.items : [];
    return { kind: "done", value: { items, next_cursor: results.next_cursor } };
  });
}

/** One page of the job's records exported as `format`, at the largest page size. */
export async function exportJobPage(
  client: ApiClient,
  id: string,
  format: ExportFormat,
  cursor: string | null,
): Promise<ApiResult<ExportPage>> {
  const query: ResultsQuery = {
    format,
    limit: EXPORT_LIMIT,
    ...(cursor === null ? {} : { cursor }),
    // An export is saved as a file for spreadsheets: quote formula-like cells (OWASP CSV Injection, D-0879).
    ...(format === "csv_records" ? { csv_safe: true } : {}),
  };
  const result = await apiResult(() => results(client, id, query), "Exporting the job's records");
  if (result.kind === "failed") return result;
  const page = result.value;
  if (!("content" in page))
    throw new Error(`GET /v1/jobs/{id}/results answered format=${format} with JSON`);
  return { kind: "done", value: page };
}

/** Queues a batch scrape; the answer is the new job's id. */
export async function submitBatch(
  client: ApiClient,
  body: BatchRequest,
): Promise<ApiResult<string>> {
  const result = await apiResult(
    // The server applies the defaults this request leaves out (see `BatchRequest`).
    () => client.POST("/v1/batch/scrape", { body: body as Schemas["BatchScrapeRequest"] }),
    "Queuing the batch",
  );
  return result.kind === "done" ? { kind: "done", value: result.value.job_id } : result;
}

/** Queues a crawl; the answer is the new job's id. */
export async function submitCrawl(
  client: ApiClient,
  body: CrawlRequest,
): Promise<ApiResult<string>> {
  const result = await apiResult(
    // The server applies the defaults this request leaves out (see `CrawlRequest`).
    () => client.POST("/v1/crawl", { body: body as Schemas["CrawlRequest"] }),
    "Queuing the crawl",
  );
  return result.kind === "done" ? { kind: "done", value: result.value.job_id } : result;
}

/** Queues an extract; a prompt is drafted into a schema first (SPEC-10 §4.6). The answer is the new job's id. */
export async function submitExtract(
  client: ApiClient,
  body: ExtractRequest,
): Promise<ApiResult<string>> {
  const result = await apiResult(
    // The server applies the defaults this request leaves out (see `ExtractRequest`).
    () => client.POST("/v1/extract", { body: body as Schemas["ExtractRequest"] }),
    "Queuing the extract",
  );
  return result.kind === "done" ? { kind: "done", value: result.value.job_id } : result;
}

/** The site's URLs (`POST /v1/map` answers at once; it makes no job). */
export function mapUrls(client: ApiClient, body: MapRequest): Promise<ApiResult<MapResult>> {
  return apiResult(
    // The server applies the defaults this request leaves out (see `MapRequest`).
    () => client.POST("/v1/map", { body: body as Schemas["MapRequest"] }),
    "Mapping the site",
  );
}

/** Opens the job's event stream after `lastEventId` with the client's key (SPEC-12 §4.1: `EventSource` cannot send
 * it). `followEvents` reads the response's body, or its status and parsed error body. */
export async function openJobEvents(
  client: ApiClient,
  id: string,
  lastEventId: string | null,
  signal: AbortSignal,
): Promise<Opened> {
  const { response, error } = await client.GET("/v1/jobs/{job_id}/events", {
    params: {
      path: { job_id: id },
      ...(lastEventId === null ? {} : { header: { "last-event-id": lastEventId } }),
    },
    parseAs: "stream",
    signal,
  });
  return { response, error };
}

export type SearchResult = Schemas["SearchResult"];
export type SearchHit = Schemas["SearchHit"];
/** The search request as the form builds it: `scrape` leaves out the members it does not set, so the server's defaults
 * apply. */
export interface SearchRequest {
  query: string;
  limit?: number;
  scrape?: {
    formats: Schemas["SearchScrape"]["formats"];
    schema?: { id: string };
    page_kind?: PageKindRule["page_kind"];
  };
}

/** The web results of a query (`POST /v1/search` answers at once); with `scrape`, a batch job scrapes them. */
export function searchWeb(
  client: ApiClient,
  body: SearchRequest,
): Promise<ApiResult<SearchResult>> {
  return apiResult(
    // The server applies the defaults this request leaves out (see `SearchRequest`).
    () => client.POST("/v1/search", { body: body as Schemas["SearchRequest"] }),
    "Searching the web",
  );
}
