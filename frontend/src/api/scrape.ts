/** `POST /v1/scrape`. The answer is the generated `ScrapeResult`. */
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The request, as the API's schema defines it: a member the form leaves out takes the server's default. */
export type ScrapeRequest = Schemas["ScrapeRequest-Input"];
export type ScrapeFormat = ScrapeRequest["formats"][number];
export type PageKind = NonNullable<ScrapeRequest["page_kind"]>;
/** The `fetch` member every page request shares. */
export type FetchMember = Schemas["FetchOptions-Input"];
export type MethodHint = NonNullable<FetchMember["method_hint"]>;
/** The paging mechanisms a listing's browser actions may be told to use. */
export type PagingHint = NonNullable<Schemas["BrowserActions-Input"]["hint"]>;
/** `fetch.cache`: reuse a stored capture as `max_age` allows, always fetch, or only serve a stored one. */
export type CacheMode = NonNullable<FetchMember["cache"]>;
/** A page step the browser runs before it reads the page. */
export type PageAction = NonNullable<FetchMember["actions"]>[number];
/** The area a `screenshot` format shows: what the browser's window shows, or the whole page. */
export type ScreenshotArea = NonNullable<FetchMember["screenshot"]>;
/** `markdown_fit`'s options: a query that keeps the blocks relevant to it, and at most this many blocks. */
export type FitOptions = Schemas["FitOptions-Input"];
/** `chunks`' options: how the markdown is split, the size of a chunk and the overlap, in words. */
export type ChunkOptions = Schemas["ChunkOptions-Input"];
export type ChunkStrategy = NonNullable<ChunkOptions["strategy"]>;
export type ChunkSource = NonNullable<ChunkOptions["source"]>;
export type Chunk = Schemas["Chunk"];
/** A file the browser made of the page, served by the API at its `url` (a path on the API's own origin). */
export type Artifact = Schemas["Artifact"];

/** A schema by id, inline (a SchemaDef the server validates), or drafted by role S from a prompt or from field names. */
export type SchemaRef = NonNullable<ScrapeRequest["schema"]>;

/** Every field carries the §13.1 attributes plus `reason`, `source_kind` and `derived_by`. */
export type RecordField = Schemas["RecordField"];
export type ScrapeRecord = Schemas["ScrapedRecord"];

/** The answer: a requested format's member is present, the others are absent. `schema` is the draft when a prompt
 * was used; `records` holds the page's record when they were asked for. */
export type ScrapeResponse = Schemas["ScrapeResult"];

export type FetchAttempt = Schemas["AttemptRecord"];
/** How a page was fetched: the kept attempt, the platform adapter that read it, and every attempt. */
export type FetchSummary = Schemas["FetchSummary"];
export type PageMetadata = Schemas["PageMetadata"];
