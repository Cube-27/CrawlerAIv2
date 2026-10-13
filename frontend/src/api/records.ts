/** `GET /v1/records` and `POST /v1/captures/{id}/replay` (SPEC-07 §4.6), typed from the generated client. */
import type { ApiClient } from "./client";
import { apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** A stored record: the field shape of SPEC-07 §4.4, with the capture it was extracted from (null once the capture
 * expired), the schema version its fields follow, and its own version (ARCHITECTURE §14). */
export type StoredRecord = Schemas["StoredRecord"];

/** One page of records, newest first; `next_cursor` is null on the last page. */
export type RecordPage = Schemas["RecordPage"];

/** The filters `GET /v1/records` takes; an empty one is left out. */
export interface RecordFilters {
  schema_id: string;
  job_id: string;
  site: string;
}

/** A record a replay made: not stored (§13.1), so it has no id. */
export type ExtractedRecord = Schemas["ExtractedRecord"];

/** What a replay extracted from the capture now. */
export type ReplayResult = Schemas["ReplayResult"];

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

/** Replays the capture with the current engine and the site's active config, calling no LLM (SPEC-07 §4.6). */
export function replayCapture(
  client: ApiClient,
  captureId: string,
): Promise<ApiResult<ReplayResult>> {
  return apiResult(
    () =>
      client.POST("/v1/captures/{capture_id}/replay", {
        params: { path: { capture_id: captureId } },
        body: { allow_llm: false },
      }),
    "The replay",
  );
}
