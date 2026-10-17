/** `POST /v1/scrape` (SPEC-07 §4.4). The answer is the generated `ScrapeResult`. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ScrapeFormat = "markdown" | "html" | "raw_html" | "links" | "metadata" | "records";
export type PageKind = "detail" | "listing";
export type MethodHint = "auto" | "http" | "browser";
/** The paging mechanisms a listing's browser actions may be told to use (owner #52). */
export type PagingHint = "load_more" | "show_more" | "pagination" | "next" | "scroll";

/** A schema by id, inline (a SchemaDef the server validates), or drafted by role S from a prompt or from field names
 * (SPEC-14 §4.10). */
export type SchemaRef =
  | { id: string }
  | { inline: Readonly<Record<string, unknown>> }
  | { prompt: string }
  | { fields: string[] };

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
  /** A listing's browser actions (owner #52): a soft row target and an optional mechanism. */
  browser_actions?: { records?: number; hint?: PagingHint };
}

/** Every field carries the §13.1 attributes plus `reason`, `source_kind` and `derived_by` (SPEC-07 §4.4). */
export type RecordField = Schemas["RecordField"];
export type ScrapeRecord = Schemas["ScrapedRecord"];

/** The answer: a requested format's member is present, the others are absent. `schema` is the draft when a prompt
 * was used; `records` holds the page's record when they were asked for. */
export type ScrapeResponse = Schemas["ScrapeResult"];

export type ScrapeOutcome = ScrapeResponse["outcome"];
export type FetchAttempt = Schemas["AttemptRecord"];
export type PageMetadata = Schemas["PageMetadata"];
