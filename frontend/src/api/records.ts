/** `GET /v1/records` and `POST /v1/captures/{id}/replay` as SPEC-07 §4.6 defines them, narrowed by hand until SPEC-07
 * PR 8 puts them in `openapi.json`. The module augmentation below adds them to the generated `paths`, so the calls go
 * through the authenticated client (and its 401 handling); delete it, and these types, once `make api-client`
 * generates them. */
import type { ApiClient } from "./client";
import { apiResult, type ApiResult } from "./result";
import type { ScrapeRecord } from "./scrape";

/** A stored record: the field shape of SPEC-07 §4.4, with the capture it was extracted from, the schema version its
 * fields follow, and its own version (ARCHITECTURE §14). */
export interface StoredRecord extends ScrapeRecord {
  capture_id: string;
  schema_id: string;
  version: number;
}

/** One page of records; `next_cursor` is null on the last page. */
export interface RecordPage {
  items: StoredRecord[];
  next_cursor: string | null;
}

/** The filters `GET /v1/records` takes; an empty one is left out. */
export interface RecordFilters {
  schema_id: string;
  job_id: string;
  site: string;
}

/** What a replay extracted from the capture now: not persisted (§13.1). */
export interface ReplayResult {
  records: ScrapeRecord[];
}

interface RecordQuery {
  schema_id?: string;
  job_id?: string;
  site?: string;
  cursor?: string;
}

/** The filters that are set, by name: an empty one is left out of a query. */
export function activeFilters(filters: RecordFilters): Partial<RecordFilters> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== ""));
}

function recordQuery(filters: RecordFilters, cursor: string | null): RecordQuery {
  return { ...activeFilters(filters), ...(cursor === null ? {} : { cursor }) };
}

/** The page of records at `cursor` (the first page when null); the page size is the server's. */
export function listRecords(
  client: ApiClient,
  filters: RecordFilters,
  cursor: string | null,
): Promise<ApiResult<RecordPage>> {
  return apiResult(
    () => client.GET("/v1/records", { params: { query: recordQuery(filters, cursor) } }),
    "Listing the records",
  );
}

/** Replays the capture with the current engine and the site's active config. The body is empty, so the server's
 * default applies and the replay calls no LLM (SPEC-07 §4.6). */
export function replayCapture(
  client: ApiClient,
  captureId: string,
): Promise<ApiResult<ReplayResult>> {
  return apiResult(
    () =>
      client.POST("/v1/captures/{capture_id}/replay", {
        params: { path: { capture_id: captureId } },
        body: {},
      }),
    "The replay",
  );
}

interface NoParameters {
  query?: never;
  header?: never;
  path?: never;
  cookie?: never;
}

interface JsonBody<T> {
  headers: Readonly<Record<string, unknown>>;
  content: { "application/json": T };
}

/** Any error answer: an RFC 9457 problem (SPEC-07 §4.3), read by `problemOf`. */
interface ProblemBody {
  headers: Readonly<Record<string, unknown>>;
  content: { "application/problem+json": unknown };
}

interface CaptureParameters {
  query?: never;
  header?: never;
  path: { capture_id: string };
  cookie?: never;
}

declare module "./schema" {
  interface paths {
    "/v1/records": {
      parameters: NoParameters;
      get: {
        parameters: { query?: RecordQuery; header?: never; path?: never; cookie?: never };
        requestBody?: never;
        responses: { 200: JsonBody<RecordPage>; default: ProblemBody };
      };
    };
    "/v1/captures/{capture_id}/replay": {
      parameters: NoParameters;
      post: {
        parameters: CaptureParameters;
        requestBody: { content: { "application/json": { allow_llm?: boolean } } };
        responses: { 200: JsonBody<ReplayResult>; default: ProblemBody };
      };
    };
  }
}
