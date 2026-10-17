/** `POST /v1/scrape` (SPEC-07 §4.4). The answer is the generated `ScrapeResult`. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ScrapeFormat =
  | "markdown"
  | "markdown_fit"
  | "chunks"
  | "html"
  | "raw_html"
  | "links"
  | "metadata"
  | "screenshot"
  | "pdf"
  | "records";
export type PageKind = "detail" | "listing";
export type MethodHint = "auto" | "http" | "browser";
/** The paging mechanisms a listing's browser actions may be told to use (owner #52). */
export type PagingHint = "load_more" | "show_more" | "pagination" | "next" | "scroll";

/** `fetch.cache` (D-1435): reuse a stored capture as `max_age` allows, always fetch, or only serve a stored one. */
export type CacheMode = "default" | "bypass" | "only";

/** A page step the browser runs before it reads the page (D-1436, `config_ir/page_actions.py`). */
export type PageAction =
  | { type: "wait"; ms?: number; selector?: string; network_idle?: boolean }
  | { type: "click"; selector?: string; text?: string }
  | { type: "scroll"; to?: "bottom"; by?: number; until?: "stable" }
  | { type: "press"; key: string }
  | { type: "type"; selector: string; text: string };

/** The `fetch` member every page request shares, with the members the form sets; the others take the server's
 * defaults. */
export interface FetchMember {
  method_hint: MethodHint;
  max_rows?: number;
  headers?: Record<string, string>;
  cookies?: Record<string, string>;
  proxy_pool?: string;
  wait_for?: number | string;
  actions?: PageAction[];
  cache?: CacheMode;
  screenshot?: ScreenshotArea;
}
/** The area a `screenshot` format shows: what the browser's window shows, or the whole page. */
export type ScreenshotArea = Schemas["FetchOptions"]["screenshot"];
/** `markdown_fit`'s options: a query that keeps the blocks relevant to it, and at most this many blocks. */
export type FitOptions = Schemas["FitOptions"];
/** `chunks`' options: how the markdown is split, the size of a chunk and the overlap, in words. */
export type ChunkOptions = Schemas["ChunkOptions"];
export type ChunkStrategy = ChunkOptions["strategy"];
export type ChunkSource = ChunkOptions["source"];
export type Chunk = Schemas["Chunk"];
/** A file the browser made of the page, served by the API at its `url` (a path on the API's own origin). */
export type Artifact = Schemas["Artifact"];

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
  fetch: FetchMember;
  /** Omitted to take the server's default. */
  max_age?: number;
  timeout_s?: number;
  budget?: { llm_calls: number };
  /** A listing's browser actions (owner #52): a soft row target and an optional mechanism. */
  browser_actions?: { records?: number; hint?: PagingHint };
  /** `markdown_fit`'s and `chunks`' options: sent only with their format, with the members that are set. */
  fit?: FitOptions;
  chunking?: Partial<ChunkOptions>;
}

/** Every field carries the §13.1 attributes plus `reason`, `source_kind` and `derived_by` (SPEC-07 §4.4). */
export type RecordField = Schemas["RecordField"];
export type ScrapeRecord = Schemas["ScrapedRecord"];

/** The answer: a requested format's member is present, the others are absent. `schema` is the draft when a prompt
 * was used; `records` holds the page's record when they were asked for. */
export type ScrapeResponse = Schemas["ScrapeResult"];

export type ScrapeOutcome = ScrapeResponse["outcome"];
export type FetchAttempt = Schemas["AttemptRecord"];
/** How a page was fetched: the kept attempt, the platform adapter that read it, and every attempt. */
export type FetchSummary = Schemas["FetchSummary"];
export type PageMetadata = Schemas["PageMetadata"];
