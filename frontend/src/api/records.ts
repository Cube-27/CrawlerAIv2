/** `GET /v1/records` and `POST /v1/captures/{id}/replay` (rest-api spec), typed from the generated client. */
import type { ApiClient } from "./client";
import { apiResult, type ApiResult } from "./result";
import type { components, operations } from "./schema";

type Schemas = components["schemas"];

/** A stored record: the field shape of rest-api spec, with the capture it was extracted from (null once the capture
 * expired), the schema version its fields follow, and its own version. */
export type StoredRecord = Schemas["StoredRecord"];

/** One page of records, newest first; `next_cursor` is null on the last page. */
export type RecordPage = Schemas["RecordPage"];

/** The filters `GET /v1/records` takes; an empty one is left out. `changed_since` is an ISO 8601 instant: only the
 * new entities and new versions stored from then on, the change feed (jobs spec). */
export interface RecordFilters {
  schema_id: string;
  job_id: string;
  site: string;
  changed_since: string;
}

/** A record a replay made: not stored (§13.1), so it has no id. */
export type ExtractedRecord = Schemas["ExtractedRecord"];

/** What a replay extracted from the capture now. */
export type ReplayResult = Schemas["ReplayResult"];

type RecordQuery = NonNullable<operations["list_records_v1_records_get"]["parameters"]["query"]>;

/** The filters that are set, by name: an empty one is left out of a query. */
export function activeFilters(filters: RecordFilters): Partial<RecordFilters> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== ""));
}

function recordQuery(filters: RecordFilters, cursor: string | null, limit: number): RecordQuery {
  return { ...activeFilters(filters), ...(cursor === null ? {} : { cursor }), limit };
}

/** The page of records at `cursor` (the first page when null), `limit` records at most. */
export function listRecords(
  client: ApiClient,
  { filters, cursor, limit }: { filters: RecordFilters; cursor: string | null; limit: number },
): Promise<ApiResult<RecordPage>> {
  return apiResult(
    () => client.GET("/v1/records", { params: { query: recordQuery(filters, cursor, limit) } }),
    "Listing the records",
  );
}

/** Replays the capture with the current engine, cold until learning-configs spec wires configs, calling no LLM (rest-api spec). */
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
