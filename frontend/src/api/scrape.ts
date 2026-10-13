/** `POST /v1/scrape` (SPEC-07 §4.4). The answer is the generated `ScrapeResult`; the records and the draft schema
 * are narrowed by hand until SPEC-07 PRs 5 and 6 put them in `openapi.json`. */
import type { FieldResult, FieldTypeSpec } from "./field";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ScrapeFormat = "markdown" | "html" | "raw_html" | "links" | "metadata" | "records";
export type PageKind = "detail" | "listing";
export type MethodHint = "auto" | "http" | "browser";

/** A schema by id, inline (a SchemaDef the server validates), or drafted from a prompt by role S. */
export type SchemaRef =
  | { id: string }
  | { inline: Readonly<Record<string, unknown>> }
  | { prompt: string };

/** The request as the form builds it. It leaves out the limits it doesn't set, so the server's defaults apply; the
 * generated type marks every member with a default as required (openapi-typescript), so `runScrape` sends it as
 * that type, and the server validates it. */
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

/** The generated answer, with the members SPEC-07 PRs 5 and 6 add (`records`, and `schema` when a prompt was
 * used), narrowed by hand until then. A requested format's member is present; the others are absent. */
export type ScrapeResponse = Schemas["ScrapeResult"] & {
  schema?: SchemaSummary;
  records?: ScrapeRecord[];
};

export type ScrapeOutcome = ScrapeResponse["outcome"];
export type FetchAttempt = Schemas["AttemptRecord"];
export type PageMetadata = Schemas["PageMetadata"];
