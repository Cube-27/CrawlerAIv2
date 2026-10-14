import type { BatchRequest, CrawlRequest, JobSchemaRef, MapRequest } from "../../api/jobs";
import type { MethodHint, PageKind, ScrapeFormat } from "../../api/scrape";
import { orderedFormats } from "../../components/FormatChoices";
import { parseJsonObject } from "../scrape/form";

/** The job forms' state and the requests they send (SPEC-10 §4.3–4.5). The server validates every request; a form
 * checks only what it must hold to be sent. An empty limit (NaN) or text is left out, so the server's default
 * applies. */

export type JobSchemaSource = "none" | "id" | "inline";

export interface JobSchemaState {
  source: JobSchemaSource;
  id: string;
  json: string;
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

export interface MapFormState {
  url: string;
  include: string;
  exclude: string;
  limit: number;
  useSitemaps: boolean;
  useLinks: boolean;
}

const NO_SCHEMA: JobSchemaState = { source: "none", id: "", json: "" };

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

type SchemaChoice = { kind: "ok"; schema: JobSchemaRef | null } | { kind: "invalid" };

function schemaChoice({ source, id, json }: JobSchemaState): SchemaChoice {
  switch (source) {
    case "none":
      return { kind: "ok", schema: null };
    case "id":
      return { kind: "ok", schema: { id } };
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

function webhook(url: string): { webhook_url?: string } {
  const trimmed = url.trim();
  return trimmed === "" ? {} : { webhook_url: trimmed };
}

/** The batch request for `form`, or null when its inline schema is not a JSON object (the form shows why). */
export function buildBatch(form: BatchFormState): BatchRequest | null {
  const choice = schemaChoice(form.schema);
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
  const choice = schemaChoice(form.schema);
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
