import type {
  BatchRequest,
  CrawlRequest,
  ExtractRequest,
  JobSchemaRef,
  MapRequest,
} from "../../api/jobs";
import type { MethodHint, PageKind, SchemaRef, ScrapeFormat } from "../../api/scrape";
import { orderedFormats } from "../../components/FormatChoices";
import { parseJsonObject } from "../../api/json";

/** The job forms' state and the requests they send (SPEC-10 §4.3–4.6). The server validates every request; a form
 * checks only what it must hold to be sent. An empty limit (NaN) or text is left out, so the server's default
 * applies. */

/** Where a job's schema comes from: none, a stored one, inline JSON, or a draft from a prompt. */
export type SchemaSource = "none" | "id" | "inline" | "prompt";

/** A job's schema as edited. A batch or crawl offers none, a stored one or inline JSON; an extract needs one, and may
 * have it drafted from a prompt. */
export interface JobSchemaState {
  source: SchemaSource;
  id: string;
  json: string;
  prompt: string;
}

/** One page-kind rule as edited: `key` keeps a row's inputs when another row is removed. */
export interface RuleRow {
  key: string;
  pattern: string;
  pageKind: PageKind;
}

export interface BatchFormState {
  /** One URL per line. */
  urls: string;
  formats: readonly ScrapeFormat[];
  schema: JobSchemaState;
  pageKind: PageKind | null;
  methodHint: MethodHint;
  webhookUrl: string;
}

export interface CrawlFormState {
  url: string;
  formats: readonly ScrapeFormat[];
  schema: JobSchemaState;
  rules: readonly RuleRow[];
  /** One glob per line. */
  include: string;
  exclude: string;
  maxDepth: number;
  limit: number;
  methodHint: MethodHint;
  webhookUrl: string;
}

export interface ExtractFormState {
  /** One URL or URL glob per line. */
  urls: string;
  schema: JobSchemaState;
  pageKind: PageKind | null;
  limit: number;
  llmCalls: number;
  methodHint: MethodHint;
  webhookUrl: string;
}

export interface MapFormState {
  url: string;
  include: string;
  exclude: string;
  limit: number;
  useSitemaps: boolean;
  useLinks: boolean;
}

const NO_SCHEMA: JobSchemaState = { source: "none", id: "", json: "", prompt: "" };

export const INITIAL_BATCH: BatchFormState = {
  urls: "",
  formats: ["markdown"],
  schema: NO_SCHEMA,
  pageKind: null,
  // FetchPolicy's own default (SPEC-02 §4.2).
  methodHint: "auto",
  webhookUrl: "",
};

export const INITIAL_CRAWL: CrawlFormState = {
  url: "",
  formats: ["markdown"],
  schema: NO_SCHEMA,
  rules: [],
  include: "",
  exclude: "",
  maxDepth: Number.NaN,
  limit: Number.NaN,
  methodHint: "auto",
  webhookUrl: "",
};

export const INITIAL_EXTRACT: ExtractFormState = {
  urls: "",
  schema: { ...NO_SCHEMA, source: "id" },
  pageKind: null,
  limit: Number.NaN,
  llmCalls: Number.NaN,
  methodHint: "auto",
  webhookUrl: "",
};

// MapRequest's own defaults (SPEC-10 §4.4): both sources are read.
export const INITIAL_MAP: MapFormState = {
  url: "",
  include: "",
  exclude: "",
  limit: Number.NaN,
  useSitemaps: true,
  useLinks: true,
};

/** The non-blank lines of `text`, trimmed: a list entered one entry per line. */
export function lines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

type SchemaChoice<T> = { kind: "ok"; schema: T } | { kind: "invalid" };

/** The schema of `state`; invalid for inline text that is not a JSON object. */
function schemaChoice({
  source,
  id,
  json,
  prompt,
}: JobSchemaState): SchemaChoice<SchemaRef | null> {
  switch (source) {
    case "none":
      return { kind: "ok", schema: null };
    case "id":
      return { kind: "ok", schema: { id } };
    case "prompt":
      return { kind: "ok", schema: { prompt } };
    case "inline": {
      const inline = parseJsonObject(json);
      return inline === null ? { kind: "invalid" } : { kind: "ok", schema: { inline } };
    }
    default: {
      const exhaustive: never = source;
      return exhaustive;
    }
  }
}

/** A batch's or crawl's schema: these requests take no prompt, so one is invalid (their forms don't offer it). */
function jobSchema(state: JobSchemaState): SchemaChoice<JobSchemaRef | null> {
  const choice = schemaChoice(state);
  if (choice.kind === "invalid") return choice;
  const { schema } = choice;
  if (schema !== null && "prompt" in schema) return { kind: "invalid" };
  return { kind: "ok", schema };
}

function webhook(url: string): { webhook_url?: string } {
  const trimmed = url.trim();
  return trimmed === "" ? {} : { webhook_url: trimmed };
}

/** The batch request for `form`, or null when its inline schema is not a JSON object (the form shows why). */
export function buildBatch(form: BatchFormState): BatchRequest | null {
  const choice = jobSchema(form.schema);
  if (choice.kind === "invalid") return null;
  return {
    urls: lines(form.urls),
    formats: orderedFormats(form.formats),
    schema: choice.schema,
    page_kind: form.pageKind,
    fetch: { method_hint: form.methodHint },
    ...webhook(form.webhookUrl),
  };
}

/** The crawl request for `form`, or null as for `buildBatch`. A rule without a pattern is left out. */
export function buildCrawl(form: CrawlFormState): CrawlRequest | null {
  const choice = jobSchema(form.schema);
  if (choice.kind === "invalid") return null;
  return {
    url: form.url.trim(),
    formats: orderedFormats(form.formats),
    schema: choice.schema,
    page_kind_rules: form.rules
      .filter(({ pattern }) => pattern.trim() !== "")
      .map(({ pattern, pageKind }) => ({ pattern: pattern.trim(), page_kind: pageKind })),
    include: lines(form.include),
    exclude: lines(form.exclude),
    fetch: { method_hint: form.methodHint },
    ...(Number.isNaN(form.maxDepth) ? {} : { max_depth: form.maxDepth }),
    ...(Number.isNaN(form.limit) ? {} : { limit: form.limit }),
    ...webhook(form.webhookUrl),
  };
}

/** The extract request for `form`, or null when it has no schema, or an inline schema that is not a JSON object. */
export function buildExtract(form: ExtractFormState): ExtractRequest | null {
  const choice = schemaChoice(form.schema);
  if (choice.kind === "invalid" || choice.schema === null || form.pageKind === null) return null;
  return {
    urls: lines(form.urls),
    schema: choice.schema,
    page_kind: form.pageKind,
    fetch: { method_hint: form.methodHint },
    ...(Number.isNaN(form.limit) ? {} : { limit: form.limit }),
    ...(Number.isNaN(form.llmCalls) ? {} : { budget: { llm_calls: form.llmCalls } }),
    ...webhook(form.webhookUrl),
  };
}

export function buildMap(form: MapFormState): MapRequest {
  return {
    url: form.url.trim(),
    include: lines(form.include),
    exclude: lines(form.exclude),
    use_sitemaps: form.useSitemaps,
    use_links: form.useLinks,
    ...(Number.isNaN(form.limit) ? {} : { limit: form.limit }),
  };
}
