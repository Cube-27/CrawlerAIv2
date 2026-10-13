/** `POST /v1/scrape` and `GET /v1/schemas/{schema_id}` as SPEC-07 §4.4 and §4.6 define them, narrowed by hand until
 * SPEC-07 PRs 4–7 put them in `openapi.json`. The module augmentation below adds them to the generated `paths`, so the
 * calls go through the authenticated client (and its 401 handling); delete it, and these types, once `make
 * api-client` generates them. */
import type { FieldResult, FieldTypeSpec } from "./field";

export type ScrapeFormat = "markdown" | "html" | "raw_html" | "links" | "metadata" | "records";
export type PageKind = "detail" | "listing";
export type MethodHint = "auto" | "http" | "browser";

/** A schema by id, inline (a SchemaDef the server validates), or drafted from a prompt by role S. */
export type SchemaRef =
  | { id: string }
  | { inline: Readonly<Record<string, unknown>> }
  | { prompt: string };

export interface ScrapeRequest {
  url: string;
  formats: ScrapeFormat[];
  schema: SchemaRef | null;
  page_kind: PageKind | null;
  fetch: { method_hint: MethodHint };
  /** Omitted to take the server's default. */
  max_age?: number;
  timeout_s?: number;
  budget?: { llm_calls: number };
}

/** `url_task.outcome` (ARCHITECTURE §6). */
export type ScrapeOutcome = "extracted" | "partial" | "blocked" | "shell" | "not_found" | "failed";

/** One fetch rung tried (SPEC-02 §4.2 `AttemptRecord`). */
export interface FetchAttempt {
  method: string;
  status: number | null;
  block_class: string;
  duration_ms: number;
  error?: string | null;
}

/** Every field carries the §13.1 attributes plus `reason`, `source_kind` and `derived_by` (SPEC-07 §4.4). */
export interface RecordField extends FieldResult {
  evidence: string | null;
  confidence: number | null;
  calibrated: boolean;
  source_kind: string | null;
  locator: string | null;
  derived_by: string | null;
}

export interface ScrapeRecord {
  id: string;
  mode: string;
  complete: boolean;
  confidence: number | null;
  fields: Readonly<Record<string, RecordField>>;
}

export interface SchemaSummary {
  id: string;
  name: string;
  version: number;
  origin: "preset" | "user" | "prompt_draft";
  fields: Readonly<Record<string, FieldTypeSpec>>;
}

export interface PageMetadata {
  title: string | null;
  description: string | null;
  language: string | null;
  canonical: string | null;
  og: Readonly<Record<string, string>>;
  structured_data_types: string[];
}

export interface ScrapeUsage {
  llm_calls: number;
  llm_tokens_in: number;
  llm_tokens_out: number;
  browser_seconds: number;
  http_requests: number;
}

/** A requested format's member is present; the others are absent. `schema` is present when a prompt was used. */
export interface ScrapeResponse {
  job_id: string;
  capture_id: string;
  url: string;
  final_url: string;
  fetched_at: string;
  outcome: ScrapeOutcome;
  fetch: {
    method: string;
    status_code: number | null;
    block_class: string;
    attempts: FetchAttempt[];
  };
  markdown?: string;
  html?: string;
  raw_html?: string;
  links?: string[];
  metadata?: PageMetadata;
  schema?: SchemaSummary;
  records?: ScrapeRecord[];
  usage: ScrapeUsage;
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

/** Any error answer: an RFC 9457 problem (SPEC-07 §4.3), read by `parseProblem`. */
interface ProblemBody {
  headers: Readonly<Record<string, unknown>>;
  content: { "application/problem+json": unknown };
}

declare module "./schema" {
  interface paths {
    "/v1/scrape": {
      parameters: NoParameters;
      post: {
        parameters: NoParameters;
        requestBody: { content: { "application/json": ScrapeRequest } };
        responses: { 200: JsonBody<ScrapeResponse>; default: ProblemBody };
      };
    };
    "/v1/schemas/{schema_id}": {
      parameters: NoParameters;
      get: {
        parameters: Omit<NoParameters, "path"> & { path: { schema_id: string } };
        requestBody?: never;
        responses: { 200: JsonBody<SchemaSummary>; default: ProblemBody };
      };
    };
  }
}
