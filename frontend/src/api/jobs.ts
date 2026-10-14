/** The job endpoints (SPEC-10 §4.2–4.5), in the generated shapes. */
import type { ApiClient } from "./client";
import type { RecordPage, StoredRecord } from "./records";
import type { Opened } from "./events";
import { apiResult, type ApiResult } from "./result";
import type { components, operations } from "./schema";
import type { SchemaRef } from "./scrape";

type Schemas = components["schemas"];

/** A job's schema: by id, or inline (a SchemaDef the server validates). `BatchScrapeRequest` and
 * `CrawlRequest` take no prompt. */
export type JobSchemaRef = Exclude<SchemaRef, { prompt: string }>;

export type JobSummary = Schemas["JobSummary"];
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
export type PageKindRule = Schemas["PageKindRule"];
export type MapResult = Schemas["MapResult"];

/** The requests as the forms build them. The generated types mark every member with a default as required
 * (openapi-typescript), so a request that leaves a default to the server is sent as that type; the server validates
 * it. */
export type BatchRequest = Omit<Schemas["BatchScrapeRequest"], "fetch" | "schema"> & {
  fetch: Pick<Schemas["FetchOptions"], "method_hint">;
  schema: JobSchemaRef | null;
};
export type CrawlRequest = Omit<Schemas["CrawlRequest"], "fetch" | "schema" | "limit" | "max_depth"> & {
  fetch: Pick<Schemas["FetchOptions"], "method_hint">;
  schema: JobSchemaRef | null;
  limit?: number;
  max_depth?: number;
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

function resultsPage(page: RecordPage | ExportPage | PageOutputPage): ResultsPage {
  if ("content" in page) throw new Error("GET /v1/jobs/{id}/results answered an export to format=json");
  const items: (StoredRecord | PageOutput)[] = page.items;
  const { next_cursor } = page;
  const outputs = items.filter(isPageOutput);
  // An empty page is a page of records: a job without a schema lists every task from its start (D-0630).
  return outputs.length === 0
    ? { kind: "records", page: { items: items.filter(isRecord), next_cursor } }
    : { kind: "pages", page: { items: outputs, next_cursor } };
}

type ResultsQuery = NonNullable<operations["job_results_v1_jobs__job_id__results_get"]["parameters"]["query"]>;

function results(client: ApiClient, id: string, query: ResultsQuery) {
  return client.GET("/v1/jobs/{job_id}/results", { params: { path: { job_id: id }, query } });
}

export function getJob(client: ApiClient, id: string): Promise<ApiResult<JobSummary>> {
  return apiResult(
    () => client.GET("/v1/jobs/{job_id}", { params: { path: { job_id: id } } }),
    "Loading the job",
  );
}

/** Cancels the job; the answer is its summary after the cancel. */
export function cancelJob(client: ApiClient, id: string): Promise<ApiResult<JobSummary>> {
  return apiResult(
    () => client.DELETE("/v1/jobs/{job_id}", { params: { path: { job_id: id } } }),
    "Cancelling the job",
  );
}

/** The job's results at `cursor` (the first page when null), at the server's page size. */
export async function listJobResults(
  client: ApiClient,
  id: string,
  cursor: string | null,
): Promise<ApiResult<ResultsPage>> {
  const query: ResultsQuery = cursor === null ? {} : { cursor };
  const result = await apiResult(() => results(client, id, query), "Listing the job's results");
  return result.kind === "done" ? { kind: "done", value: resultsPage(result.value) } : result;
}

/** One page of the job's records exported as `format`, at the largest page size. */
export async function exportJobPage(
  client: ApiClient,
  id: string,
  format: ExportFormat,
  cursor: string | null,
): Promise<ApiResult<ExportPage>> {
  const query: ResultsQuery = { format, limit: EXPORT_LIMIT, ...(cursor === null ? {} : { cursor }) };
  const result = await apiResult(() => results(client, id, query), "Exporting the job's records");
  if (result.kind === "failed") return result;
  const page = result.value;
  if (!("content" in page)) throw new Error(`GET /v1/jobs/{id}/results answered format=${format} with JSON`);
  return { kind: "done", value: page };
}

/** Queues a batch scrape; the answer is the new job's id. */
export async function submitBatch(client: ApiClient, body: BatchRequest): Promise<ApiResult<string>> {
  const result = await apiResult(
    // The server applies the defaults this request leaves out (see `BatchRequest`).
    () => client.POST("/v1/batch/scrape", { body: body as Schemas["BatchScrapeRequest"] }),
    "Queuing the batch",
  );
  return result.kind === "done" ? { kind: "done", value: result.value.job_id } : result;
}

/** Queues a crawl; the answer is the new job's id. */
export async function submitCrawl(client: ApiClient, body: CrawlRequest): Promise<ApiResult<string>> {
  const result = await apiResult(
    // The server applies the defaults this request leaves out (see `CrawlRequest`).
    () => client.POST("/v1/crawl", { body: body as Schemas["CrawlRequest"] }),
    "Queuing the crawl",
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
